import cv2
import pytesseract
import re

def extract_reading(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return ""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. Bilateral Denoising & CLAHE
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    clahe_applied = clahe.apply(denoised)

    # 2. Rescale & Add Quiet Border Margin Padding
    h, w = clahe_applied.shape
    scaled = cv2.resize(clahe_applied, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    padded_normal = cv2.copyMakeBorder(scaled, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    padded_inverted = cv2.copyMakeBorder(255 - scaled, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

    candidates = []
    configs = [
        r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789',
        r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789',
        r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789',
        r'--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789'
    ]

    for pimg in [padded_normal, padded_inverted]:
        for cfg in configs:
            try:
                text = pytesseract.image_to_string(pimg, config=cfg)
                nums = re.findall(r'\d+', text)
                for num in nums:
                    if len(num) >= 2:
                        candidates.append(num)
            except Exception:
                pass

    if candidates:
        # Prefer typical 3-7 digit readings first
        candidates.sort(key=lambda x: (3 <= len(x) <= 7, -len(x)), reverse=True)
        return candidates[0]

    return ""

if __name__ == "__main__":
    reading = extract_reading("static/images/meter_reading.jpg")
    print("Extracted Reading:", reading)

