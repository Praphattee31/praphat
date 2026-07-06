from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# เปลี่ยนค่าพวกนี้ให้ตรงกับของคุณ (หรือดึงจาก Environment Variables)
APP_ID = "cli_aac1901298f89bef"
APP_SECRET = "WwevlgARDeUkYogLsCpDCdTAmo3kSA2m"

def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    response = requests.post(url, json=payload)
    return response.json().get("tenant_access_token")

def send_feishu_message(target_id, content):
    token = get_tenant_access_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    params = {"receive_id_type": "open_id"} # หรือ chat_id ถ้าส่งเข้ากลุ่ม
    
    # หากต้องการส่งเข้ากลุ่ม ต้องปรับ receive_id_type เป็น "chat_id"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "receive_id": target_id,
        "msg_type": "text",
        "content": '{"text":"' + content + '"}'
    }
    requests.post(url, headers=headers, params=params, json=payload)

@app.route("/", methods=["POST"])
def feishu_webhook():
    data = request.json
    print(f"DEBUG: Received data: {data}") # ดูข้อมูลใน Logs ของ Render

    # 1. การยืนยัน URL (จำเป็นต้องมี)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # 2. การรับข้อความจากแชท
    if "event" in data:
        event = data["event"]
        if event.get("type") == "im.message.receive_v1":
            # ดึงข้อมูลผู้ส่งและข้อมูลข้อความ
            sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
            
            # บอทตอบกลับ
            send_feishu_message(sender_id, "ได้รับข้อความแล้วครับ!")
            
    return jsonify({"message": "success"})

if __name__ == "__main__":
    app.run(port=10000)
