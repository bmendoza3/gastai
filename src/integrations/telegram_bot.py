import logging
import os
from io import BytesIO

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")

def _extract_name(raw: str) -> tuple[str, str]:
    """
    Usa el LLM para extraer nombre completo y apodo preferido.
    Retorna (full_name, nickname).
    Ej: 'Bastián Mendoza pero dime Mendo' → ('Bastián Mendoza', 'Mendo')
    """
    from src.agent.agents import client, MODEL
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extrae el nombre completo y el apodo preferido de la respuesta. "
                    "Responde SOLO en formato JSON: {\"full_name\": \"...\", \"nickname\": \"...\"}. "
                    "Si no hay apodo distinto, nickname debe ser el primer nombre. "
                    "Ejemplos:\n"
                    "'Bastián Mendoza pero dime Mendo' → {\"full_name\": \"Bastián Mendoza\", \"nickname\": \"Mendo\"}\n"
                    "'me llamo Juan Carlos' → {\"full_name\": \"Juan Carlos\", \"nickname\": \"Juan Carlos\"}\n"
                    "'soy el Cote' → {\"full_name\": \"Cote\", \"nickname\": \"Cote\"}"
                ),
            },
            {"role": "user", "content": raw},
        ],
        max_tokens=40,
    )
    import json as _json
    try:
        data = _json.loads(response.choices[0].message.content.strip())
        full_name = data.get("full_name", raw.strip()).strip().strip("\"'")
        nickname = data.get("nickname", full_name.split()[0]).strip().strip("\"'")
    except Exception:
        full_name = raw.strip().split()[0].capitalize()
        nickname = full_name
    return full_name, nickname

_app: Application | None = None
_onboarding: dict[str, str] = {}  # chat_id → estado ("WAITING_NAME")

WELCOME_MSG = (
    "¡Hola! Soy *GastAI* 💸\n\n"
    "Tu asistente de finanzas personales por Telegram.\n\n"
    "¿Cómo te llamas?"
)

_ONBOARDING_MENU_MSG = (
    "¡Listo, {name}! 🎉 Esto es lo que puedo hacer por ti:\n\n"
    "📧 *Con Gmail conectado:*\n"
    "  · Detecto tus compras con tarjeta automáticamente\n"
    "  · Te aviso cada vez que llega un cargo\n"
    "  · Clasificamos juntos cada gasto\n\n"
    "📊 *Sin Gmail (planificación manual):*\n"
    "  · Registras tu sueldo e ingresos\n"
    "  · Configuras gastos fijos (arriendo, Netflix, etc.)\n"
    "  · Te digo cuánto te queda libre cada mes\n"
    "  · Defines presupuestos por categoría\n"
    "  · Registras deudas y cargos pendientes\n\n"
    "¿Por dónde quieres empezar?"
)

