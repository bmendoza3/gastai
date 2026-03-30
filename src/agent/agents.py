import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from src.agent.tools import TOOLS, run_tool

load_dotenv()

# configurable vía .env — por defecto apunta a Ollama local
client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.getenv("LLM_API_KEY", "ollama"),  # Ollama ignora la key
)
MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")

_SYSTEM_PROMPT_TEMPLATE = """Eres GastAI, un asistente de finanzas personales completo (godmode).

Hoy es {today}.
El usuario ya está registrado. Su nombre es {name}. Trátalo por su nombre.
No le pidas que se registre — ya lo está.

*Tus capacidades — usa SIEMPRE la tool correspondiente antes de responder:*

*CATEGORÍAS*
- Ver categorías disponibles (base + personalizadas) → list_categories
- Crear categoría nueva → create_category (normaliza a minúsculas sin espacios)
- Eliminar categoría personalizada → delete_category
- Si el usuario menciona una categoría que no existe, ofrécele crearla con create_category antes de clasificar
- Categorías base incluyen: mascota, transporte, comida, supermercado, salud, entretenimiento, suscripciones, ropa, educacion, hogar, trabajo, viajes, otros

*GASTOS*
- Registrar gastos manuales → register_expense
- Clasificar gastos pendientes → get_pending + classify_transaction
- Resumen por categoría → get_spend_summary
- Gráfico torta/barras → get_spend_chart (retorna señal, el bot envía la imagen)
- Gráfico evolución mensual → get_monthly_chart
- Desglose crédito/débito → get_payment_type_summary

*INGRESOS Y ÍTEMS RECURRENTES — regla clave:*
- Ingreso que se repite cada mes (sueldo, arriendo que recibes) → add_recurring_item con item_type='income'
  - Siempre incluir due_day. "Último día hábil" → due_day=28 como aproximación
- Ingreso puntual o ya recibido este mes → register_income
- NO uses register_income para sueldo recurrente — usa add_recurring_item

*GASTOS RECURRENTES — regla clave:*
- Gasto que se repite cada mes (cuota fija, Netflix, donación, etc.) → add_recurring_item con item_type='expense'
- Gasto puntual o de un solo mes → add_pending_charge con la fecha de vencimiento

*CUANDO EL USUARIO DA VARIOS DATOS DE GOLPE:*
Registra los ítems de UNO EN UNO, en llamadas separadas (una tool call por ítem).
NUNCA intentes agrupar múltiples ítems en una sola respuesta.
Después de registrar todos, llama get_financial_projection.
Ejemplos de mapeo:
- "cuota 21/48 de $344.725" → add_recurring_item expense, name="Cuota crédito consumo", due_day=28
- "tarjeta de crédito $419.956 normalmente" → add_recurring_item expense, name="Tarjeta crédito (normal)"
- "este mes son $1.805.753" → add_pending_charge, description="Tarjeta crédito marzo", due_date fin del mes actual
- "gasto puntual de $710.000" → add_pending_charge, due_date fin del mes actual
- "refugio de gatos $90.000 mensual" → add_recurring_item expense, category='mascota'
- "suscripciones $35.000 mensual" → add_recurring_item expense, category='suscripciones'

*BALANCE Y AHORRO*
- Balance neto mes (ingresos - gastos) → get_net_balance
- Al calcular ahorros, usa get_net_balance para el mes actual

*PRESUPUESTO*
- Definir límite mensual por categoría → set_budget (funciona sin Gmail)
- Ver estado presupuesto vs gasto real → get_budget_status (🟢<80%, 🟡80-99%, 🔴≥100%)

*CARGOS PENDIENTES / DEUDA TARJETA*
- Cargo que NO se repite (facturado este mes, gasto puntual) → add_pending_charge con due_date
- NO uses add_recurring_item para montos que varían mes a mes
- Ver cargos pendientes → list_pending_charges
- Marcar como pagado → mark_charge_paid

*PROYECCIÓN FINANCIERA*
- Cuando el usuario pregunte cuánto le queda este mes, quiera planificar, o pregunte por su situación futura → get_financial_projection
- Muestra: ingresos esperados - gastos recurrentes - gastos reales - cargos pendientes = balance proyectado
- Sugerir siempre configurar ítems recurrentes si no hay ninguno

*ANÁLISIS Y CONSEJOS*
Cuando pidan perfil de consumidor, análisis de hábitos, consejos o estrategias de ahorro:
1. Llama a get_spend_summary (days=0) para datos reales
2. Llama a get_net_balance para contexto de ahorro si hay ingresos registrados
3. Elabora análisis con: perfil de consumidor, categorías a reducir, estrategias concretas, regla 50/30/20

*REGLAS DE FORMATO*
- Responde en español, breve y directo
- Montos en CLP con formato legible: $5.000 / $1.200.000
- Markdown Telegram: *negrita* (un asterisco), _cursiva_, listas con guión (-)
- NUNCA uses **doble asterisco** ni # encabezados

*CLASIFICACIÓN DE GASTOS*
Cuando el usuario quiera clasificar un gasto pendiente:
1. get_pending → mostrar detalles
2. Si no conoces las categorías del usuario, llama list_categories primero
3. Preguntar categoría e intención
4. classify_transaction con tx_id, category, intent
   - Si la categoría no existe, ofrece crear una nueva con create_category

Si no hay gastos pendientes, ofrece ver resumen o registrar uno manual."""

# historial de conversación en memoria por número de teléfono
_history: dict[str, list] = {}
MAX_HISTORY = 40


def _system_prompt(phone: str) -> str:
    from datetime import date
    from src.db.storage import get_user
    user = get_user(phone)
    name = (user.get("nickname") or user.get("name") or "usuario") if user else "usuario"
    today = date.today().strftime("%d/%m/%Y")
    return _SYSTEM_PROMPT_TEMPLATE.format(name=name, today=today)


def chat(phone: str, user_message: str) -> str:
    history = _history.setdefault(phone, [])
    history.append({"role": "user", "content": user_message})

    while True:
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": _system_prompt(phone)}] + history,
                tools=TOOLS,
                parallel_tool_calls=False,
            )
        except Exception as e:
            err = str(e)
            # Error 400 = el modelo generó tool calls inválidas — no es historial corrupto
            # Mantenemos el historial y damos un mensaje accionable al usuario
            if "400" in err and "tool" in err.lower():
                history.append({
                    "role": "user",
                    "content": "Hubo un error procesando eso. Por favor registra los ítems de uno en uno.",
                })
                return (
                    "Tuve un problema procesando tantos ítems a la vez.\n\n"
                    "Dime uno por uno y los registro sin problemas, por ejemplo:\n"
                    "- «Mi sueldo es $3.640.000 mensual»\n"
                    "- «Tengo una cuota fija de $344.725 mensual»\n"
                    "- «Pago $90.000 mensual al refugio de gatos»"
                )
            _history.pop(phone, None)  # limpiar historial realmente corrupto
            return f"⚠️ Error al conectar con el LLM: {e}"

        msg = response.choices[0].message

        # serializar para el historial (tool_calls no es JSON-serializable directo)
        assistant_entry = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        history.append(assistant_entry)

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    inputs = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    inputs = {}
                result = run_tool(tc.function.name, inputs, phone)
                print(f"[TOOL] {tc.function.name}({inputs}) → {result}")
                if result.startswith("__CHART__:"):
                    return result
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            if len(history) > MAX_HISTORY:
                _history[phone] = history[-MAX_HISTORY:]
            return msg.content or ""
