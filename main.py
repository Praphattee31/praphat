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

# --- CONFIG ---
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
ENCRYPT_KEY = os.environ.get("ENCRYPT_KEY")

client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()
user_sessions = {}

# --- DECRYPTION (แก้ปัญหา NameError) ---
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
    if "encrypt" in data:
        try: return AESCipher(ENCRYPT_KEY).decrypt(data["encrypt"])
        except: return {}
    return data

# --- CARDS ---
def build_card(title, template, lines, actions=None, note=None):
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if actions:
        elements.append({"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": a["text"]}, "type": a.get("type", "default"), "value": a["value"]} for a in actions]})
    if note:
        elements.extend([{"tag": "hr"}, {"tag": "note", "elements": [{"tag": "lark_md", "content": note}]}])
    return {"header": {"title": {"tag": "plain_text", "content": title}, "template": template}, "elements": elements}

def send_card(chat_id, card):
    req = im.CreateMessageRequest.builder().receive_id_type("chat_id").request_body(im.CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("interactive").content(json.dumps(card, ensure_ascii=False)).build()).build()
    client.im.v1.message.create(req)

def card_welcome():
    return build_card("👋 สวัสดีครับ", "blue", ["กรุณาเลือกสิ่งที่ต้องการทำ:"], 
                      [{"text": "🔍 ค้นหา ID", "value": {"menu": "search"}, "type": "primary"}, 
                       {"text": "🔑 เพิ่ม Token", "value": {"menu": "token"}}])

def card_user_menu(user):
    is_enable = user.get("isEnable") == 1
    return build_card(f"✅ {user['name']}", "green", [f"**Staff No:** {user['staffNo']}", f"**สถานะ:** {'🟢 เปิดใช้งาน' if is_enable else '🔴 ปิดใช้งาน'}"],
                      [{"text": "🟢 เปิด", "value": {"choice": "1"}}, {"text": "🔴 ปิด", "value": {"choice": "2"}},
                       {"text": "🔑 Reset PDA", "value": {"choice": "3"}}, {"text": "🔑 Reset JMS", "value": {"choice": "4"}},
                       {"text": "🚫 ยกเลิก", "value": {"choice": "cancel"}, "type": "danger"}])

def card_result(user, success, message, new_password=None):
    lines = [f"**ผลลัพธ์:** {message}"]
    if new_password: lines.append(f"**รหัสผ่านใหม่:** `{new_password}`")
    return build_card("✅ ดำเนินการสำเร็จ" if success else "❌ ดำเนินการไม่สำเร็จ", "green" if success else "red", lines,
                      [{"text": "🔙 กลับไปเมนูเดิม", "value": {"choice": "back", "staffNo": user['staffNo']}}])

# --- MAIN LOGIC ---
@app.route("/", methods=["POST"])
def event_handler():
    data = decrypt_event(request.json)
    if not data: return jsonify({"status": "success"})
    
    event = data.get("event", {})
    chat_id = event.get("context", {}).get("open_chat_id") or event.get("message", {}).get("chat_id")
    val = event.get("action", {}).get("value", {})
    
    # 1. จัดการปุ่มกด (เงื่อนไข 2, 3, 4)
    if "choice" in val:
        if val["choice"] == "cancel": send_card(chat_id, card_welcome())
        elif val["choice"] == "back": send_card(chat_id, card_user_menu(jms_api.search_user(val["staffNo"])))
        elif val["choice"] in ["1", "2", "3", "4"]:
            user = user_sessions.get(data.get("event",{}).get("operator",{}).get("open_id"), {}).get("user_data")
            # โค้ดประมวลผลเดิมของคุณ (process_choice)
            res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (val["choice"] == "1")) if val["choice"] in ["1","2"] else (jms_api.reset_password_pda(user["id"]) if val["choice"] == "3" else jms_api.reset_password_jms(user["id"]))
            send_card(chat_id, card_result(user, res.get("success"), res.get("message"), res.get("new_password")))
        return jsonify({"status": "success"})

    # 2. จัดการข้อความพิมพ์ (เงื่อนไข 1: ไม่มีการแจ้งเตือนเลือกใหม่)
    if "im.message.receive_v1" in str(data):
        text = data["event"]["message"]["content"].lower()
        if "ค้นหา" in text:
            # logic เดิมของคุณ...
            pass
        elif "สวัสดี" in text or not text:
            send_card(chat_id, card_welcome())
            
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
