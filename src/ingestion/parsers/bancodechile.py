# src/ingestion/parsers/bancodechile.py
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


# Patrón basado en el formato real del email:
# "compra por $33.110 con cargo a Cuenta ****7506 en LA MOM BY RAVAL D el 22/03/2026 12:34"
# "compra por $23.960 con Tarjeta de Crédito ****6982 en MERCADOPAGO*MERCADOLIBRE Las Condes CL el 22/03/2026 21:27"
_PATTERN = re.compile(
    r"compra por \$([\d\.]+)"          # monto: $33.110
    r".+?\*{4}(\d{4})"                 # últimos 4 dígitos de la cuenta/tarjeta
    r" en (.+?)"                       # comercio
    r" el (\d{2}/\d{2}/\d{4} \d{2}:\d{2})",  # fecha y hora
    re.IGNORECASE | re.DOTALL,
)


def parse_bancochile_email(sender: str, subject: str, body: str) -> Optional[ParsedExpense]:
    sender_l = sender.lower()
    body_l = body.lower()

    # Filtro: solo emails de BancoChile con aviso de compra
    if "bancochile" not in sender_l and "banco de chile" not in body_l:
        return None
    if "compra por" not in body_l:
        return None

    m = _PATTERN.search(body)
    if not m:
        return None

    monto_txt, last4, comercio, fecha_txt = m.group(1), m.group(2), m.group(3), m.group(4)

    # Monto: "33.110" → 33110
    try:
        amount = float(monto_txt.replace(".", "")) * -1
    except ValueError:
        return None

    # Comercio: limpiar espacios extra y sufijos de ciudad/país (ej: "Las Condes CL", "SANTIAGO CL")
    comercio = " ".join(comercio.split())
    comercio = re.sub(r"\s+[A-Z][a-z][\w\s]+\s+CL$", "", comercio).strip()
    comercio = re.sub(r"\s+[A-Z]{2,}\s+CL$", "", comercio).strip()

    # Timestamp: "22/03/2026 12:34"
    try:
        ts = datetime.strptime(fecha_txt, "%d/%m/%Y %H:%M")
    except ValueError:
        ts = datetime.now()

    account_hint = f"BancoChile-{last4}"

    return ParsedExpense(
        amount_clp=amount,
        description=comercio,
        timestamp=ts,
        account_hint=account_hint,
    )
