import hashlib
import json


def event_key(payload):
    if not isinstance(payload, dict):
        raise ValueError("event")
    event_type = payload.get("update_type")
    if event_type == "message_created":
        message = payload.get("message") or {}
        message_id = (message.get("body") or {}).get("mid")
        user_id = (message.get("sender") or {}).get("user_id")
        if not isinstance(message_id, str) or not message_id or not user_id:
            raise ValueError("message")
        return "message_created:" + message_id
    if event_type == "message_callback":
        callback = payload.get("callback") or {}
        callback_id = callback.get("callback_id")
        user_id = (callback.get("user") or {}).get("user_id")
        if not isinstance(callback_id, str) or not callback_id or not user_id:
            raise ValueError("callback")
        return "message_callback:" + callback_id
    if event_type == "bot_started":
        user_id = (payload.get("user") or {}).get("user_id")
        chat_id = payload.get("chat_id")
        timestamp = payload.get("timestamp")
        if not user_id or chat_id is None or type(timestamp) is not int:
            raise ValueError("start")
        fields = [event_type, user_id, chat_id, timestamp, payload.get("payload")]
        text = json.dumps(fields, ensure_ascii=False)
        return "bot_started:" + hashlib.sha256(text.encode()).hexdigest()
    raise ValueError("type")
