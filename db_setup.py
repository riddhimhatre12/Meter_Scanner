import mysql.connector

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="yourpassword"
)

cursor = db.cursor()
cursor.execute("CREATE DATABASE IF NOT EXISTS meter_db")
cursor.execute("USE meter_db")

# Create Users Table
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
)
""")

# Create Meter Readings Table
cursor.execute("""
CREATE TABLE IF NOT EXISTS meter_readings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    image_path VARCHAR(255),
    reading INT,
    bill_amount FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
""")

db.commit()
print("Database setup complete.")