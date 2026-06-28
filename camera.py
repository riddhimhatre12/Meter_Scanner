import cv2

def capture_image():
    cap = cv2.VideoCapture(0)
    while True:
        ret, frame = cap.read()
        cv2.imshow('Capture Meter Reading', frame)

        if cv2.waitKey(1) & 0xFF == ord('s'):  # Press 's' to save image
            cv2.imwrite("static/images/meter_reading.jpg", frame)
            break

    cap.release()
    cv2.destroyAllWindows()

capture_image()
