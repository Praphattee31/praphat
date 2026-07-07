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
ENCRYPT_KEY = os.environ.get("ENCRYPT_KEY")

client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
user_sessions = {}

# --- ระบบถอดรหัส ---
class AESCipher:
    def __init__(self, key: str):
        self.key = hashlib.sha256(key.encode("utf-8")).digest()
    def decrypt(self, encrypt_data: str) -> dict:
        raw = base64.b64decode(encrypt_data)
        iv = raw[: AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(raw[AES.block_size:])
        pad_len = decrypted[-1]
        return json.loads(decrypted[:-pad_len].decode("utf-8"))

def decrypt_event(data: dict) -> dict:
    if "encrypt" in data and ENCRYPT_KEY:
        try: return AESCipher(ENCRYPT_KEY).decrypt(data["encrypt"])
        except: return {}
    return data

# --- สร้าง Card ---
def build_card(title: str, template: str, lines: list, actions: list = None) -> dict:
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if actions:
        elements.append({"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": a["text"]}, "type": a.get("type", "default"), "value": a["value"]} for a in actions]})
    return {"config": {"wide_screen_mode": True}, "header": {"title": {"tag": "plain_text", "content": title}, "template": template}, "elements": elements}

def send_card(chat_id: str, card: dict):
    req = im.CreateMessageRequest.builder().receive_id_type("chat_id").request_body(im.CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("interactive").content(json.dumps(card, ensure_ascii=False)).build()).build()
    client.im.v1.message.create(req)

# --- หน้าจอเมนูหลัก ---
def card_user_menu(user: dict):
    is_enable = user.get("isEnable") == 1
    return build_card(f"✅ {user['name']}", "green", [f"**Staff No:** {user['staffNo']}", f"**สถานะ:** {'🟢 เปิดใช้งาน' if is_enable else '🔴 ปิดใช้งาน'}", "", "**เลือกดำเนินการ:**"], 
                      [{"text": "🟢 เปิด", "value": {"choice": "1"}}, {"text": "🔴 ปิด", "value": {"choice": "2"}}, {"text": "🔑 Reset PDA", "value": {"choice": "3"}}, {"text": "🔑 Reset JMS", "value": {"choice": "4"}}, {"text": "🚫 ยกเลิก", "value": {"choice": "5"}, "type": "danger"}])

# --- Route หลัก ---
@app.route("/", methods=["POST"])
def event_handler():
    data = decrypt_event(request.json)
    if data.get("type") == "url_verification": return jsonify({"challenge": data.get("challenge")})
    
    event_type = data.get("header", {}).get("event_type")
    
    # 1. จัดการกดปุ่มบนการ์ด
    if event_type == "card.action.trigger":
        event = data.get("event", {})
        sender_id = event.get("operator", {}).get("open_id")
        chat_id = event.get("context", {}).get("open_chat_id")
        choice = event.get("action", {}).get("value", {}).get("choice")

        if choice == "5":
            user_sessions.pop(sender_id, None)
            send_card(chat_id, build_card("🚫 ยกเลิก", "grey", ["ยกเลิกรายการเรียบร้อยแล้ว"]))
            return jsonify({"toast": {"type": "success", "content": "ยกเลิกแล้ว"}})
        
        # เพิ่ม Logic การทำงาน (1-4) เรียก jms_api ของคุณที่นี่
        # หลังจากทำงานเสร็จให้ใช้ send_card(chat_id, card_user_menu(user)) อีกครั้งเพื่อค้างหน้าจอ
        return jsonify({"toast": {"type": "success", "content": "ดำเนินการสำเร็จ"}})

    # 2. จัดการข้อความที่พิมพ์
    if event_type == "im.message.receive_v1":
        sender_id = data["event"]["sender"]["sender_id"]["open_id"]
        chat_id = data["event"]["message"]["chat_id"]
        text = json.loads(data["event"]["message"]["content"])["text"].strip().lower()

        if text == "ค้นหา id":
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            send_card(chat_id, build_card("🔎 ค้นหา", "blue", ["กรุณากรอก Staff No ที่ต้องการค้นหา"]))
        elif text == "เพิ่ม token":
            user_sessions[sender_id] = {"state": "waiting_token"}
            send_card(chat_id, build_card("🔑 เพิ่ม Token", "turquoise", ["กรุณาส่ง Token มาในแชท"]))
        elif user_sessions.get(sender_id, {}).get("state") == "waiting_token":
            # นำ Token ไปบันทึกที่นี่
            res = jms_api.save_token(text)
            send_card(chat_id, build_card("ผลลัพธ์", "green", [res.get("message", "บันทึก Token สำเร็จ")]))
            user_sessions.pop(sender_id, None)
        
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
