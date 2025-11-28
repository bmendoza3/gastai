from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import re

# capa de datos
from src.db.storage import (
    insert_transactions,
    get_pending_transactions,
    get_transaction,
    set_transaction_category,
    set_transaction_intent,
    con as db_con,
)

# integración con Meta
from src.integrations.whatsapp_cloud import verify_token, send_message


app = FastAPI(
    title="ClauFiPe",
    description="API mínima para interactuar con el agente financiero (pendientes, clasificar, etc.)",
    version="0.1.0",
)

# ============== MODELOS ==============

class NewTxRequest(BaseModel):
    tx_id: str
    timestamp: datetime
    description: str
    amount_clp: float
    account_id: str

class PendingTxResponse(BaseModel):
    tx_id: str
    timestamp: datetime
    description: str
    amount_clp: float
    account_id: str
    category: Optional[str]
    intent: Optional[str]

class SetCategoryRequest(BaseModel):
    tx_id: str
    category: str

class SetIntentRequest(BaseModel):
    tx_id: str
    intent: str

class SimpleMessage(BaseModel):
    message: str

class WhatsAppMessageIn(BaseModel):
    text: str
    phone_number: str

class WhatsAppMessageOut(BaseModel):
    reply: str


# ============== CONSTANTES ==============

CATEGORIES = [
    "supermercado",
    "farmacia",
    "delivery",
    "transporte",
    "restaurantes",
    "servicios",
    "otros",
]

INTENTS = ["planeado", "imprevisto", "antojo"]


# estado conversacional en memoria
conversation_state = {
    "mode": None,          # None | "awaiting_category" | "awaiting_intent"
    "current_tx_id": None  # tx_id que estamos editando
}

# ============== HELPERS ==============

def _row_to_pending_payload(row) -> PendingTxResponse:
    return PendingTxResponse(
        tx_id=row.tx_id,
        timestamp=row.ts,
        description=row.description,
        amount_clp=row.amount_clp,
        account_id=row.account_id,
        category=row.category,
        intent=row.intent,
    )

def parse_new_expense_from_text(user_text: str):
    """
    Soporta comandos tipo:
    - 'añadir gasto 5000 cruz verde'
    - 'anadir gasto 5000 cruz verde'
    - 'agregar gasto 12000 supermercado lider'
    - 'nuevo 8000 sushi'
    - 'añadir transaccion 3000 farmacia'

    Regla: primer número que encuentre = monto, el resto = descripción.
    """
    original = user_text.strip()
    lower = original.lower()

    prefixes = [
        "añadir gasto",
        "anadir gasto",
        "agregar gasto",
        "nuevo",
        "añadir transaccion",
        "anadir transaccion",
    ]

    body = None
    for p in prefixes:
        if lower.startswith(p):
            body = original[len(p):].strip()
            break

    if not body:
        return False, "No detecto el formato 😅. Prueba con: 'añadir gasto 5000 cruz verde'"

    # buscar primer número
    m = re.search(r"(-?\d+(?:[.,]\d+)?)", body)
    if not m:
        return False, "Necesito un monto, ej: 'añadir gasto 5000 cruz verde'"

    amount_str = m.group(1)
    # normalizar: 10.000 -> 10000 ; 10,5 -> 10.5
    amount_norm = amount_str.replace(".", "").replace(",", ".")
    try:
        amount = float(amount_norm)
    except ValueError:
        return False, "No pude entender el monto 🧠. Prueba algo como: 'añadir gasto 5000 cruz verde'"

    # descripción = texto antes y después del número
    desc_before = body[:m.start()].strip()
    desc_after = body[m.end():].strip()
    description = (desc_before + " " + desc_after).strip()
    if not description:
        description = "Gasto desde WhatsApp"

    ts = datetime.now().isoformat()
    tx_id = f"whatsapp-{int(datetime.now().timestamp())}"

    insert_transactions([{
        "tx_id": tx_id,
        "timestamp": ts,
        "description": description,
        "amount_clp": amount,
        "account_id": "whatsapp",
        "category": None,
        "intent": None,
        "needs_review": True,
    }])

    reply = (
        f"Anoté un gasto de {abs(amount):,.0f} CLP en '{description}'.\n"
        "Lo dejé pendiente para clasificación.\n"
        "Escribe 'revisar' para etiquetarlo."
    )
    return True, reply


