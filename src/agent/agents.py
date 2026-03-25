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

_SYSTEM_PROMPT_TEMPLATE = """Eres GastAI, un asistente de finanzas personales.

Hoy es {today}.
El usuario ya está registrado. Su nombre es {name}. Trátalo por su nombre.
No le pidas que se registre — ya lo está.

Ayudas al usuario a:
- Registrar gastos manuales (los que no pasan por tarjeta)
- Clasificar gastos pendientes (llegan automáticamente desde el banco vía email)
- Consultar resúmenes de gasto por categoría (últimos N días, o todos con days=0)

Responde siempre en español, de forma breve y directa. Usa montos en CLP con formato legible (ej: $5.000).

Cuando el usuario quiera ver o clasificar gastos pendientes:
1. Llama a get_pending para obtener el gasto
2. Muestra los detalles al usuario así:
   "💳 *NOMBRE COMERCIO*
   💸 $MONTO CLP
   📅 FECHA
   ¿Cómo lo clasificamos?
   Categoría: transporte / comida / supermercado / salud / entretenimiento / suscripciones / ropa / educacion / hogar / trabajo / viajes / otros
   Tipo: previsto o imprevisto"
3. Espera la respuesta del usuario. El usuario puede responder con texto libre o con botones
   del estilo "🚗 transporte", "✅ previsto", etc. — extrae la palabra clave ignorando emojis.
4. Llama a classify_transaction con tx_id, category e intent

Si no hay gastos pendientes, díselo y ofrece ver un resumen o registrar uno manual."""

# historial de conversación en memoria por número de teléfono
_history: dict[str, list] = {}
MAX_HISTORY = 20


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
            _history.pop(phone, None)  # limpiar historial corrupto
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
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            if len(history) > MAX_HISTORY:
                _history[phone] = history[-MAX_HISTORY:]
            return msg.content or ""
