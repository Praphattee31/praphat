import requests
import os

BASE_URL = "https://jmsgw.jtexpress.co.th"

def get_current_token() -> str:
    # ดึงค่า Token จากตัวแปร Environment ที่เราตั้งค่าไว้ใน Render
    token = os.environ.get("JMS_AUTH_TOKEN")
    if not token:
        raise ValueError("⚠️ ไม่พบ JMS_AUTH_TOKEN ใน Environment Variables!")
    return token

def get_headers(token: str, routename: str = "") -> dict:
    headers = {
        "Authtoken": token,
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://jms.jtexpress.co.th",
        "Referer": "https://jms.jtexpress.co.th/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/149.0.0.0",
    }
    if routename: headers["Routename"] = routename
    return headers

def search_user(staff_no: str) -> dict:
    token = get_current_token()
    url = f"{BASE_URL}/oauth/sysUser/staffNosPage"
    payload = {"current": 1, "size": 20, "staffNo": staff_no, "countryId": "1"}
    try:
        resp = requests.post(url, json=payload, headers=get_headers(token, "userList|permissionIndex"), timeout=15)
        records = resp.json().get("data", {}).get("records", [])
        if not records: return {"found": False, "message": "ไม่พบ user ที่มี staffNo นี้"}
        u = records[0]
        return {"found": True, "id": u["id"], "name": u["name"], "staffNo": u["staffNo"], "isEnable": u["isEnable"]}
    except Exception as e: return {"found": False, "message": str(e)}

def enable_user(user_id: int, name: str, staff_no: str, current_is_enable: int, enable: bool) -> dict:
    token = get_current_token()
    action_path = "enable" if enable else "disable"
    url = f"{BASE_URL}/oauth/sysUser/{action_path}"
    payload = [{"newData": {"id": user_id, "name": name, "staffNo": staff_no, "isEnable": current_is_enable}, 
                "oldData": {"id": user_id, "name": name, "staffNo": staff_no, "isEnable": current_is_enable}}]
    try:
        resp = requests.post(url, json=payload, headers=get_headers(token, "userList|permissionIndex"), timeout=15)
        return {"success": resp.json().get("succ", False), "message": resp.json().get("msg", "")}
    except Exception as e: return {"success": False, "message": str(e)}

def reset_password_pda(user_id: int) -> dict:
    token = get_current_token()
    url = f"{BASE_URL}/oauth/sysUser/resetPasswordByApp"
    try:
        resp = requests.post(url, params={"id": user_id}, headers=get_headers(token), timeout=15)
        body = resp.json()
        return {"success": body.get("succ"), "new_password": body.get("data"), "message": body.get("msg")}
    except Exception as e: return {"success": False, "message": str(e)}

def reset_password_jms(user_id: int) -> dict:
    token = get_current_token()
    url = f"{BASE_URL}/oauth/sysUser/resetPasswordByJms"
    try:
        resp = requests.post(url, params={"id": user_id}, json={"countryId": "1"}, headers=get_headers(token), timeout=15)
        body = resp.json()
        return {"success": body.get("succ"), "new_password": body.get("data"), "message": body.get("msg")}
    except Exception as e: return {"success": False, "message": str(e)}
