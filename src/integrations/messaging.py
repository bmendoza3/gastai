"""
Dispatcher de mensajería multi-canal.

Configurar via .env:
    MESSAGING_CHANNELS=telegram           # solo Telegram
    MESSAGING_CHANNELS=whatsapp           # solo WhatsApp
    MESSAGING_CHANNELS=telegram,whatsapp  # ambos
"""
import logging
import os
from io import BytesIO

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_CHANNELS = [c.strip() for c in os.getenv("MESSAGING_CHANNELS", "whatsapp").split(",") if c.strip()]


async def send_message(phone: str, text: str):
    """Envía texto al usuario por todos los canales configurados."""
    from src.db.storage import get_user
    user = get_user(phone)

    for channel in _CHANNELS:
        if channel == "whatsapp":
            try:
                from src.integrations.whatsapp_cloud import send_message as _send
                _send(phone, text)
            except Exception as e:
                logger.error("[whatsapp] Error enviando a %s: %s", phone, e)

        elif channel == "telegram":
            if not user or not user.get("telegram_chat_id"):
                logger.debug("[telegram] %s sin telegram_chat_id, omitiendo", phone)
                continue
            try:
                from src.integrations.telegram_bot import send_message as _send
                await _send(user["telegram_chat_id"], text)
            except Exception as e:
                logger.error("[telegram] Error enviando a %s: %s", phone, e)


async def send_image(phone: str, image_buf: BytesIO, caption: str = ""):
    """Envía imagen al usuario por todos los canales configurados."""
    from src.db.storage import get_user
    user = get_user(phone)

    for channel in _CHANNELS:
        if channel == "whatsapp":
            try:
                from src.integrations.whatsapp_cloud import send_image as _send
                _send(phone, image_buf, caption)
            except Exception as e:
                logger.error("[whatsapp] Error enviando imagen a %s: %s", phone, e)

        elif channel == "telegram":
            if not user or not user.get("telegram_chat_id"):
                continue
            try:
                from src.integrations.telegram_bot import send_image as _send
                await _send(user["telegram_chat_id"], image_buf, caption)
            except Exception as e:
                logger.error("[telegram] Error enviando imagen a %s: %s", phone, e)
