# src/ingestion/gmail_client.py

from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any

import base64
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# Solo lectura de Gmail
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = Path(__file__).resolve().parents[2]
CREDS_DIR = BASE_DIR / "credentials"
CREDS_DIR.mkdir(exist_ok=True)

CREDS_FILE = CREDS_DIR / "gmail_credentials.json"  # lo bajas de Google Cloud
TOKEN_FILE = CREDS_DIR / "gmail_token.json"        # se genera solo la primera vez


def build_gmail_service():
    """
    Devuelve un client de Gmail autenticado.
    La primera vez te abrirá un browser para aceptar permisos.
    """
    creds: Credentials | None = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with TOKEN_FILE.open("w") as token:
            token.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    return service


def list_messages(service, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
    """
    Busca mensajes por query de Gmail (misma sintaxis que en la UI).
    Incluye Spam y Trash para no perder alertas bancarias eliminadas.
    Devuelve una lista de dicts con 'id' y 'threadId'.
    """
    resp = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results, includeSpamTrash=True)
        .execute()
    )
    return resp.get("messages", [])


def get_message(service, msg_id: str) -> Dict[str, Any]:
    """
    Obtiene el mensaje completo (headers + body).
    """
    return (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )


def _decode_part(part: Dict[str, Any]) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    decoded_bytes = base64.urlsafe_b64decode(data.encode("UTF-8"))
    return decoded_bytes.decode("UTF-8", errors="ignore")


def _strip_html(html: str) -> str:
    """Elimina tags HTML y decodifica entidades básicas."""
    import re as _re
    text = _re.sub(r"<[^>]+>", " ", html)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&nbsp;", " ").replace("&#160;", " "))
    return _re.sub(r"\s+", " ", text).strip()


def extract_text_from_message(message: Dict[str, Any]) -> str:
    """
    Extrae texto plano del email. Prefiere text/plain sobre text/html.
    Si solo hay HTML, stripea los tags para obtener texto parseable.
    """
    payload = message.get("payload", {})
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        return _decode_part(payload)

    if mime_type == "text/html":
        return _strip_html(_decode_part(payload))

    if mime_type.startswith("multipart/"):
        plain_parts: list[str] = []
        html_parts: list[str] = []

        def walk_parts(part: Dict[str, Any]):
            mt = part.get("mimeType", "")
            if mt == "text/plain":
                plain_parts.append(_decode_part(part))
            elif mt == "text/html":
                html_parts.append(_decode_part(part))
            for sub in part.get("parts", []) or []:
                walk_parts(sub)

        walk_parts(payload)

        if plain_parts:
            return "\n\n".join(plain_parts)
        return _strip_html("\n\n".join(html_parts))

    return ""
