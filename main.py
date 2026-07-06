import os
import json
from flask import Flask, request, jsonify
from lark_oapi import Client
import lark_oapi.api.im.v1 as im
import jms_api

app = Flask(__name__)

# ดึงค่าจาก Environment Variables ใน Render
APP_ID = os.environ.get("APP_ID")
APP_SECRET = os.environ.get("APP_SECRET")
client = Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

user_sessions = {}

@app.route("/", methods=["POST"])
def event_handler():
    data = request.json
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    
    if data.get("header", {}).get("event_type") == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
        
        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()
        reply_text = ""
        
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
                    status = "เปิดใช้งานอยู่" if user["isEnable"] == 1 else "ปิดใช้งานอยู่"
                    user_sessions[sender_id].update({"state": "waiting_choice", "user_data": user})
                    reply_text = f"✅ พบผู้ใช้: {user['name']} | สถานะ: {status}\nเลือก: 1.เปิด | 2.ปิด | 3.Reset PDA | 4.Reset JMS"
            elif state == "waiting_choice":
                user = user_sessions[sender_id]["user_data"]
                if text in ['1', '2', '3', '4']:
                    if text in ['1', '2']: res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (text == '1'))
                    elif text == '3': res = jms_api.reset_password_pda(user["id"])
                    else: res = jms_api.reset_password_jms(user["id"])
                    reply_text = f"ผลลัพธ์: {res.get('message', '')} {' รหัสใหม่: ' + res.get('new_password', '') if 'new_password' in res else ''}"
                    user_sessions.pop(sender_id, None)
                else: reply_text = "กรุณาเลือกหมายเลข 1-4 หรือพิมพ์ 'exit'"

        # --- แก้ไขส่วนการส่งข้อความให้ถูกต้องตามโครงสร้าง Builder ---
        req = im.CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .receive_id(chat_id) \
            .content(json.dumps({"text": reply_text})) \
            .msg_type("text") \
            .build()
        
        client.im.v1.message.create(req)
        
    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(port=10000)