# ============== ROOT (para que no salga 404) ==============

@app.get("/")
def root():
    return {
        "app": "claufipe-finanzas",
        "status": "ok",
        "docs": "/docs",
        "webhook": "/whatsapp/incoming",
    }


# ============== ENDPOINTS BASE ==============

@app.post("/tx/new", response_model=SimpleMessage)
def add_transaction(tx: NewTxRequest):
    insert_transactions([{
        "tx_id": tx.tx_id,
        "timestamp": tx.timestamp.isoformat(),
        "description": tx.description,
        "amount_clp": tx.amount_clp,
        "account_id": tx.account_id,
        "category": None,
        "intent": None,
        "needs_review": True,
    }])
    return SimpleMessage(message="Transacción registrada y marcada como pendiente.")


@app.get("/tx/pending", response_model=Optional[PendingTxResponse])
def get_next_pending():
    df = get_pending_transactions(limit=1)
    if df.empty:
        return None
    return _row_to_pending_payload(df.iloc[0])


@app.post("/tx/set_category", response_model=SimpleMessage)
def assign_category(body: SetCategoryRequest):
    set_transaction_category(body.tx_id, body.category)
    tx_final = get_transaction(body.tx_id)
    return SimpleMessage(message=f"Categoría '{body.category}' asignada. intent={tx_final['intent']}")


@app.post("/tx/set_intent", response_model=SimpleMessage)
def assign_intent(body: SetIntentRequest):
    set_transaction_intent(body.tx_id, body.intent)
    tx_final = get_transaction(body.tx_id)
    return SimpleMessage(message=f"Intención '{body.intent}' asignada. needs_review={tx_final['needs_review']}")


# ============== CONVERSACIONAL LOCAL ==============

