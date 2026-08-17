from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from sqlite3 import Error
import os
from werkzeug.security import generate_password_hash, check_password_hash
import cv2
import time
from datetime import datetime, timedelta
import json
import calendar
import numpy as np
import re
import csv
import io
import logging
import random
from logging.handlers import RotatingFileHandler
import requests
from urllib.parse import urlencode
import threading
from threading import Lock

try:
    import pytesseract
    from PIL import Image
    tcmd = os.getenv("TESSERACT_CMD")
    if tcmd:
        pytesseract.pytesseract.tesseract_cmd = tcmd
    else:
        # Verified path on user machine
        common_tess_path = r'C:\Tesseract-OCR\tesseract.exe'
        if os.path.exists(common_tess_path):
            pytesseract.pytesseract.tesseract_cmd = common_tess_path
        else:
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except Exception as e:
    logger = logging.getLogger(__name__)
    logger.error(f'Could not initialize Tesseract: {e}')
    pytesseract = None

# Global lock for camera access
camera_lock = Lock()

app = Flask(__name__)

# Load .env file automatically
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

app.secret_key = os.environ.get("SECRET_KEY", "your_secret_key")

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', 'your-google-client-id')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', 'your-google-client-secret')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Database setup
DB_FILE = "meter.db"

# Ensure uploads directory exists
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Global variable for camera
camera = None

# Electricity rate slabs (units: rate per unit in Rs)
ELECTRICITY_SLABS = [
    (0, 50, 2.50),     # 0-50 units: Rs 2.50 per unit (Lifeline consumers)
    (51, 100, 3.50),   # 51-100 units: Rs 3.50 per unit
    (101, 300, 4.50),  # 101-300 units: Rs 4.50 per unit
    (301, 500, 6.50),  # 301-500 units: Rs 6.50 per unit
    (501, float('inf'), 8.50)  # Above 500 units: Rs 8.50 per unit
]

# Time of day rates (multiplier)
TIME_OF_DAY_RATES = {
    'peak': 1.25,      # 6 PM - 10 PM
    'normal': 1.0,     # 6 AM - 6 PM
    'off_peak': 0.8    # 10 PM - 6 AM
}

# Seasonal rates (multiplier)
SEASONAL_RATES = {
    'summer': 1.2,     # March to June
    'monsoon': 1.0,    # July to October
    'winter': 0.9      # November to February
}

# Fixed charges based on connection type
FIXED_CHARGES = {
    'residential': 50.0,
    'commercial': 100.0,
    'industrial': 200.0
}

# Other charges
FUEL_SURCHARGE = 0.15  # 15% of energy charges
GST_RATE = 0.18       # 18% GST
METER_RENT = 25.0     # Rs per month
ELECTRICITY_DUTY = 0.16  # 16% of energy charges

