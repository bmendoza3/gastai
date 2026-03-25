# src/ingestion/gmail_client.py
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Dict, Any

import base64

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = Path(__file__).resolve().parents[2]
CREDS_DIR = BASE_DIR / "credentials"
CREDS_DIR.mkdir(exist_ok=True)
TOKENS_DIR = CREDS_DIR / "tokens"
TOKENS_DIR.mkdir(exist_ok=True)

CREDS_FILE = CREDS_DIR / "gmail_credentials.json"


def _sanitize_phone(phone: str) -> str:
    return re.sub(r"[^\w]", "_", phone)


def _token_path(phone: str) -> Path:
    return TOKENS_DIR / f"{_sanitize_phone(phone)}.json"


def has_token(phone: str) -> bool:
    return _token_path(phone).exists()


def build_gmail_service(phone: str):
    """
    Devuelve un client de Gmail autenticado para el usuario dado.
    Lanza ValueError si el usuario aún no completó el OAuth.
    """
    token_file = _token_path(phone)
    if not token_file.exists():
        raise ValueError(
            f"Sin token de Gmail para {phone}. "
            f"Completa el OAuth en /admin/users/{phone}/gmail/connect"
        )

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with token_file.open("w") as f:
                f.write(creds.to_json())
        else:
            raise ValueError(
                f"Token expirado para {phone} sin refresh_token. "
                f"Re-autoriza en /admin/users/{phone}/gmail/connect"
            )

    return build("gmail", "v1", credentials=creds)


def get_oauth_url(phone: str, redirect_uri: str) -> str:
    """Genera la URL de autorización de Google para el usuario."""
    flow = Flow.from_client_secrets_file(
        str(CREDS_FILE), scopes=SCOPES, redirect_uri=redirect_uri
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=phone,
        prompt="consent",  # forzar refresh_token siempre
    )
    return auth_url


def exchange_code_for_token(phone: str, code: str, redirect_uri: str) -> None:
    """Intercambia el código OAuth por credenciales y las persiste."""
    flow = Flow.from_client_secrets_file(
        str(CREDS_FILE), scopes=SCOPES, redirect_uri=redirect_uri, state=phone
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_file = _token_path(phone)
    with token_file.open("w") as f:
        f.write(creds.to_json())


# ---- helpers de API ----

def list_messages(service, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
    resp = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results, includeSpamTrash=True)
        .execute()
    )
    return resp.get("messages", [])


def get_message(service, msg_id: str) -> Dict[str, Any]:
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
    import re as _re
    text = _re.sub(r"<[^>]+>", " ", html)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&nbsp;", " ").replace("&#160;", " "))
    return _re.sub(r"\s+", " ", text).strip()


def extract_text_from_message(message: Dict[str, Any]) -> str:
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
