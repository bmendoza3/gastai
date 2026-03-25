# src/ingestion/parsers/__init__.py

from __future__ import annotations

from typing import Optional

from .bancodechile import parse_bancochile_email, ParsedExpense, GMAIL_QUERY as _Q_BANCOCHILE

# Query combinada: atrapa emails de todos los bancos soportados
# Agregar aquí cada nuevo banco que se incorpore
COMBINED_GMAIL_QUERY = " OR ".join([
    f"({_Q_BANCOCHILE})",
    # f"({_Q_SANTANDER})",
    # f"({_Q_BCI})",
])


def parse_email_any(sender: str, subject: str, body: str) -> Optional[ParsedExpense]:
    """
    Intenta parsear el email con cada banco en orden.
    Retorna ParsedExpense o None si ningún parser lo reconoce.
    """
    parsed = parse_bancochile_email(sender, subject, body)
    if parsed is not None:
        return parsed

    # Agregar aquí los parsers de nuevos bancos:
    # parsed = parse_santander_email(sender, subject, body)
    # if parsed is not None:
    #     return parsed

    return None
