# src/ingestion/gmail_ingest.py

from __future__ import annotations

from typing import List, Dict, Any

from src.ingestion.gmail_client import (
    build_gmail_service,
    list_messages,
    get_message,
    extract_text_from_message,
)
from src.ingestion.parsers import parse_email_any
from src.db.storage import insert_transactions


def _get_header(headers: List[Dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def ingest_gmail_expenses(
    query: str = 'from:(@bancochile.cl) "compra"',
    max_results: int = 20,
):
    """
    Busca en Gmail mails que parezcan gastos (según query),
    los parsea y los inserta en DuckDB como transacciones pendientes.
    """
    service = build_gmail_service()

    msgs = list_messages(service, query=query, max_results=max_results)
    print(f"🔍 Encontrados {len(msgs)} mensajes candidatos")

    for m in msgs:
        msg_id = m["id"]
        full = get_message(service, msg_id)
        payload = full.get("payload", {})
        headers = payload.get("headers", [])

        sender = _get_header(headers, "From")
        subject = _get_header(headers, "Subject")

        body_text = extract_text_from_message(full)

        parsed = parse_email_any(sender, subject, body_text)
        if parsed is None:
            print(f"⏭  Ignorando mensaje {msg_id} (no matcheó ningún parser)")
            continue

        print(f"✅ Parsed {msg_id}: {parsed.description} | {parsed.amount_clp}")

        tx = {
            "tx_id": f"gmail-{msg_id}",              # evita duplicados
            "timestamp": parsed.timestamp.isoformat(),
            "description": parsed.description,
            "amount_clp": parsed.amount_clp,
            "account_id": parsed.account_hint,       # TODO: mapear a usuario/whatsapp si quieres
            "category": None,
            "intent": None,
            "needs_review": True,
        }

        insert_transactions([tx])

    print("✨ Ingesta Gmail terminada.")


if __name__ == "__main__":
    ingest_gmail_expenses()
