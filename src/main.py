import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from pydantic import BaseModel

from src.agent.agents import chat
from src.db.storage import con as db_con, get_all_users, get_transaction, insert_transactions
from src.ingestion.gmail_ingest import ingest_gmail_expenses
from src.integrations.whatsapp_cloud import send_image, send_message, verify_token
from src.reports.charts import spend_bar_chart, spend_pie_chart

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLLING_INTERVAL_MINUTES = int(os.getenv("POLLING_INTERVAL_MINUTES", "5"))


def _format_new_tx_notification(tx: dict) -> str:
    amount = abs(tx["amount_clp"])
    ts = tx["ts"]
    try:
        hora = datetime.fromisoformat(str(ts)).strftime("%H:%M")
        fecha = datetime.fromisoformat(str(ts)).strftime("%d/%m")
    except Exception:
        hora = fecha = str(ts)

    return (
        f"Nuevo gasto detectado 💳\n"
        f"📍 {tx['description']}\n"
        f"💸 ${amount:,.0f} CLP\n"
        f"🕐 {fecha} a las {hora}\n\n"
        f"Responde para clasificarlo o escribe *pendientes* para ver todos."
    )


async def poll_gmail_all_users():
    """Polling de Gmail para todos los usuarios registrados."""
    users = get_all_users()
    if not users:
        logger.debug("Sin usuarios registrados, omitiendo polling")
        return

    for user in users:
        phone = user["phone"]
        try:
            new_ids = ingest_gmail_expenses(user)
            for tx_id in new_ids:
                tx = get_transaction(tx_id)
                if tx:
                    msg = _format_new_tx_notification(tx)
                    send_message(phone, msg)
                    logger.info(f"Notificación enviada a {phone}: {tx_id}")
        except Exception as e:
            logger.error(f"Error en polling para {phone}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_gmail_all_users,
        "interval",
        minutes=POLLING_INTERVAL_MINUTES,
        id="gmail_poll",
    )
    scheduler.start()
    logger.info(f"Scheduler iniciado — polling cada {POLLING_INTERVAL_MINUTES} min")
    yield
    scheduler.shutdown()
    logger.info("Scheduler detenido")


app = FastAPI(title="GastAI", version="0.3.0", lifespan=lifespan)


# ============== MODELOS ==============

class NewTxRequest(BaseModel):
    tx_id: str
    timestamp: datetime
    description: str
    amount_clp: float
    user_phone: str

class WhatsAppMessageIn(BaseModel):
    text: str
    phone_number: str

class WhatsAppMessageOut(BaseModel):
    reply: str


# ============== ROOT ==============

@app.get("/")
def root():
    return {"app": "gastai", "version": "0.3.0", "status": "ok", "docs": "/docs"}


# ============== TRANSACCIONES ==============

@app.post("/tx/new")
def add_transaction(tx: NewTxRequest):
    insert_transactions([{
        "tx_id": tx.tx_id,
        "timestamp": tx.timestamp.isoformat(),
        "description": tx.description,
        "amount_clp": tx.amount_clp,
        "user_phone": tx.user_phone,
        "category": None,
        "intent": None,
        "needs_review": True,
        "source": "api",
    }])
    return {"message": "Transacción registrada."}


@app.get("/debug/transactions")
def debug_transactions():
    df = db_con.execute(
        "SELECT tx_id, ts, description, amount_clp, user_phone, category, intent, needs_review, source "
        "FROM transactions ORDER BY ts DESC"
    ).fetchdf()
    return df.to_dict(orient="records")


# ============== POLLING MANUAL ==============

@app.post("/admin/poll")
async def trigger_poll():
    """Dispara el polling de Gmail manualmente (útil para testing)."""
    await poll_gmail_all_users()
    return {"status": "ok"}


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
    if message.get("type") != "text":
        return {"status": "ignored"}

    text = message["text"]["body"]
    from_number = message["from"]

    reply = chat(from_number, text)

    # Si el agente generó un gráfico, enviarlo como imagen
    if reply.startswith("__CHART__:"):
        _, chart_type, days_str = reply.split(":")
        days = int(days_str)
        buf = spend_pie_chart(from_number, days) if chart_type == "pie" else spend_bar_chart(from_number, days)
        period = f"últimos {days} días" if days != 30 else "último mes"
        send_image(from_number, buf, caption=f"Tus gastos — {period}")
    else:
        send_message(from_number, reply)

    return {"status": "sent"}
