from datetime import datetime

from src.db.storage import (
    get_pending_transactions,
    get_spend_by_category,
    get_spend_by_payment_type,
    get_transaction,
    insert_transactions,
    set_transaction_category,
    set_transaction_intent,
    insert_income,
    get_income_summary,
    get_total_income,
    get_total_expenses,
    set_budget,
    get_budget_status,
    add_recurring_item,
    get_recurring_items,
    remove_recurring_item,
    update_recurring_item,
    add_pending_charge,
    get_pending_charges,
    mark_charge_paid,
    get_financial_projection,
    add_user_category,
    get_user_categories,
    delete_user_category,
    BASE_CATEGORIES,
)

# Categorías base (usadas en definiciones de tools estáticas)
CATEGORIES = BASE_CATEGORIES
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
                    "amount": {"type": "string", "description": "Monto en CLP (positivo)"},
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
                        "description": "Categoría del gasto. Usa list_categories para ver las disponibles (incluye categorías personalizadas del usuario).",
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
                    "days": {"type": "string", "description": "Días hacia atrás, ej: '7', '30'. Usa 'all' para todos los gastos sin límite."},
                    "month": {"type": "string", "description": "Mes específico (1-12), ej: '2' para febrero."},
                    "year":  {"type": "string", "description": "Año específico, ej: '2026'."},
                },
                "required": [],
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
                    "days": {"type": "string", "description": "Días hacia atrás, ej: '7', '30'. Usa 'all' para todos los gastos sin límite."},
                    "month": {"type": "string", "description": "Mes específico (1-12), ej: '2' para febrero."},
                    "year":  {"type": "string", "description": "Año específico, ej: '2026'."},
                    "chart_type": {
                        "type": "string",
                        "enum": ["pie", "bar"],
                        "description": "Tipo de gráfico: torta (pie) o barras (bar)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_payment_type_summary",
            "description": "Desglose de gastos por tipo de pago: crédito, débito o transferencia. Úsalo cuando el usuario pregunte qué gastó con tarjeta de crédito vs débito.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "string", "description": "Días hacia atrás. Usa 'all' para todos."},
                    "month": {"type": "string", "description": "Mes específico (1-12)."},
                    "year":  {"type": "string", "description": "Año específico, ej: '2026'."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_chart",
            "description": "Genera un gráfico de barras con el gasto total por mes. Úsalo cuando el usuario pida ver evolución mensual, comparar meses, o 'analizar por mes'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "register_income",
            "description": "Registra un ingreso del usuario: sueldo, pago freelance, transferencia recibida, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "description": "Monto en CLP (positivo)"},
                    "description": {"type": "string", "description": "Descripción, ej: 'Sueldo marzo', 'Pago proyecto X'"},
                    "income_type": {
                        "type": "string",
                        "enum": ["sueldo", "freelance", "transferencia", "arriendo", "bono", "otro"],
                        "description": "Tipo de ingreso",
                    },
                },
                "required": ["amount", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_net_balance",
            "description": "Calcula el balance neto: ingresos menos gastos del mes. Útil para saber cuánto ahorraste. Úsalo cuando pregunten por ahorros, balance, o 'cuánto me queda'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Mes (1-12). Si no se especifica, usa el mes actual."},
                    "year":  {"type": "string", "description": "Año, ej: '2026'. Si no se especifica, usa el año actual."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_budget",
            "description": "Define o actualiza el presupuesto mensual de una categoría. Úsalo cuando el usuario quiera establecer un límite de gasto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Categoría del presupuesto. Puede ser una categoría base o personalizada.",
                    },
                    "monthly_limit": {"type": "string", "description": "Límite mensual en CLP"},
                },
                "required": ["category", "monthly_limit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budget_status",
            "description": "Muestra el estado del presupuesto mensual: cuánto se ha gastado vs el límite definido por categoría. Úsalo cuando el usuario pregunte por su presupuesto, cuánto le queda, o si está dentro del presupuesto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Mes (1-12). Si no se especifica, usa el mes actual."},
                    "year":  {"type": "string", "description": "Año, ej: '2026'. Si no se especifica, usa el año actual."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "Lista todas las categorías disponibles para este usuario: las base más las personalizadas que haya creado.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_category",
            "description": "Crea una categoría personalizada para el usuario. Úsala cuando el usuario quiera una categoría que no existe, como 'mascota', 'deporte', 'bebé', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Nombre de la nueva categoría (en minúsculas, sin espacios ni caracteres especiales)"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_category",
            "description": "Elimina una categoría personalizada del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Nombre de la categoría a eliminar"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_recurring_item",
            "description": "Agrega un ingreso o gasto recurrente mensual (sueldo, arriendo, Netflix, gym, etc.). Úsalo cuando el usuario mencione pagos o ingresos que se repiten cada mes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string", "description": "Nombre descriptivo, ej: 'Sueldo', 'Arriendo', 'Netflix'"},
                    "amount":      {"type": "string", "description": "Monto en CLP"},
                    "item_type":   {"type": "string", "enum": ["income", "expense"], "description": "'income' si es ingreso, 'expense' si es gasto"},
                    "category":    {"type": "string", "description": "Categoría del gasto (solo para item_type=expense). Puede ser base o personalizada."},
                    "income_type": {"type": "string", "enum": ["sueldo", "freelance", "arriendo", "bono", "otro"], "description": "Tipo de ingreso (solo para item_type=income)"},
                    "due_day":     {"type": "string", "description": "Día del mes en que se cobra/recibe (1-31)"},
                    "frequency":   {"type": "string", "enum": ["monthly", "annual"], "description": "Frecuencia. Por defecto mensual."},
                },
                "required": ["name", "amount", "item_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recurring_items",
            "description": "Lista todos los ingresos y gastos recurrentes configurados por el usuario.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_recurring_item",
            "description": "Elimina un ítem recurrente por su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "ID del ítem recurrente a eliminar"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_recurring_item",
            "description": "Modifica un ítem recurrente existente (monto, nombre, categoría, día de cobro). Úsalo cuando el usuario diga 'cambia', 'actualiza', 'modifica' un ingreso o gasto recurrente. Primero llama list_recurring_items para obtener el item_id si no lo tienes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id":    {"type": "string", "description": "ID del ítem a modificar"},
                    "name":       {"type": "string", "description": "Nuevo nombre (opcional)"},
                    "amount":     {"type": "string", "description": "Nuevo monto en CLP (opcional)"},
                    "category":   {"type": "string", "description": "Nueva categoría (opcional)"},
                    "due_day":    {"type": "string", "description": "Nuevo día de cobro 1-31 (opcional)"},
                    "income_type":{"type": "string", "enum": ["sueldo", "freelance", "arriendo", "bono", "otro"], "description": "Nuevo tipo de ingreso (opcional)"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_pending_charge",
            "description": "Registra un cargo futuro: deuda de tarjeta de crédito, cuota, factura pendiente de pago. Úsalo cuando el usuario mencione que le van a cobrar algo próximamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Descripción del cargo, ej: 'Facturado tarjeta crédito marzo', 'Cuota auto'"},
                    "amount":      {"type": "string", "description": "Monto en CLP"},
                    "due_date":    {"type": "string", "description": "Fecha de vencimiento en formato YYYY-MM-DD"},
                    "charge_type": {"type": "string", "enum": ["deuda_tarjeta", "cuota", "factura", "otro"], "description": "Tipo de cargo"},
                },
                "required": ["description", "amount", "due_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_charges",
            "description": "Lista los cargos pendientes de pago: deudas de tarjeta, cuotas, facturas.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_charge_paid",
            "description": "Marca un cargo pendiente como pagado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "charge_id": {"type": "string", "description": "ID del cargo a marcar como pagado"},
                },
                "required": ["charge_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_projection",
            "description": "Proyección financiera del mes: ingresos esperados menos gastos recurrentes y cargos pendientes. Muestra cuánto queda disponible. Úsalo cuando el usuario pregunte cuánto le queda este mes, quiera planificar, o pregunte por su situación financiera futura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Mes (1-12). Por defecto mes actual."},
                    "year":  {"type": "string", "description": "Año, ej: '2026'. Por defecto año actual."},
                },
                "required": [],
            },
        },
    },
]