def init_db():
    """Initialize the database with required tables."""
    try:
        # Remove database if it exists and is corrupted
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.close()
        except sqlite3.DatabaseError:
            print("Corrupted database detected, recreating...")
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
    except Exception as e:
        print(f"Error checking database: {e}")

    # Create new database
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Create users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        
        # Create readings table
        c.execute('''
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                reading_value TEXT,
                confidence REAL,
                debug_image TEXT,
                status TEXT DEFAULT 'auto',
                notes TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Create indices for better performance
        c.execute('CREATE INDEX IF NOT EXISTS idx_readings_user_id ON readings(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp)')
        
        conn.commit()
        # logging not configured yet here; safe print
        print("Database initialized successfully")
    except Exception as e:
        print(f"Error initializing database: {e}")
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def ensure_schema():
    # Add missing columns for readings schema when upgrading existing DBs
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("PRAGMA table_info(readings)")
        cols = {row[1] for row in c.fetchall()}
        alterations = []
        if 'confidence' not in cols:
            alterations.append("ALTER TABLE readings ADD COLUMN confidence REAL")
        if 'debug_image' not in cols:
            alterations.append("ALTER TABLE readings ADD COLUMN debug_image TEXT")
        if 'status' not in cols:
            alterations.append("ALTER TABLE readings ADD COLUMN status TEXT DEFAULT 'auto'")
        if 'notes' not in cols:
            alterations.append("ALTER TABLE readings ADD COLUMN notes TEXT")
        for stmt in alterations:
            c.execute(stmt)
        if alterations:
            conn.commit()
        
        # Check and add missing columns for users table
        c.execute("PRAGMA table_info(users)")
        user_cols = {row[1] for row in c.fetchall()}
        user_alterations = []
        if 'google_id' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN google_id TEXT")
        if 'email' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
        if 'first_name' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN first_name TEXT")
        if 'last_name' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN last_name TEXT")
        if 'phone' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN phone TEXT")
        if 'address' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN address TEXT")
        if 'created_at' not in user_cols:
            user_alterations.append("ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
        for stmt in user_alterations:
            c.execute(stmt)
        if user_alterations:
            conn.commit()
        
        # Create new tables for additional features
        c.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                threshold_value REAL,
                condition_type TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                budget_type TEXT NOT NULL,
                monthly_limit REAL,
                current_spending REAL DEFAULT 0,
                month TEXT,
                year INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS meters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                meter_name TEXT NOT NULL,
                meter_type TEXT NOT NULL,
                meter_number TEXT,
                location TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                meter_id INTEGER,
                maintenance_type TEXT NOT NULL,
                scheduled_date DATE,
                status TEXT DEFAULT 'scheduled',
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (meter_id) REFERENCES meters (id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS energy_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tip_category TEXT NOT NULL,
                tip_title TEXT NOT NULL,
                tip_description TEXT,
                potential_savings REAL,
                difficulty_level TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insert sample energy tips
        c.execute("SELECT COUNT(*) FROM energy_tips")
        if c.fetchone()[0] == 0:
            tips = [
                ('lighting', 'Switch to LED Bulbs', 'Replace traditional bulbs with LED bulbs to save up to 75% on lighting costs', 15.0, 'easy'),
                ('cooling', 'Optimize AC Usage', 'Set AC temperature to 24°C and use fans for better circulation', 20.0, 'medium'),
                ('appliances', 'Unplug Idle Devices', 'Unplug chargers and appliances when not in use to prevent phantom power drain', 5.0, 'easy'),
                ('water', 'Fix Leaky Faucets', 'Repair dripping faucets to save water and reduce water heating costs', 10.0, 'medium'),
                ('insulation', 'Improve Insulation', 'Add weather stripping to doors and windows to prevent air leaks', 25.0, 'hard'),
                ('timing', 'Use Off-Peak Hours', 'Run heavy appliances during off-peak hours to benefit from lower rates', 12.0, 'easy')
            ]
            c.executemany('INSERT INTO energy_tips (tip_category, tip_title, tip_description, potential_savings, difficulty_level) VALUES (?, ?, ?, ?, ?)', tips)
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                complaint_id TEXT NOT NULL,
                type TEXT NOT NULL,
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT NOT NULL,
                contact_method TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                attachment_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
def get_db_connection():
    """Get a database connection with row factory."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError as e:
        print(f"Database error: {e}")
        # Try to reinitialize the database
        init_db()
        # Try one more time
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

# Logging setup (rotating file handler)
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'), exist_ok=True)
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'app.log')
handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
handler.setFormatter(formatter)
logger = logging.getLogger('meter_scanner')
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(handler)

# Initialize database
init_db()
logger.info('Application started. Database initialized.')
ensure_schema()
logger.info('Schema ensured (confidence/debug_image/status/notes).')

class User(UserMixin):
    def __init__(self, id, username, password, email=None, first_name=None,
                 last_name=None, phone=None, address=None, google_id=None):
        self.id = id
        self.username = username
        self.password = password
        self.email = email or ''
        self.first_name = first_name or ''
        self.last_name = last_name or ''
        self.phone = phone or ''
        self.address = address or ''
        self.google_id = google_id or ''

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    if conn is not None:
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = c.fetchone()
            if user:
                keys = user.keys()
                return User(
                    id=user['id'],
                    username=user['username'],
                    password=user['password'],
                    email=user['email'] if 'email' in keys else '',
                    first_name=user['first_name'] if 'first_name' in keys else '',
                    last_name=user['last_name'] if 'last_name' in keys else '',
                    phone=user['phone'] if 'phone' in keys else '',
                    address=user['address'] if 'address' in keys else '',
                    google_id=user['google_id'] if 'google_id' in keys else '',
                )
        finally:
            conn.close()
    return None


def get_season(date):
    month = date.month
    if 3 <= month <= 6:
        return 'summer'
    elif 7 <= month <= 10:
        return 'monsoon'
    else:
        return 'winter'

def get_time_of_day(hour):
    if 18 <= hour < 22:  # 6 PM - 10 PM
        return 'peak'
    elif 6 <= hour < 18:  # 6 AM - 6 PM
        return 'normal'
    else:  # 10 PM - 6 AM
        return 'off_peak'

def calculate_slab_charges(units, season, time_of_day='normal', connection_type='residential'):
    total_charge = 0
    remaining_units = units
    slab_breakup = []
    
    # Apply seasonal and time of day multipliers
    season_multiplier = SEASONAL_RATES[season]
    tod_multiplier = TIME_OF_DAY_RATES[time_of_day]
    
    for start, end, base_rate in ELECTRICITY_SLABS:
        if remaining_units <= 0:
            break
            
        slab_units = min(remaining_units, end - start + 1)
        adjusted_rate = base_rate * season_multiplier * tod_multiplier
        slab_charge = slab_units * adjusted_rate
        
        slab_breakup.append({
            'start': start,
            'end': end,
            'units': slab_units,
            'base_rate': base_rate,
            'adjusted_rate': round(adjusted_rate, 2),
            'season_multiplier': season_multiplier,
            'tod_multiplier': tod_multiplier,
            'charge': round(slab_charge, 2)
        })
        
        total_charge += slab_charge
        remaining_units -= slab_units
    
    return total_charge, slab_breakup

# Chatbot responses with detailed information
CHATBOT_RESPONSES = {
    "greeting": [
        "Hello! I'm your Meter Scanner Assistant. I can help you with meter scanning, reading history, and answering questions about your utility usage. What would you like to know?",
        "Hi there! I'm here to assist you with all things related to meter scanning. You can ask me how to scan, check your usage history, or get help with any issues.",
        "Welcome to Meter Scanner! I'm your AI assistant. How can I help you with your meter readings today?"
    ],
    "how_to_scan": [
        "🔍 How to scan your meter:\n\n1. Position your camera directly in front of the meter\n2. Ensure good, even lighting (avoid shadows and glare)\n3. Keep the meter display centered in the frame\n4. Hold your phone steady and tap the capture button\n5. The app will automatically detect and extract the reading\n\n💡 Tip: For analog meters, make sure the dials are clearly visible. For digital meters, ensure the display is not reflecting light.",
        "📱 Scanning tips for best results:\n\n• Clean the meter display before scanning\n• Hold your phone parallel to the meter\n• Stand about 12-18 inches away\n• Make sure all digits are clearly visible\n• Avoid taking photos at an angle\n\nThe app works best in well-lit conditions with minimal reflections on the meter display."
    ],
    "meter_types": [
        "🔄 Supported Meter Types:\n\n• Digital Electric Meters\n• Analog (Dial) Electric Meters\n• Smart Meters\n• Water Meters\n• Gas Meters\n\nThe app automatically detects the meter type and processes it accordingly. If you're having trouble with a specific meter, let me know!"
    ],
    "troubleshooting": [
        "🔧 Common Scanning Issues & Solutions:\n\n1. Blurry Images\n   • Clean your camera lens\n   • Hold your phone steady\n   • Ensure good lighting\n\n2. Numbers Not Detected\n   • Get closer to the meter\n   • Adjust the angle\n   • Try manual entry if needed\n\n3. Poor Lighting\n   • Use your phone's flash\n   • Try scanning during daylight\n   • Avoid direct sunlight on the display\n\nWould you like more specific help with any of these issues?",
        "❓ Having trouble? Try these steps:\n\n• Make sure you're not too close or too far from the meter\n• Check for any glare or reflections\n• Try cleaning the meter display\n• Ensure all digits are clearly visible\n• If possible, try scanning in natural light\n\nIf you're still having issues, you can manually enter the reading."
    ],
    "reading_history": [
        "📊 Your Reading History:\n\nYou can view your complete reading history in the 'Readings' section of the app. Here's what you can do:\n\n• View past meter readings with timestamps\n• Track your consumption over time\n• Export your data for record-keeping\n• Set up usage alerts\n\nWould you like me to help you analyze your usage patterns?",
        "📈 Understanding Your Usage:\n\nYour reading history helps you:\n\n• Monitor daily/weekly/monthly consumption\n• Identify unusual usage patterns\n• Track the impact of energy-saving measures\n• Compare usage across different periods\n\nYou can access detailed analytics in the 'Analytics' section."
    ],
    "billing": [
        "💳 Billing Information:\n\n• Current billing cycle: 1st to end of month\n• Due date: 15th of each month\n• Payment methods: Credit/Debit, Bank Transfer, UPI\n• View your current bill in the 'Bills' section\n\nFor specific billing questions, please have your account number ready.",
        "💰 Understanding Your Bill:\n\nYour bill is calculated based on:\n\n• Units consumed (kWh for electricity, m³ for water/gas)\n• Current tariff rates\n• Any applicable taxes and surcharges\n• Previous balance if any\n\nYou can view a detailed breakdown in the 'Bills' section."
    ],
    "contact_support": [
        "📞 Contact Support:\n\nFor immediate assistance, please contact our support team:\n\n• Phone: 1800-123-4567 (24/7)\n• Email: support@meterscanner.com\n• Live Chat: Available in the app\n\nOur average response time is under 2 hours during business hours.",
        "🛠 Need Help?\n\nHere's how to reach us:\n\n• Customer Service: 1800-123-4567\n• Technical Support: support@meterscanner.com\n• In-App: Go to Settings > Help & Support\n• FAQ: Check our Help Center in the app"
    ],
    "default": [
        "I'm not sure I understand. Could you try rephrasing your question? I can help with:\n• Meter scanning\n• Reading history\n• Billing questions\n• Troubleshooting\n• And more!"
    ]
}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chatbot')
def chatbot():
    """Render the chatbot interface"""
    # Create a response that doesn't extend base.html
    from flask import make_response
    with app.app_context():
        response = make_response(render_template('chatbot.html'))
        # Add headers to prevent caching
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json() or {}
        msg = data.get('message', '').strip()
        if not msg:
            return jsonify({'response': 'Please enter a message.', 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            
        # Check for Gemini API key
        gemini_api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        
        # If API key is set, use Gemini API for professional response
        if gemini_api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_api_key)
                
                # Use gemini-1.5-flash
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=(
                        "You are MeterBot, a professional AI customer service assistant for Meter Scanner Pro. "
                        "Meter Scanner Pro is a utility meter tracking application that allows users to scan their digital "
                        "and analog electricity, water, or gas meters using their camera, perform OCR to extract readings, "
                        "calculate bills, view consumption trends/analytics, set alerts/budget limits, and schedule maintenance. "
                        "Always respond professionally, politely, and helpfully. Keep your responses relatively concise. "
                        "Answer in the same language as the user. If they ask off-topic questions (e.g., weather, politics, jokes, generic programming), "
                        "politely pivot back to helping them with Meter Scanner Pro services or utility management."
                    )
                )
                
                response = model.generate_content(msg)
                if response.text:
                    return jsonify({'response': response.text, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            except Exception as e:
                logger.error(f"Gemini API chat failed, falling back to rule-based: {e}")
        
        # Safely handle translation only if non-ASCII characters exist
        msg_en = msg.lower().strip()
        detected_lang = 'en'
        
        is_non_ascii = any(ord(c) > 127 for c in msg)
        if is_non_ascii:
            try:
                from deep_translator import GoogleTranslator
                translator_to_en = GoogleTranslator(source='auto', target='en')
                translated = translator_to_en.translate(msg)
                if translated:
                    msg_en = translated.lower().strip()
                detected_lang = getattr(translator_to_en, 'source', 'en') or 'en'
            except Exception as e:
                logger.warning(f"Translation service unavailable, using raw text: {e}")
                msg_en = msg.lower().strip()
                detected_lang = 'en'

        OFF_TOPIC = ['weather','cricket','football','movie','song','recipe',
            'politics','news','stock','crypto','bitcoin','relationship',
            'love','joke','poem','write code','javascript','translate',
            'capital of','population of','president','prime minister',
            'who invented','physics','mathematics','game','sport',
            'fashion','travel','hotel','flight','instagram','facebook',
            'twitter','youtube','tiktok']
        
        # Numbers in the English message
        nums = re.findall(r'\d+\.?\d*', msg_en)
        
        # Match against professional replies
        r_en = ""
        
        if any(k in msg_en for k in OFF_TOPIC):
            r_en = ("Sorry, I can only assist with **Meter Scanner Pro** and utility management topics! ⚡\n\n"
                    "I specialize in:\n"
                    "• 📷 **Meter scanning** and OCR\n"
                    "• 💰 **Bill calculation** and Indian slab rates\n"
                    "• 📊 **Usage analytics** and consumption trends\n"
                    "• 🔔 **Smart alerts** and monthly budget planning\n"
                    "• 💡 **Energy-saving recommendations**\n"
                    "• 🔧 **Scanning troubleshooting** & meter maintenance\n\n"
                    "Please ask about your utility meters or energy bills and I'll be happy to help! 😊")

        elif any(w in msg_en for w in ['hello','hi','hey','greetings','good morning','good afternoon','good evening','namaste']):
            r_en = ("Hello! 👋 I'm **MeterBot**, your professional energy assistant for Meter Scanner Pro.\n\n"
                    "I can assist you with:\n"
                    "• 📷 **Meter Scanning**: How to scan your digital or analog meters.\n"
                    "• 💰 **Bill Calculation**: Estimating bills based on slab rates.\n"
                    "• 📊 **Analytics & Export**: Tracking usage patterns and downloading reports.\n"
                    "• 🔔 **Alerts & Budgets**: Setting thresholds and monthly spending limits.\n\n"
                    "How can I help you manage your energy consumption today?")
            
        elif any(w in msg_en for w in ['who are you','what are you','your name','introduce','about you','what can you do']):
            r_en = ("I am **MeterBot** 🤖, the dedicated AI assistant for Meter Scanner Pro.\n\n"
                    "I specialize in assisting you with all features of Meter Scanner Pro, including OCR meter scanning, "
                    "electricity bill calculation, usage analytics, CSV exports, budget planning, alerts, and troubleshooting "
                    "camera issues. I am here to help you optimize your utility management and save on your bills.")
            
        elif any(w in msg_en for w in ['scan','capture','camera','ocr','take photo','read meter','how to scan','meter reading']):
            r_en = ("### How to scan your meter: 📷\n\n"
                    "1. Navigate to the **Dashboard** and click **Scan Meter** (or go to the Scan section).\n"
                    "2. Grant camera permissions if prompted.\n"
                    "3. Center your utility meter display inside the alignment frame.\n"
                    "4. Ensure proper, glare-free lighting for maximum accuracy.\n"
                    "5. Press **Capture**. Our OCR will automatically extract the reading.\n\n"
                    "*Note: We support digital, analog, smart, water, and gas meters. Clean the meter glass if it's dirty for better results.*")
            
        elif any(w in msg_en for w in ['slab','tariff','per unit','electricity rate','kwh rate','unit rate']):
            r_en = ("### Current Electricity Slab Rates (INR):\n\n"
                    "• **0–50 units**: ₹2.50 / unit (Lifeline slab)\n"
                    "• **51–100 units**: ₹3.50 / unit\n"
                    "• **101–300 units**: ₹4.50 / unit\n"
                    "• **301–500 units**: ₹6.50 / unit\n"
                    "• **500+ units**: ₹8.50 / unit\n\n"
                    "*Additional fees apply including a 15% fuel surcharge, 18% GST, and ₹25 monthly meter rent. Surcharges vary by season and peak hours.*")
            
        elif any(w in msg_en for w in ['bill','calculate','cost','charge','amount','invoice','payment']):
            if len(nums) >= 2:
                u, rate = float(nums[0]), float(nums[1])
                energy = u * rate; gst = energy * 0.18; total = energy + gst + 25
                r_en = (f"### Estimated Bill Calculation\n\n"
                        f"• **Units Consumed**: {u} kWh\n"
                        f"• **Rate per Unit**: ₹{rate:.2f}\n"
                        f"• **Energy Charge**: ₹{energy:.2f}\n"
                        f"• **Fixed Meter Rent**: ₹25.00\n"
                        f"• **GST (18%)**: ₹{gst:.2f}\n"
                        f"**Estimated Total Bill**: **₹{total:.2f}**\n\n"
                        "Please check the Bills page for a detailed slab-wise breakdown.")
            elif len(nums) == 1:
                u = float(nums[0])
                r_en = (f"I have received your units consumption: **{u} kWh**. "
                        f"To estimate the bill, please specify the rate per unit.\n"
                        f"Example: *'calculate bill for {u} units at ₹6 per unit'*, or visit the Bills page.")
            else:
                r_en = ("I can help calculate your estimated electricity bill. "
                        "Please provide your units consumed and the unit rate (e.g. *'calculate bill for 150 units at ₹4.5'*) "
                        "or visit the Bills section to generate an official bill from your scanned readings.")
            
        elif any(w in msg_en for w in ['history','past reading','analytics','trend','graph','monthly','consumption','track','usage']):
            r_en = ("### Usage History & Analytics\n\n"
                    "You can view your history and analytics across the application:\n"
                    "• **Readings Page**: View all historical meter scans, OCR confidence scores, and notes.\n"
                    "• **Dashboard**: See your 6-month usage trends and estimated current month bill.\n"
                    "• **Analytics Page**: Comparative analysis showing peak days and efficiency scores (A+ to C).\n"
                    "• **CSV Export**: Download your entire history in Excel-compatible format from the Readings page.")
            
        elif any(w in msg_en for w in ['alert','notification','warning','threshold','notify']):
            r_en = ("### Usage Alerts & Reminders\n\n"
                    "Go to the Alerts page to configure warning notifications:\n"
                    "• **High Usage**: Alert when consumption exceeds your target.\n"
                    "• **Bill Threshold**: Alert when estimated bill amount exceeds a budget.\n"
                    "• **Missed Scans**: Get reminders to capture readings regularly.")
            
        elif any(w in msg_en for w in ['budget','limit','spending','budget planner']):
            r_en = ("### Budget Planner\n\n"
                    "Set monthly spending limits in the **Budget Planner** (under the Alerts page). "
                    "It tracks your estimated daily spend vs target budget and sends warnings before you exceed your limit. "
                    "Setting a budget 10% lower than your average bill is a proven way to reduce energy waste.")
            
        elif any(w in msg_en for w in ['tip','save energy','reduce','saving','efficient','lower bill']):
            r_en = ("### Professional Energy Saving Tips:\n\n"
                    "1. **Lighting**: Switch to LED bulbs to save up to 75% energy compared to incandescent lights.\n"
                    "2. **Thermostat**: Set your air conditioner to 24°C. Every degree lower increases consumption by 6%.\n"
                    "3. **Phantom Load**: Unplug electronics and chargers when not in use to save up to 10% on standby energy.\n"
                    "4. **Load Management**: Run high-consumption appliances (washing machines, water heaters) during off-peak hours (10 PM – 6 AM).")
            
        elif any(w in msg_en for w in ['export','download','csv','report','data']):
            r_en = ("### Data Export\n\n"
                    "You can download your meter reading history as a CSV file. Go to the **Readings** page, click the "
                    "**Export to CSV** button, and import it into Excel or Google Sheets for custom analysis.")
            
        elif any(w in msg_en for w in ['maintenance','service','repair','schedule']):
            r_en = ("### Meter Maintenance\n\n"
                    "Regular inspection prevents errors. In the **Settings -> Maintenance** tab, you can schedule meter "
                    "inspections, log completed services, and receive alerts when maintenance is due.")
            
        elif any(w in msg_en for w in ['complaint','support','contact','dispute','wrong reading']):
            r_en = ("### Support & Complaints\n\n"
                    "If you notice a billing discrepancy or scanning issue, you can file a formal complaint under "
                    "**Settings -> Complaints** or contact support:\n"
                    "• **Email**: support@meterscanner.com\n"
                    "• **Helpline**: 1800-123-4567 (Toll-Free, 24/7)")
            
        elif any(w in msg_en for w in ['login','register','sign up','account','profile','password','google','logout']):
            r_en = ("### Account & Access Management\n\n"
                    "We support login via standard username/password or Google OAuth. "
                    "You can update your personal profile, phone number, address, and change passwords in "
                    "**Settings -> Profile**. To enable Google Login, configure client IDs in the environment.")
            
        elif any(w in msg_en for w in ['dashboard','overview','summary']):
            r_en = ("### Dashboard Overview\n\n"
                    "The Dashboard is your main control center. It shows units consumed, bill projections, "
                    "efficiency ratings, 6-month visual consumption trends, and quick access buttons to scan, calculate bills, or plan budgets.")
            
        elif any(w in msg_en for w in ['blurry','blur','not detected','dark','glare','problem','issue','cannot scan','trouble']):
            r_en = ("### Scanning & OCR Troubleshooting\n\n"
                    "• **Blurry Image**: Clean your camera lens, hold the phone steady, and maintain a distance of 15-25cm.\n"
                    "• **Poor Lighting**: Turn on your device flash/torch before capturing.\n"
                    "• **Reflection/Glare**: Tilt the camera slightly to avoid direct light reflection.\n"
                    "• **Alternative**: If automatic OCR fails, you can use the **Manual Entry** option on the scanning screen.")
            
        elif any(w in msg_en for w in ['thank','thanks','great','awesome','nice','helpful']):
            r_en = "You are very welcome! 😊 I am glad I could assist you. Let me know if you need anything else."
            
        elif any(w in msg_en for w in ['bye','goodbye','see you']):
            r_en = "Thank you for using Meter Scanner Pro. Goodbye, and have a great day! ⚡"
            
        elif len(nums) >= 2:
            u, rate = float(nums[0]), float(nums[1])
            energy = u * rate; gst = energy * 0.18; total = energy + gst + 25
            r_en = (f"### Billing Projection\n\n"
                    f"Consumption of **{u} units** at a rate of **₹{rate:.2f}/unit** results in an estimated energy charge of "
                    f"₹{energy:.2f}. Adding fixed rent (₹25) and GST (₹{gst:.2f}) brings the total bill estimate to **₹{total:.2f}**.")
            
        elif len(nums) == 1:
            u = float(nums[0])
            r_en = (f"Recognized consumption of **{u} kWh**. To calculate the total cost, please mention the tariff rate per unit, "
                    f"or say *'calculate bill for {u} units'*.")
            
        else:
            # General professional default response
            r_en = ("I am MeterBot 🤖, your utility management assistant. I specialize in answering questions about: "
                    "meter scanning (OCR), bill calculations, consumption history, energy-saving recommendations, and alerts. "
                    "Could you please specify how I can assist you with your utility management today?")
            
        # Translate response back to original language (if not English and translation worked)
        if detected_lang and detected_lang not in ['en', 'english']:
            try:
                from deep_translator import GoogleTranslator
                r = GoogleTranslator(source='en', target=detected_lang).translate(r_en)
            except Exception as e:
                logger.error(f"Failed to translate response back to {detected_lang}: {e}")
                r = r_en
        else:
            r = r_en
            
        return jsonify({'response': r, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        
    except Exception as e:
        logger.error(f'Chat error: {e}')
        return jsonify({'response': 'An error occurred. Please try again.', 'error': str(e)}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, username))
                user = c.fetchone()
                
                if user and check_password_hash(user['password'], password):
                    keys = user.keys()
                    user_obj = User(
                        id=user['id'], username=user['username'], password=user['password'],
                        email=user['email'] if 'email' in keys else '',
                        first_name=user['first_name'] if 'first_name' in keys else '',
                        last_name=user['last_name'] if 'last_name' in keys else '',
                        phone=user['phone'] if 'phone' in keys else '',
                        address=user['address'] if 'address' in keys else '',
                        google_id=user['google_id'] if 'google_id' in keys else '',
                    )
                    login_user(user_obj)
                    flash('Logged in successfully!', 'success')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid username/email or password', 'error')
            finally:
                conn.close()
    
    return render_template('login.html')

@app.route('/google_login')
def google_login():
    """Redirect user to Google OAuth consent screen."""
    if GOOGLE_CLIENT_ID == 'your-google-client-id':
        flash('Google login is not configured yet. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.', 'warning')
        return redirect(url_for('login'))
    try:
        # Fetch Google's OpenID configuration
        oidc_config = requests.get(GOOGLE_DISCOVERY_URL, timeout=5).json()
        authorization_endpoint = oidc_config['authorization_endpoint']
    except Exception as e:
        logger.error(f'Failed to fetch OIDC config: {e}')
        flash('Google login is currently unavailable. Please try again later.', 'danger')
        return redirect(url_for('login'))

    import secrets as _secrets
    state = _secrets.token_urlsafe(16)
    session['oauth_state'] = state

    redirect_uri = url_for('google_callback', _external=True)
    if '127.0.0.1' in redirect_uri:
        redirect_uri = redirect_uri.replace('127.0.0.1', 'localhost')
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'online',
    }
    auth_url = authorization_endpoint + '?' + urlencode(params)
    return redirect(auth_url)


@app.route('/google/callback')
def google_callback():
    """Handle Google OAuth callback and log the user in."""
    # Verify state to prevent CSRF
    if request.args.get('state') != session.pop('oauth_state', None):
        flash('Invalid OAuth state. Please try again.', 'danger')
        return redirect(url_for('login'))

    code = request.args.get('code')
    if not code:
        error = request.args.get('error', 'Unknown error')
        flash(f'Google login failed: {error}', 'danger')
        return redirect(url_for('login'))

    try:
        oidc_config = requests.get(GOOGLE_DISCOVERY_URL, timeout=5).json()
        token_endpoint = oidc_config['token_endpoint']
        userinfo_endpoint = oidc_config['userinfo_endpoint']
    except Exception as e:
        logger.error(f'Failed to fetch OIDC config in callback: {e}')
        flash('Google login is currently unavailable. Please try again later.', 'danger')
        return redirect(url_for('login'))

    # Exchange code for tokens
    redirect_uri = url_for('google_callback', _external=True)
    if '127.0.0.1' in redirect_uri:
        redirect_uri = redirect_uri.replace('127.0.0.1', 'localhost')
    try:
        token_resp = requests.post(
            token_endpoint,
            data={
                'code': code,
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except Exception as e:
        logger.error(f'Token exchange failed: {e}')
        flash('Google login failed during token exchange. Please try again.', 'danger')
        return redirect(url_for('login'))

    # Fetch user info
    try:
        userinfo_resp = requests.get(
            userinfo_endpoint,
            headers={'Authorization': f'Bearer {tokens["access_token"]}'},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()
    except Exception as e:
        logger.error(f'Userinfo fetch failed: {e}')
        flash('Could not fetch your Google profile. Please try again.', 'danger')
        return redirect(url_for('login'))

    if not userinfo.get('email_verified', False):
        flash('Your Google email is not verified. Please verify it and try again.', 'warning')
        return redirect(url_for('login'))

    google_id  = userinfo.get('sub')
    email      = userinfo.get('email', '')
    given_name = userinfo.get('given_name', '')
    family_name= userinfo.get('family_name', '')
    # Build a unique username from the email local part
    base_username = email.split('@')[0].replace('.', '_').lower()

    conn = get_db_connection()
    try:
        c = conn.cursor()
        # Try find by google_id first
        c.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
        user_row = c.fetchone()

        if not user_row:
            # Try find by email
            if email:
                c.execute("SELECT * FROM users WHERE email = ?", (email,))
                user_row = c.fetchone()
            if not user_row:
                # Try find by username derived from email
                c.execute("SELECT * FROM users WHERE username = ?", (base_username,))
                user_row = c.fetchone()
            if user_row:
                # Link existing account with Google
                c.execute(
                    "UPDATE users SET google_id=?, first_name=?, last_name=?, email=? WHERE id=?",
                    (google_id, given_name, family_name, email, user_row['id'])
                )
                conn.commit()
            else:
                # Create new account — no password needed for OAuth users
                from werkzeug.security import generate_password_hash as _gph
                import secrets as _s
                dummy_pw = _gph(_s.token_hex(24))
                c.execute(
                    "INSERT INTO users (username, password, google_id, email, first_name, last_name) VALUES (?,?,?,?,?,?)",
                    (base_username, dummy_pw, google_id, email, given_name, family_name)
                )
                conn.commit()
                c.execute("SELECT * FROM users WHERE username = ?", (base_username,))
                user_row = c.fetchone()


        user_obj = User(
            id=user_row['id'], username=user_row['username'], password=user_row['password'],
            email=email,
            first_name=given_name,
            last_name=family_name,
            google_id=google_id,
        )
        login_user(user_obj)
        flash(f'Welcome, {given_name or user_row["username"]}! Logged in with Google.', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f'Google OAuth DB error: {e}')
        flash('An error occurred during Google login. Please try again.', 'danger')
        return redirect(url_for('login'))
    finally:
        conn.close()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email', '')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not username or not password or not confirm_password:
            flash('All fields are required', 'error')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        
        conn = get_db_connection()
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username = ?", (username,))
                existing_user = c.fetchone()
                
                if existing_user:
                    flash('Username already exists', 'error')
                    return redirect(url_for('register'))
                
                if email:
                    c.execute("SELECT * FROM users WHERE email = ?", (email,))
                    existing_email = c.fetchone()
                    if existing_email:
                        flash('Email already registered', 'error')
                        return redirect(url_for('register'))
                
                c.execute("INSERT INTO users (username, password, email) VALUES (?, ?, ?)",
                         (username, hashed_password, email))
                conn.commit()
                flash('Registration successful! Please login.', 'success')
                return redirect(url_for('login'))
            except Error as e:
                flash('An error occurred. Please try again.', 'error')
            finally:
                conn.close()
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Get recent readings for history
        c.execute("""
            SELECT id, reading_value, confidence, status, notes, timestamp, image_path
            FROM readings 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 10
        """, (current_user.id,))
        
        recent_readings = c.fetchall()
        
        # Get current month stats
        c.execute("""
            SELECT AVG(CAST(reading_value AS REAL)) as current_month_avg,
                   COUNT(*) as current_month_count,
                   MAX(CAST(reading_value AS REAL)) as current_month_max,
                   MIN(CAST(reading_value AS REAL)) as current_month_min
            FROM readings 
            WHERE user_id = ? 
            AND strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
        """, (current_user.id,))
        
        current_stats = c.fetchone()
        
        # Get previous month stats for comparison
        c.execute("""
            SELECT AVG(CAST(reading_value AS REAL)) as prev_month_avg
            FROM readings 
            WHERE user_id = ? 
            AND strftime('%Y-%m', timestamp) = strftime('%Y-%m', date('now', '-1 month'))
        """, (current_user.id,))
        
        prev_stats = c.fetchone()
        
        # Calculate estimated bill based on current usage
        current_avg = current_stats['current_month_avg'] if current_stats['current_month_avg'] else 0
        prev_avg = prev_stats['prev_month_avg'] if prev_stats['prev_month_avg'] else 0
        
        # Simple bill calculation
        estimated_bill = current_avg * 4.50 if current_avg else 0  # Base rate
        
        # Calculate usage change percentage
        usage_change = 0
        if prev_avg > 0:
            usage_change = ((current_avg - prev_avg) / prev_avg) * 100
        
        # Get monthly data for charts
        c.execute("""
            SELECT strftime('%Y-%m', timestamp) as month, 
                   AVG(CAST(reading_value AS REAL)) as avg_reading,
                   COUNT(*) as reading_count
            FROM readings 
            WHERE user_id = ? 
            AND timestamp >= date('now', '-6 months')
            GROUP BY strftime('%Y-%m', timestamp)
            ORDER BY month
        """, (current_user.id,))
        
        monthly_data = []
        for row in c.fetchall():
            monthly_data.append({
                'month': row['month'],
                'avg_reading': round(row['avg_reading'], 2) if row['avg_reading'] else 0,
                'reading_count': row['reading_count']
            })
        
        dashboard_data = {
            'recent_readings': [dict(reading) for reading in recent_readings],
            'current_month_avg': round(current_avg, 2),
            'current_month_count': current_stats['current_month_count'] or 0,
            'current_month_max': round(current_stats['current_month_max'], 2) if current_stats['current_month_max'] else 0,
            'estimated_bill': round(estimated_bill, 2),
            'usage_change': round(usage_change, 1),
            'monthly_data': monthly_data,
            'efficiency_score': 'A+' if usage_change < 0 else 'B' if usage_change < 10 else 'C'
        }
        
        return render_template("dashboard.html", **dashboard_data)
        
    finally:
        conn.close()

@app.route('/meterbot')
@login_required
def meterbot():
    """MeterBot AI Assistant page"""
    return render_template('meterbot.html')

@app.route('/settings')
@login_required
def settings():
    """Settings page with profile, account, and complaint options"""
    conn = get_db_connection()
    complaints = []
    if conn is not None:
        try:
            c = conn.cursor()
            c.execute("""
                SELECT complaint_id, type, subject, description, priority, status, created_at
                FROM complaints
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 5
            """, (current_user.id,))
            complaints = c.fetchall()
        except sqlite3.Error as e:
            app.logger.error(f"Error fetching complaints: {e}")
        finally:
            conn.close()
    return render_template("settings.html", complaints=complaints)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    """Update user profile information"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute("""
            UPDATE users 
            SET first_name = ?, last_name = ?, phone = ?, address = ?
            WHERE id = ?
        """, (
            data.get('first_name'),
            data.get('last_name'),
            data.get('phone'),
            data.get('address'),
            current_user.id
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Profile updated successfully!'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """Change user password"""
    try:
        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        # Verify current password
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE id = ?", (current_user.id,))
        user = c.fetchone()
        
        if not user or not check_password_hash(user[0], current_password):
            return jsonify({'success': False, 'error': 'Current password is incorrect'})
        
        # Update password
        hashed_password = generate_password_hash(new_password)
        c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_password, current_user.id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Password changed successfully!'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/submit_complaint', methods=['POST'])
@login_required
def submit_complaint():
    """Submit a complaint"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        c = conn.cursor()
        
        # Generate complaint ID
        complaint_id = f"CMP-{datetime.now().strftime('%Y')}-{random.randint(1000, 9999)}"
        
        c.execute("""
            INSERT INTO complaints 
            (user_id, complaint_id, type, subject, description, priority, contact_method, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            current_user.id,
            complaint_id,
            data.get('type'),
            data.get('subject'),
            data.get('description'),
            data.get('priority'),
            data.get('contact_method'),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        
        conn.commit()
        conn.close()
        
        # Send email notification (implement email sending logic here)
        
        return jsonify({
            'success': True, 
            'message': 'Complaint submitted successfully!',
            'complaint_id': complaint_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/capture')
@login_required
def capture():
    return render_template('capture.html')

def extract_meter_number(image, debug_mode=False):
    """
    Enhanced meter number extraction with improved preprocessing and digit detection.
    
    Args:
        image: Input image in BGR format
        debug_mode: If True, returns debug information and images
        
    Returns:
        If debug_mode is False: Detected meter number as string
        If debug_mode is True: Tuple of (detected_number, debug_info, processed_images)
    """
    try:
        debug_info = []
        processed_images = {}
        
        # Convert to grayscale and store for debug
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if debug_mode:
            processed_images['01_original_gray'] = gray.copy()
        
        # Get center region of the image (where meter likely is)
        height, width = gray.shape
        center_y, center_x = height // 2, width // 2
        crop_height = int(height * 0.8)  # Increased to 80% to capture more context
        crop_width = int(width * 0.9)
        
        # Crop to center region with boundary checks
        crop_y1 = max(0, center_y - crop_height//2)
        crop_y2 = min(height, center_y + crop_height//2)
        crop_x1 = max(0, center_x - crop_width//2)
        crop_x2 = min(width, center_x + crop_width//2)
        gray_cropped = gray[crop_y1:crop_y2, crop_x1:crop_x2]
        
        if debug_mode:
            processed_images['02_cropped'] = gray_cropped.copy()
        
        # --- Enhanced Preprocessing Pipeline ---
        # Method 1: Standard preprocessing
        processed_results = []
        
        # 1. Denoise with bilateral filter (preserves edges better)
        denoised = cv2.bilateralFilter(gray_cropped, 9, 75, 75)
        
        # 2. Contrast enhancement using CLAHE
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        clahe_applied = clahe.apply(denoised)
        
        # 3. Multiple thresholding approaches
        methods = []
        
        # Method A: Adaptive threshold
        binary_adaptive = cv2.adaptiveThreshold(
            clahe_applied, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY_INV, 15, 8
        )
        methods.append(('adaptive', binary_adaptive))
        
        # Method B: Otsu threshold
        _, binary_otsu = cv2.threshold(clahe_applied, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        methods.append(('otsu', binary_otsu))
        
        # Method C: Local threshold with different parameters
        binary_local = cv2.adaptiveThreshold(
            clahe_applied, 255, 
            cv2.ADAPTIVE_THRESH_MEAN_C, 
            cv2.THRESH_BINARY_INV, 11, 5
        )
        methods.append(('local', binary_local))
        
        if debug_mode:
            processed_images['03_denoised'] = denoised
            processed_images['04_clahe'] = clahe_applied
            processed_images['05_adaptive'] = binary_adaptive
            processed_images['06_otsu'] = binary_otsu
            processed_images['07_local'] = binary_local
        
        # Try each method and collect results
        best_result = ""
        best_confidence = 0
        best_method = ""
        
        for method_name, binary_img in methods:
            # Morphological operations to clean up
            kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            kernel_medium = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            
            cleaned = cv2.morphologyEx(binary_img, cv2.MORPH_CLOSE, kernel_small)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel_small)
            
            # Find contours
            contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter contours for digit-like shapes
            digit_contours = []
            img_height, img_width = cleaned.shape
            min_area = 50
            max_area = (img_height * img_width) * 0.1  # Max 10% of image area
            
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = cv2.contourArea(contour)
                aspect_ratio = w / float(h) if h > 0 else 0
                
                # Enhanced filtering for digits
                if (min_area < area < max_area and 
                    0.15 < aspect_ratio < 1.5 and  # Wider aspect ratio range
                    h > 10 and w > 5 and  # Minimum size requirements
                    h < img_height * 0.5 and w < img_width * 0.3):  # Maximum size limits
                    digit_contours.append((x, y, w, h, area, aspect_ratio))
            
            # Sort contours by area descending to keep the most significant (largest) candidate digits,
            # up to a maximum of 8 contours, then sort them left-to-right to prevent performance explosion on noise.
            if len(digit_contours) > 8:
                digit_contours.sort(key=lambda x: x[4], reverse=True)
                digit_contours = digit_contours[:8]
            digit_contours.sort(key=lambda x: x[0])
            
            # Extract digits using multiple OCR approaches
            method_result = ""
            method_confidences = []
            
            for i, (x, y, w, h, area, aspect_ratio) in enumerate(digit_contours):
                # Extract ROI from the original grayscale image (better for OCR)
                roi = gray_cropped[y:y+h, x:x+w]
                
                # Multiple preprocessing for OCR
                roi_results = []
                
                # Approach 1: Direct OCR
                roi_enhanced = cv2.resize(roi, (w*3, h*3), interpolation=cv2.INTER_CUBIC)
                _, roi_thresh = cv2.threshold(roi_enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                
                # Approach 2: Inverted
                roi_inverted = cv2.bitwise_not(roi_thresh)
                

                
                for roi_version in [roi_thresh, roi_inverted]:
                    # Add padding
                    padded = cv2.copyMakeBorder(roi_version, 10, 10, 10, 10, 
                                              cv2.BORDER_CONSTANT, value=255 if roi_version is roi_inverted else 0)
                    
                    # Single character PSM is best suited for individual cropped digits
                    configs = [
                        r'--oem 3 --psm 10 -c tessedit_char_whitelist=0123456789'
                    ]
                    
                    for config in configs:
                        try:
                            result = pytesseract.image_to_string(padded, config=config)
                            data = pytesseract.image_to_data(padded, config=config, output_type=pytesseract.Output.DICT)
                            
                            if data['text'] and len(data['text']) > 0 and data['text'][0].strip():
                                digit = data['text'][0].strip()
                                if digit.isdigit():
                                    confidence = float(data['conf'][0]) / 100.0
                                    if confidence > 0.5:  # Minimum confidence threshold
                                        roi_results.append((digit, confidence))
                                        break
                        except:
                            continue
                    
                    if roi_results:
                        break
                
                # Take the best result for this ROI
                if roi_results:
                    best_digit, best_digit_conf = max(roi_results, key=lambda x: x[1])
                    method_result += best_digit
                    method_confidences.append(best_digit_conf)
            
            # Calculate method confidence
            method_avg_conf = sum(method_confidences) / len(method_confidences) if method_confidences else 0
            
            # Update best result if this method is better (longer sequence, or same length with higher confidence)
            if len(method_result) >= 2:
                if (not best_result or 
                    len(method_result) > len(best_result) or 
                    (len(method_result) == len(best_result) and method_avg_conf > best_confidence)):
                    best_result = method_result
                    best_confidence = method_avg_conf
                    best_method = method_name
        
        # If we successfully extracted digit contours, return the best candidate
        if best_result:
            if debug_mode:
                debug_info = {
                    'detected_number': best_result,
                    'confidence': best_confidence,
                    'method_used': best_method,
                    'num_digits': len(best_result),
                    'validation': 'success'
                }
                return best_result, debug_info, processed_images
            return best_result
        
        # Fallback 1: Try whole image OCR with multiple PSM modes
        try:
            # Enhance the entire cropped image
            enhanced = cv2.resize(gray_cropped, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(enhanced)
            _, enhanced_thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Try modes for single block of text vs single line vs sparse numbers
            for psm in ['6', '7', '11']:
                whole_config = f'--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789'
                whole_result = pytesseract.image_to_string(enhanced_thresh, config=whole_config)
                
                # Extract numbers from the result
                nums = re.findall(r'\d+', whole_result)
                if nums:
                    # Take the longest numeric string found
                    fallback_result = max(nums, key=len)
                    if len(fallback_result) >= 2:
                        if debug_mode:
                            fallback_info = {
                                'detected_number': fallback_result,
                                'confidence': 0.70,
                                'method_used': f'fallback_psm_{psm}',
                                'num_digits': len(fallback_result),
                                'validation': 'success'
                            }
                            return fallback_result, fallback_info, processed_images
                        return fallback_result
        except Exception as e:
            logger.error(f'Fallback 1 failed: {e}')
        
        if debug_mode:
            debug_info = {
                'detected_number': None,
                'confidence': 0,
                'method_used': 'none',
                'num_digits': 0,
                'validation': 'failed'
            }
            return None, debug_info, processed_images
        
        return None
        
    except Exception as e:
        logger.error(f"Error in extract_meter_number: {str(e)}")
        if debug_mode:
            debug_info = {'error': str(e)}
            return None, debug_info, {}
        return None

@app.route('/gen_frames')
@login_required
def gen_frames():
    global camera
    try:
        if camera is None:
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Add CAP_DSHOW for Windows
            if not camera.isOpened():
                logger.error("Failed to open camera")
                return
            
            # Wait a bit for camera to initialize
            time.sleep(0.5)
            
            # Set camera properties
            camera.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            # Verify settings were applied
            if not camera.get(cv2.CAP_PROP_FRAME_WIDTH) == 1280 or not camera.get(cv2.CAP_PROP_FRAME_HEIGHT) == 720:
                logger.warning("Camera resolution could not be set to 1280x720")
        
        while True:
            with camera_lock:
                if camera is None:
                    # In case it was released outside
                    break
                success, frame = camera.read()
                
            if not success:
                logger.warning("Failed to grab frame in gen_frames")
                time.sleep(0.1)  # Add small delay before retry
                continue
                
            try:
                # Add timestamp
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cv2.putText(frame, timestamp, (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                
                # Add alignment rectangle
                height, width = frame.shape[:2]
                center_x = width // 2
                center_y = height // 2
                rect_width = 400
                rect_height = 200
                
                cv2.rectangle(frame, 
                            (center_x - rect_width//2, center_y - rect_height//2),
                            (center_x + rect_width//2, center_y + rect_height//2),
                            (0, 255, 0), 2)
                
                # Add guide text
                cv2.putText(frame, "Align meter within the box", 
                           (center_x - 150, center_y - rect_height//2 - 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                
                # Convert frame to jpg
                ret, buffer = cv2.imencode('.jpg', frame)
                if not ret:
                    logger.warning("Failed to encode frame")
                    continue
                    
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            except Exception:
                logger.exception("Error processing frame")
                time.sleep(0.1)  # Add small delay before retry
                continue
    except Exception as e:
        logger.exception("Camera error")
        if camera is not None:
            camera.release()
            camera = None

@app.route('/video_feed')
@login_required
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# AMR: System health for readiness checks
@app.route('/health')
@login_required
def health():
    status = {
        'database': False,
        'tesseract': False,
        'camera': False
    }
    # DB check
    try:
        conn = get_db_connection()
        if conn is not None:
            c = conn.cursor()
            c.execute('SELECT 1')
            status['database'] = True
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # Tesseract check
    try:
        if pytesseract is not None:
            _ = pytesseract.get_tesseract_version()
            status['tesseract'] = True
    except Exception:
        status['tesseract'] = False
    # Camera check using lock and existing instance
    try:
        with camera_lock:
            if camera is not None and camera.isOpened():
                ret, _ = camera.read()
                status['camera'] = bool(ret)
            else:
                # Try opening briefly if not open
                temp_cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                status['camera'] = temp_cam.isOpened()
                temp_cam.release()
    except Exception:
        status['camera'] = False
    return jsonify({'ok': all(status.values()), 'status': status})

@app.route('/take_photo', methods=['POST'])
@login_required
def take_photo():
    global camera
    try:
        if camera is None:
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Add CAP_DSHOW for Windows
            # Set focus to auto
            camera.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            # Set resolution to 1280x720
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            # Wait for camera to initialize
            time.sleep(0.5)
        
        if not camera.isOpened():
            logger.error("take_photo: camera not opened")
            return jsonify({'success': False, 'error': 'Could not access camera'})
        
        # Capture multiple frames and pick the sharpest
        best_frame = None
        best_focus = -1.0
        capture_count = 5
        
        with camera_lock:
            for _ in range(3): # Clear buffer
                camera.read()
                
            for _ in range(capture_count):
                success, frm = camera.read()
                if not success:
                    time.sleep(0.05)
                    continue
                gray = cv2.cvtColor(frm, cv2.COLOR_BGR2GRAY)
                focus = cv2.Laplacian(gray, cv2.CV_64F).var()
                if focus > best_focus:
                    best_focus = focus
                    best_frame = frm
                time.sleep(0.03)

        if best_frame is None:
            logger.warning("take_photo: no clear frame captured")
            return jsonify({'success': False, 'error': 'Failed to capture a clear frame'})
        
        frame = best_frame
        
        # Save the original image
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'meter_{timestamp}.jpg'
        filepath = os.path.join('static', 'uploads', filename)
        
        # Ensure uploads directory exists
        os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
        
        # Save original image
        cv2.imwrite(os.path.join(app.root_path, filepath), frame)
        
        # Process the image with unified return type handling
        ocr_result = extract_meter_number(frame, debug_mode=False)
        
        # Unified handling for result (whether it is a string or dictionary)
        sanitized_value = None
        conf = 0.0
        status_flag = 'rejected'
        debug_img_name = None

        if ocr_result is None:
            # Not detected
            response_data = {
                'success': True,
                'image_path': filename,
                'error': 'Reading not clear or no digits found. Try again with better light.',
                'message': 'Image captured, but OCR failed.'
            }
        elif isinstance(ocr_result, str):
            # Simple string match from extract_meter_number
            sanitized_value = re.sub(r"\D", "", ocr_result)
            conf = 75.0 if len(sanitized_value) >= 4 else 55.0  # Estimated confidence for simple extraction
            status_flag = 'auto' if len(sanitized_value) >= 4 else 'review'
            response_data = {
                'success': True,
                'image_path': filename,
                'meter_number': sanitized_value,
                'confidence': conf,
                'message': 'Reading extracted successfully'
            }
        elif isinstance(ocr_result, dict):
            # Complex result dictionary (if I update extract_meter_number to return dict)
            sanitized_value = ocr_result.get('value')
            conf = float(ocr_result.get('confidence') or 0)
            status_flag = ocr_result.get('status', 'review')
            debug_img_name = ocr_result.get('debug_image')
            response_data = {
                'success': True,
                'image_path': filename,
                'meter_number': sanitized_value,
                'confidence': conf,
                'debug_image': debug_img_name,
                'message': ocr_result.get('message', 'Reading extracted successfully')
            }
        
        # Determine status flag final
        if sanitized_value and len(sanitized_value) > 0:
            status_flag = 'auto' if conf > 70 else 'review'
        else:
            status_flag = 'rejected'

        # Save to database
        conn = get_db_connection()
        if conn is not None:
            try:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO readings (user_id, image_path, reading_value, confidence, debug_image, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (current_user.id, filename, sanitized_value, conf, debug_img_name, status_flag))
                conn.commit()
            finally:
                conn.close()

        return jsonify(response_data)
        
    except Exception as e:
        logger.exception("Photo capture error")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/close_camera', methods=['POST'])
@login_required
def close_camera():
    global camera
    if camera is not None:
        camera.release()
        camera = None
    return jsonify({'success': True})

@app.route('/readings')
@login_required
def readings():
    conn = get_db_connection()
    if conn is not None:
        try:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM readings 
                WHERE user_id = ? 
                ORDER BY timestamp DESC
            """, (current_user.id,))
            readings = c.fetchall()
            return render_template('readings.html', readings=readings)
        finally:
            conn.close()
    return render_template('readings.html', readings=[])

# AMR: JSON API for readings
@app.route('/api/readings', methods=['GET'])
@login_required
def api_readings():
    conn = get_db_connection()
    items = []
    if conn is not None:
        try:
            c = conn.cursor()
            c.execute(
                """
                SELECT id, image_path, reading_value, confidence, debug_image, status, timestamp
                FROM readings
                WHERE user_id = ?
                ORDER BY timestamp DESC
                """,
                (current_user.id,)
            )
            rows = c.fetchall()
            for r in rows:
                items.append({
                    'id': r['id'],
                    'image_path': r['image_path'],
                    'reading_value': r['reading_value'],
                    'confidence': r['confidence'],
                    'debug_image': r['debug_image'],
                    'status': r['status'],
                    'timestamp': r['timestamp']
                })
        finally:
            conn.close()
    return jsonify({'count': len(items), 'items': items})

# AMR: CSV export for readings
@app.route('/export/readings.csv', methods=['GET'])
@login_required
def export_readings_csv():
    conn = get_db_connection()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'timestamp', 'reading_value', 'confidence', 'status', 'debug_image', 'image_path'])
    if conn is not None:
        try:
            c = conn.cursor()
            c.execute(
                """
                SELECT id, timestamp, reading_value, confidence, status, debug_image, image_path
                FROM readings
                WHERE user_id = ?
                ORDER BY timestamp DESC
                """,
                (current_user.id,)
            )
            for row in c.fetchall():
                writer.writerow([row['id'], row['timestamp'], row['reading_value'], row['confidence'], row['status'], row['debug_image'], row['image_path']])
        finally:
            conn.close()
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    filename = f"readings_{current_user.id}.csv"
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=filename)

@app.route('/delete_reading/<int:reading_id>', methods=['POST'])
def delete_reading(reading_id):
    conn = get_db_connection()
    if conn is not None:
        try:
            # Get the image path before deleting
            c = conn.cursor()
            c.execute("SELECT image_path FROM readings WHERE id = ?", (reading_id,))
            reading = c.fetchone()
            
            if reading and reading['image_path']:
                # Delete the image file
                image_path = os.path.join(app.static_folder, 'uploads', reading['image_path'])
                if os.path.exists(image_path):
                    os.remove(image_path)
            
            # Delete the reading from database
            c.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
            conn.commit()
            
            flash('Reading deleted successfully', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Error deleting reading: {str(e)}', 'error')
        finally:
            conn.close()
    
    return redirect(url_for('readings'))

@app.route('/analytics')
@login_required
def analytics():
    conn = get_db_connection()
    if conn is not None:
        try:
            c = conn.cursor()
            
            # Get total readings count
            c.execute("""
                SELECT COUNT(*) as total_readings
                FROM readings 
                WHERE user_id = ?
            """, (current_user.id,))
            total_readings = c.fetchone()['total_readings']
            
            # Get readings by month (last 6 months)
            six_months_ago = datetime.now() - timedelta(days=180)
            c.execute("""
                SELECT 
                    strftime('%Y-%m', timestamp) as month,
                    COUNT(*) as count
                FROM readings 
                WHERE user_id = ? 
                    AND timestamp >= ?
                GROUP BY strftime('%Y-%m', timestamp)
                ORDER BY month DESC
            """, (current_user.id, six_months_ago))
            monthly_data = c.fetchall()
            
            # Format monthly data for chart
            months = []
            counts = []
            for row in monthly_data:
                year, month = row['month'].split('-')
                month_name = calendar.month_abbr[int(month)]
                months.append(f"{month_name} {year}")
                counts.append(row['count'])
            
            # Get readings by day of week
            c.execute("""
                SELECT 
                    strftime('%w', timestamp) as day_of_week,
                    COUNT(*) as count
                FROM readings 
                WHERE user_id = ?
                GROUP BY strftime('%w', timestamp)
                ORDER BY day_of_week
            """, (current_user.id,))
            daily_data = c.fetchall()
            
            # Format daily data
            days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            daily_counts = [0] * 7
            for row in daily_data:
                daily_counts[int(row['day_of_week'])] = row['count']
            
            # Get recent activity
            c.execute("""
                SELECT timestamp
                FROM readings 
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 5
            """, (current_user.id,))
            recent_activity = c.fetchall()
            
            return render_template('analytics.html',
                                total_readings=total_readings,
                                months=json.dumps(months),
                                counts=json.dumps(counts),
                                days=json.dumps(days),
                                daily_counts=json.dumps(daily_counts),
                                recent_activity=recent_activity)
        finally:
            conn.close()
    return render_template('analytics.html')

@app.route('/generate_bill/<int:reading_id>')
def generate_bill(reading_id):
    conn = get_db_connection()
    if conn is not None:
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM readings WHERE id = ?", (reading_id,))
            reading = c.fetchone()
            
            # Get previous reading
            c.execute("""
                SELECT * FROM readings 
                WHERE user_id = ? AND timestamp < ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (reading['user_id'], reading['timestamp']))
            prev_reading = c.fetchone()
            
            # Calculate units consumed (robust, non-negative)
            def to_float_safe(val):
                try:
                    return float(val)
                except Exception:
                    return 0.0
            current_val = to_float_safe(reading['reading_value'])
            prev_val = to_float_safe(prev_reading['reading_value']) if prev_reading else 0.0
            units_consumed = max(0.0, current_val - prev_val)
            
            # Get season and connection type
            reading_date = datetime.strptime(reading['timestamp'], '%Y-%m-%d %H:%M:%S')
            season = get_season(reading_date)
            connection_type = 'residential'  # You can make this dynamic based on user profile
            
            # Calculate charges
            energy_charges, slab_breakup = calculate_slab_charges(
                units_consumed, 
                season,
                'normal',  # Default to normal time-of-day rate
                connection_type
            )
            
            # Calculate additional charges
            fixed_charge = FIXED_CHARGES[connection_type]
            fuel_surcharge = energy_charges * FUEL_SURCHARGE
            electricity_duty = energy_charges * ELECTRICITY_DUTY
            subtotal = energy_charges + fixed_charge + fuel_surcharge + electricity_duty + METER_RENT
            gst_amount = subtotal * GST_RATE
            total_amount = subtotal + gst_amount
            
            # Calculate monthly average
            c.execute("""
                SELECT AVG(reading_value) as avg_reading
                FROM readings
                WHERE user_id = ?
                AND timestamp >= date(?, '-3 months')
            """, (reading['user_id'], reading['timestamp']))
            avg_result = c.fetchone()
            monthly_average = avg_result['avg_reading'] if avg_result['avg_reading'] else 0
            
            bill_data = {
                'reading_id': reading_id,
                'current_reading': reading['reading_value'],
                'previous_reading': prev_reading['reading_value'] if prev_reading else 0,
                'units_consumed': round(units_consumed, 2),
                'monthly_average': round(monthly_average, 2),
                'connection_type': connection_type.title(),
                'season': season.title(),
                'season_multiplier': SEASONAL_RATES[season],
                'slab_breakup': slab_breakup,
                'energy_charges': round(energy_charges, 2),
                'fixed_charge': fixed_charge,
                'meter_rent': METER_RENT,
                'fuel_surcharge_rate': FUEL_SURCHARGE * 100,
                'fuel_surcharge': round(fuel_surcharge, 2),
                'electricity_duty_rate': ELECTRICITY_DUTY * 100,
                'electricity_duty': round(electricity_duty, 2),
                'subtotal': round(subtotal, 2),
                'gst_rate': GST_RATE * 100,
                'gst_amount': round(gst_amount, 2),
                'total_amount': round(total_amount, 2),
                'bill_date': reading_date.strftime('%Y-%m-%d'),
                'due_date': (reading_date + timedelta(days=3)).strftime('%Y-%m-%d'),
                'payment_options': [
                    {'method': 'UPI', 'discount': '1%'},
                    {'method': 'Credit Card', 'surcharge': '2%'},
                    {'method': 'Net Banking', 'discount': '0.5%'}
                ]
            }
            
            return render_template('bill.html', bill=bill_data)
        finally:
            conn.close()

# New Features Routes
@app.route('/api/bill_calculator', methods=['POST'])
@login_required
def api_bill_calculator():
    """API endpoint for bill calculation"""
    try:
        data = request.get_json()
        units = float(data.get('units', 0))
        connection_type = data.get('connection_type', 'residential')
        season = data.get('season', 'summer')
        time_of_day = data.get('time_of_day', 'normal')
        
        # Calculate bill using existing function
        energy_charges, slab_breakup = calculate_slab_charges(units, season, time_of_day, connection_type)
        
        # Calculate additional charges
        fixed_charge = FIXED_CHARGES[connection_type]
        fuel_surcharge = energy_charges * FUEL_SURCHARGE
        electricity_duty = energy_charges * ELECTRICITY_DUTY
        subtotal = energy_charges + fixed_charge + fuel_surcharge + electricity_duty + METER_RENT
        gst_amount = subtotal * GST_RATE
        total_amount = subtotal + gst_amount
        
        return jsonify({
            'success': True,
            'bill_breakdown': {
                'energy_charges': round(energy_charges, 2),
                'fixed_charge': fixed_charge,
                'meter_rent': METER_RENT,
                'fuel_surcharge': round(fuel_surcharge, 2),
                'electricity_duty': round(electricity_duty, 2),
                'gst_amount': round(gst_amount, 2),
                'total_amount': round(total_amount, 2),
                'slab_breakup': slab_breakup
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/analytics_data')
@login_required
def api_analytics_data():
    """Get analytics data for charts"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Get monthly usage data
        c.execute("""
            SELECT strftime('%Y-%m', timestamp) as month, 
                   AVG(CAST(reading_value AS REAL)) as avg_reading,
                   COUNT(*) as reading_count
            FROM readings 
            WHERE user_id = ? 
            AND timestamp >= date('now', '-12 months')
            GROUP BY strftime('%Y-%m', timestamp)
            ORDER BY month
        """, (current_user.id,))
        
        monthly_data = []
        for row in c.fetchall():
            monthly_data.append({
                'month': row['month'],
                'avg_reading': round(row['avg_reading'], 2) if row['avg_reading'] else 0,
                'reading_count': row['reading_count']
            })
        
        # Get current month stats
        c.execute("""
            SELECT AVG(CAST(reading_value AS REAL)) as current_month_avg,
                   COUNT(*) as current_month_count
            FROM readings 
            WHERE user_id = ? 
            AND strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
        """, (current_user.id,))
        
        current_stats = c.fetchone()
        
        return jsonify({
            'monthly_data': monthly_data,
            'current_month_avg': round(current_stats['current_month_avg'], 2) if current_stats['current_month_avg'] else 0,
            'current_month_count': current_stats['current_month_count'] or 0
        })
    finally:
        conn.close()

@app.route('/alerts')
@login_required
def alerts():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Get active alerts
        c.execute("""
            SELECT id, alert_type, threshold_value, condition_type, is_active, created_at
            FROM alerts 
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """, (current_user.id,))
        
        alerts_data = c.fetchall()
        active_alerts = []
        for alert in alerts_data:
            active_alerts.append({
                'id': alert['id'],
                'alert_type': alert['alert_type'],
                'threshold_value': alert['threshold_value'],
                'condition_type': alert['condition_type'],
                'is_active': bool(alert['is_active']),
                'created_at': alert['created_at'],
                'priority': 'high' if alert['alert_type'] == 'usage_threshold' else 'medium',
                'description': f"Alert when usage is {alert['condition_type']} {alert['threshold_value']} units",
                'unit': 'units'
            })
        
        # Get sample triggered today data
        triggered_today = [alert for alert in active_alerts[:2]] if active_alerts else []
        
        # Calculate efficiency score
        efficiency_score = 'A+'
        monthly_savings = 15
        
        # Sample recent notifications
        recent_notifications = [
            {
                'alert_type': 'usage_threshold',
                'message': 'Your daily usage exceeded the threshold of 10 units',
                'priority': 'high',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'is_read': False
            },
            {
                'alert_type': 'bill_estimate',
                'message': 'Your estimated bill for this month is ₹1,245',
                'priority': 'medium',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'is_read': True
            }
        ]
        
        return render_template('alerts.html', 
                            active_alerts=active_alerts,
                            triggered_today=triggered_today,
                            monthly_savings=monthly_savings,
                            efficiency_score=efficiency_score,
                            recent_notifications=recent_notifications)
        
    finally:
        conn.close()

@app.route('/multi_meter')
@login_required
def multi_meter():
    """Multi-meter management page"""
    return render_template('multi_meter.html')

@app.route('/budget_planner')
@login_required
def budget_planner():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Get current budget
        current_month = datetime.now().strftime('%B')
        current_year = datetime.now().year
        
        c.execute("""
            SELECT id, budget_type, monthly_limit, current_spending, month, year
            FROM budgets 
            WHERE user_id = ? AND month = ? AND year = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (current_user.id, current_month, current_year))
        
        budget_row = c.fetchone()
        current_budget = dict(budget_row) if budget_row else {
            'monthly_limit': 1500,
            'current_spending': 0,
            'budget_type': 'electricity'
        }
        
        # Calculate budget metrics
        usage_percentage = (current_budget['current_spending'] / current_budget['monthly_limit'] * 100) if current_budget['monthly_limit'] > 0 else 0
        remaining_budget = current_budget['monthly_limit'] - current_budget['current_spending']
        days_left = (calendar.monthrange(current_year, datetime.now().month)[1] - datetime.now().day)
        daily_average = current_budget['current_spending'] / (datetime.now().day or 1)
        projected_total = daily_average * calendar.monthrange(current_year, datetime.now().month)[1]
        savings_percentage = max(0, 100 - usage_percentage)
        
        # Get spending breakdown
        spending_breakdown = [
            {'name': 'Energy Charges', 'amount': current_budget['current_spending'] * 0.6, 'percentage': 60},
            {'name': 'Fixed Charges', 'amount': current_budget['current_spending'] * 0.15, 'percentage': 15},
            {'name': 'Taxes & Duties', 'amount': current_budget['current_spending'] * 0.25, 'percentage': 25}
        ]
        
        # Get monthly data for chart
        monthly_labels = []
        actual_spending = []
        budget_limits = []
        
        for i in range(6):
            month_date = datetime.now() - timedelta(days=30*i)
            month_name = month_date.strftime('%b')
            monthly_labels.insert(0, month_name)
            actual_spending.insert(0, 1200 + (i * 50))  # Sample data
            budget_limits.insert(0, 1500)  # Sample data
        
        # Get energy tips
        c.execute("""
            SELECT tip_title, tip_description, potential_savings, difficulty_level
            FROM energy_tips 
            ORDER BY potential_savings DESC
            LIMIT 6
        """)
        
        tips_data = c.fetchall()
        savings_tips = []
        for tip in tips_data:
            savings_tips.append({
                'title': tip['tip_title'],
                'description': tip['tip_description'],
                'potential_savings': int(tip['potential_savings']),
                'difficulty': tip['difficulty_level']
            })
        
        return render_template('budget_planner.html',
                            current_budget=current_budget,
                            usage_percentage=round(usage_percentage, 1),
                            remaining_budget=round(remaining_budget, 2),
                            days_left=days_left,
                            daily_average=round(daily_average, 2),
                            projected_total=round(projected_total, 2),
                            savings_percentage=round(savings_percentage, 1),
                            spending_breakdown=spending_breakdown,
                            monthly_labels=monthly_labels,
                            actual_spending=actual_spending,
                            budget_limits=budget_limits,
                            savings_tips=savings_tips)
        
    finally:
        conn.close()

@app.route('/comparative_analysis')
@login_required
def comparative_analysis():
    """Comparative analysis page"""
    return render_template('comparative_analysis.html')

@app.route('/maintenance')
@login_required
def maintenance():
    """Maintenance scheduler page"""
    return render_template('maintenance.html')

@app.route('/energy_tips')
@login_required
def energy_tips():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Get all energy tips
        c.execute("""
            SELECT id, tip_category, tip_title, tip_description, potential_savings, difficulty_level
            FROM energy_tips 
            ORDER BY potential_savings DESC
        """)
        
        tips_data = c.fetchall()
        energy_tips = []
        max_savings = 0
        total_savings = 0
        
        for tip in tips_data:
            tip_dict = {
                'id': tip['id'],
                'tip_category': tip['tip_category'],
                'tip_title': tip['tip_title'],
                'tip_description': tip['tip_description'],
                'potential_savings': tip['potential_savings'],
                'difficulty_level': tip['difficulty_level']
            }
            energy_tips.append(tip_dict)
            max_savings = max(max_savings, tip['potential_savings'])
            total_savings += tip['potential_savings']
        
        # Calculate statistics
        total_tips = len(energy_tips)
        avg_savings = round(total_savings / total_tips) if total_tips > 0 else 0
        implemented_count = 3  # Sample data - would come from user_implemented_tips table
        
        return render_template('energy_tips.html',
                            energy_tips=energy_tips,
                            total_tips=total_tips,
                            max_savings=int(max_savings),
                            avg_savings=avg_savings,
                            implemented_count=implemented_count)
        
    finally:
        conn.close()

@app.route('/smart_home')
@login_required
def smart_home():
    """Smart home integration page"""
    return render_template('smart_home.html')

@app.route('/export_data')
@login_required
def export_data():
    """Export data in various formats"""
    format_type = request.args.get('format', 'csv')
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT reading_value, confidence, status, notes, timestamp
            FROM readings 
            WHERE user_id = ? 
            ORDER BY timestamp DESC
        """, (current_user.id,))
        
        readings = c.fetchall()
        
        if format_type == 'csv':
            # Create CSV
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Reading Value', 'Confidence', 'Status', 'Notes', 'Timestamp'])
            
            for reading in readings:
                writer.writerow([
                    reading['reading_value'],
                    reading['confidence'],
                    reading['status'],
                    reading['notes'],
                    reading['timestamp']
                ])
            
            mem = io.BytesIO()
            mem.write(output.getvalue().encode('utf-8'))
            mem.seek(0)
            
            filename = f"meter_readings_{current_user.id}_{datetime.now().strftime('%Y%m%d')}.csv"
            return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=filename)
        
        elif format_type == 'pdf':
            # PDF export would require additional library like ReportLab
            flash('PDF export coming soon!', 'info')
            return redirect(url_for('dashboard'))
            
    finally:
        conn.close()

@app.route('/api/budgets', methods=['GET', 'POST'])
@login_required
def api_budgets():
    """API for managing budgets"""
    if request.method == 'POST':
        # Create or update budget
        data = request.get_json()
        conn = get_db_connection()
        try:
            c = conn.cursor()
            current_month = datetime.now().strftime('%B')
            current_year = datetime.now().year
            
            # Check if budget exists for current month
            c.execute("""
                SELECT id FROM budgets 
                WHERE user_id = ? AND budget_type = ? AND month = ? AND year = ?
            """, (current_user.id, data['budget_type'], current_month, current_year))
            
            existing_budget = c.fetchone()
            
            if existing_budget:
                # Update existing budget
                c.execute("""
                    UPDATE budgets 
                    SET monthly_limit = ?, current_spending = COALESCE(current_spending, 0)
                    WHERE id = ?
                """, (data['monthly_limit'], existing_budget['id']))
            else:
                # Create new budget
                c.execute("""
                    INSERT INTO budgets (user_id, budget_type, monthly_limit, current_spending, month, year)
                    VALUES (?, ?, ?, 0, ?, ?)
                """, (current_user.id, data['budget_type'], data['monthly_limit'], current_month, current_year))
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Budget updated successfully'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
        finally:
            conn.close()
    else:
        # Get existing budgets
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT id, budget_type, monthly_limit, current_spending, month, year
                FROM budgets 
                WHERE user_id = ? 
                ORDER BY year DESC, month DESC
            """, (current_user.id,))
            
            budgets = []
            for row in c.fetchall():
                budgets.append({
                    'id': row['id'],
                    'budget_type': row['budget_type'],
                    'monthly_limit': row['monthly_limit'],
                    'current_spending': row['current_spending'],
                    'month': row['month'],
                    'year': row['year']
                })
            
            return jsonify({'budgets': budgets})
        finally:
            conn.close()

@app.route('/api/alerts', methods=['GET', 'POST'])
@login_required
def api_alerts():
    """API for managing alerts"""
    if request.method == 'POST':
        # Create new alert
        data = request.get_json()
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO alerts (user_id, alert_type, threshold_value, condition_type, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (current_user.id, data['alert_type'], data['threshold_value'], data['condition_type']))
            conn.commit()
            return jsonify({'success': True, 'message': 'Alert created successfully'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
        finally:
            conn.close()
    else:
        # Get existing alerts
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT id, alert_type, threshold_value, condition_type, is_active, created_at
                FROM alerts 
                WHERE user_id = ? 
                ORDER BY created_at DESC
            """, (current_user.id,))
            
            alerts = []
            for row in c.fetchall():
                alerts.append({
                    'id': row['id'],
                    'alert_type': row['alert_type'],
                    'threshold_value': row['threshold_value'],
                    'condition_type': row['condition_type'],
                    'is_active': bool(row['is_active']),
                    'created_at': row['created_at']
                })
            
            return jsonify({'alerts': alerts})
        finally:
            conn.close()

@app.route('/api/alerts/<int:alert_id>/toggle', methods=['POST'])
@login_required
def api_toggle_alert(alert_id):
    """Toggle alert active status"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE alerts 
            SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
            WHERE id = ? AND user_id = ?
        """, (alert_id, current_user.id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Alert status updated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/alerts/<int:alert_id>', methods=['DELETE'])
@login_required
def api_delete_alert(alert_id):
    """Delete alert"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, current_user.id))
        conn.commit()
        return jsonify({'success': True, 'message': 'Alert deleted'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/usage_alerts', methods=['GET', 'POST'])
@login_required
def api_usage_alerts():
    """API for managing usage alerts (legacy)"""
    if request.method == 'POST':
        # Create new alert
        data = request.get_json()
        # Implementation would save to database
        return jsonify({'success': True, 'message': 'Alert created successfully'})
    else:
        # Get existing alerts
        # Implementation would fetch from database
        return jsonify({
            'alerts': [
                {
                    'id': 1,
                    'type': 'usage_threshold',
                    'threshold': 300,
                    'current_usage': 245,
                    'status': 'active'
                }
            ]
        })

if __name__ == "__main__":
    print("\n" + "="*50)
    print("      Meter Scanner Pro is starting...")
    print(f"      Local: http://127.0.0.1:5000")
    print(f"      Network: http://0.0.0.0:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)