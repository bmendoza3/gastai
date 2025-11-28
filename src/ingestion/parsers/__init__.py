# src/ingestion/parsers/__init__.py

from __future__ import annotations

from typing import Optional

from .bancodechile import parse_bancochile_email, ParsedExpense


def parse_email_any(sender: str, subject: str, body: str) -> Optional[ParsedExpense]:
    """
    Punto de entrada genérico:
    - Recibe info básica del mail
    - Intenta distintos parsers (bancos) en orden
    - Devuelve ParsedExpense o None
    """

    # 1) Banco de Chile
    parsed = parse_bancochile_email(sender, subject, body)
    if parsed is not None:
        return parsed

    # 2) Otros bancos en el futuro:
    # parsed = parse_santander_email(...)
    # if parsed is not None:
    #     return parsed

    return None