def _to_float(val) -> float:
    """Coerciona string o número a float, tolerando puntos de miles y comas decimales."""
    if val is None:
        return 0.0
    s = str(val).strip().replace("$", "").replace(" ", "")
    # "1.200.000" → "1200000" | "1,200,000" → "1200000"
    if s.count(".") > 1:
        s = s.replace(".", "")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif "." in s and "," in s:
        s = s.replace(",", "")  # "1,200.00" → "1200.00"
    else:
        s = s.replace(",", ".")  # "1200,50" → "1200.50"
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_days(inputs: dict) -> int:
    """Parsea el parámetro days tolerando strings, 'all', valores falsy, etc."""
    raw = inputs.get("days", "7")
    if not raw or str(raw).lower() in ("all", "todo", "todos", "0", "none", ""):
        return 0  # 0 = sin límite
    try:
        return int(str(raw))
    except ValueError:
        return 7


def run_tool(name: str, inputs: dict, phone: str) -> str:
    if name == "register_expense":
        amount = abs(_to_float(inputs["amount"])) * -1
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
        category = inputs["category"].lower().strip()
        valid_cats = get_user_categories(phone)
        if category not in valid_cats:
            return f"Categoría '{category}' no existe. Categorías disponibles: {', '.join(valid_cats)}. Puedes crear una nueva con create_category."
        set_transaction_category(inputs["tx_id"], category)
        set_transaction_intent(inputs["tx_id"], inputs["intent"])
        tx = get_transaction(inputs["tx_id"])
        return f"Clasificado: '{tx['description']}' → {tx['category']} / {tx['intent']}"

    if name == "get_spend_summary":
        month = int(inputs["month"]) if inputs.get("month") else None
        year  = int(inputs["year"])  if inputs.get("year")  else None
        days  = _parse_days(inputs) if not (month and year) else 0
        df = get_spend_by_category(user_phone=phone, days_back=days, month=month, year=year)
        if df.empty:
            return f"Sin gastos registrados en los últimos {days} días."
        lines = [f"- {row.category}: {row.spent_clp:,.0f} CLP" for _, row in df.iterrows()]
        return f"Gastos últimos {days} días:\n" + "\n".join(lines)

    if name == "get_spend_chart":
        month = int(inputs["month"]) if inputs.get("month") else None
        year  = int(inputs["year"])  if inputs.get("year")  else None
        days  = _parse_days(inputs) if not (month and year) else 0
        chart_type = inputs.get("chart_type", "bar")
        suffix = f"{month}:{year}" if (month and year) else str(days)
        return f"__CHART__:{chart_type}:{suffix}"

    if name == "get_payment_type_summary":
        month = int(inputs["month"]) if inputs.get("month") else None
        year  = int(inputs["year"])  if inputs.get("year")  else None
        days  = _parse_days(inputs) if not (month and year) else 0
        df = get_spend_by_payment_type(user_phone=phone, days_back=days, month=month, year=year)
        if df.empty:
            return "Sin gastos registrados."
        labels = {"credito": "Tarjeta de crédito", "debito": "Tarjeta de débito",
                  "transferencia": "Transferencia", "desconocido": "Sin clasificar"}
        lines = [f"- {labels.get(row.payment_type, row.payment_type)}: {row.spent_clp:,.0f} CLP"
                 for _, row in df.iterrows()]
        return "Gastos por tipo de pago:\n" + "\n".join(lines)

    if name == "get_monthly_chart":
        return "__CHART__:monthly:0"

    if name == "register_income":
        amount = abs(_to_float(inputs["amount"]))
        description = inputs["description"]
        income_type = inputs.get("income_type", "otro")
        income_id = insert_income(phone, amount, description, income_type)
        return f"Ingreso registrado: {amount:,.0f} CLP — '{description}' ({income_type}). id={income_id}"

    if name == "get_net_balance":
        from datetime import datetime as dt
        month = int(inputs["month"]) if inputs.get("month") else dt.now().month
        year  = int(inputs["year"])  if inputs.get("year")  else dt.now().year
        ingresos = get_total_income(phone, month=month, year=year)
        gastos   = get_total_expenses(phone, month=month, year=year)
        balance  = ingresos - gastos
        ingreso_df = get_income_summary(phone, month=month, year=year)
        detalle = ""
        if not ingreso_df.empty:
            detalle = " | ".join(f"{r.income_type}: {r.total_clp:,.0f}" for _, r in ingreso_df.iterrows())
        return (
            f"Balance {month}/{year}:\n"
            f"- Ingresos: {ingresos:,.0f} CLP ({detalle or 'sin registros'})\n"
            f"- Gastos:   {gastos:,.0f} CLP\n"
            f"- Balance:  {balance:,.0f} CLP ({'ahorro' if balance >= 0 else 'déficit'})"
        )

    if name == "set_budget":
        category = inputs["category"]
        monthly_limit = abs(_to_float(inputs["monthly_limit"]))
        set_budget(phone, category, monthly_limit)
        return f"Presupuesto para '{category}' definido en {monthly_limit:,.0f} CLP/mes."

    if name == "get_budget_status":
        from datetime import datetime as dt
        month = int(inputs["month"]) if inputs.get("month") else dt.now().month
        year  = int(inputs["year"])  if inputs.get("year")  else dt.now().year
        df = get_budget_status(phone, month=month, year=year)
        if df.empty:
            return "No tienes presupuestos definidos. Usa set_budget para configurarlos."
        lines = []
        for _, row in df.iterrows():
            icon = "🔴" if row.pct_used >= 100 else "🟡" if row.pct_used >= 80 else "🟢"
            lines.append(
                f"{icon} {row.category}: {row.spent_clp:,.0f} / {row.monthly_limit:,.0f} CLP ({row.pct_used}%)"
            )
        return f"Presupuesto {month}/{year}:\n" + "\n".join(lines)

    if name == "clear_incomes":
        from src.db.storage import con
        month = int(inputs["month"]) if inputs.get("month") else __import__("datetime").datetime.now().month
        year  = int(inputs["year"])  if inputs.get("year")  else __import__("datetime").datetime.now().year
        con.execute(
            "DELETE FROM incomes WHERE user_phone = ? "
            "AND EXTRACT(month FROM ts) = ? AND EXTRACT(year FROM ts) = ?",
            [phone, month, year]
        )
        return f"Ingresos de {month}/{year} eliminados. Puedes volver a registrarlos."

    if name == "list_categories":
        cats = get_user_categories(phone)
        base = [c for c in cats if c in BASE_CATEGORIES]
        custom = [c for c in cats if c not in BASE_CATEGORIES]
        lines = ["*Categorías disponibles:*", f"Base: {', '.join(base)}"]
        if custom:
            lines.append(f"Personalizadas: {', '.join(custom)}")
        else:
            lines.append("(sin categorías personalizadas aún)")
        return "\n".join(lines)

    if name == "create_category":
        cat = inputs["category"].lower().strip().replace(" ", "_")
        if cat in BASE_CATEGORIES:
            return f"'{cat}' ya existe como categoría base."
        created = add_user_category(phone, cat)
        if not created:
            return f"La categoría '{cat}' ya existe."
        return f"Categoría '{cat}' creada. Ya puedes usarla para clasificar gastos y definir presupuestos."

    if name == "delete_category":
        cat = inputs["category"].lower().strip()
        if cat in BASE_CATEGORIES:
            return f"No puedes eliminar categorías base ('{cat}'). Solo puedes eliminar las personalizadas."
        delete_user_category(phone, cat)
        return f"Categoría '{cat}' eliminada."

    if name == "add_recurring_item":
        item_id = add_recurring_item(
            user_phone=phone,
            name=inputs["name"],
            amount_clp=_to_float(inputs["amount"]),
            item_type=inputs["item_type"],
            category=inputs.get("category"),
            income_type=inputs.get("income_type"),
            due_day=int(inputs.get("due_day") or 1),
            frequency=inputs.get("frequency", "monthly"),
        )
        tipo = "Ingreso" if inputs["item_type"] == "income" else "Gasto"
        return f"{tipo} recurrente '{inputs['name']}' registrado: {float(inputs['amount']):,.0f} CLP/mes el día {inputs.get('due_day', 1)}. id={item_id}"

    if name == "list_recurring_items":
        df = get_recurring_items(phone)
        if df.empty:
            return "No tienes ítems recurrentes configurados."
        incomes = df[df.item_type == "income"]
        expenses = df[df.item_type == "expense"]
        lines = []
        if not incomes.empty:
            lines.append("*Ingresos recurrentes:*")
            for _, r in incomes.iterrows():
                lines.append(f"- {r['name']}: +{r.amount_clp:,.0f} CLP (día {r.due_day}) [id: {r.item_id}]")
        if not expenses.empty:
            lines.append("*Gastos recurrentes:*")
            for _, r in expenses.iterrows():
                cat = f" ({r.category})" if r.category else ""
                lines.append(f"- {r['name']}: -{r.amount_clp:,.0f} CLP (día {r.due_day}){cat} [id: {r.item_id}]")
        total_in = incomes["amount_clp"].sum() if not incomes.empty else 0
        total_out = expenses["amount_clp"].sum() if not expenses.empty else 0
        lines.append(f"\nTotal ingresos fijos: {total_in:,.0f} CLP | Total gastos fijos: {total_out:,.0f} CLP")
        return "\n".join(lines)

    if name == "remove_recurring_item":
        remove_recurring_item(inputs["item_id"])
        return f"Ítem {inputs['item_id']} eliminado."

    if name == "update_recurring_item":
        kwargs = {}
        if "name" in inputs:
            kwargs["name"] = inputs["name"]
        if "amount" in inputs:
            kwargs["amount_clp"] = _to_float(inputs["amount"])
        if "category" in inputs:
            kwargs["category"] = inputs["category"]
        if "due_day" in inputs:
            kwargs["due_day"] = int(inputs["due_day"])
        if "income_type" in inputs:
            kwargs["income_type"] = inputs["income_type"]
        ok = update_recurring_item(inputs["item_id"], **kwargs)
        if not ok:
            return f"No se encontró el ítem {inputs['item_id']} o no hay cambios que aplicar."
        changes = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        return f"Ítem {inputs['item_id']} actualizado: {changes}."

    if name == "add_pending_charge":
        charge_id = add_pending_charge(
            user_phone=phone,
            description=inputs["description"],
            amount_clp=_to_float(inputs["amount"]),
            due_date=inputs["due_date"],
            charge_type=inputs.get("charge_type", "otro"),
        )
        return f"Cargo pendiente '{inputs['description']}' registrado: {float(inputs['amount']):,.0f} CLP vence {inputs['due_date']}. id={charge_id}"

    if name == "list_pending_charges":
        df = get_pending_charges(phone)
        if df.empty:
            return "No tienes cargos pendientes registrados."
        lines = ["*Cargos pendientes:*"]
        for _, r in df.iterrows():
            lines.append(f"- {r.description}: {r.amount_clp:,.0f} CLP — vence {r.due_date} ({r.charge_type}) [id: {r.charge_id}]")
        total = df["amount_clp"].sum()
        lines.append(f"\nTotal por pagar: {total:,.0f} CLP")
        return "\n".join(lines)

    if name == "mark_charge_paid":
        mark_charge_paid(inputs["charge_id"])
        return f"Cargo {inputs['charge_id']} marcado como pagado."

    if name == "get_financial_projection":
        from datetime import datetime as dt
        month = int(inputs["month"]) if inputs.get("month") else dt.now().month
        year  = int(inputs["year"])  if inputs.get("year")  else dt.now().year
        p = get_financial_projection(phone, month=month, year=year)

        lines = [f"*Proyección {month}/{year}*\n"]

        # Ingresos recurrentes
        lines.append(f"*Ingresos: +{p['rec_income_total']:,.0f} CLP*")
        for item in p["rec_income_items"]:
            lines.append(f"  · {item['name']}: +{item['amount']:,.0f} (día {item['due_day']})")
        if not p["rec_income_items"]:
            lines.append("  _(sin ingresos recurrentes configurados)_")

        # Gastos recurrentes
        lines.append(f"\n*Gastos fijos: -{p['rec_expense_total']:,.0f} CLP*")
        for item in p["rec_expense_items"]:
            cat = f" ({item['category']})" if item.get("category") else ""
            lines.append(f"  · {item['name']}: -{item['amount']:,.0f}{cat}")
        if not p["rec_expense_items"]:
            lines.append("  _(ninguno configurado)_")

        # Cargos puntuales del mes
        if p["pending_items"]:
            lines.append(f"\n*Cargos puntuales este mes: -{p['pending_total']:,.0f} CLP*")
            for ch in p["pending_items"]:
                lines.append(f"  · {ch['description']}: -{ch['amount_clp']:,.0f}")

        # Fórmula clara
        lines.append(
            f"\n{p['rec_income_total']:,.0f} − {p['rec_expense_total']:,.0f} − {p['pending_total']:,.0f} ="
        )
        icon = "✅" if p["projected_balance"] >= 0 else "⚠️"
        lines.append(f"{icon} *Disponible: {p['projected_balance']:,.0f} CLP*")
        if p["projected_balance"] < 0:
            lines.append("_Tus gastos superan tus ingresos este mes._")

        return "\n".join(lines)

    return f"Tool desconocida: {name}"
