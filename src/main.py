from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from src.db.storage import (
    insert_transactions,
    get_pending_transactions,
    get_transaction,
    set_transaction_category,
    set_transaction_intent,
)

app = FastAPI(
    title="ClauFiPe",
    description="API mínima para interactuar con el agente financiero (pendientes, clasificar, etc.)",
    version="0.1.0",
)

# -----------------------------
# Modelos existentes
# -----------------------------

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

# --- NEW ---
class WhatsAppMessageIn(BaseModel):
    # lo que el usuario escribió en WhatsApp, tal cual texto plano
    text: str

class WhatsAppMessageOut(BaseModel):
    # lo que el bot contestaría
    reply: str

# --- NEW ---
CATEGORIES = ["Supermercado", "Farmacia", "Delivery", "Transporte", "Restaurantes", "Servicios", "Otros"]
INTENTS = ["Planeado", "Imprevisto", "Antojo"]

# --- NEW ---
conversation_state = {
    "mode": None,          # None | "awaiting_category" | "awaiting_intent"
    "current_tx_id": None  # tx_id que estamos etiquetando
}


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

# -----------------------------
# Endpoints base del agente
# -----------------------------

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
    return SimpleMessage(message="Transacción registrada y marcada como pendiente de clasificar.")


@app.get("/tx/pending", response_model=Optional[PendingTxResponse])
def get_next_pending():
    df = get_pending_transactions(limit=1)
    if df.empty:
        return None
    row = df.iloc[0]
    return _row_to_pending_payload(row)


@app.post("/tx/set_category", response_model=SimpleMessage)
def assign_category(body: SetCategoryRequest):
    set_transaction_category(body.tx_id, body.category)
    tx_final = get_transaction(body.tx_id)
    return SimpleMessage(
        message=f"Categoría '{body.category}' asignada a {body.tx_id}. "
                f"Estado actual: category={tx_final['category']}, intent={tx_final['intent']}."
    )


@app.post("/tx/set_intent", response_model=SimpleMessage)
def assign_intent(body: SetIntentRequest):
    set_transaction_intent(body.tx_id, body.intent)
    tx_final = get_transaction(body.tx_id)
    return SimpleMessage(
        message=f"Intención '{body.intent}' asignada a {body.tx_id}. "
                f"Ahora needs_review={tx_final['needs_review']}."
    )


# -----------------------------
# --- NEW ---
# /whatsapp/webhook
# -----------------------------
@app.post("/whatsapp/webhook", response_model=WhatsAppMessageOut)
def whatsapp_webhook(msg: WhatsAppMessageIn):
    """
    Este endpoint simula lo que haría WhatsApp:
    - msg.text es lo que tú escribes.
    - devolvemos .reply que sería lo que el bot te manda.
    - conversation_state mantiene el contexto (en qué paso vamos).
    """

    user_text = msg.text.strip()

    # 1. Si estamos esperando categoría:
    if conversation_state["mode"] == "awaiting_category" and conversation_state["current_tx_id"]:
        chosen_category = user_text  # Ej: "Farmacia"
        # validamos que exista dentro de las categorías conocidas
        if chosen_category not in CATEGORIES:
            # si no calza, ofrecemos las opciones
            opts = ", ".join(CATEGORIES)
            return WhatsAppMessageOut(
                reply=f"No caché esa categoría 🤔. Elige una de: {opts}"
            )

        # guardamos categoría
        set_transaction_category(conversation_state["current_tx_id"], chosen_category)

        # avanzamos a preguntar intención
        conversation_state["mode"] = "awaiting_intent"
        opts_int = ", ".join(INTENTS)
        return WhatsAppMessageOut(
            reply=f"✔ Categoría '{chosen_category}' guardada.\n"
                  f"¿Fue Planeado, Imprevisto o Antojo?\n"
                  f"Opciones: {opts_int}"
        )

    # 2. Si estamos esperando intención:
    if conversation_state["mode"] == "awaiting_intent" and conversation_state["current_tx_id"]:
        chosen_intent = user_text  # Ej: "Imprevisto"
        if chosen_intent not in INTENTS:
            opts_int = ", ".join(INTENTS)
            return WhatsAppMessageOut(
                reply=f"No caché esa intención 🙈. Opciones: {opts_int}"
            )

        # guardamos intención y marcamos needs_review=False en storage
        set_transaction_intent(conversation_state["current_tx_id"], chosen_intent)

        tx_final = get_transaction(conversation_state["current_tx_id"])

        # cerramos la conversación
        conversation_state["mode"] = None
        conversation_state["current_tx_id"] = None

        return WhatsAppMessageOut(
            reply=(
                "Listo ✅\n"
                f"Monto: {abs(tx_final['amount_clp']):,.0f} CLP\n"
                f"Descripción: {tx_final['description']}\n"
                f"Categoría: {tx_final['category']}\n"
                f"Intención: {tx_final['intent']}\n"
                "Guardado.\n"
                "¿Quieres revisar otro gasto? Escribe: revisar"
            )
        )

    # 3. Si el usuario escribe "revisar":
    if user_text.lower() in ["revisar", "pendiente", "siguiente"]:
        df = get_pending_transactions(limit=1)
        if df.empty:
            return WhatsAppMessageOut(
                reply="No tienes gastos pendientes 🎉"
            )
        row = df.iloc[0]

        # seteamos contexto conversación
        conversation_state["mode"] = "awaiting_category"
        conversation_state["current_tx_id"] = row.tx_id

        opts = ", ".join(CATEGORIES)
        return WhatsAppMessageOut(
            reply=(
                "Tengo este gasto pendiente:\n"
                f"- {abs(row.amount_clp):,.0f} CLP en {row.description}\n"
                f"- Fecha: {row.ts}\n\n"
                f"¿En qué categoría lo pongo?\n"
                f"Opciones: {opts}"
            )
        )

    # 4. Si manda cualquier otra cosa fuera de flujo:
    return WhatsAppMessageOut(
        reply=(
            "Hola 👋 Soy tu agente de gastos.\n"
            "Escribe:\n"
            "- 'revisar' para clasificar el próximo gasto pendiente\n"
            "- o responde una categoría/intención si ya estamos en eso"
        )
    )