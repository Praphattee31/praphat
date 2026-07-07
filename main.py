import os
import json
import base64
import hashlib
import threading
import time
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

# ============================================================
#  ระบบกัน Event ซ้ำ (Deduplication)
#  Lark จะ Retry ส่ง Event ซ้ำถ้าไม่ได้รับ 200 ภายใน 3 วินาที
#  ใช้ event_id + message_id เพื่อกันซ้ำทั้ง card action และ text message
# ============================================================
_processed_events = {}
_DEDUP_TTL = 300  # เก็บไว้ 5 นาที


def _is_duplicate(uid: str) -> bool:
    if not uid:
        return False
    now = time.time()
    # ลบตัวที่หมดอายุ
    expired = [k for k, v in _processed_events.items() if now - v > _DEDUP_TTL]
    for k in expired:
        del _processed_events[k]
    if uid in _processed_events:
        return True
    _processed_events[uid] = now
    return False


# แปลข้อความจีน → ไทย
MSG_TRANSLATE = {
    "请求成功": "คำขอสำเร็จ",
    "操作成功": "ดำเนินการสำเร็จ",
    "成功": "สำเร็จ",
    "失败": "ไม่สำเร็จ",
    "操作失败": "ดำเนินการไม่สำเร็จ",
    "系统异常": "ระบบขัดข้อง",
    "参数错误": "พารามิเตอร์ไม่ถูกต้อง",
    "用户不存在": "ไม่พบผู้ใช้นี้ในระบบ",
    "权限不足": "สิทธิ์ไม่เพียงพอ",
}


def translate_msg(msg):
    if not msg:
        return msg
    return MSG_TRANSLATE.get(msg.strip(), msg)


# ============================================================
#  ถอดรหัส Event (AES-256-CBC)
# ============================================================
class AESCipher:
    def __init__(self, key):
        self.key = hashlib.sha256(key.encode("utf-8")).digest()

    def decrypt(self, enc):
        raw = base64.b64decode(enc)
        iv = raw[:AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        dec = cipher.decrypt(raw[AES.block_size:])
        return json.loads(dec[:-dec[-1]].decode("utf-8"))


def decrypt_event(data):
    if "encrypt" in data:
        if not ENCRYPT_KEY:
            return {}
        try:
            return AESCipher(ENCRYPT_KEY).decrypt(data["encrypt"])
        except Exception as e:
            print(f"❌ ถอดรหัสไม่สำเร็จ: {e}", flush=True)
            return {}
    return data


# ============================================================
#  Card Builder & Sender
# ============================================================
def build_card(title, template, lines, note=None, actions=None):
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if actions:
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": a["text"]},
                    "type": a.get("type", "default"),
                    "value": a["value"],
                }
                for a in actions
            ],
        })
    if note:
        elements.append({"tag": "hr"})
        elements.append({"tag": "note", "elements": [{"tag": "lark_md", "content": note}]})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "elements": elements,
    }