_ONBOARDING_KEYBOARD = ReplyKeyboardMarkup(
    [["📧 Conectar Gmail", "📊 Planificar sin Gmail"]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

_PLANNING_GUIDE_MSG = (
    "Perfecto. Te guío para configurar tu perfil financiero:\n\n"
    "*Paso 1* — Cuéntame tu sueldo o ingresos mensuales\n"
    "_Ej: «Recibo $1.800.000 de sueldo el día 30»_\n\n"
    "*Paso 2* — Dime tus gastos fijos\n"
    "_Ej: «Pago arriendo $450.000 el día 5, Netflix $6.000, gym $25.000»_\n\n"
    "*Paso 3* — Define tus presupuestos (opcional)\n"
    "_Ej: «Ponme $80.000 de presupuesto en comida»_\n\n"
    "Con eso te puedo decir exactamente cuánto te queda disponible cada mes 📊\n\n"
    "¿Empezamos? Cuéntame tu sueldo o ingresos."
)


async def send_message(chat_id: str | int, text: str):
    await _app.bot.send_message(chat_id=chat_id, text=text)


async def _reply(update, text: str, **kwargs):
    """Envía con Markdown; si falla por entidades inválidas, reenvía como texto plano."""
    from telegram.error import BadRequest
    try:
        await update.message.reply_text(text, parse_mode="Markdown", **kwargs)
    except BadRequest as e:
        if "parse" in str(e).lower() or "entity" in str(e).lower():
            await update.message.reply_text(text, **kwargs)
        else:
            raise


async def send_image(chat_id: str | int, image_buf: BytesIO, caption: str = ""):
    image_buf.seek(0)
    await _app.bot.send_photo(chat_id=chat_id, photo=image_buf, caption=caption)


_CATEGORY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🚗 transporte",    "🍔 comida",         "🛒 supermercado"],
        ["💊 salud",         "🎬 entretenimiento", "📱 suscripciones"],
        ["👕 ropa",          "📚 educacion",       "🏠 hogar"],
        ["💼 trabajo",       "✈️ viajes",           "🐾 mascota"],
        ["📦 otros"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="¿A qué categoría pertenece?",
)

_INTENT_KEYBOARD = ReplyKeyboardMarkup(
    [["✅ previsto", "⚡ imprevisto"]],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="¿Era un gasto esperado?",
)

_CATEGORIES = {
    "transporte", "comida", "supermercado", "salud", "entretenimiento",
    "suscripciones", "ropa", "educacion", "hogar", "trabajo", "viajes",
    "mascota", "otros",
}
_INTENTS = {"previsto", "imprevisto"}


def _strip_button(text: str) -> str:
    """'🚗 transporte' → 'transporte', '✈️ viajes' → 'viajes'"""
    text_lower = text.lower()
    for known in _CATEGORIES | _INTENTS:
        if known in text_lower:
            return known
    # fallback: quitar todo lo que no sea letra
    import re
    return re.sub(r"^[^a-záéíóúüña-z]+", "", text, flags=re.IGNORECASE).strip().lower()


def _is_classification_prompt(text: str) -> bool:
    return "¿Cómo lo clasificamos?" in text


def _extract_pending_tx_id(phone: str) -> str | None:
    """Extrae el tx_id del último get_pending en el historial del agente."""
    import re
    from src.agent.agents import _history
    for msg in reversed(_history.get(phone, [])):
        if msg.get("role") == "tool" and "tx_id=" in (msg.get("content") or ""):
            m = re.search(r"tx_id=(\S+)", msg["content"])
            if m:
                return m.group(1).strip("|").strip()
    return None


async def _show_next_pending(chat_id: str, phone: str, update) -> bool:
    """Muestra el siguiente gasto pendiente. Retorna True si hay uno, False si no."""
    from datetime import datetime
    from src.db.storage import get_pending_transactions
    df = get_pending_transactions(user_phone=phone, limit=1)
    if df.empty:
        await update.message.reply_text(
            "✅ ¡Sin más pendientes! Todos tus gastos están clasificados.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return False
    row = df.iloc[0]
    tx_id = row["tx_id"]
    _onboarding[chat_id] = f"CLASSIFYING_CATEGORY:{tx_id}"
    try:
        fecha = datetime.fromisoformat(str(row["ts"])).strftime("%d/%m/%Y")
    except Exception:
        fecha = str(row["ts"])
    await update.message.reply_text(
        f"💳 {row['description']}\n"
        f"💸 ${abs(row['amount_clp']):,.0f} CLP  •  📅 {fecha}\n\n"
        "¿Cómo lo clasificamos?",
        reply_markup=_CATEGORY_KEYBOARD,
    )
    return True


def _gmail_connect_msg(phone: str) -> str:
    url = f"{FASTAPI_BASE_URL}/admin/users/{phone}/gmail/connect"
    return (
        "Para conectar tu Gmail, abre este link en tu browser:\n"
        f"{url}\n\n"
        "(Puedes hacerlo más tarde con /gmail)"
    )


async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.storage import get_user_by_telegram_id
    chat_id = str(update.effective_chat.id)
    user = get_user_by_telegram_id(chat_id)
    if user:
        from src.ingestion.gmail_client import has_token
        phone = user["phone"]
        display = user.get("nickname") or user["name"]
        gmail_status = "✅ Gmail conectado" if has_token(phone) else "❌ Gmail no conectado (/gmail para conectar)"
        await update.message.reply_text(
            f"¡Hola de nuevo, {display}! 👋\n\n"
            f"{gmail_status}\n\n"
            "¿Qué quieres hacer?\n"
            "· «ver mis gastos» / «gráfico» / «resumen del mes»\n"
            "· «cuánto me queda este mes» → proyección financiera\n"
            "· «mi presupuesto» → estado vs límites\n"
            "· «gastos recurrentes» → ver/agregar fijos\n"
            "· «registrar gasto» → anotar algo manual\n"
            "· «clasificar pendientes» → revisar alertas del banco\n\n"
            "O simplemente escríbeme en lenguaje natural 💬",
            parse_mode="Markdown",
        )
        return
    _onboarding[chat_id] = "WAITING_NAME"
    await update.message.reply_text(WELCOME_MSG, parse_mode="Markdown")


async def _handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.storage import get_user_by_telegram_id
    chat_id = str(update.effective_chat.id)
    user = get_user_by_telegram_id(chat_id)
    if not user:
        await update.message.reply_text("No tienes una cuenta registrada.")
        return
    _onboarding[chat_id] = "WAITING_CLEAR_CONFIRM"
    await update.message.reply_text(
        f"⚠️ Esto eliminará tu cuenta ({user['name']}) y *todos* tus datos de GastAI.\n\n"
        "Escribe *confirmar* para continuar o cualquier otra cosa para cancelar.",
        parse_mode="Markdown",
    )


async def _handle_gmail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.db.storage import get_user_by_telegram_id
    chat_id = str(update.effective_chat.id)
    user = get_user_by_telegram_id(chat_id)
    if not user:
        await update.message.reply_text("Primero regístrate con /start.")
        return
    await update.message.reply_text(_gmail_connect_msg(user["phone"]))


async def notify_gmail_connected(chat_id: str, phone: str):
    """Llamado desde main.py después del OAuth. Notifica y ofrece escaneo completo."""
    _onboarding[chat_id] = "WAITING_GMAIL_SCAN_CONFIRM"
    await send_message(
        chat_id,
        "✅ ¡Gmail conectado!\n\n"
        "¿Quieres que analice todos tus emails para encontrar gastos pasados? "
        "Esto puede tardar un momento.\n\n"
        "Responde *sí* para escanear o *no* para empezar solo desde ahora.",
    )


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.agent.agents import chat
    from src.db.storage import get_user_by_telegram_id, upsert_user
    from src.reports.charts import spend_bar_chart, spend_pie_chart

    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    user = get_user_by_telegram_id(chat_id)
    phone = user["phone"] if user else None

    # ── /clear: esperando confirmación ──
    if _onboarding.get(chat_id) == "WAITING_CLEAR_CONFIRM":
        del _onboarding[chat_id]
        if text.lower() == "confirmar":
            from src.db.storage import delete_user
            from src.agent.agents import _history
            if user:
                phone = user["phone"]
                delete_user(phone)
                _history.pop(phone, None)
            await update.message.reply_text(
                "✓ Cuenta eliminada. Todos tus datos han sido borrados.\n"
                "Si quieres volver, escribe /start."
            )
        else:
            await update.message.reply_text("Cancelado. Tu cuenta sigue activa.")
        return

    # ── Post-Gmail: ofrecer escaneo completo ──
    if _onboarding.get(chat_id) == "WAITING_GMAIL_SCAN_CONFIRM":
        del _onboarding[chat_id]
        if user and text.lower() in ("sí", "si", "s", "yes", "dale", "ok"):
            await update.message.reply_text("🔍 Escaneando tu historial de emails, un momento...")
            from src.ingestion.gmail_ingest import ingest_gmail_expenses
            new_ids = ingest_gmail_expenses(user, full_scan=True)
            if new_ids:
                await update.message.reply_text(
                    f"✅ Encontré *{len(new_ids)} gasto(s)* en tu historial.\n"
                    "Escribe *pendientes* para empezar a clasificarlos.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "No encontré emails bancarios en tu historial. "
                    "A partir de ahora detectaré los nuevos automáticamente."
                )
        else:
            await update.message.reply_text(
                "Ok, detectaré tus gastos desde ahora en adelante."
            )
        return

    # ── Onboarding: esperando nombre ──
    if _onboarding.get(chat_id) == "WAITING_NAME":
        full_name, nickname = _extract_name(text)
        phone = f"tg_{chat_id}"
        upsert_user(phone, full_name, telegram_chat_id=chat_id, nickname=nickname)
        _onboarding[chat_id] = "WAITING_ONBOARDING_CHOICE"
        await update.message.reply_text(
            _ONBOARDING_MENU_MSG.format(name=nickname),
            parse_mode="Markdown",
            reply_markup=_ONBOARDING_KEYBOARD,
        )
        return

    # ── Onboarding: eligiendo ruta ──
    if _onboarding.get(chat_id) == "WAITING_ONBOARDING_CHOICE":
        del _onboarding[chat_id]
        if not user:
            await update.message.reply_text("Ocurrió un error. Escribe /start para reintentar.")
            return
        phone = user["phone"]
        if "conectar" in text.lower():
            await update.message.reply_text(
                "Perfecto 📧 Conecta tu Gmail para que pueda detectar tus compras automáticamente.\n\n"
                + _gmail_connect_msg(phone),
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await update.message.reply_text(
                _PLANNING_GUIDE_MSG,
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
        return

    # ── Clasificación guiada: esperando categoría ──
    state = _onboarding.get(chat_id, "")
    if state.startswith("CLASSIFYING_CATEGORY:"):
        tx_id = state.split(":", 1)[1]
        category = _strip_button(text)
        if category not in _CATEGORIES:
            await update.message.reply_text(
                "Selecciona una categoría del teclado 👇",
                reply_markup=_CATEGORY_KEYBOARD,
            )
            return
        _onboarding[chat_id] = f"CLASSIFYING_INTENT:{tx_id}:{category}"
        await update.message.reply_text(
            f"Categoría: {category} ✓\n¿Era un gasto previsto o imprevisto?",
            reply_markup=_INTENT_KEYBOARD,
        )
        return

    # ── Clasificación guiada: esperando intención ──
    if state.startswith("CLASSIFYING_INTENT:"):
        _, tx_id, category = state.split(":", 2)
        intent = _strip_button(text)
        if intent not in _INTENTS:
            await update.message.reply_text(
                "Selecciona una opción 👇",
                reply_markup=_INTENT_KEYBOARD,
            )
            return
        del _onboarding[chat_id]
        from src.agent.tools import run_tool
        from src.agent.agents import _history
        run_tool("classify_transaction", {"tx_id": tx_id, "category": category, "intent": intent}, phone or "")
        _history.pop(phone, None)  # resetear historial — quedó en estado inconsistente
        await update.message.reply_text(f"✅ {category} / {intent}")
        await _show_next_pending(chat_id, phone, update)
        return

    # ── Flujo normal ──
    if not user:
        await update.message.reply_text("No estás registrado. Escribe /start para comenzar.")
        return

    reply = chat(phone, text)

    if reply.startswith("__CHART__:"):
        parts = reply.split(":")
        chart_type = parts[1]
        if chart_type == "monthly":
            from src.reports.charts import spend_monthly_chart
            buf = spend_monthly_chart(phone)
            await send_image(chat_id, buf, caption="Tus gastos por mes")
        elif len(parts) == 4:  # __CHART__:tipo:mes:año
            month, year = int(parts[2]), int(parts[3])
            fn = spend_pie_chart if chart_type == "pie" else spend_bar_chart
            buf = fn(phone, days_back=0, month=month, year=year)
            await send_image(chat_id, buf, caption=f"Tus gastos — {month}/{year}")
        else:  # __CHART__:tipo:dias
            days = int(parts[2])
            fn = spend_pie_chart if chart_type == "pie" else spend_bar_chart
            buf = fn(phone, days_back=days)
            period = "todos" if days == 0 else (f"últimos {days} días" if days != 30 else "último mes")
            await send_image(chat_id, buf, caption=f"Tus gastos — {period}")
    elif _is_classification_prompt(reply):
        tx_id = _extract_pending_tx_id(phone)
        if tx_id:
            _onboarding[chat_id] = f"CLASSIFYING_CATEGORY:{tx_id}"
            await _reply(update, reply, reply_markup=_CATEGORY_KEYBOARD)
        else:
            await _reply(update, reply)
    else:
        await _reply(update, reply)


async def start_bot():
    global _app
    _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _app.add_handler(CommandHandler("start", _handle_start))
    _app.add_handler(CommandHandler("gmail", _handle_gmail_cmd))
    _app.add_handler(CommandHandler("clear", _handle_clear))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot iniciado (polling)")


async def stop_bot():
    if _app:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
    logger.info("Telegram bot detenido")
