import json
from flask import Flask, request, jsonify
from lark_oapi import Client
import lark_oapi.api.im.v1 as im

app = Flask(__name__)

# เก็บสถานะการสนทนาของผู้ใช้
user_sessions = {}

@app.route("/", methods=["POST"])
def event_handler():
    data = request.json
    if "challenge" in data: return jsonify({"challenge": data["challenge"]})
    
    if data.get("header", {}).get("event_type") == "im.message.receive_v1":
        event = data["event"]["event"]
        sender_id = event["sender"]["sender_id"]["open_id"]
        content = json.loads(event["content"])
        text = content.get("text", "").strip()
        chat_id = event["chat_id"]

        # logic การทำงาน
        reply = ""
        if text.lower() == "start":
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            reply = "กรุณากรอก Staff No (พิมพ์ 'exit' เพื่อออก):"
        
        elif user_sessions.get(sender_id, {}).get("state") == "waiting_staff_no":
            if text.lower() == "exit":
                del user_sessions[sender_id]
                reply = "ยกเลิกรายการแล้ว"
            else:
                # ตรงนี้คือส่วนที่คุณเอา Logic ดึงข้อมูลพนักงานจากระบบเดิมมาใส่
                staff_info = check_staff_in_db(text) # ฟังก์ชันดึงข้อมูลจาก DB ของคุณ
                if staff_info:
                    reply = f"✅ พบผู้ใช้: {staff_info['name']} | สถานะ: {staff_info['status']}\nเลือกคำสั่ง: 1.เปิด | 2.ปิด"
                    user_sessions[sender_id]["state"] = "waiting_command"
                else:
                    reply = "❌ ไม่พบข้อมูล กรุณากรอก Staff No ใหม่"

        # ส่ง reply กลับไปที่ Feishu
        send_feishu_message(chat_id, reply)

    return jsonify({"status": "success"})
