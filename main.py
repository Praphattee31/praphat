import os
import json
import base64
import hashlib
from flask import Flask, request, jsonify
from lark_oapi import Client
import lark_oapi.api.im.v1 as im
from Crypto.Cipher import AES
import jms_api

app = Flask(__name__)

APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
ENCRYPT_KEY = os.environ.get("ENCRYPT_KEY")

client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

user_sessions = {}
processed_events = set()

# ... (ฟังก์ชัน AESCipher, decrypt_event เหมือนเดิม) ...

@app.route("/", methods=["POST"])
def event_handler():
    raw_data = request.json
    data = decrypt_event(raw_data)

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    event_id = data.get("header", {}).get("event_id")
    if event_id in processed_events:
        return jsonify({"status": "already_processed"})
    if event_id:
        processed_events.add(event_id)

    if data.get("header", {}).get("event_type") == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()
        reply_text = ""

        # 1. จัดการกรณีผู้ใช้พิมพ์ข้อความเข้ามา (ไม่ว่าจะค้างสถานะไหน ถ้าพิมพ์ ID ใหม่มา ให้เริ่มเช็คทันที)
        # ตรวจสอบก่อนว่าเป็น ID JMS หรือไม่ (สมมติว่าเป็น ID ถ้าไม่ใช่คำสั่งเมนู)
        if text.lower() == "exit":
            user_sessions.pop(sender_id, None)
            reply_text = "ยกเลิกรายการแล้ว"
        
        elif sender_id in user_sessions and text in ['1', '2', '3', '4', '5']:
            # กรณีอยู่ในเมนูและเลือกเลข
            state_data = user_sessions[sender_id]
            if text == '5':
                user_sessions.pop(sender_id, None)
                reply_text = "ยกเลิกรายการแล้ว"
            else:
                user = state_data["user_data"]
                if text in ['1', '2']:
                    res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (text == '1'))
                elif text == '3':
                    res = jms_api.reset_password_pda(user["id"])
                else:
                    res = jms_api.reset_password_jms(user["id"])
                
                reply_text = f"✅ ดำเนินการสำเร็จ {'| รหัสใหม่: ' + res.get('new_password', '') if 'new_password' in res else ''}"
                user_sessions.pop(sender_id, None) # ล้างทันทีหลังจบงาน
        
        else:
            # กรณีพิมพ์อะไรมาก็ตามที่ไม่ใช่เลขเมนู ให้มองว่าเป็น ID JMS ใหม่เสมอ
            user = jms_api.search_user(text)
            if user and user.get("found"):
                status = "เปิดใช้งานอยู่" if user.get("isEnable") == 1 else "ปิดใช้งานอยู่"
                user_sessions[sender_id] = {"state": "waiting_choice", "user_data": user}
                reply_text = f"✅ พบผู้ใช้: {user['name']} | สถานะ: {status}\nเลือก: 1.เปิด | 2.ปิด | 3.Reset PDA | 4.Reset JMS | 5.ออก"
            else:
                # แก้ปัญหา: ไม่ต้องพิมพ์ exit แค่บอกว่าไม่มี
                user_sessions.pop(sender_id, None)
                reply_text = f"❌ ไม่พบข้อมูลสำหรับ: {text} \nกรุณากรอก ID JMS ใหม่ได้เลยครับ"

        if reply_text and chat_id:
            # ... (ส่วนการส่งข้อความเหมือนเดิม) ...
            req = im.CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(im.CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(json.dumps({"text": reply_text}))
                    .build()) \
                .build()
            client.im.v1.message.create(req)

    return jsonify({"status": "success"})
