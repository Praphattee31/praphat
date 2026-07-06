

        # --- ส่วนการส่งข้อความ ---
        if reply_text:
            req = im.CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .receive_id(chat_id) \
                .content(json.dumps({"text": reply_text})) \
                .msg_type("text") \
                .build()
            client.im.v1.message.create(req)
        
    return jsonify({"status": "success"})

if __name__ == "__main__":
    # จุดที่แก้ไข: กำหนด host='0.0.0.0' และใช้ PORT จาก env
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
