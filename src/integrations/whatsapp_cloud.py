# src/integrations/whatsapp_cloud.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "gastai_verify")

GRAPH_URL = f"https://graph.facebook.com/v20.0/{META_PHONE_NUMBER_ID}/messages"


def verify_token(mode: str, token: str, challenge: str):
    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return int(challenge)
    return None


def send_message(to_number: str, text: str):
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    resp = requests.post(GRAPH_URL, headers=headers, json=payload, timeout=10)
    try:
        resp.raise_for_status()
    except Exception:
        print("❌ Error enviando mensaje a WhatsApp:", resp.text)
        raise
    return resp.json()