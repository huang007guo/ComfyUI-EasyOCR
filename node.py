import folder_paths
import json
import cv2
import easyocr
import os
import logging
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger("ComfyUI-EasyOCR")
model_dir_name = "EasyOCR"

lang_list = {
    "English": "en",
    "简体中文": "ch_sim",
    "繁體中文": "ch_tra",
    "العربية": "ar",
    "Azərbaycan": "az",
    "Euskal": "eu",
    "Bosanski": "bs",
    "Български": "bg",
    "Català": "ca",
    "Hrvatski": "hr",
    "Čeština": "cs",
    "Dansk": "da",
    "Nederlands": "nl",
    "Eesti": "et",
    "Suomi": "fi",
    "Français": "fr",
    "Galego": "gl",
    "Deutsch": "de",
    "Ελληνικά": "el",
    "עברית": "he",
    "हिन्दी": "hi",
    "Magyar": "hu",
    "Íslenska": "is",
    "Indonesia": "id",
    "Italiano": "it",
    "日本語": "ja",
    "한국어": "ko",
    "Latviešu": "lv",
    "Lietuvių": "lt",
    "Македонски": "mk",
    "Norsk": "no",
    "Polski": "pl",
    "Português": "pt",
    "Română": "ro",
    "Русский": "ru",
    "Српски": "sr",
    "Slovenčina": "sk",
    "Slovenščina": "sl",
    "Español": "es",
    "Svenska": "sv",
    "ไทย": "th",
    "Türkçe": "tr",
    "Українська": "uk",
    "Tiếng Việt": "vi",
}

def get_lang_list():
    result = []
    for key, value in lang_list.items():
        result.append(key)
    return result


def get_classes(label):
    label = label.lower()
    labels = label.split(",")
    result = []
    for l in labels:
        for key, value in lang_list.items():
            if l == value:
                result.append(value)
                break
    return result


def get_classes2(label):
    label = label.lower()
    labels = label.split(",")
    result = []
    for l in labels:
        for key, value in lang_list.items():
            if l == key:
                result.append(value)
                break
    return result


def plot_boxes_to_image(image_pil, tgt):
    H, W = tgt["size"]
    result = tgt["result"]

    res_mask = []
    res_image = []

    box_color = (255, 0, 0)  # Red color for the box
    text_color = (255, 255, 255)  # White color for the text

    draw = ImageDraw.Draw(image_pil)

    # Get the current file path and use it to create a relative path to the font file
    current_file_path = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(current_file_path, "docs", "PingFangRegular.ttf")
    font_size = 20
    font = ImageFont.truetype(font_path, font_size)

    labelme_data = {
        "version": "4.5.6",
        "flags": {},
        "shapes": [],
        "imagePath": None,
        "imageData": None,
        "imageHeight": H,
        "imageWidth": W,
    }

    for item in result:
        formatted_points, label, threshold = item

        x1, y1 = formatted_points[0]
        x2, y2 = formatted_points[2]
        threshold = round(threshold, 2)

        # Ensure coordinates are valid
        x_min, x_max = sorted([int(x1), int(x2)])
        y_min, y_max = sorted([int(y1), int(y2)])

        points = [[x_min, y_min], [x_max, y_max]]

        # Save labelme json
        shape = {
            "label": label,
            "points": points,
            "group_id": None,
            "shape_type": "rectangle",
            "flags": {},
        }
        labelme_data["shapes"].append(shape)

        # Change label
        label = f"{label}:{threshold}"
        shape["threshold"] = str(threshold)

        # Draw rectangle on the image using PIL
        draw.rectangle([(x_min, y_min), (x_max, y_max)], outline=box_color, width=3)

        # Draw label on the image using PIL
        text_bbox = draw.textbbox((x_min, y_min), label, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        label_ymin = max(y_min, text_height + 10)
        draw.rectangle(
            [(x_min, y_min - text_height - 10), (x_min + text_width, y_min)], fill=box_color
        )
        draw.text((x_min, y_min - text_height - 10), label, font=font, fill=text_color)

        # Draw mask
        mask = np.zeros((H, W, 1), dtype=np.uint8)
        cv2.rectangle(mask, (x_min, y_min), (x_max, y_max), (255, 255, 255), -1)
        mask_tensor = torch.from_numpy(mask).permute(2, 0, 1).float() / 255.0
        res_mask.append(mask_tensor)

    if len(res_mask) == 0:
        mask = np.zeros((H, W, 1), dtype=np.uint8)
        mask_tensor = torch.from_numpy(mask).permute(2, 0, 1).float() / 255.0
        res_mask.append(mask_tensor)

    # Convert the PIL image back to a numpy array
    image_with_boxes = np.array(image_pil)

    # Convert the modified image to a torch tensor
    image_with_boxes_tensor = torch.from_numpy(
        image_with_boxes.astype(np.float32) / 255.0
    ).unsqueeze(0)
    res_image.append(image_with_boxes_tensor)

    return res_image, res_mask, labelme_data


class ApplyEasyOCR:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "gpu": (
                    "BOOLEAN",
                    {"default": True},
                ),
                "detect": (
                    ["choose", "input"],
                    {"default": "choose"},
                ),
                "language_list": (
                    get_lang_list(),
                    {"default": "English"},
                ),
                "language_name": (
                    "STRING",
                    {"default": "ch_sim,en", "multiline": False},
                ),
            },
        }

    CATEGORY = "ComfyUI-EasyOCR"
    FUNCTION = "main"
    RETURN_TYPES = (
        "IMAGE",
        "MASK",
        "JSON",
    )

    def main(self, image, gpu, detect, language_list, language_name):
        res_images = []
        res_masks = []
        res_labels = []

        for item in image:
            image_pil = Image.fromarray(np.clip(255.0 * item.cpu().numpy(), 0, 255).astype(np.uint8)).convert("RGB")

            language = None
            if detect == "choose":
                language = get_classes2(language_list)
            else:
                language = get_classes(language_name)

            model_storage_directory = os.path.join(folder_paths.models_dir, model_dir_name)
            if not os.path.exists(model_storage_directory):
                os.makedirs(model_storage_directory)

            reader = easyocr.Reader(language, model_storage_directory=model_storage_directory, gpu=gpu)
            result = reader.readtext(np.array(image_pil))

            size = image_pil.size
            pred_dict = {
                "size": [size[1], size[0]],
                "result": result
            }

            image_tensor, mask_tensor, labelme_data = plot_boxes_to_image(image_pil, pred_dict)

            res_images.extend(image_tensor)
            res_masks.extend(mask_tensor)
            res_labels.append(labelme_data)

        # 合并所有的蒙版为一个单一的蒙版
        if len(res_masks) > 0:
            combined_mask = torch.max(torch.stack(res_masks, dim=0), dim=0).values
        else:
            # 创建一个默认的空蒙版，假设所有图像都有相同的尺寸
            default_mask = np.zeros((image[0].shape[1], image[0].shape[2], 1), dtype=np.uint8)
            combined_mask = torch.from_numpy(default_mask).permute(2, 0, 1).float() / 255.0

        return (
            torch.cat(res_images, dim=0),
            combined_mask,
            res_labels,
        )