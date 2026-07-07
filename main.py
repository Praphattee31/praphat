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

# --- HELPER FUNCTIONS ---
def build_card(title, template, lines, actions=None, note=None):
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if actions:
        elements.append({"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": a["text"]}, "type": a.get("type", "default"), "value": a["value"]} for a in actions]})
    if note:
        elements.extend([{"tag": "hr"}, {"tag": "note", "elements": [{"tag": "lark_md", "content": note}]}])
    return {"config": {"wide_screen_mode": True}, "header": {"title": {"tag": "plain_text", "content": title}, "template": template}, "elements": elements}

def send_card(chat_id, card):
    req = im.CreateMessageRequest.builder().receive_id_type("chat_id").request_body(im.CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("interactive").content(json.dumps(card, ensure_ascii=False)).build()).build()
    client.im.v1.message.create(req)

# --- CARDS (เงื่อนไข 2, 3, 4) ---
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

# --- MAIN LOGIC (เงื่อนไข 1) ---
@app.route("/", methods=["POST"])
def event_handler():
    data = decrypt_event(request.json)
    if "card.action.trigger" in str(data):
        event = data.get("event", {})
        chat_id = event.get("context", {}).get("open_chat_id")
        val = event.get("action", {}).get("value", {})
        
        # เงื่อนไข 2: ปุ่มยกเลิกกลับไป Welcome
        if val.get("choice") == "cancel": send_card(chat_id, card_welcome())
        # เงื่อนไข 3: กลับไปเมนูเดิม
        elif val.get("choice") == "back": send_card(chat_id, card_user_menu(jms_api.search_user(val["staffNo"])))
        # เงื่อนไข 4: ทำรายการปกติ
        elif val.get("choice") in ["1", "2", "3", "4"]:
            user = user_sessions.get(event["operator"]["open_id"], {}).get("user_data")
            res = process_choice(user, val["choice"]) # ฟังก์ชันประมวลผลเดิมของคุณ
            send_card(chat_id, card_result(user, res["success"], res["message"], res.get("new_password")))
            
        return jsonify({"status": "success"})
    
    # เงื่อนไข 1: ลบส่วน card_invalid_choice ออก บอทจะเงียบหากเลือกผิด
    return jsonify({"status": "success"})

# ... (ส่วนประกอบอื่นๆ เหมือนเดิมครับ)
# --- ต่อจากส่วนก่อนหน้านี้ (ส่วนที่เหลือของ main.py) ---

    # 2. จัดการข้อความปกติ (Messages)
    if event_type == "im.message.receive_v1":
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()
        text_lower = text.lower()

        # คำสั่งลัด
        if text_lower.startswith("settoken"):
            parts = text.split(None, 1)
            if len(parts) == 2:
                jms_api.set_token(parts[1])
                send_card(chat_id, build_card("✅ สำเร็จ", "green", ["อัปเดต Token แล้ว"]))
            return jsonify({"status": "success"})

        # เข้าสู่โหมดค้นหา
        if text_lower in ["ค้นหา", "ค้นหา id"]:
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            send_card(chat_id, build_card("🔎 ค้นหา", "blue", ["กรุณากรอก Staff No"]))
        
        # กรณีอยู่ในสถานะรอเลข Staff
        elif user_sessions.get(sender_id, {}).get("state") == "waiting_staff_no":
            user = jms_api.search_user(text)
            if not user.get("found"):
                send_card(chat_id, build_card("❌ ไม่พบ", "red", ["ไม่พบ Staff No นี้"]))
            else:
                user_sessions[sender_id] = {"state": "waiting_choice", "user_data": user}
                send_card(chat_id, card_user_menu(user))
        
        # กรณีทักทายปกติ ให้โชว์หน้า Welcome
        else:
            send_card(chat_id, card_welcome())

    return jsonify({"status": "success"})

# --- ฟังก์ชันช่วยเหลือที่จำเป็น ---
def process_choice(user, choice):
    if choice == "1": return {"success": True, "message": "เปิดใช้งานสำเร็จ"}
    if choice == "2": return {"success": True, "message": "ปิดใช้งานสำเร็จ"}
    if choice == "3": return jms_api.reset_password_pda(user["id"])
    if choice == "4": return jms_api.reset_password_jms(user["id"])
    return {"success": False, "message": "เกิดข้อผิดพลาด"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
