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

SYSTEM_PROMPT = """Eres GastAI, un asistente de finanzas personales que opera por WhatsApp.

Ayudas al usuario a:
- Registrar gastos manuales (los que no pasan por tarjeta)
- Clasificar gastos pendientes (llegan automáticamente desde el banco vía email)
- Consultar resúmenes de gasto por categoría

Responde siempre en español, de forma breve y directa. Usa montos en CLP con formato legible (ej: 5.000 CLP).

Cuando el usuario quiera clasificar un gasto:
1. Llama primero a get_pending para obtener el tx_id y los detalles
2. Pregunta por categoría e intención si no están claras en el contexto
3. Llama a classify_transaction con tx_id, category e intent

Si no hay gastos pendientes, díselo y ofrece otras opciones."""

# historial de conversación en memoria por número de teléfono
_history: dict[str, list] = {}
MAX_HISTORY = 20


def chat(phone: str, user_message: str) -> str:
    history = _history.setdefault(phone, [])
    history.append({"role": "user", "content": user_message})

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
            tools=TOOLS,
        )

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
                inputs = json.loads(tc.function.arguments)
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
