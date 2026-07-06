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

class AESCipher:
    def __init__(self, key: str):
        self.key = hashlib.sha256(key.encode("utf-8")).digest()

    def decrypt(self, encrypt_data: str) -> dict:
        raw = base64.b64decode(encrypt_data)
        iv = raw[: AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(raw[AES.block_size:])
        pad_len = decrypted[-1]
        decrypted = decrypted[:-pad_len]
        return json.loads(decrypted.decode("utf-8"))

def decrypt_event(data: dict) -> dict:
    if "encrypt" in data:
        if not ENCRYPT_KEY:
            return {}
        cipher = AESCipher(ENCRYPT_KEY)
        return cipher.decrypt(data["encrypt"])
    return data

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

        # 1. เช็คคำสั่งยกเลิกก่อนเสมอ
        if text.lower() == "exit":
            user_sessions.pop(sender_id, None)
            reply_text = "ยกเลิกรายการแล้ว"
        
        # 2. กรณีมี session อยู่แล้ว (กำลังทำรายการ)
        elif sender_id in user_sessions:
            state = user_sessions[sender_id]["state"]
            
            if state == "waiting_choice":
                user = user_sessions[sender_id]["user_data"]
                if text in ['1', '2', '3', '4', '5']:
                    if text == '5':
                        user_sessions.pop(sender_id, None)
                        reply_text = "ยกเลิกรายการแล้ว"
                    else:
                        if text in ['1', '2']:
                            res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (text == '1'))
                        elif text == '3':
                            res = jms_api.reset_password_pda(user["id"])
                        else:
                            res = jms_api.reset_password_jms(user["id"])
                        
                        reply_text = f"✅ ดำเนินการสำเร็จ {'| รหัสใหม่: ' + res.get('new_password', '') if 'new_password' in res else ''}"
                        user_sessions.pop(sender_id, None)
                else:
                    reply_text = "กรุณาเลือกหมายเลข 1-5 หรือพิมพ์ 'exit'"
        
        # 3. กรณีเริ่มรายการใหม่ (ยังไม่มี session)
        else:
            user = jms_api.search_user(text)
            if user and user.get("found"):
                status = "เปิดใช้งานอยู่" if user.get("isEnable") == 1 else "ปิดใช้งานอยู่"
                user_sessions[sender_id] = {"state": "waiting_choice", "user_data": user}
                reply_text = f"✅ พบผู้ใช้: {user['name']} | สถานะ: {status}\nเลือก: 1.เปิด | 2.ปิด | 3.Reset PDA | 4.Reset JMS | 5.ออก"
            else:
                # ถ้าหาไม่เจอ ให้เริ่มใหม่หรือแจ้งเตือน
                user_sessions[sender_id] = {"state": "waiting_staff_no"}
                reply_text = "กรุณากรอก ID JMS (พิมพ์ 'exit' เพื่อออก):"

        if reply_text and chat_id:
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