@app.post("/whatsapp/webhook", response_model=WhatsAppMessageOut)
def whatsapp_webhook(msg: WhatsAppMessageIn):
    user_text = msg.text.strip()
    user_text_lower = user_text.lower()
    user_phone_number= msg.phone_number

    print("🔎 STATE ANTES:", conversation_state, "| TEXT:", user_text)

    # 0) comando para añadir gasto desde texto
    if user_text_lower.startswith((
        "añadir gasto",
        "anadir gasto",
        "agregar gasto",
        "nuevo",
        "añadir transaccion",
        "anadir transaccion",
    )):
        ok, reply = parse_new_expense_from_text(user_text)
        print("➕ NUEVO GASTO OK?", ok)
        return WhatsAppMessageOut(reply=reply)

    # 1) esperando categoría
    if conversation_state["mode"] == "awaiting_category" and conversation_state["current_tx_id"]:
        chosen_lower = user_text_lower
        if chosen_lower not in CATEGORIES:
            options = ", ".join(c.title() for c in CATEGORIES)
            return WhatsAppMessageOut(
                reply=f"No caché esa categoría 🤔. Opciones: {options}"
            )

        # guardamos tal cual en minúscula o capitalizada, da igual para DB
        set_transaction_category(conversation_state["current_tx_id"], chosen_lower)

        conversation_state["mode"] = "awaiting_intent"

        options_int = ", ".join(i.title() for i in INTENTS)
        print("🔎 STATE DESPUÉS:", conversation_state)
        return WhatsAppMessageOut(
            reply=(
                f"✔ Categoría '{chosen_lower.title()}' guardada.\n"
                f"¿Fue Planeado, Imprevisto o Antojo?\n"
                f"Opciones: {options_int}"
            )
        )

    # 2) esperando intención
    if conversation_state["mode"] == "awaiting_intent" and conversation_state["current_tx_id"]:
        chosen_lower = user_text_lower
        if chosen_lower not in INTENTS:
            options = ", ".join(i.title() for i in INTENTS)
            return WhatsAppMessageOut(
                reply=f"No caché esa intención 🙈. Opciones: {options}"
            )

        set_transaction_intent(conversation_state["current_tx_id"], chosen_lower)
        tx_final = get_transaction(conversation_state["current_tx_id"])

        # limpiar estado
        conversation_state["mode"] = None
        conversation_state["current_tx_id"] = None

        print("🔎 STATE DESPUÉS:", conversation_state)
        return WhatsAppMessageOut(
            reply=(
                "Listo ✅\n"
                f"Monto: {abs(tx_final['amount_clp']):,.0f} CLP\n"
                f"Descripción: {tx_final['description']}\n"
                f"Categoría: {str(tx_final['category']).title()}\n"
                f"Intención: {str(tx_final['intent']).title()}\n"
                "¿Quieres revisar otro gasto? Escribe: revisar"
            )
        )

    # 3) comando "revisar"
    if user_text_lower in ["revisar", "pendiente", "siguiente"]:
        df = get_pending_transactions(account_id=user_phone_number,limit=1)
        if df.empty:
            return WhatsAppMessageOut(
                reply=(
                    "No tienes gastos pendientes 🎉\n\n"
                    "Puedes:\n"
                    "- Enviar algo como: 'añadir gasto 5000 cruz verde'\n"
                    "- O volver a escribir 'revisar' cuando entre otro gasto."
                )
            )

        row = df.iloc[0]
        conversation_state["mode"] = "awaiting_category"
        conversation_state["current_tx_id"] = row.tx_id

        options = ", ".join(c.title() for c in CATEGORIES)

        print("🔎 STATE DESPUÉS:", conversation_state)
        return WhatsAppMessageOut(
            reply=(
                "Tengo este gasto pendiente:\n"
                f"- {abs(row.amount_clp):,.0f} CLP en {row.description}\n"
                f"- Fecha: {row.ts}\n\n"
                f"¿En qué categoría lo pongo?\n"
                f"Opciones: {options}"
            )
        )

    # 4) mensaje fuera de flujo
    return WhatsAppMessageOut(
        reply=(
            "Hola 👋 Soy tu agente de gastos.\n"
            "- Escribe 'revisar' para clasificar el próximo gasto pendiente.\n"
            "- O envía 'añadir gasto 5000 cruz verde' para registrar un gasto nuevo."
        )
    )



# ============== DEBUG (ver DB) ==============

@app.get("/debug/transactions")
def debug_transactions():
    df = db_con.execute("""
        SELECT tx_id, ts, description, amount_clp, account_id, category, intent, needs_review
        FROM transactions
        ORDER BY ts DESC
    """).fetchdf()
    return df.to_dict(orient="records")


# ============== WEBHOOK DE META (ENTRANTE) ==============

@app.get("/whatsapp/incoming")
async def whatsapp_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    print("✅ VERIF GET:", mode, token, challenge)
    res = verify_token(mode, token, challenge)
    if res is not None:
        return res
    return {"error": "invalid token"}


@app.post("/whatsapp/incoming")
async def whatsapp_incoming(request: Request):
    body = await request.json()
    print("📩 LLEGÓ POST DE META:", body)

    # la estructura típica: entry[0].changes[0].value.messages[0]
    try:
        value = body["entry"][0]["changes"][0]["value"]
    except Exception:
        return {"status": "no-value"}

    # si son mensajes reales
    if "messages" in value:
        message = value["messages"][0]
        text = message["text"]["body"]
        from_number = message["from"]

        print(f"[WHATSAPP] {from_number} → {text}")

        # pasar a nuestra lógica interna
        bot_reply = whatsapp_webhook(WhatsAppMessageIn(text=text,
                                                       phone_number=from_number))

        # responder por la Cloud API
        send_message(from_number, bot_reply.reply)

        print(f"[WHATSAPP] BOT → {bot_reply.reply}")

        return {"status": "sent"}

    # si no venía messages, puede ser delivery/status
    print("ℹ️ No venía 'messages' en el webhook. Claves:", value.keys())
    return {"status": "ignored"}