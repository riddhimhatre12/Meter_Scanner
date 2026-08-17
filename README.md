# ⚡ Meter Scanner Pro

> **Smart AI-Powered Utility Meter Tracking, OCR Scanning & Bill Management Platform**

Meter Scanner Pro is an intelligent web application designed to help homeowners, commercial property managers, and utility administrators seamlessly scan electricity, water, and gas meters using their device's camera, extract readings via Optical Character Recognition (OCR), estimate bills using tiered tariff slabs, analyze consumption trends, and interact with an AI assistant (**MeterBot**).

---

## ✨ Features

### 📷 1. Smart Camera & OCR Meter Scanning
- **Live Video Feed**: High-resolution camera stream (`1280x720`) with auto-focus optimization.
- **Multi-Frame Capture**: Analyzes image sharpness using Laplacian variance detection to pick the clearest frame.
- **Intelligent Digit Segmentation**: Preprocesses frames (grayscale, Gaussian blur, adaptive thresholding, morphological ops, digit contour sorting) before running OCR.
- **Multi-Format Support**: Works with Digital, Analog, Smart, Water, and Gas meters.
- **Manual Override**: Allows user correction if meter glass is dirty or digits are obscured.

### 🤖 2. MeterBot — AI Energy Assistant
- **Interactive Chat Interface**: Modern UI with quick-action chips and rich Markdown rendering (`### Headers`, `**bold**`, bullet lists).
- **Gemini API Integration**: Uses Google's Gemini models when an API key is provided for natural conversational support.
- **Rule-Based Fallback**: Fast offline rule engine for bill calculations, tariff queries, scanning guides, and energy tips.
- **Multi-Language Support**: Automatically detects non-English inputs and translates responses using `deep_translator`.
- **Off-Topic Protection**: Gently redirects non-utility questions back to energy management.

### 💰 3. Bill Calculator & Slab Rate Engine
- **Indian Electricity Tariff Slabs**:
  - `0 – 50 units`: ₹2.50 / unit (Lifeline)
  - `51 – 100 units`: ₹3.50 / unit
  - `101 – 300 units`: ₹4.50 / unit
  - `301 – 500 units`: ₹6.50 / unit
  - `500+ units`: ₹8.50 / unit
- **Automatic Taxes & Levies**: Calculates 15% fuel surcharge, 18% GST, and ₹25 fixed monthly meter rent.
- **Custom Rates**: Supports custom per-unit rate overrides for commercial or custom provider tariffs.

### 📊 4. Usage Analytics & Monthly Trends
- **Visual Consumption Charts**: 6-month visual consumption trend graphs powered by Chart.js.
- **Efficiency Scoring**: Assigns an energy efficiency rating from **A+** to **C** based on month-over-month usage changes.
- **Peak & Off-Peak Tracking**: Identifies highest usage days and consumption anomalies.

### 🔔 5. Alerts & Budget Planner
- **Monthly Budget Limits**: Set target spending limits and monitor current consumption against budget targets.
- **Threshold Warnings**: Get alerted when usage or bill projections cross critical thresholds.
- **Scan Reminders**: Receive notifications to scan meters on scheduled dates.

### 📁 6. Data Export & Management
- **CSV Export**: Export all historical readings (timestamps, values, OCR confidence scores, notes, debug image paths) with a single click.
- **Multi-Meter Management**: Manage multiple residential or commercial meters under a single account.

### 🔐 7. Security & User Access
- **Authentication**: Secure password hashing with `Werkzeug` / `bcrypt`.
- **Google OAuth Integration**: One-click sign-in via Google accounts.
- **Profile Management**: Update user info, address, contact details, and password.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **Backend Framework** | Python 3.10+, Flask 3.x, Flask-Login |
| **Database** | SQLite3 (`meter.db`) |
| **Computer Vision & OCR** | OpenCV (`cv2`), Pytesseract, Pillow, NumPy |
| **AI & Translation** | Google Generative AI (`google-generativeai`), `deep-translator` |
| **Frontend** | HTML5, CSS3 (Glassmorphism, Dark/Light Themes), Vanilla JavaScript, Bootstrap Icons |
| **Authentication** | Werkzeug Security, Google OAuth 2.0 (`google-auth`) |

---

## 🚀 Quick Start Guide

### Prerequisites
- Python **3.10** or higher
- [Tesseract OCR Engine](https://github.com/UB-Mannheim/tesseract/wiki) installed on host system (if using OCR scanning)

### 1. Clone the Repository
```bash
git clone https://github.com/riddhimhatre12/Meter_Scanner.git
cd Meter_Scanner
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the root directory (or rename `.env.example`):
```env
SECRET_KEY=your-secret-key-here
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GEMINI_API_KEY=your-optional-gemini-api-key
PORT=5000
```

### 5. Run the Application
```bash
python run.py
```
Open your browser and navigate to **`http://127.0.0.1:5000`**.

---

## 📂 Project Structure

```
Meter_Scanner/
├── app.py                      # Main Flask application & route handlers
├── run.py                      # Application entry point & env loader
├── db_setup.py                 # SQLite database schema initializer
├── models.py                   # Data models & helper functions
├── ocr.py                      # Image preprocessing & OCR logic
├── camera.py                   # OpenCV camera feed handler
├── billing.py                  # Bill calculation logic
├── config.py                   # Configuration settings
├── requirements.txt            # Python package dependencies
├── .env.example                # Sample environment file
├── static/                     # CSS stylesheets, JS scripts, and uploaded images
│   ├── css/
│   ├── js/
│   └── uploads/
├── templates/                  # HTML templates (Jinja2)
│   ├── index.html              # Landing page
│   ├── login.html              # Login & Google OAuth
│   ├── dashboard.html          # Main user dashboard
│   ├── capture.html            # Camera scan interface
│   ├── chatbot.html            # MeterBot AI chat interface
│   ├── settings.html           # Profile & settings
│   └── ...
└── README.md                   # Project documentation
```

---

## 📸 Key Application Screens

- **Home Page (`/`)**: Hero section highlighting key features, call to action, and quick login links.
- **Dashboard (`/dashboard`)**: Overview statistics, recent readings table, quick action cards, and Chart.js analytics.
- **Meter Scanning (`/capture`)**: Real-time camera feed with interactive target box, focus detection, and instant OCR result modal.
- **MeterBot AI Assistant (`/chatbot`)**: Embedded full-screen or popup AI assistant for instant support and bill calculations.

---

## 📄 License

This project is licensed under the **MIT License**.

---

⭐ *Developed with passion for smart energy tracking & utility management.*
