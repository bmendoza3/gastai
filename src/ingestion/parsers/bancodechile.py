# src/ingestion/parsers/bancochile.py

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ParsedExpense:
    amount_clp: float
    description: str
    timestamp: datetime
    account_hint: str  # ej: 'BancoChile-TC-1234'


def parse_bancochile_email(sender: str, subject: str, body: str) -> Optional[ParsedExpense]:
    """
    Intenta parsear un mail del Banco de Chile que corresponda a un gasto.
    Si no reconoce el formato, devuelve None.
    """

    sender_l = sender.lower()
    subj_l = subject.lower()
    body_l = body.lower()

    # 1) Filtro grueso: sólo si parece aviso de compra
    if "bancodechile" not in sender_l and "banco de chile" not in body_l:
        return None

    if "compra con tarjeta" not in subj_l and "compra con su tarjeta" not in body_l:
        # puedes ir agregando más variantes a medida que veas mails reales
        return None

    # 2) Buscar monto (ej: $ 12.345, $12.345, CLP 12.345)
    monto_re = re.search(r"\$ ?([\d\.]+)", body)
    if not monto_re:
        return None

    monto_txt = monto_re.group(1)  # '12.345'
    monto_clean = monto_txt.replace(".", "")
    try:
        amount = float(monto_clean) * -1  # gasto → negativo
    except ValueError:
        return None

    # 3) Intentar sacar comercio (muy heurístico)
    comercio = "Compra Banco de Chile"
    comercio_match = re.search(r"en ([A-Z0-9\-\& \.\,]{3,40})", body, flags=re.IGNORECASE)
    if comercio_match:
        comercio = comercio_match.group(1).strip()

    # 4) Hint de cuenta / tarjeta (últimos 4 dígitos si logras capturarlos)
    account_hint = "BancoChile"
    tarjeta_match = re.search(r"terminada en (\d{4})", body)
    if tarjeta_match:
        account_hint = f"BancoChile-TC-{tarjeta_match.group(1)}"

    # 5) Timestamp: por ahora usamos now(); podrías refinar con la fecha del mail
    ts = datetime.now()

    return ParsedExpense(
        amount_clp=amount,
        description=f"{comercio} (Banco de Chile)",
        timestamp=ts,
        account_hint=account_hint,
    )
