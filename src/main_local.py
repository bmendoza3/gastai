from datetime import datetime
from db.storage import (
    insert_transactions,
    get_pending_transactions,
    set_transaction_category,
    set_transaction_intent,
    get_transaction
)

# --- Categorías e intenciones disponibles ---
CATEGORIES = ["Supermercado", "Farmacia", "Delivery", "Transporte", "Restaurantes", "Servicios", "Otros"]
INTENTS = ["Planeado", "Imprevisto", "Antojo"]

# --- Paso 1: insertar gasto nuevo (simulando correo o input automático) ---
tx = {
    "tx_id": "tarjeta123-2025-10-24T13:02-5000-cruzverde",
    "timestamp": datetime.now().isoformat(),
    "description": "CRUZ VERDE",
    "amount_clp": -5000.0,
    "account_id": "tarjeta ****1234",
    "category": None,
    "intent": None,
    "needs_review": True
}
insert_transactions([tx])
print("✅ Nuevo gasto registrado.\n")

# --- Paso 2: revisar pendientes (como haría el bot de WhatsApp) ---
pendientes = get_pending_transactions()
if pendientes.empty:
    print("No hay gastos pendientes de revisión.")
else:
    row = pendientes.iloc[0]
    print(f"💬 Tienes un gasto pendiente:\n"
          f"  • {abs(row.amount_clp):,.0f} CLP en {row.description}\n"
          f"  • Fecha: {row.ts}\n")

    # Pregunta simulada
    print("¿En qué categoría quieres clasificarlo?")
    for i, cat in enumerate(CATEGORIES, start=1):
        print(f"  {i}. {cat}")

    idx = int(input("👉 Elige número de categoría: "))
    chosen_cat = CATEGORIES[idx - 1]
    set_transaction_category(row.tx_id, chosen_cat)
    print(f"✔ Categoría asignada: {chosen_cat}\n")

    print("¿Fue Planeado, Imprevisto o Antojo?")
    for i, intent in enumerate(INTENTS, start=1):
        print(f"  {i}. {intent}")

    idx2 = int(input("👉 Elige número de intención: "))
    chosen_intent = INTENTS[idx2 - 1]
    set_transaction_intent(row.tx_id, chosen_intent)
    print(f"✔ Intención asignada: {chosen_intent}\n")

    # Mostrar resultado final
    tx_final = get_transaction(row.tx_id)
    print("🧾 Registro final guardado:")
    for k, v in tx_final.items():
        print(f"  {k}: {v}")