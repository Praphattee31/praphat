import os
import json
import base64
import hashlib
import time
import threading
from flask import Flask, request, jsonify
from lark_oapi import Client
import lark_oapi.api.im.v1 as im
from Crypto.Cipher import AES
import jms_api

app = Flask(__name__)

# --- 1. CONFIGURATION & CLIENT SETUP ---
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
ENCRYPT_KEY = os.environ.get("ENCRYPT_KEY")

client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
user_sessions = {}

# --- 2. SECURITY & DECRYPTION ENGINE ---
class AESCipher:
    """Class สำหรับถอดรหัสข้อมูลที่ส่งมาจาก Feishu"""
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
        except Exception as e:
            print(f"Decryption Error: {e}")
            return {}
    return data

# --- 3. UI BUILDER (CARD GENERATION) ---
def build_card(title: str, template: str, lines: list, actions: list = None) -> dict:
    """ฟังก์ชันสร้างโครงสร้าง Message Card"""
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if actions:
        actions_list = []
        for a in actions:
            btn = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": a["text"]},
                "type": a.get("type", "default"),
                "value": a["value"]
            }
            actions_list.append(btn)
        elements.append({"tag": "action", "actions": actions_list})
    
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "elements": elements
    }

def send_card(chat_id: str, card: dict):
    """ส่งการ์ดไปยังแชท Feishu"""
    try:
        req = im.CreateMessageRequest.builder().receive_id_type("chat_id").request_body(
            im.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        ).build()
        client.im.v1.message.create(req)
    except Exception as e:
        print(f"Send Card Error: {e}")

# --- 4. UI TEMPLATES ---
def card_user_menu(user: dict):
    is_enable = user.get("isEnable") == 1
    return build_card(
        f"✅ จัดการพนักงาน: {user['name']}", "green", 
        [
            f"**Staff No:** {user['staffNo']}",
            f"**สถานะ:** {'🟢 เปิดใช้งาน' if is_enable else '🔴 ปิดใช้งาน'}",
            "", "**เลือกดำเนินการ:**"
        ], 
        [
            {"text": "🟢 เปิดใช้งาน", "value": {"choice": "1"}},
            {"text": "🔴 ปิดใช้งาน", "value": {"choice": "2"}},
            {"text": "🔑 Reset PDA", "value": {"choice": "3"}},
            {"text": "🔑 Reset JMS", "value": {"choice": "4"}},
            {"text": "🚫 ยกเลิก", "value": {"choice": "5"}, "type": "danger"}
        ]
    )

# --- 5. MAIN EVENT HANDLER ---
@app.route("/", methods=["GET", "POST", "HEAD"])
def event_handler():
    # รองรับการตรวจสอบ URL จาก Feishu
    if request.method in ["GET", "HEAD"]:
        return jsonify({"status": "ok"}), 200
    
    data = decrypt_event(request.json)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    event_type = data.get("header", {}).get("event_type")
    
    # กรณีมีการกดปุ่มในแชท (Card Action)
    if event_type == "card.action.trigger":
        event = data.get("event", {})
        sender_id = event.get("operator", {}).get("open_id")
        chat_id = event.get("context", {}).get("open_chat_id")
        choice = event.get("action", {}).get("value", {}).get("choice")
        
        if choice == "5":
            send_card(chat_id, build_card("🚫 ยกเลิกรายการ", "grey", ["ยกเลิกการทำงานเรียบร้อยแล้ว"]))
        else:
            send_card(chat_id, build_card(f"🔄 กำลังทำรายการ {choice}", "blue", ["กำลังประมวลผลคำสั่ง..."]))
        return jsonify({"status": "success"})

    # กรณีได้รับข้อความปกติ
    if event_type == "im.message.receive_v1":
        sender_id = data["event"]["sender"]["sender_id"]["open_id"]
        chat_id = data["event"]["message"]["chat_id"]
        try:
            content = json.loads(data["event"]["message"]["content"])
            text = content.get("text", "").strip().lower()
        except: text = ""

        if "ค้นหา id" in text:
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            send_card(chat_id, build_card("🔎 ค้นหาพนักงาน", "blue", ["กรุณากรอก Staff No ที่ต้องการค้นหา"]))
            
        elif user_sessions.get(sender_id, {}).get("state") == "waiting_staff_no":
            res = jms_api.search_user(text)
            if res.get("found"):
                send_card(chat_id, card_user_menu(res))
            else:
                send_card(chat_id, build_card("❌ ไม่พบข้อมูล", "red", ["ไม่พบ Staff No นี้ในระบบ"]))
            user_sessions.pop(sender_id, None)

    return jsonify({"status": "success"})

if __name__ == "__main__":
    # รันบนพอร์ต 10000 ตามมาตรฐาน Render
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
