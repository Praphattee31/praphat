"""
jms_api.py
-----------
ระบบจัดการผู้ใช้ JMS ครบวงจร (ค้นหา / เปิด-ปิดใช้งาน / Reset รหัสผ่าน)
"""

import requests
import json
import os

BASE_URL = "https://jmsgw.jtexpress.co.th"
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")

def get_current_token() -> str:
    """อ่านหรือสร้างไฟล์ token.json เพื่อเก็บ Token"""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)["token"]
        except: pass
    
    print("\n⚠️ ไม่พบ Token! กรุณาดึง Authtoken จากหน้าเว็บ JMS (F12 > Network > Headers)")
    new_token = input("กรุณาวาง 'Authtoken' ที่ก๊อปปี้มาแล้วกด Enter: ").strip()
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"token": new_token}, f)
    return new_token

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

def search_user(staff_no: str, token: str = None) -> dict:
    if token is None: token = get_current_token()
    url = f"{BASE_URL}/oauth/sysUser/staffNosPage"
    payload = {"current": 1, "size": 20, "staffNo": staff_no, "countryId": "1"}
    try:
        resp = requests.post(url, json=payload, headers=get_headers(token, "userList|permissionIndex"), timeout=15)
        if resp.status_code == 401:
            if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
            return {"found": False, "message": "Token หมดอายุ กรุณารันใหม่"}
        records = resp.json().get("data", {}).get("records", [])
        if not records: return {"found": False, "message": "ไม่พบ user ที่มี staffNo นี้"}
        u = records[0]
        return {"found": True, "id": u["id"], "name": u["name"], "staffNo": u["staffNo"], "isEnable": u["isEnable"]}
    except Exception as e: return {"found": False, "message": str(e)}

def enable_user(user_id: int, name: str, staff_no: str, current_is_enable: int, enable: bool, token: str = None) -> dict:
    """
    เปิด/ปิดใช้งานผู้ใช้
    หมายเหตุ: ระบบ JMS ใช้ endpoint แยกกันระหว่างเปิด (/enable) กับปิด (/disable)
    ไม่ได้ใช้ endpoint เดียวแล้วสลับค่า isEnable ในตัว payload
    (ตรวจสอบจาก DevTools > Network ตอนกดปิดใช้งานจริงบนหน้าเว็บ)
    """
    if token is None: token = get_current_token()
    action_path = "enable" if enable else "disable"
    url = f"{BASE_URL}/oauth/sysUser/{action_path}"
    payload = [{"newData": {"id": user_id, "name": name, "staffNo": staff_no, "isEnable": current_is_enable}, 
                "oldData": {"id": user_id, "name": name, "staffNo": staff_no, "isEnable": current_is_enable}}]
    try:
        resp = requests.post(url, json=payload, headers=get_headers(token, "userList|permissionIndex"), timeout=15)
        return {"success": resp.json().get("succ", False), "message": resp.json().get("msg", "")}
    except Exception as e: return {"success": False, "message": str(e)}

def reset_password_pda(user_id: int, token: str = None) -> dict:
    """Reset รหัสผ่านสำหรับแอป PDA (พนักงานแอปสปินเตอร์)"""
    if token is None: token = get_current_token()
    url = f"{BASE_URL}/oauth/sysUser/resetPasswordByApp"
    try:
        resp = requests.post(url, params={"id": user_id}, headers=get_headers(token), timeout=15)
        body = resp.json()
        return {"success": body.get("succ"), "new_password": body.get("data"), "message": body.get("msg")}
    except Exception as e: return {"success": False, "message": str(e)}

def reset_password_jms(user_id: int, token: str = None) -> dict:
    """Reset รหัสผ่านสำหรับระบบ JMS"""
    if token is None: token = get_current_token()
    url = f"{BASE_URL}/oauth/sysUser/resetPasswordByJms"
    try:
        resp = requests.post(url, params={"id": user_id}, json={"countryId": "1"}, headers=get_headers(token), timeout=15)
        body = resp.json()
        return {"success": body.get("succ"), "new_password": body.get("data"), "message": body.get("msg")}
    except Exception as e: return {"success": False, "message": str(e)}

if __name__ == "__main__":
    print("=== ระบบจัดการผู้ใช้ JMS (พร้อมใช้งาน) ===")
    while True:
        print("\n" + "-"*40)
        s_no = input("กรุณากรอก Staff No (พิมพ์ 'exit' เพื่อออก): ").strip()
        
        # ป้องกันกรณีเผลอกด Enter หรือไม่ได้กรอกข้อมูล[cite: 1]
        if not s_no:
            print("❌ ไม่มีการป้อนข้อมูล กรุณากรอก Staff No ใหม่")
            continue
            
        if s_no.lower() == 'exit': 
            break
        
        # ดำเนินการค้นหาหลังจากตรวจสอบแล้วว่ามีค่า[cite: 1]
        user = search_user(s_no)
        if not user["found"]:
            print(f"❌ {user['message']}")
        else:
            status = "เปิดใช้งานอยู่" if user["isEnable"] == 1 else "ปิดใช้งานอยู่"
            print(f"✅ พบผู้ใช้: {user['name']} | สถานะ: {status}")
            print("เลือกคำสั่ง: 1.เปิดใช้งาน | 2.ปิดใช้งาน | 3.Reset Password PDA | 4.Reset Password JMS | 0.ข้าม")
            choice = input("เลือกหมายเลข: ").strip()
            
            if choice in ['1', '2']:
                res = enable_user(user["id"], user["name"], user["staffNo"], user["isEnable"], (choice == '1'))
                print(f"ผลลัพธ์: {res['message']}")
            elif choice == '3':
                res = reset_password_pda(user["id"])
                print(f"ผลลัพธ์: {'✅ สำเร็จ! รหัสใหม่คือ: ' + res['new_password'] if res['success'] else '❌ ' + res['message']}")
            elif choice == '4':
                res = reset_password_jms(user["id"])
                print(f"ผลลัพธ์: {'✅ สำเร็จ! รหัสใหม่คือ: ' + res['new_password'] if res['success'] else '❌ ' + res['message']}")
            else:
                print("ยกเลิกรายการ")