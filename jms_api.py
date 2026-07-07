import requests
import os

BASE_URL = "https://jmsgw.jtexpress.co.th"

TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".jms_token")

_current_token = os.environ.get("JMS_AUTH_TOKEN")


def set_token(new_token: str):
    global _current_token
    _current_token = new_token.strip()
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(_current_token)
    except Exception as e:
        print(f"⚠️ ไม่สามารถบันทึก Token ลงไฟล์ได้: {e}", flush=True)


def get_current_token() -> str:
    global _current_token
    if not _current_token:
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    _current_token = f.read().strip()
            except Exception as e:
                print(f"⚠️ ไม่สามารถอ่าน Token จากไฟล์ได้: {e}", flush=True)
    if not _current_token:
        raise ValueError("ไม่พบ Token กรุณาตั้งค่าด้วยคำสั่ง settoken ในแชท")
    return _current_token


def get_headers(token: str, routename: str = "") -> dict:
    headers = {
        "Authtoken": token,
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://jms.jtexpress.co.th",
        "Referer": "https://jms.jtexpress.co.th/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/149.0.0.0",
    }
    if routename:
        headers["Routename"] = routename
    return headers


def _is_token_invalid(resp) -> bool:
    if resp.status_code in (401, 403):
        return True
    try:
        body = resp.json()
    except Exception:
        return False
    msg = f"{body.get('msg', '')} {body.get('message', '')}".lower()
    code = body.get("code")
    keywords = ["token", "登录", "过期", "unauthorized", "登陆", "expired", "auth"]
    if any(k.lower() in msg for k in keywords):
        return True
    if code in (401, 403, "401", "403"):
        return True
    return False


def search_user(staff_no: str) -> dict:
    try:
        token = get_current_token()
    except ValueError as e:
        return {"found": False, "token_invalid": True, "message": str(e)}
    url = f"{BASE_URL}/oauth/sysUser/staffNosPage"
    payload = {"current": 1, "size": 20, "staffNo": staff_no, "countryId": "1"}
    try:
        resp = requests.post(url, json=payload, headers=get_headers(token, "userList|permissionIndex"), timeout=15)
        if _is_token_invalid(resp):
            return {"found": False, "token_invalid": True, "message": "Token หมดอายุหรือไม่ถูกต้อง"}
        resp_json = resp.json()
        data = resp_json.get("data") or {}
        records = data.get("records", []) if isinstance(data, dict) else []
        if not records:
            return {"found": False, "message": "ไม่พบ user ที่มี staffNo นี้"}
        u = records[0]
        return {"found": True, "id": u["id"], "name": u["name"], "staffNo": u["staffNo"], "isEnable": u["isEnable"]}
    except Exception as e:
        return {"found": False, "message": str(e)}


def enable_user(user_id: int, name: str, staff_no: str, current_is_enable: int, enable: bool) -> dict:
    try:
        token = get_current_token()
    except ValueError as e:
        return {"success": False, "token_invalid": True, "message": str(e)}
    action_path = "enable" if enable else "disable"
    url = f"{BASE_URL}/oauth/sysUser/{action_path}"
    new_is_enable = 1 if enable else 0
    payload = [
        {
            "newData": {"id": user_id, "name": name, "staffNo": staff_no, "isEnable": new_is_enable},
            "oldData": {"id": user_id, "name": name, "staffNo": staff_no, "isEnable": current_is_enable},
        }
    ]
    try:
        resp = requests.post(url, json=payload, headers=get_headers(token, "userList|permissionIndex"), timeout=15)
        if _is_token_invalid(resp):
            return {"success": False, "token_invalid": True, "message": "Token หมดอายุหรือไม่ถูกต้อง"}
        body = resp.json()
        return {"success": body.get("succ", False), "message": body.get("msg", "")}
    except Exception as e:
        return {"success": False, "message": str(e)}


def reset_password_pda(user_id: int) -> dict:
    try:
        token = get_current_token()
    except ValueError as e:
        return {"success": False, "token_invalid": True, "message": str(e)}
    url = f"{BASE_URL}/oauth/sysUser/resetPasswordByApp"
    try:
        resp = requests.post(url, params={"id": user_id}, headers=get_headers(token), timeout=15)
        if _is_token_invalid(resp):
            return {"success": False, "token_invalid": True, "message": "Token หมดอายุหรือไม่ถูกต้อง"}
        body = resp.json()
        return {"success": body.get("succ"), "new_password": body.get("data"), "message": body.get("msg")}
    except Exception as e:
        return {"success": False, "message": str(e)}


def reset_password_jms(user_id: int) -> dict:
    try:
        token = get_current_token()
    except ValueError as e:
        return {"success": False, "token_invalid": True, "message": str(e)}
    url = f"{BASE_URL}/oauth/sysUser/resetPasswordByJms"
    try:
        resp = requests.post(url, params={"id": user_id}, json={"countryId": "1"}, headers=get_headers(token), timeout=15)
        if _is_token_invalid(resp):
            return {"success": False, "token_invalid": True, "message": "Token หมดอายุหรือไม่ถูกต้อง"}
        body = resp.json()
        return {"success": body.get("succ"), "new_password": body.get("data"), "message": body.get("msg")}
    except Exception as e:
        return {"success": False, "message": str(e)}
