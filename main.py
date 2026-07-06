import os
import threading
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ดึงค่าจาก Environment Variables ใน Render
# ให้ไปตั้งค่าใน Render > Environment > Add Environment Variable
APP_ID = os.environ.get("FEISHU_APP_ID")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET")

# ตั้งค่า JMS
BASE_URL = "https://jmsgw.jtexpress.co.th"
TOKEN = "df644cd70db6422b9eb1a7a7f08ed520"

def get_headers(token: str, routename: str = "") -> dict:
    headers = {
        "Authtoken": token,
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0",
    }
    if routename: headers["Routename"] = routename
    return headers

# ระบบ Keep-Alive เพื่อรักษา Token JMS
def keep_alive_task():
    while True:
        try:
            requests.get(f"{BASE_URL}/authn/checkToken", headers=get_headers(TOKEN), timeout=15)
        except Exception as e:
            print(f"Ping error: {e}")
        time.sleep(900) # 15 นาที

threading.Thread(target=keep_alive_task, daemon=True).start()

# --- ระบบรับ Event จาก Feishu ---
@app.route("/", methods=["POST"])
def feishu_webhook():
    data = request.json
    
    # 1. การยืนยัน URL ครั้งแรก
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    # 2. รับข้อความจากแชท
    if "event" in data:
        event = data["event"]
        if event.get("type") == "im.message.receive_v1":
            msg_content = event.get("message", {}).get("content")
            print(f"ได้รับข้อความ: {msg_content}")
            # ตรงนี้คุณสามารถเพิ่ม Logic การประมวลผลข้อความได้
            
    return jsonify({"message": "success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
