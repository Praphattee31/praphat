import os
from flask import Flask, request, jsonify
from lark_oapi import Client
import lark_oapi.api.im.v1 as im
import json

app = Flask(__name__)

# ตั้งค่า App Credentials ของคุณ
# นำค่ามาจากหน้า Developer Console > Credentials & Basic Info
APP_ID = "cli_aac1901298f89bef"  # แก้ไขตรงนี้
APP_SECRET = "WwevlgARDeUkYogLsCpDCdTAmo3kSA2m"  # แก้ไขตรงนี้

# สร้าง Client
client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

@app.route("/", methods=["POST"])
def event_handler():
    data = request.json
    
    # 1. การยืนยัน URL (URL Verification)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    # 2. การจัดการข้อความแชท (Message Received)
    if data.get("header", {}).get("event_type") == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        
        # ถอดรหัสข้อความจาก JSON string
        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "")
        
        # สร้างข้อความตอบกลับ
        reply_text = f"บอทได้รับข้อความของคุณแล้ว: {text}"
        
        # ส่งข้อความกลับไปที่ห้องแชท
        client.im.v1.message.create(
            im.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .body(im.CreateMessageRequestBody.builder()
                  .receive_id(chat_id)
                  .msg_type("text")
                  .content(json.dumps({"text": reply_text}))
                  .build())
            .build()
        )
        
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(port=10000)
