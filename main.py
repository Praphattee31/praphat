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

# เก็บ session ของแต่ละคนไว้ใน memory: { open_id: {"state": ..., "user_data": {...}} }
user_sessions = {}

# แปลข้อความภาษาจีนที่ระบบ JMS มักส่งกลับมา ให้เป็นภาษาไทยที่อ่านง่ายขึ้น
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


def translate_msg(msg: str) -> str:
    if not msg:
        return msg
    return MSG_TRANSLATE.get(msg.strip(), msg)


# ============================================================
#  ระบบถอดรหัส Event จาก Feishu (AES-256-CBC)
# ============================================================
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
        if not ENCRYPT_KEY:
            print("⚠️ ได้รับ event แบบเข้ารหัส แต่ไม่มี ENCRYPT_KEY ใน Environment Variables!", flush=True)
            return {}
        try:
            decrypted = AESCipher(ENCRYPT_KEY).decrypt(data["encrypt"])
            print(f"🔓 DECRYPTED EVENT: {json.dumps(decrypted, ensure_ascii=False)}", flush=True)
            return decrypted
        except Exception as e:
            print(f"❌ ถอดรหัส event ไม่สำเร็จ: {e}", flush=True)
            return {}
    return data


# ============================================================
#  Card Builder
# ============================================================
def build_card(title: str, template: str, lines: list, note: str = None, actions: list = None) -> dict:
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if actions:
        elements.append(
            {
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
            }
        )
    if note:
        elements.append({"tag": "hr"})
        elements.append({"tag": "note", "elements": [{"tag": "lark_md", "content": note}]})

    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "elements": elements,
    }


def send_card(chat_id: str, card: dict):
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
        print(f"❌ SEND FAILED: code={resp.code}, msg={resp.msg}, log_id={resp.get_log_id()}", flush=True)
    else:
        print("✅ SEND SUCCESS", flush=True)


