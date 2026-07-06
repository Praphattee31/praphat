from flask import Flask, request, jsonify
import requests
import json
import threading
import time
from datetime import datetime

app = Flask(__name__)

# ตั้งค่าพื้นฐานจาก jms_api.py
BASE_URL = "https://jmsgw.jtexpress.co.th"
# ใส่ Token ของคุณที่นี่
FIXED_TOKEN = "df644cd70db6422b9eb1a7a7f08ed520"

def get_headers(token: str, routename: str = "") -> dict:
    """สร้าง Headers สำหรับยิง API JMS"""
    headers = {
        "Authtoken": token,
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://jms.jtexpress.co.th",
        "Referer": "https://jms.jtexpress.co.th/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if routename: headers["Routename"] = routename
    return headers

# ระบบ Keep-Alive (Ping JMS ทุก 15 นาที เพื่อไม่ให้ Token หลุด)
def keep_alive_task():
    print("Starting Keep-Alive background task...")
    while True:
        url = f"{BASE_URL}/authn/checkToken"
        try:
            # ใช้ Token ที่ระบุไว้เพื่อตรวจสอบสถานะ
            response = requests.get(url, headers=get_headers(FIXED_TOKEN), timeout=15)
            if response.status_code == 200:
                print(f"[{datetime.now()}] Ping successful")
            else:
                print(f"[{datetime.now()}] Ping returned status: {response.status_code}")
        except Exception as e:
            print(f"Ping failed: {e}")
        # รอ 15 นาที
        time.sleep(15 * 60)

# เริ่มรัน thread แยกสำหรับการ keep-alive ทันทีที่เซิร์ฟเวอร์เริ่มทำงาน
threading.Thread(target=keep_alive_task, daemon=True).start()

# --- ส่วนสำหรับเชื่อมกับ Feishu (Webhook) ---
@app.route("/", methods=["POST"])
def feishu_webhook():
    data = request.json
    
    # 1. ตอบสนอง Verification Challenge จาก Feishu ครั้งแรกที่ตั้งค่า
    if "type" in data and data["type"] == "url_verification":
        return jsonify({"challenge": data["challenge"]})
    
    # 2. กรณีรับข้อความจากผู้ใช้ (รองรับการขยายฟังก์ชันในอนาคต)
    return jsonify({"message": "Received"})

# รันด้วย Flask (Render จะใช้ gunicorn มาเรียกใช้ app นี้ผ่านคำสั่ง start command)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)