# src/ingestion/gmail_ingest.py
from __future__ import annotations

import logging
from typing import List, Dict

from src.ingestion.gmail_client import (
    build_gmail_service,
    list_messages,
    get_message,
    extract_text_from_message,
)
from src.ingestion.parsers import parse_email_any, COMBINED_GMAIL_QUERY
from src.db.storage import insert_transactions

logger = logging.getLogger(__name__)


def _get_header(headers: List[Dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def ingest_gmail_expenses(user: Dict, max_results: int = 50, full_scan: bool = False) -> List[str]:
    """
    Busca emails bancarios en Gmail del usuario y los ingesta en DuckDB.
    La detección de banco es automática vía parsers — no requiere configuración.

    Args:
        user: dict con key 'phone'
        max_results: máximo de emails a procesar por ciclo

    Returns:
        Lista de tx_ids nuevos insertados
    """
    phone = user["phone"]
    service = build_gmail_service(phone)
    limit = 500 if full_scan else max_results
    msgs = list_messages(service, query=COMBINED_GMAIL_QUERY, max_results=limit)
    logger.info(f"[{phone}] {len(msgs)} mensajes candidatos")

    rows = []
    for m in msgs:
        msg_id = m["id"]
        full = get_message(service, msg_id)
        headers = full.get("payload", {}).get("headers", [])

        sender = _get_header(headers, "From")
        subject = _get_header(headers, "Subject")
        body_text = extract_text_from_message(full)

        parsed = parse_email_any(sender, subject, body_text)
        if parsed is None:
            logger.debug(f"[{phone}] Ignorando {msg_id} (sin parser)")
            continue

        logger.info(f"[{phone}] {msg_id}: {parsed.description} | {parsed.amount_clp}")
        rows.append({
            "tx_id": f"gmail-{msg_id}",
            "timestamp": parsed.timestamp.isoformat(),
            "description": parsed.description,
            "amount_clp": parsed.amount_clp,
            "user_phone": phone,
            "category": None,
            "intent": None,
            "needs_review": True,
            "source": "gmail",
        })

    new_ids = insert_transactions(rows)
    logger.info(f"[{phone}] {len(new_ids)} transacciones nuevas")
    return new_ids


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    test_user = {"phone": sys.argv[1] if len(sys.argv) > 1 else "+56900000000"}
    new = ingest_gmail_expenses(test_user)
    print(f"Nuevas tx: {new}")
