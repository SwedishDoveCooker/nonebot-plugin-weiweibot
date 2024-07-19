import re
import cv2
import hashlib
from cnocr import CnOcr
from pathlib import Path
from nonebot import logger

def clean_filename(filename):
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z ]', '', filename)

def is_chinese(text):
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False

def contains_invalid_phrase(text):
    return re.search(r'人正在看', text) is not None

def get_file_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def rename_images(folder_path):
    valid_extensions = ('.jpg', '.png', '.webp', '.jpeg', '.JPG', '.PNG', '.WEBP', '.JPEG')
    files = folder_path.iterdir()
    image_files = [f for f in files if f.suffix.lower() in valid_extensions]
    
    for file in image_files:
        old_file_path = folder_path.joinpath(file)
        extension = old_file_path.suffix
        md5_hash = get_file_md5(old_file_path)
        new_filename = f"{md5_hash}{extension}"
        new_file_path = folder_path.joinpath(new_filename)
        if not new_file_path.exists():
            old_file_path.rename(new_file_path)
            logger.info(f"Renamed: {file} -> {new_filename}\n")

def process_images(folder_path):
    files = folder_path.iterdir()
    ocr = CnOcr()
    valid_extensions = ('.jpg', '.png', '.webp', '.jpeg', '.JPG', '.PNG', '.WEBP', '.JPEG')
    image_files = [f for f in files if f.suffix.lower() in valid_extensions]
    for f in image_files:
        img_fp = folder_path.joinpath(f)
        img = cv2.imread(str(img_fp))
        height, width = img.shape[:2]
        start_y = int(height * 4 // 5)
        cropped_img = img[start_y:, :]
        temp_cropped_img_path = folder_path.joinpath('temp_cropped_img'+img_fp.suffix)
        cv2.imwrite(str(temp_cropped_img_path), cropped_img)
        ocr_results = ocr.ocr(str(temp_cropped_img_path))
        filtered_results = []
        for result in ocr_results:
            text = result['text']
            position = result['position']
            if position[0][0] <= width // 2 and is_chinese(text) and not contains_invalid_phrase(text):
                filtered_results.append(result)
        if len(filtered_results) > 1:
            filtered_results = filtered_results[1:]
        filename = ' '.join([result['text'] for result in filtered_results])
        cleaned_filename = clean_filename(filename)
        new_file_path = folder_path.joinpath(f"{cleaned_filename}{img_fp.suffix}")
        if not new_file_path.exists():
            img_fp.rename(new_file_path)
            logger.info(f"Renamed: {f} -> {cleaned_filename}{img_fp.suffix}\n")
        temp_cropped_img_path.unlink()