def send_card(chat_id, card):
    req = (
        im.CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            im.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        print(f"❌ SEND CARD FAILED: {resp.code} {resp.msg}", flush=True)


def send_text(chat_id, text):
    """ส่งข้อความ text ธรรมดา (กดค้างคัดลอกได้ทันที)"""
    req = (
        im.CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            im.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        print(f"❌ SEND TEXT FAILED: {resp.code} {resp.msg}", flush=True)


def send_async(chat_id, card):
    threading.Thread(target=send_card, args=(chat_id, card)).start()


def send_text_async(chat_id, text):
    threading.Thread(target=send_text, args=(chat_id, text)).start()


# ============================================================
#  Card Templates
# ============================================================
def card_welcome():
    return build_card(
        "👋 สวัสดีครับ", "blue",
        ["กรุณาเลือกสิ่งที่ต้องการทำ:"],
        actions=[
            {"text": "🔍 ค้นหา ID", "value": {"menu": "search"}, "type": "primary"},
            {"text": "🔑 เพิ่ม Token", "value": {"menu": "token"}, "type": "default"},
        ],
        note="หรือพิมพ์ `ค้นหา ID` / `เพิ่ม Token` ก็ได้เช่นกัน",
    )


def card_ask_staff_no():
    return build_card(
        "🔎 ค้นหาผู้ใช้งาน", "blue",
        ["กรุณากรอก **Staff No** ที่ต้องการค้นหา"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิกเมื่อไหร่ก็ได้",
    )


def card_not_found(message):
    return build_card(
        "❌ ไม่พบผู้ใช้งาน", "red",
        [f"**สาเหตุ:** {message}", "กรุณาตรวจสอบ Staff No แล้วลองใหม่อีกครั้ง"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_user_menu(user):
    is_on = user.get("isEnable") == 1
    lines = [
        f"**ชื่อ:** {user['name']}",
        f"**Staff No:** {user['staffNo']}",
        f"**สถานะ:** {'🟢 เปิดใช้งานอยู่' if is_on else '🔴 ปิดใช้งานอยู่'}",
        "",
        "**เลือกดำเนินการ:**",
    ]
    return build_card(
        "✅ พบผู้ใช้งาน", "green", lines,
        actions=[
            {"text": "🟢 เปิดใช้งาน", "value": {"choice": "1"}, "type": "primary"},
            {"text": "🔴 ปิดใช้งาน", "value": {"choice": "2"}, "type": "danger"},
            {"text": "🔑 Reset PDA", "value": {"choice": "3"}, "type": "default"},
            {"text": "🔑 Reset JMS", "value": {"choice": "4"}, "type": "default"},
            {"text": "🚫 ยกเลิก", "value": {"choice": "cancel"}, "type": "default"},
        ],
        note="กดปุ่ม หรือพิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_result(success, message):
    return build_card(
        "✅ ดำเนินการสำเร็จ" if success else "❌ ดำเนินการไม่สำเร็จ",
        "green" if success else "red",
        [f"**ผลลัพธ์:** {message}"],
        note="พิมพ์ `ค้นหา ID` เพื่อเริ่มค้นหาผู้ใช้อื่น",
    )


def card_token_invalid():
    return build_card(
        "⚠️ Token หมดอายุ", "orange",
        [
            "Token สำหรับเชื่อมต่อระบบ JMS **หมดอายุหรือไม่ถูกต้อง**",
            "", "**วิธีแก้ไข:**",
            "1. Login เว็บ JMS ใหม่ผ่านเบราว์เซอร์",
            "2. คัดลอกค่า `Authtoken` จาก Developer Tools",
            "3. พิมพ์คำสั่งนี้ในแชท:",
            "`settoken <token ใหม่>`",
        ],
        note="ตัวอย่าง: settoken abc123def456",
    )


def card_ask_token():
    return build_card(
        "🔑 อัปเดต Token", "blue",
        ["กรุณาวาง **Token ใหม่** เป็นข้อความถัดไป", "(คัดลอกมาจาก Authtoken ในเว็บ JMS)"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_token_updated():
    return build_card(
        "✅ อัปเดต Token สำเร็จ", "green",
        [
            "Token ใหม่ถูกบันทึกเรียบร้อยแล้ว",
            "สามารถใช้งานค้นหา Staff ได้ตามปกติ",
            "",
            "⚠️ **หมายเหตุ:** แนะนำให้อัปเดต `JMS_AUTH_TOKEN` ใน Environment ด้วย",
        ],
        note="พิมพ์ `ค้นหา ID` เพื่อเริ่มค้นหา",
    )


def card_token_format_error():
    return build_card(
        "⚠️ รูปแบบคำสั่งไม่ถูกต้อง", "orange",
        ["กรุณาพิมพ์ตามรูปแบบ:", "`settoken <token ใหม่>`"],
        note="ตัวอย่าง: settoken abc123def456",
    )


# ============================================================
#  ประมวลผลตัวเลือก 1-4 แล้วส่งการ์ดผลลัพธ์ + ข้อความรหัสผ่าน
# ============================================================
def do_choice_and_send(chat_id, user, choice):
    if choice in ["1", "2"]:
        res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (choice == "1"))
    elif choice == "3":
        res = jms_api.reset_password_pda(user["id"])
    else:
        res = jms_api.reset_password_jms(user["id"])

    if res.get("token_invalid"):
        send_card(chat_id, card_token_invalid())
        return

    result_msg = translate_msg(res.get("message", ""))
    new_password = res.get("new_password")

    # ส่งการ์ดผลลัพธ์สีเขียว/แดง
    send_card(chat_id, card_result(bool(res.get("success")), result_msg))

    # ถ้ามีรหัสผ่านใหม่ ส่งเป็นข้อความแยกเพื่อให้กดค้างคัดลอกได้ง่าย
    if new_password:
        send_text(chat_id, f"🔑 รหัสผ่านใหม่: {new_password}")

    # ส่ง Welcome Card เพื่อรีเซ็ตหน้าจอ
    send_card(chat_id, card_welcome())


# ============================================================
#  Route หลัก
# ============================================================
@app.route("/", methods=["GET", "POST", "HEAD"])
def event_handler():
    if request.method in ["GET", "HEAD"]:
        return jsonify({"status": "ok"}), 200

    raw_data = request.get_json(silent=True) or {}
    print(f"📩 RAW: {json.dumps(raw_data, ensure_ascii=False)}", flush=True)

    data = decrypt_event(raw_data)
    if not data:
        return jsonify({"status": "error"}), 400

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # กัน Event ซ้ำ (Lark Retry)
    event_id = data.get("header", {}).get("event_id", "")
    if _is_duplicate(event_id):
        print(f"⚠️ DUPLICATE IGNORED: {event_id}", flush=True)
        return jsonify({"status": "success"}), 200

    event_type = data.get("header", {}).get("event_type")

    # ---------------------------------------------------
    # 1. กดปุ่มบน Card
    # ---------------------------------------------------
    if event_type == "card.action.trigger":
        event = data.get("event", {})
        op_id = event.get("operator", {}).get("open_id")
        chat_id = event.get("context", {}).get("open_chat_id")
        value = event.get("action", {}).get("value", {})

        print(f"🖱️ ACTION: op={op_id}, chat={chat_id}, val={value}", flush=True)

        def handle_card_action():
            if "menu" in value:
                menu = value["menu"]
                if menu == "search":
                    user_sessions[op_id] = {"state": "waiting_staff_no"}
                    send_card(chat_id, card_ask_staff_no())
                elif menu == "token":
                    user_sessions[op_id] = {"state": "waiting_token"}
                    send_card(chat_id, card_ask_token())

            elif "choice" in value:
                choice = value["choice"]

                if choice == "cancel":
                    user_sessions.pop(op_id, None)
                    send_card(chat_id, card_welcome())

                elif op_id in user_sessions and user_sessions[op_id].get("state") == "waiting_choice":
                    user = user_sessions[op_id]["user_data"]
                    user_sessions.pop(op_id, None)
                    do_choice_and_send(chat_id, user, choice)

                else:
                    send_card(chat_id, card_welcome())

        # รันใน thread แยก แล้วตอบ Lark ทันที
        threading.Thread(target=handle_card_action).start()
        return jsonify({"status": "success"}), 200

    # ---------------------------------------------------
    # 2. ข้อความปกติ
    # ---------------------------------------------------
    if event_type == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        chat_type = message.get("chat_type")
        sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")

        # กัน message ซ้ำด้วย message_id
        msg_id = message.get("message_id", "")
        if msg_id and _is_duplicate(msg_id):
            print(f"⚠️ DUPLICATE MSG IGNORED: {msg_id}", flush=True)
            return jsonify({"status": "success"}), 200

        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()

        mentions = message.get("mentions", [])
        for m in mentions:
            key = m.get("key")
            if key:
                text = text.replace(key, "")
        text = text.strip()
        text_lower = text.lower()

        print(f"👤 sender={sender_id}, chat={chat_id}, text='{text}'", flush=True)

        card = None
        EXIT_WORDS = {"exit", "ยกเลิก"}
        RESTART_WORDS = {"ค้นหา", "ค้นหา id", "start", "เริ่ม", "เริ่มค้นหา"}
        ADD_TOKEN_WORDS = {"เพิ่ม token", "เพิ่มtoken", "add token"}
        current_state = user_sessions.get(sender_id, {}).get("state")

        if text_lower.startswith("settoken"):
            parts = text.split(None, 1)
            if len(parts) == 2 and parts[1].strip():
                jms_api.set_token(parts[1].strip())
                user_sessions.pop(sender_id, None)
                card = card_token_updated()
            else:
                card = card_token_format_error()

        elif text_lower in EXIT_WORDS:
            user_sessions.pop(sender_id, None)
            card = card_welcome()

        elif current_state == "waiting_token":
            jms_api.set_token(text.strip())
            user_sessions.pop(sender_id, None)
            card = card_token_updated()

        elif text_lower in ADD_TOKEN_WORDS:
            user_sessions[sender_id] = {"state": "waiting_token"}
            card = card_ask_token()

        elif text_lower in RESTART_WORDS:
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            card = card_ask_staff_no()

        elif current_state == "waiting_choice":
            if text in ["1", "2", "3", "4"]:
                user = user_sessions[sender_id]["user_data"]
                user_sessions.pop(sender_id, None)
                do_choice_and_send(chat_id, user, text)

        elif current_state == "waiting_staff_no":
            user = jms_api.search_user(text)
            if user.get("token_invalid"):
                card = card_token_invalid()
            elif not user["found"]:
                card = card_not_found(user["message"])
            else:
                user_sessions[sender_id] = {"state": "waiting_choice", "user_data": user}
                card = card_user_menu(user)

        else:
            greetings = {"สวัสดี", "หวัดดี", "สวัสดีครับ", "สวัสดีค่ะ", "สวัสดีจ้า",
                         "เริ่ม", "hello", "hi", "เมนู", "menu", "ช่วยหน่อย", "help"}
            if text_lower in greetings:
                card = card_welcome()
            else:
                if len(text) >= 5 and any(c.isdigit() for c in text):
                    user = jms_api.search_user(text)
                    if user.get("token_invalid"):
                        card = card_token_invalid()
                    elif user.get("found"):
                        user_sessions[sender_id] = {"state": "waiting_choice", "user_data": user}
                        card = card_user_menu(user)
                    else:
                        card = card_not_found(user["message"])
                elif chat_type == "p2p":
                    card = card_welcome()

        if card and chat_id:
            send_card(chat_id, card)

    return jsonify({"status": "success"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
