import cv2
import pytesseract

def extract_reading(image_path):
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # OCR extraction
    text = pytesseract.image_to_string(gray, config='--psm 6')
    
    # Extract only numbers
    reading = ''.join(filter(str.isdigit, text))
    
    return reading

reading = extract_reading("static/images/meter_reading.jpg")
print("Extracted Reading:", reading)
