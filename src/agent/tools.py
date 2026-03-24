from datetime import datetime

from src.db.storage import (
    get_pending_transactions,
    get_spend_by_category,
    get_transaction,
    insert_transactions,
    set_transaction_category,
    set_transaction_intent,
)

CATEGORIES = [
    "transporte", "comida", "supermercado", "salud", "entretenimiento",
    "suscripciones", "ropa", "educacion", "hogar", "trabajo", "viajes", "otros",
]
INTENTS = ["previsto", "imprevisto"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "register_expense",
            "description": "Registra un gasto nuevo ingresado manualmente por el usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Monto en CLP (positivo)"},
                    "description": {"type": "string", "description": "Descripción del comercio o gasto, ej: 'Cruz Verde', 'Uber Eats'"},
                },
                "required": ["amount", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending",
            "description": "Obtiene el próximo gasto pendiente de clasificar para este usuario.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_transaction",
            "description": "Clasifica una transacción pendiente con categoría e intención de compra.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tx_id": {"type": "string", "description": "ID de la transacción"},
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": "Categoría del gasto",
                    },
                    "intent": {
                        "type": "string",
                        "enum": INTENTS,
                        "description": "Si el gasto era previsto o imprevisto",
                    },
                },
                "required": ["tx_id", "category", "intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spend_summary",
            "description": "Resumen de gastos agrupados por categoría en los últimos N días.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Días hacia atrás (default 7)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spend_chart",
            "description": "Genera y envía un gráfico visual de gastos por categoría. Úsalo cuando el usuario pida ver un gráfico, reporte visual o resumen visual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Días hacia atrás (default 7)"},
                    "chart_type": {
                        "type": "string",
                        "enum": ["pie", "bar"],
                        "description": "Tipo de gráfico: torta (pie) o barras (bar)",
                    },
                },
            },
        },
    },
]


def run_tool(name: str, inputs: dict, phone: str) -> str:
    if name == "register_expense":
        amount = abs(float(inputs["amount"])) * -1
        description = inputs["description"]
        tx_id = f"wa-{int(datetime.now().timestamp())}"
        insert_transactions([{
            "tx_id": tx_id,
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "amount_clp": amount,
            "user_phone": phone,
            "category": None,
            "intent": None,
            "needs_review": True,
            "source": "manual",
        }])
        return f"Gasto registrado: {abs(amount):,.0f} CLP en '{description}'. tx_id={tx_id}"

    if name == "get_pending":
        df = get_pending_transactions(user_phone=phone, limit=1)
        if df.empty:
            return "No hay gastos pendientes de clasificar."
        row = df.iloc[0]
        return (
            f"tx_id={row.tx_id} | "
            f"{abs(row.amount_clp):,.0f} CLP | "
            f"{row.description} | "
            f"Fecha: {row.ts}"
        )

    if name == "classify_transaction":
        set_transaction_category(inputs["tx_id"], inputs["category"])
        set_transaction_intent(inputs["tx_id"], inputs["intent"])
        tx = get_transaction(inputs["tx_id"])
        return f"Clasificado: '{tx['description']}' → {tx['category']} / {tx['intent']}"

    if name == "get_spend_summary":
        days = int(inputs.get("days", 7))
        df = get_spend_by_category(user_phone=phone, days_back=days)
        if df.empty:
            return f"Sin gastos registrados en los últimos {days} días."
        lines = [f"- {row.category}: {row.spent_clp:,.0f} CLP" for _, row in df.iterrows()]
        return f"Gastos últimos {days} días:\n" + "\n".join(lines)

    if name == "get_spend_chart":
        # Retorna señal especial para que el webhook envíe la imagen
        days = int(inputs.get("days", 7))
        chart_type = inputs.get("chart_type", "bar")
        return f"__CHART__:{chart_type}:{days}"

    return f"Tool desconocida: {name}"
