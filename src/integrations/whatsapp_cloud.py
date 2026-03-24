# src/integrations/whatsapp_cloud.py
import logging
import os
from io import BytesIO

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "gastai_verify")

GRAPH_BASE = f"https://graph.facebook.com/v20.0/{META_PHONE_NUMBER_ID}"
GRAPH_URL = f"{GRAPH_BASE}/messages"


def verify_token(mode: str, token: str, challenge: str):
    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return int(challenge)
    return None


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {META_ACCESS_TOKEN}"}


def send_message(to_number: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text},
    }
    resp = requests.post(
        GRAPH_URL,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    try:
        resp.raise_for_status()
    except Exception:
        logger.error("Error enviando mensaje a WhatsApp: %s", resp.text)
        raise
    return resp.json()


def _upload_image(image_buf: BytesIO, filename: str = "report.png") -> str:
    """Sube una imagen a Meta y retorna el media_id."""
    image_buf.seek(0)
    resp = requests.post(
        f"{GRAPH_BASE}/media",
        headers=_auth_headers(),
        files={"file": (filename, image_buf, "image/png")},
        data={"messaging_product": "whatsapp"},
        timeout=30,
    )
    try:
        resp.raise_for_status()
    except Exception:
        logger.error("Error subiendo imagen a Meta: %s", resp.text)
        raise
    return resp.json()["id"]


def send_image(to_number: str, image_buf: BytesIO, caption: str = ""):
    """Sube una imagen PNG y la envía por WhatsApp."""
    media_id = _upload_image(image_buf)
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": {"id": media_id, "caption": caption},
    }
    resp = requests.post(
        GRAPH_URL,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    try:
        resp.raise_for_status()
    except Exception:
        logger.error("Error enviando imagen a WhatsApp: %s", resp.text)
        raise
    return resp.json()