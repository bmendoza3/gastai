from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel

from src.agent.agents import chat
from src.db.storage import con as db_con, insert_transactions
from src.integrations.whatsapp_cloud import send_message, verify_token

app = FastAPI(title="GastAI", version="0.2.0")


# ============== MODELOS ==============

class NewTxRequest(BaseModel):
    tx_id: str
    timestamp: datetime
    description: str
    amount_clp: float
    account_id: str

class WhatsAppMessageIn(BaseModel):
    text: str
    phone_number: str

class WhatsAppMessageOut(BaseModel):
    reply: str


# ============== ROOT ==============

@app.get("/")
def root():
    return {"app": "gastai", "status": "ok", "docs": "/docs"}


# ============== TRANSACCIONES (REST para ingesta externa / debug) ==============

@app.post("/tx/new")
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
    return {"message": "Transacción registrada."}


@app.get("/debug/transactions")
def debug_transactions():
    df = db_con.execute("""
        SELECT tx_id, ts, description, amount_clp, account_id, category, intent, needs_review
        FROM transactions ORDER BY ts DESC
    """).fetchdf()
    return df.to_dict(orient="records")


# ============== WEBHOOK DE PRUEBA (sin Meta) ==============

@app.post("/whatsapp/webhook", response_model=WhatsAppMessageOut)
def whatsapp_test(msg: WhatsAppMessageIn):
    reply = chat(msg.phone_number, msg.text)
    return WhatsAppMessageOut(reply=reply)


# ============== WEBHOOK DE META ==============

@app.get("/whatsapp/incoming")
async def whatsapp_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    res = verify_token(mode, token, challenge)
    return res if res is not None else {"error": "invalid token"}


@app.post("/whatsapp/incoming")
async def whatsapp_incoming(request: Request):
    body = await request.json()
    try:
        value = body["entry"][0]["changes"][0]["value"]
    except Exception:
        return {"status": "no-value"}

    if "messages" not in value:
        return {"status": "ignored"}

    message = value["messages"][0]
    text = message["text"]["body"]
    from_number = message["from"]

    reply = chat(from_number, text)
    send_message(from_number, reply)

    return {"status": "sent"}
