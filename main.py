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

# ดึงค่าจาก Environment Variables
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
ENCRYPT_KEY = os.environ.get("ENCRYPT_KEY")  # ต้องตั้งค่านี้ใน Render ให้ตรงกับหน้า Encryption Strategy

client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

user_sessions = {}


class AESCipher:
    """ถอดรหัสข้อมูลที่ Feishu ส่งมาแบบ encrypt (AES-256-CBC)"""
    def __init__(self, key: str):
        self.key = hashlib.sha256(key.encode("utf-8")).digest()

    def decrypt(self, encrypt_data: str) -> dict:
        raw = base64.b64decode(encrypt_data)
        iv = raw[: AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(raw[AES.block_size:])
        # ตัด PKCS7 padding ออก
        pad_len = decrypted[-1]
        decrypted = decrypted[:-pad_len]
        return json.loads(decrypted.decode("utf-8"))


def decrypt_event(data: dict) -> dict:
    """ถ้ามี key 'encrypt' แปลว่าข้อมูลถูกเข้ารหัส ต้องถอดก่อนใช้งาน"""
    if "encrypt" in data:
        if not ENCRYPT_KEY:
            print("⚠️ ได้รับ event แบบเข้ารหัส แต่ไม่มี ENCRYPT_KEY ใน Environment Variables!", flush=True)
            return {}
        cipher = AESCipher(ENCRYPT_KEY)
        try:
            decrypted = cipher.decrypt(data["encrypt"])
            print(f"🔓 DECRYPTED EVENT: {json.dumps(decrypted, ensure_ascii=False)}", flush=True)
            return decrypted
        except Exception as e:
            print(f"❌ ถอดรหัส event ไม่สำเร็จ: {e}", flush=True)
            return {}
    return data


@app.route("/", methods=["POST"])
def event_handler():
    raw_data = request.json
    print(f"📩 RAW EVENT: {json.dumps(raw_data, ensure_ascii=False)}", flush=True)

    data = decrypt_event(raw_data)

    # 1. การตอบรับ URL Challenge
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # 2. การจัดการ Events
    if data.get("header", {}).get("event_type") == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")

        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()
        reply_text = ""

        print(f"👤 sender_id={sender_id}, chat_id={chat_id}, text='{text}'", flush=True)

        # --- Logic จัดการสถานะ ---
        if text.lower() == "exit":
            user_sessions.pop(sender_id, None)
            reply_text = "ยกเลิกรายการแล้ว"
        elif sender_id not in user_sessions:
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            reply_text = "กรุณากรอก Staff No (พิมพ์ 'exit' เพื่อออก):"
        else:
            state = user_sessions[sender_id]["state"]
            if state == "waiting_staff_no":
                user = jms_api.search_user(text)
                if not user["found"]:
                    reply_text = f"❌ {user['message']}"
                else:
                    status = "เปิดใช้งานอยู่" if user.get("isEnable") == 1 else "ปิดใช้งานอยู่"
                    user_sessions[sender_id].update({"state": "waiting_choice", "user_data": user})
                    reply_text = f"✅ พบผู้ใช้: {user['name']} | สถานะ: {status}\nเลือก: 1.เปิด | 2.ปิด | 3.Reset PDA | 4.Reset JMS"
            elif state == "waiting_choice":
                user = user_sessions[sender_id]["user_data"]
                if text in ['1', '2', '3', '4']:
                    if text in ['1', '2']:
                        res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (text == '1'))
                    elif text == '3':
                        res = jms_api.reset_password_pda(user["id"])
                    else:
                        res = jms_api.reset_password_jms(user["id"])

                    reply_text = f"ผลลัพธ์: {res.get('message', '')} {' รหัสใหม่: ' + res.get('new_password', '') if 'new_password' in res else ''}"
                    user_sessions.pop(sender_id, None)
                else:
                    reply_text = "กรุณาเลือกหมายเลข 1-4 หรือพิมพ์ 'exit'"

        print(f"💬 reply_text='{reply_text}'", flush=True)

        # --- ส่วนการส่งข้อความ (พร้อม logging ผลลัพธ์) ---
        if reply_text and chat_id:
            req = im.CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .receive_id(chat_id) \
                .content(json.dumps({"text": reply_text})) \
                .msg_type("text") \
                .build()
            resp = client.im.v1.message.create(req)

            if not resp.success():
                print(
                    f"❌ SEND FAILED: code={resp.code}, msg={resp.msg}, log_id={resp.get_log_id()}",
                    flush=True,
                )
            else:
                print("✅ SEND SUCCESS", flush=True)
        else:
            print(f"⚠️ ไม่ได้ส่งข้อความ: reply_text='{reply_text}', chat_id='{chat_id}'", flush=True)

    return jsonify({"status": "success"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