# ============================================================
#  Card templates
# ============================================================
def card_ask_staff_no():
    return build_card(
        title="🔎 ค้นหาผู้ใช้งาน",
        template="blue",
        lines=["กรุณากรอก **Staff No** ที่ต้องการค้นหา"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิกเมื่อไหร่ก็ได้",
    )


def card_not_found(message: str):
    return build_card(
        title="❌ ไม่พบผู้ใช้งาน",
        template="red",
        lines=[f"**สาเหตุ:** {message}", "กรุณาตรวจสอบ Staff No แล้วลองใหม่อีกครั้ง"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_user_menu(user: dict):
    is_enable = user.get("isEnable") == 1
    status_icon = "🟢" if is_enable else "🔴"
    status_text = "เปิดใช้งานอยู่" if is_enable else "ปิดใช้งานอยู่"
    return build_card(
        title="✅ พบผู้ใช้งาน",
        template="green",
        lines=[
            f"**ชื่อ:** {user['name']}",
            f"**Staff No:** {user['staffNo']}",
            f"**สถานะ:** {status_icon} {status_text}",
            "",
            "**เลือกดำเนินการ:**",
        ],
        actions=[
            {"text": "🟢 เปิดใช้งาน", "value": {"choice": "1"}, "type": "primary"},
            {"text": "🔴 ปิดใช้งาน", "value": {"choice": "2"}, "type": "danger"},
            {"text": "🔑 Reset PDA", "value": {"choice": "3"}, "type": "default"},
            {"text": "🔑 Reset JMS", "value": {"choice": "4"}, "type": "default"},
        ],
        note="กดปุ่ม หรือพิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_result(success: bool, message: str, new_password: str = None):
    lines = [f"**ผลลัพธ์:** {message}"]
    if new_password:
        lines.append(f"**รหัสผ่านใหม่:** `{new_password}`")
    return build_card(
        title="✅ ดำเนินการสำเร็จ" if success else "❌ ดำเนินการไม่สำเร็จ",
        template="green" if success else "red",
        lines=lines,
        note="พิมพ์ `ค้นหา ID` เพื่อเริ่มค้นหาผู้ใช้อื่น",
    )


def card_cancelled():
    return build_card(
        title="🚫 ยกเลิกรายการ",
        template="grey",
        lines=["ยกเลิกรายการเรียบร้อยแล้ว"],
        note="พิมพ์ `ค้นหา ID` เพื่อเริ่มค้นหาผู้ใช้ใหม่",
    )


def card_invalid_choice():
    return build_card(
        title="⚠️ กรุณาเลือกใหม่",
        template="orange",
        lines=["กรุณากดปุ่ม หรือพิมพ์หมายเลข **1-4** เท่านั้น"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_token_invalid():
    return build_card(
        title="⚠️ Token หมดอายุ",
        template="orange",
        lines=[
            "Token สำหรับเชื่อมต่อระบบ JMS **หมดอายุหรือไม่ถูกต้อง**",
            "",
            "**วิธีแก้ไข:**",
            "1. Login เว็บ JMS ใหม่ผ่านเบราว์เซอร์",
            "2. คัดลอกค่า `Authtoken` จาก Developer Tools",
            "3. พิมพ์คำสั่งนี้ในแชท:",
            "`settoken <token ใหม่>`",
        ],
        note="ตัวอย่าง: settoken abc123def456",
    )


def card_ask_token():
    return build_card(
        title="🔑 อัปเดต Token",
        template="blue",
        lines=["กรุณาวาง **Token ใหม่** เป็นข้อความถัดไป", "(คัดลอกมาจาก Authtoken ในเว็บ JMS)"],
        note="พิมพ์ `ยกเลิก` เพื่อยกเลิก",
    )


def card_token_updated():
    return build_card(
        title="✅ อัปเดต Token สำเร็จ",
        template="green",
        lines=[
            "Token ใหม่ถูกบันทึกเรียบร้อยแล้ว",
            "สามารถใช้งานค้นหา Staff ได้ตามปกติ",
            "",
            "⚠️ **หมายเหตุ:** ค่านี้จะหายไปถ้าเซิร์ฟเวอร์ restart",
            "แนะนำให้อัปเดต `JMS_AUTH_TOKEN` ใน Render ด้วยเพื่อความชัวร์",
        ],
        note="พิมพ์ `ค้นหา ID` เพื่อเริ่มค้นหา",
    )


def card_token_format_error():
    return build_card(
        title="⚠️ รูปแบบคำสั่งไม่ถูกต้อง",
        template="orange",
        lines=["กรุณาพิมพ์ตามรูปแบบ:", "`settoken <token ใหม่>`"],
        note="ตัวอย่าง: settoken abc123def456",
    )


# ============================================================
#  Logic กลาง: ประมวลผลตัวเลือก 1-4 (ใช้ร่วมกันทั้งพิมพ์เลขและกดปุ่ม)
# ============================================================
def process_choice(user: dict, choice: str) -> dict:
    if choice in ["1", "2"]:
        res = jms_api.enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (choice == "1"))
    elif choice == "3":
        res = jms_api.reset_password_pda(user["id"])
    else:
        res = jms_api.reset_password_jms(user["id"])

    if res.get("token_invalid"):
        return card_token_invalid()

    result_msg = translate_msg(res.get("message", ""))
    return card_result(
        success=bool(res.get("success")),
        message=result_msg,
        new_password=res.get("new_password"),
    )


# ============================================================
#  Route หลัก
# ============================================================
@app.route("/", methods=["GET", "POST", "HEAD"])
def event_handler():
    if request.method in ["GET", "HEAD"]:
        return jsonify({"status": "ok"}), 200

    raw_data = request.json
    print(f"📩 RAW EVENT: {json.dumps(raw_data, ensure_ascii=False)}", flush=True)

    data = decrypt_event(raw_data)
    if not data:
        return jsonify({"status": "error"}), 400

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    event_type = data.get("header", {}).get("event_type")

    # ---------------------------------------------------
    # 1. การกดปุ่มบน Card
    # ---------------------------------------------------
    if event_type == "card.action.trigger":
        event = data.get("event", {})
        operator_id = event.get("operator", {}).get("open_id")
        chat_id = event.get("context", {}).get("open_chat_id")
        choice = event.get("action", {}).get("value", {}).get("choice")

        print(f"🖱️ CARD ACTION: operator_id={operator_id}, chat_id={chat_id}, choice={choice}", flush=True)

        card = None
        if operator_id in user_sessions and user_sessions[operator_id].get("state") == "waiting_choice":
            user = user_sessions[operator_id]["user_data"]
            card = process_choice(user, choice)
            user_sessions.pop(operator_id, None)
        else:
            card = build_card(
                title="⚠️ รายการหมดอายุ",
                template="orange",
                lines=["รายการนี้ถูกใช้ไปแล้ว หรือหมดอายุ", "กรุณาพิมพ์ `ค้นหา ID` เพื่อค้นหาใหม่"],
            )

        if card and chat_id:
            send_card(chat_id, card)

        return jsonify({"toast": {"type": "success", "content": "กำลังดำเนินการ..."}})

    # ---------------------------------------------------
    # 2. ข้อความปกติ
    # ---------------------------------------------------
    if event_type == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        chat_id = message.get("chat_id")
        sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")

        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()
        text_lower = text.lower()

        print(f"👤 sender_id={sender_id}, chat_id={chat_id}, text='{text}'", flush=True)

        card = None

        EXIT_WORDS = {"exit", "ยกเลิก"}
        RESTART_WORDS = {"ค้นหา", "ค้นหา id", "start", "เริ่ม", "เริ่มค้นหา"}
        ADD_TOKEN_WORDS = {"เพิ่ม token", "เพิ่มtoken", "add token"}

        current_state = user_sessions.get(sender_id, {}).get("state")

        # --- คำสั่ง settoken <token> (พิมพ์รวมบรรทัดเดียว สำหรับผู้ใช้ที่คุ้นเคย) ---
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
            card = card_cancelled()

        # --- กำลังรอรับ Token ที่วางมาเป็นข้อความถัดไป (จากปุ่ม 'เพิ่ม Token') ---
        elif current_state == "waiting_token":
            jms_api.set_token(text.strip())
            user_sessions.pop(sender_id, None)
            card = card_token_updated()

        # --- กดปุ่มเมนู / พิมพ์ 'เพิ่ม Token' เพื่อเข้าสู่โหมดรอรับ token ---
        elif text_lower in ADD_TOKEN_WORDS:
            user_sessions[sender_id] = {"state": "waiting_token"}
            card = card_ask_token()

        elif text_lower in RESTART_WORDS:
            user_sessions[sender_id] = {"state": "waiting_staff_no"}
            card = card_ask_staff_no()

        elif current_state == "waiting_choice":
            if text in ["1", "2", "3", "4"]:
                user = user_sessions[sender_id]["user_data"]
                card = process_choice(user, text)
                user_sessions.pop(sender_id, None)
            else:
                card = card_invalid_choice()

        # --- ค่าเริ่มต้น: ไม่ว่าจะยังไม่มี session หรืออยู่ใน state waiting_staff_no
        #     ก็ถือว่าข้อความนี้คือ Staff No แล้วค้นหาทันที (แก้บั๊กต้องพิมพ์ 2 รอบ) ---
        else:
            user = jms_api.search_user(text)
            if user.get("token_invalid"):
                card = card_token_invalid()
            elif not user["found"]:
                card = card_not_found(user["message"])
                user_sessions[sender_id] = {"state": "waiting_staff_no"}
            else:
                user_sessions[sender_id] = {"state": "waiting_choice", "user_data": user}
                card = card_user_menu(user)

        print(f"💬 card='{json.dumps(card, ensure_ascii=False) if card else None}'", flush=True)

        if card and chat_id:
            send_card(chat_id, card)
        else:
            print(f"⚠️ ไม่ได้ส่งข้อความ: card={card}, chat_id='{chat_id}'", flush=True)

    return jsonify({"status": "success"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
