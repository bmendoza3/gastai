# src/ingestion/parsers/bancodechile.py
from __future__ import annotations

GMAIL_QUERY = 'from:(@bancochile.cl) ("compra" OR "transferencia" OR "abono")'

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
    payment_type: str  # 'credito' | 'debito' | 'transferencia'


# Patrón compras:
# "compra por $33.110 con cargo a Cuenta ****7506 en LA MOM BY RAVAL D el 22/03/2026 12:34"
# "compra por $23.960 con Tarjeta de Crédito ****6982 en MERCADOPAGO*MERCADOLIBRE el 22/03/2026 21:27"
_PATTERN_COMPRA = re.compile(
    r"compra por \$([\d\.]+)"
    r"(.+?)\*{4}(\d{4})"
    r" en (.+?)"
    r" el (\d{2}/\d{2}/\d{4} \d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)

# Patrón transferencia enviada:
# "transferencia de $50.000 desde Cuenta ****7506 a nombre de JUAN PEREZ el 22/03/2026 14:00"
_PATTERN_TRANSFERENCIA = re.compile(
    r"transferencia de \$([\d\.]+)"
    r".+?a nombre de (.+?)"
    r" el (\d{2}/\d{2}/\d{4} \d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)

# Patrón abono/transferencia recibida:
# "abono de $200.000 desde EMPRESA SA el 22/03/2026 09:00"
_PATTERN_ABONO = re.compile(
    r"abono de \$([\d\.]+)"
    r".+?desde (.+?)"
    r" el (\d{2}/\d{2}/\d{4} \d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)


def _detect_payment_type(instrument_text: str) -> str:
    t = instrument_text.lower()
    if "crédito" in t or "credito" in t:
        return "credito"
    if "cuenta" in t or "débito" in t or "debito" in t:
        return "debito"
    return "debito"


def _parse_ts(fecha_txt: str) -> datetime:
    try:
        return datetime.strptime(fecha_txt, "%d/%m/%Y %H:%M")
    except ValueError:
        return datetime.now()


def parse_bancochile_email(sender: str, subject: str, body: str) -> Optional[ParsedExpense]:
    sender_l = sender.lower()
    body_l = body.lower()

    if "bancochile" not in sender_l and "banco de chile" not in body_l:
        return None

    # --- Compra ---
    if "compra por" in body_l:
        m = _PATTERN_COMPRA.search(body)
        if not m:
            return None
        monto_txt, instrument, last4, comercio, fecha_txt = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        try:
            amount = float(monto_txt.replace(".", "")) * -1
        except ValueError:
            return None
        comercio = " ".join(comercio.split())
        comercio = re.sub(r"\s+[A-Z][a-z][\w\s]+\s+CL$", "", comercio).strip()
        comercio = re.sub(r"\s+[A-Z]{2,}\s+CL$", "", comercio).strip()
        return ParsedExpense(
            amount_clp=amount,
            description=comercio,
            timestamp=_parse_ts(fecha_txt),
            account_hint=f"BancoChile-{last4}",
            payment_type=_detect_payment_type(instrument),
        )

    # --- Transferencia enviada ---
    if "transferencia de" in body_l:
        m = _PATTERN_TRANSFERENCIA.search(body)
        if not m:
            return None
        monto_txt, destinatario, fecha_txt = m.group(1), m.group(2), m.group(3)
        try:
            amount = float(monto_txt.replace(".", "")) * -1
        except ValueError:
            return None
        return ParsedExpense(
            amount_clp=amount,
            description=f"Transferencia a {destinatario.strip()}",
            timestamp=_parse_ts(fecha_txt),
            account_hint="BancoChile-transferencia",
            payment_type="transferencia",
        )

    # --- Abono recibido ---
    if "abono de" in body_l:
        m = _PATTERN_ABONO.search(body)
        if not m:
            return None
        monto_txt, origen, fecha_txt = m.group(1), m.group(2), m.group(3)
        try:
            amount = float(monto_txt.replace(".", ""))  # positivo: ingreso
        except ValueError:
            return None
        return ParsedExpense(
            amount_clp=amount,
            description=f"Abono desde {origen.strip()}",
            timestamp=_parse_ts(fecha_txt),
            account_hint="BancoChile-abono",
            payment_type="transferencia",
        )

    return None
