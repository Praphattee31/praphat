import requests
import os

BASE_URL = "https://jmsgw.jtexpress.co.th"

# ใช้ตัวแปร Global เพื่อเก็บ Token ไว้ใน Memory ของเครื่อง Server ชั่วคราว
# เมื่อมีการอัปเดต Token ใหม่ มันจะเขียนทับค่านี้ให้ทันที
TEMP_TOKEN = os.environ.get("JMS_AUTH_TOKEN", "")

def update_token(new_token: str):
    """ใช้ฟังก์ชันนี้เมื่อผู้ใช้กดปุ่ม 'เพิ่ม Token' แล้วกรอกค่าเข้ามาใหม่"""
    global TEMP_TOKEN
    TEMP_TOKEN = new_token
    return {"success": True, "message": "อัปเดต Token ใหม่เรียบร้อยแล้ว!"}

def get_headers(routename: str = "") -> dict:
    headers = {
        "Authtoken": TEMP_TOKEN, # ดึงจากตัวแปร Global ที่อัปเดตสดๆ
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://jms.jtexpress.co.th",
        "Referer": "https://jms.jtexpress.co.th/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/149.0.0.0",
    }
    if routename: headers["Routename"] = routename
    return headers

def search_user(staff_no: str) -> dict:
    url = f"{BASE_URL}/oauth/sysUser/staffNosPage"
    payload = {"current": 1, "size": 20, "staffNo": staff_no, "countryId": "1"}
    try:
        resp = requests.post(url, json=payload, headers=get_headers("userList|permissionIndex"), timeout=15)
        data = resp.json()
        if not data.get("succ"): return {"found": False, "message": data.get("msg", "Token หมดอายุหรือไม่ถูกต้อง")}
        records = data.get("data", {}).get("records", [])
        if not records: return {"found": False, "message": "ไม่พบ user ที่มี staffNo นี้"}
        u = records[0]
        return {"found": True, "id": u["id"], "name": u["name"], "staffNo": u["staffNo"], "isEnable": u["isEnable"]}
    except Exception as e: return {"found": False, "message": str(e)}

# --- ฟังก์ชันอื่นๆ (enable_user, reset_password_pda, reset_password_jms) ---
# ให้ใช้ฟังก์ชันเดิมของคุณ แต่เปลี่ยนบรรทัดที่เรียก headers เป็น:
# headers=get_headers("userList|permissionIndex")
