import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from pydantic import BaseModel

from fastapi.responses import HTMLResponse, RedirectResponse

from src.agent.agents import chat
from src.db.storage import con as db_con, get_all_users, get_transaction, insert_transactions, upsert_user, clear_recurring_items, clear_pending_charges, clear_all_user_data
from src.ingestion.gmail_client import exchange_code_for_token, get_oauth_url, has_token
from src.ingestion.gmail_ingest import ingest_gmail_expenses
from src.integrations.messaging import send_image, send_message
from src.integrations.whatsapp_cloud import verify_token
from src.reports.charts import spend_bar_chart, spend_pie_chart

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLLING_INTERVAL_MINUTES = int(os.getenv("POLLING_INTERVAL_MINUTES", "5"))
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/admin/gmail/callback")
MESSAGING_CHANNELS = [c.strip() for c in os.getenv("MESSAGING_CHANNELS", "whatsapp").split(",") if c.strip()]


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
        if not has_token(phone):
            logger.debug(f"[{phone}] Sin token de Gmail, omitiendo polling")
            continue
        try:
            new_ids = ingest_gmail_expenses(user)
            for tx_id in new_ids:
                tx = get_transaction(tx_id)
                if tx:
                    msg = _format_new_tx_notification(tx)
                    await send_message(phone, msg)
                    logger.info(f"Notificación enviada a {phone}: {tx_id}")
        except Exception as e:
            logger.error(f"Error en polling para {phone}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if "telegram" in MESSAGING_CHANNELS:
        from src.integrations.telegram_bot import start_bot
        await start_bot()

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
    if "telegram" in MESSAGING_CHANNELS:
        from src.integrations.telegram_bot import stop_bot
        await stop_bot()


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

class RegisterUserRequest(BaseModel):
    phone: str    # ej: +56912345678
    name: str



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


# ============== ADMIN: USUARIOS Y OAUTH ==============

@app.post("/admin/users")
def register_user(req: RegisterUserRequest):
    """Registra un usuario nuevo. Después agrega bancos y conecta Gmail."""
    upsert_user(req.phone, req.name)
    return {
        "status": "ok",
        "phone": req.phone,
        "gmail_connected": has_token(req.phone),
        "next_steps": [
            f"POST /admin/users/{req.phone}/banks  (agregar banco)",
            f"GET  /admin/users/{req.phone}/gmail/connect  (autorizar Gmail)",
        ],
    }


@app.get("/admin/users")
def list_users():
    users = get_all_users()
    return [
        {
            "phone": u["phone"],
            "name": u["name"],
            "gmail_connected": has_token(u["phone"]),
        }
        for u in users
    ]


@app.get("/admin/users/{phone}/gmail/connect")
def gmail_connect(phone: str):
    """Redirige al flujo OAuth de Google para el usuario dado."""
    url = get_oauth_url(phone, GMAIL_REDIRECT_URI)
    return RedirectResponse(url)


@app.get("/admin/gmail/callback")
async def gmail_callback(request: Request):
    """Google redirige aquí tras autorizar. Guarda el token y ya empieza el polling."""
    code = request.query_params.get("code")
    phone = request.query_params.get("state")
    if not code or not phone:
        return HTMLResponse(_callback_html("error", "Faltan parámetros. Intenta conectar Gmail de nuevo."), status_code=400)

    exchange_code_for_token(phone, code, GMAIL_REDIRECT_URI)
    logger.info(f"Gmail conectado para {phone}")

    name = ""
    from src.db.storage import get_user
    user = get_user(phone)
    if user:
        name = user["name"]

    if phone.startswith("tg_") and "telegram" in MESSAGING_CHANNELS:
        chat_id = phone[3:]
        from src.integrations.telegram_bot import notify_gmail_connected
        await notify_gmail_connected(chat_id, phone)

    return HTMLResponse(_callback_html("ok", name))


def _callback_html(status: str, name_or_error: str = "") -> str:
    if status == "ok":
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GastAI — Gmail conectado</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center;
            justify-content: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
    .card {{ background: white; border-radius: 16px; padding: 48px 40px; text-align: center;
             box-shadow: 0 2px 16px rgba(0,0,0,0.08); max-width: 360px; width: 90%; }}
    .icon {{ font-size: 56px; margin-bottom: 16px; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; color: #111; }}
    p {{ color: #555; font-size: 15px; line-height: 1.5; margin: 0; }}
    .name {{ color: #111; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>¡Gmail conectado!</h1>
    <p>{"Hola <span class='name'>" + name_or_error + "</span>, ya" if name_or_error else "Ya"}
       puedes cerrar esta ventana.<br><br>
       Vuelve a Telegram — GastAI empezará a detectar tus gastos automáticamente.</p>
  </div>
</body>
</html>"""
    else:
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GastAI — Error</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center;
            justify-content: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
    .card {{ background: white; border-radius: 16px; padding: 48px 40px; text-align: center;
             box-shadow: 0 2px 16px rgba(0,0,0,0.08); max-width: 360px; width: 90%; }}
    .icon {{ font-size: 56px; margin-bottom: 16px; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; color: #111; }}
    p {{ color: #555; font-size: 15px; line-height: 1.5; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">❌</div>
    <h1>Algo salió mal</h1>
    <p>{name_or_error}</p>
  </div>
</body>
</html>"""


# ============== RESET DE DATOS ==============

@app.delete("/admin/users/{phone}/recurring")
async def reset_recurring(phone: str):
    """Elimina todos los ítems recurrentes de un usuario."""
    n = clear_recurring_items(phone)
    return {"deleted": n}


@app.delete("/admin/users/{phone}/charges")
async def reset_charges(phone: str):
    """Marca como pagados todos los cargos pendientes de un usuario."""
    n = clear_pending_charges(phone)
    return {"cleared": n}


@app.delete("/admin/users/{phone}/reset")
async def reset_all(phone: str):
    """Limpia ítems recurrentes y cargos pendientes de un usuario."""
    rec = clear_recurring_items(phone)
    chg = clear_pending_charges(phone)
    return {"recurring_deleted": rec, "charges_cleared": chg}


@app.delete("/admin/users/{phone}/data")
async def reset_user_data(phone: str):
    """Borra todos los datos financieros de un usuario (transacciones, ingresos, recurrentes, cargos)."""
    return clear_all_user_data(phone)


@app.delete("/admin/data")
async def reset_all_data():
    """Borra todos los datos financieros de TODOS los usuarios. Usar solo en dev."""
    return clear_all_user_data()


# ============== POLLING MANUAL ==============

@app.post("/admin/poll")
async def trigger_poll():
    """Dispara el polling de Gmail manualmente (útil para testing)."""
    await poll_gmail_all_users()
    return {"status": "ok"}


# ============== WEBHOOK DE PRUEBA (sin Meta) ==============

@app.post("/whatsapp/webhook", response_model=WhatsAppMessageOut)
async def whatsapp_test(msg: WhatsAppMessageIn):
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
        await send_image(from_number, buf, caption=f"Tus gastos — {period}")
    else:
        await send_message(from_number, reply)

    return {"status": "sent"}
