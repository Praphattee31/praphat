import os
import threading
import time
import requests
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

# ดึงค่าจาก Environment Variables ใน Render (ต้องตั้งค่าใน Dashboard ของ Render ให้ตรงกับชื่อ APP_ID และ APP_SECRET)
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")

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

def send_feishu_message(open_id, text):
    # 1. ดึง Access Token ของ Feishu
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/app_access_token/"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    access_token = resp.json().get("tenant_access_token")
    
    # 2. ส่งข้อความกลับไปยังผู้ใช้
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }
    requests.post(msg_url, headers=headers, json=payload)

# ระบบรับ Event จาก Feishu
@app.route("/", methods=["POST"])
def feishu_webhook():
    data = request.json
    
    # การยืนยัน URL ครั้งแรกจาก Feishu
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    # การรับข้อความจากแชท
    if "event" in data:
        event = data["event"]
        if event.get("type") == "im.message.receive_v1":
            sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
            # สั่งให้บอทตอบกลับ
            send_feishu_message(sender_id, "ได้รับข้อความแล้วครับ!")
            
    return jsonify({"message": "success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
