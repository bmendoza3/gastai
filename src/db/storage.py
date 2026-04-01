import logging
import duckdb
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional

from src.db.crypto import decrypt, decrypt_amount, encrypt, encrypt_amount

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "finanzas.duckdb"
con = duckdb.connect(str(DB_PATH))


def init_db():
    con.execute("""
    CREATE TABLE IF NOT EXISTS users (
        phone              TEXT PRIMARY KEY,
        name               TEXT,
        nickname           TEXT,
        gmail_query        TEXT,
        bank               TEXT,
        telegram_chat_id   TEXT,
        created_at         TIMESTAMP DEFAULT NOW()
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS user_banks (
        user_phone  TEXT,
        bank        TEXT,
        gmail_query TEXT,
        PRIMARY KEY (user_phone, bank)
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        tx_id            TEXT PRIMARY KEY,
        user_phone       TEXT,
        ts               TIMESTAMP,
        description      TEXT,
        amount_clp       DOUBLE,
        description_enc  TEXT,
        amount_enc       TEXT,
        category         TEXT,
        intent           TEXT,
        needs_review     BOOLEAN,
        source           TEXT DEFAULT 'manual',
        payment_type     TEXT
    );
    """)

    # Migración: account_id → user_phone
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='transactions'"
    ).fetchall()]
    if "account_id" in cols and "user_phone" not in cols:
        logger.info("Migrando schema: account_id → user_phone")
        con.execute("ALTER TABLE transactions RENAME COLUMN account_id TO user_phone")
    if "source" not in cols:
        con.execute("ALTER TABLE transactions ADD COLUMN source TEXT DEFAULT 'manual'")
    if "description_enc" not in cols:
        con.execute("ALTER TABLE transactions ADD COLUMN description_enc TEXT")
    if "amount_enc" not in cols:
        con.execute("ALTER TABLE transactions ADD COLUMN amount_enc TEXT")
    if "payment_type" not in cols:
        con.execute("ALTER TABLE transactions ADD COLUMN payment_type TEXT")

    # Migración: agregar telegram_chat_id si no existe
    user_cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
    ).fetchall()]
    if "telegram_chat_id" not in user_cols:
        logger.info("Migrando schema: agregando telegram_chat_id a users")
        con.execute("ALTER TABLE users ADD COLUMN telegram_chat_id TEXT")
    if "nickname" not in user_cols:
        con.execute("ALTER TABLE users ADD COLUMN nickname TEXT")

    con.execute("""
    CREATE TABLE IF NOT EXISTS incomes (
        income_id    TEXT PRIMARY KEY,
        user_phone   TEXT,
        ts           TIMESTAMP,
        amount_clp   DOUBLE,
        description  TEXT,
        income_type  TEXT DEFAULT 'otro'
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS budgets (
        user_phone      TEXT,
        category        TEXT,
        monthly_limit   DOUBLE,
        PRIMARY KEY (user_phone, category)
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS user_categories (
        user_phone  TEXT,
        category    TEXT,
        PRIMARY KEY (user_phone, category)
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS recurring_items (
        item_id      TEXT PRIMARY KEY,
        user_phone   TEXT,
        name         TEXT,
        amount_clp   DOUBLE,
        item_type    TEXT,        -- 'expense' | 'income'
        category     TEXT,        -- para expenses
        income_type  TEXT,        -- para income
        frequency    TEXT DEFAULT 'monthly',  -- 'monthly' | 'annual'
        due_day      INTEGER,     -- día del mes (1-31)
        is_active    BOOLEAN DEFAULT TRUE,
        created_at   TIMESTAMP DEFAULT NOW()
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS pending_charges (
        charge_id    TEXT PRIMARY KEY,
        user_phone   TEXT,
        description  TEXT,
        amount_clp   DOUBLE,
        due_date     DATE,
        charge_type  TEXT DEFAULT 'otro',  -- 'deuda_tarjeta' | 'cuota' | 'factura' | 'otro'
        is_paid      BOOLEAN DEFAULT FALSE,
        created_at   TIMESTAMP DEFAULT NOW()
    );
    """)

    # Migración: mover bank/gmail_query de users → user_banks
    user_cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
    ).fetchall()]
    if "bank" in user_cols and "gmail_query" in user_cols:
        con.execute("""
            INSERT OR IGNORE INTO user_banks (user_phone, bank, gmail_query)
            SELECT phone, bank, gmail_query FROM users
            WHERE bank IS NOT NULL AND gmail_query IS NOT NULL
        """)


init_db()


# ----------------- Usuarios -----------------

def upsert_user(phone: str, name: str, telegram_chat_id: Optional[str] = None, nickname: Optional[str] = None):
    con.execute("""
        INSERT INTO users (phone, name, nickname, telegram_chat_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (phone) DO UPDATE SET
            name = excluded.name,
            nickname = COALESCE(excluded.nickname, users.nickname),
            telegram_chat_id = COALESCE(excluded.telegram_chat_id, users.telegram_chat_id)
    """, [phone, name, nickname, telegram_chat_id])


def get_user(phone: str) -> Optional[Dict]:
    df = con.execute("SELECT * FROM users WHERE phone = ?", [phone]).fetchdf()
    return df.to_dict(orient="records")[0] if not df.empty else None


def delete_user(phone: str):
    """Elimina usuario y todos sus datos."""
    con.execute("DELETE FROM transactions WHERE user_phone = ?", [phone])
    con.execute("DELETE FROM user_banks WHERE user_phone = ?", [phone])
    con.execute("DELETE FROM users WHERE phone = ?", [phone])
    # Borrar token de Gmail si existe
    from src.ingestion.gmail_client import TOKENS_DIR, _sanitize_phone
    token_file = TOKENS_DIR / f"{_sanitize_phone(phone)}.json"
    if token_file.exists():
        token_file.unlink()


def get_user_by_telegram_id(telegram_chat_id: str) -> Optional[Dict]:
    df = con.execute("SELECT * FROM users WHERE telegram_chat_id = ?", [telegram_chat_id]).fetchdf()
    return df.to_dict(orient="records")[0] if not df.empty else None


def get_all_users() -> List[Dict]:
    return con.execute("SELECT * FROM users").fetchdf().to_dict(orient="records")


# ----------------- Bancos por usuario -----------------

def upsert_user_bank(user_phone: str, bank: str, gmail_query: str):
    con.execute("""
        INSERT INTO user_banks (user_phone, bank, gmail_query)
        VALUES (?, ?, ?)
        ON CONFLICT (user_phone, bank) DO UPDATE SET gmail_query = excluded.gmail_query
    """, [user_phone, bank, gmail_query])


def get_user_banks(user_phone: str) -> List[Dict]:
    return con.execute(
        "SELECT * FROM user_banks WHERE user_phone = ?", [user_phone]
    ).fetchdf().to_dict(orient="records")


def get_all_user_banks() -> List[Dict]:
    return con.execute("SELECT * FROM user_banks").fetchdf().to_dict(orient="records")


# ----------------- Insertar / actualizar -----------------

def insert_transactions(rows: List[Dict]) -> List[str]:
    """Inserta transacciones nuevas. Retorna lista de tx_ids efectivamente insertados."""
    new_ids = []
    for r in rows:
        existing = con.execute(
            "SELECT tx_id FROM transactions WHERE tx_id = ?", [r["tx_id"]]
        ).fetchone()
        if existing is not None:
            continue
        user_id = r["user_phone"]
        con.execute("""
            INSERT INTO transactions
            (tx_id, user_phone, ts, description, amount_clp, description_enc, amount_enc,
             category, intent, needs_review, source, payment_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            r["tx_id"],
            user_id,
            r["timestamp"],
            None,   # description plain: omitido intencionalmente
            0.0,    # amount_clp plain: omitido intencionalmente
            encrypt(user_id, r["description"]),
            encrypt_amount(user_id, r["amount_clp"]),
            r.get("category"),
            r.get("intent"),
            r.get("needs_review", True),
            r.get("source", "manual"),
            r.get("payment_type"),
        ])
        new_ids.append(r["tx_id"])
    return new_ids


def _decrypt_df(df: pd.DataFrame) -> pd.DataFrame:
    """Descifra description y amount_clp desde las columnas _enc."""
    if df.empty or "description_enc" not in df.columns:
        return df
    for i, row in df.iterrows():
        user_id = row["user_phone"]
        if row.get("description_enc"):
            try:
                df.at[i, "description"] = decrypt(user_id, row["description_enc"])
            except Exception:
                pass
        if row.get("amount_enc"):
            try:
                df.at[i, "amount_clp"] = decrypt_amount(user_id, row["amount_enc"])
            except Exception:
                pass
    return df


def set_transaction_category(tx_id: str, category: str):
    con.execute(
        "UPDATE transactions SET category = ? WHERE tx_id = ?",
        [category, tx_id],
    )


def set_transaction_intent(tx_id: str, intent: str):
    con.execute("""
        UPDATE transactions
        SET intent = ?,
            needs_review = CASE WHEN category IS NOT NULL THEN FALSE ELSE needs_review END
        WHERE tx_id = ?
    """, [intent, tx_id])


# ----------------- Consultas -----------------

def get_pending_transactions(user_phone: Optional[str] = None, limit: int = 5) -> pd.DataFrame:
    limit = int(limit)
    if user_phone is None:
        df = con.execute(
            f"SELECT * FROM transactions WHERE needs_review = TRUE ORDER BY ts ASC LIMIT {limit}"
        ).fetchdf()
    else:
        df = con.execute(
            f"SELECT * FROM transactions WHERE needs_review = TRUE AND user_phone = ? ORDER BY ts ASC LIMIT {limit}",
            [user_phone]
        ).fetchdf()
    return _decrypt_df(df)


def get_transaction(tx_id: str) -> Optional[Dict]:
    df = con.execute("SELECT * FROM transactions WHERE tx_id = ?", [tx_id]).fetchdf()
    if df.empty:
        return None
    return _decrypt_df(df).to_dict(orient="records")[0]


def get_spend_by_month(user_phone: Optional[str] = None) -> pd.DataFrame:
    """Gastos totales agrupados por mes (año-mes), descifrados."""
    if user_phone:
        df = con.execute(
            "SELECT * FROM transactions WHERE user_phone = ?", [user_phone]
        ).fetchdf()
    else:
        df = con.execute("SELECT * FROM transactions").fetchdf()
    if df.empty:
        return pd.DataFrame(columns=["month", "spent_clp"])
    df = _decrypt_df(df)
    df["month"] = pd.to_datetime(df["ts"]).dt.to_period("M")
    result = (
        df.groupby("month")["amount_clp"]
        .apply(lambda x: x.abs().sum())
        .reset_index()
        .rename(columns={"amount_clp": "spent_clp"})
        .sort_values("month")
    )
    return result


def get_spend_by_payment_type(user_phone: Optional[str] = None, days_back: int = 0,
                              month: Optional[int] = None, year: Optional[int] = None) -> pd.DataFrame:
    days_back = int(days_back)
    if month and year:
        date_filter = f"AND EXTRACT(month FROM ts) = {int(month)} AND EXTRACT(year FROM ts) = {int(year)}"
    elif days_back <= 0:
        date_filter = ""
    else:
        date_filter = f"AND ts >= NOW() - INTERVAL {days_back} DAY"
    if user_phone:
        df = con.execute(
            f"SELECT * FROM transactions WHERE user_phone = ? {date_filter}", [user_phone]
        ).fetchdf()
    else:
        df = con.execute(f"SELECT * FROM transactions WHERE 1=1 {date_filter}").fetchdf()
    if df.empty:
        return pd.DataFrame(columns=["payment_type", "spent_clp"])
    df = _decrypt_df(df)
    df["payment_type"] = df["payment_type"].fillna("desconocido")
    return (
        df.groupby("payment_type")["amount_clp"]
        .apply(lambda x: x.abs().sum())
        .reset_index()
        .rename(columns={"amount_clp": "spent_clp"})
        .sort_values("spent_clp", ascending=False)
    )


def get_spend_by_category(user_phone: Optional[str] = None, days_back: int = 7,
                          month: Optional[int] = None, year: Optional[int] = None) -> pd.DataFrame:
    days_back = int(days_back)
    if month and year:
        date_filter = f"AND EXTRACT(month FROM ts) = {int(month)} AND EXTRACT(year FROM ts) = {int(year)}"
    elif days_back <= 0:
        date_filter = ""
    else:
        date_filter = f"AND ts >= NOW() - INTERVAL {days_back} DAY"
    if user_phone:
        df = con.execute(
            f"SELECT * FROM transactions WHERE user_phone = ? {date_filter}",
            [user_phone]
        ).fetchdf()
    else:
        df = con.execute(
            f"SELECT * FROM transactions WHERE 1=1 {date_filter}"
        ).fetchdf()

    if df.empty:
        return pd.DataFrame(columns=["category", "spent_clp"])

    df = _decrypt_df(df)
    df["category"] = df["category"].fillna("sin categoría")
    result = (
        df.groupby("category")["amount_clp"]
        .apply(lambda x: x.abs().sum())
        .reset_index()
        .rename(columns={"amount_clp": "spent_clp"})
        .sort_values("spent_clp", ascending=False)
    )
    return result


# ----------------- Ingresos -----------------

def insert_income(user_phone: str, amount_clp: float, description: str, income_type: str = "otro",
                  ts=None) -> str:
    from datetime import datetime as dt
    import uuid
    income_id = f"inc-{int(dt.now().timestamp() * 1000000)}-{uuid.uuid4().hex[:6]}"
    ts = ts or dt.now().isoformat()
    con.execute("""
        INSERT INTO incomes (income_id, user_phone, ts, amount_clp, description, income_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [income_id, user_phone, ts, abs(amount_clp), description, income_type])
    return income_id


def get_income_summary(user_phone: str, month: Optional[int] = None, year: Optional[int] = None,
                       days_back: int = 0) -> pd.DataFrame:
    if month and year:
        date_filter = f"AND EXTRACT(month FROM ts) = {int(month)} AND EXTRACT(year FROM ts) = {int(year)}"
    elif days_back > 0:
        date_filter = f"AND ts >= NOW() - INTERVAL {days_back} DAY"
    else:
        date_filter = ""
    return con.execute(
        f"SELECT income_type, SUM(amount_clp) as total_clp FROM incomes "
        f"WHERE user_phone = ? {date_filter} GROUP BY income_type ORDER BY total_clp DESC",
        [user_phone]
    ).fetchdf()


def get_total_income(user_phone: str, month: Optional[int] = None, year: Optional[int] = None) -> float:
    if month and year:
        date_filter = f"AND EXTRACT(month FROM ts) = {int(month)} AND EXTRACT(year FROM ts) = {int(year)}"
    else:
        date_filter = ""
    row = con.execute(
        f"SELECT COALESCE(SUM(amount_clp), 0) FROM incomes WHERE user_phone = ? {date_filter}",
        [user_phone]
    ).fetchone()
    return float(row[0]) if row else 0.0


def get_total_expenses(user_phone: str, month: Optional[int] = None, year: Optional[int] = None) -> float:
    if month and year:
        date_filter = f"AND EXTRACT(month FROM ts) = {int(month)} AND EXTRACT(year FROM ts) = {int(year)}"
    else:
        date_filter = ""
    df = con.execute(
        f"SELECT * FROM transactions WHERE user_phone = ? {date_filter}",
        [user_phone]
    ).fetchdf()
    if df.empty:
        return 0.0
    df = _decrypt_df(df)
    return float(df["amount_clp"].abs().sum())


# ----------------- Presupuestos -----------------

def set_budget(user_phone: str, category: str, monthly_limit: float):
    con.execute("""
        INSERT INTO budgets (user_phone, category, monthly_limit)
        VALUES (?, ?, ?)
        ON CONFLICT (user_phone, category) DO UPDATE SET monthly_limit = excluded.monthly_limit
    """, [user_phone, category, monthly_limit])


def get_budgets(user_phone: str) -> pd.DataFrame:
    return con.execute(
        "SELECT category, monthly_limit FROM budgets WHERE user_phone = ? ORDER BY category",
        [user_phone]
    ).fetchdf()


def get_budget_status(user_phone: str, month: Optional[int] = None, year: Optional[int] = None) -> pd.DataFrame:
    """Retorna presupuesto vs gasto real por categoría para el mes dado."""
    from datetime import datetime as dt
    month = month or dt.now().month
    year = year or dt.now().year

    budgets_df = get_budgets(user_phone)
    spending_df = get_spend_by_category(user_phone=user_phone, days_back=0, month=month, year=year)

    if budgets_df.empty:
        return pd.DataFrame(columns=["category", "monthly_limit", "spent_clp", "remaining_clp", "pct_used"])

    merged = budgets_df.merge(spending_df, on="category", how="left").fillna(0)
    merged["remaining_clp"] = merged["monthly_limit"] - merged["spent_clp"]
    merged["pct_used"] = (merged["spent_clp"] / merged["monthly_limit"] * 100).round(1)
    return merged.sort_values("pct_used", ascending=False)


# ----------------- Categorías personalizadas -----------------

BASE_CATEGORIES = [
    "transporte", "comida", "supermercado", "salud", "entretenimiento",
    "suscripciones", "ropa", "educacion", "hogar", "trabajo", "viajes",
    "mascota", "otros",
]


def add_user_category(user_phone: str, category: str) -> bool:
    """Agrega una categoría personalizada. Retorna False si ya existe."""
    cat = category.lower().strip()
    existing = con.execute(
        "SELECT category FROM user_categories WHERE user_phone = ? AND category = ?",
        [user_phone, cat]
    ).fetchone()
    if existing:
        return False
    con.execute("INSERT INTO user_categories (user_phone, category) VALUES (?, ?)", [user_phone, cat])
    return True


def get_user_categories(user_phone: str) -> list[str]:
    """Retorna categorías base + personalizadas del usuario."""
    custom = [r[0] for r in con.execute(
        "SELECT category FROM user_categories WHERE user_phone = ? ORDER BY category",
        [user_phone]
    ).fetchall()]
    all_cats = BASE_CATEGORIES[:]
    for c in custom:
        if c not in all_cats:
            all_cats.insert(-1, c)  # antes de 'otros'
    return all_cats


def delete_user_category(user_phone: str, category: str):
    con.execute(
        "DELETE FROM user_categories WHERE user_phone = ? AND category = ?",
        [user_phone, category.lower().strip()]
    )


# ----------------- Ítems recurrentes -----------------

def add_recurring_item(user_phone: str, name: str, amount_clp: float, item_type: str,
                       category: str = None, income_type: str = None,
                       due_day: int = 1, frequency: str = "monthly") -> str:
    from datetime import datetime as dt
    import uuid
    item_id = f"rec-{int(dt.now().timestamp() * 1000000)}-{uuid.uuid4().hex[:6]}"
    con.execute("""
        INSERT INTO recurring_items (item_id, user_phone, name, amount_clp, item_type,
                                     category, income_type, frequency, due_day)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [item_id, user_phone, name, abs(amount_clp), item_type, category, income_type, frequency, due_day])
    return item_id


def get_recurring_items(user_phone: str, item_type: str = None) -> pd.DataFrame:
    if item_type:
        return con.execute(
            "SELECT * FROM recurring_items WHERE user_phone = ? AND item_type = ? AND is_active = TRUE ORDER BY due_day",
            [user_phone, item_type]
        ).fetchdf()
    return con.execute(
        "SELECT * FROM recurring_items WHERE user_phone = ? AND is_active = TRUE ORDER BY item_type, due_day",
        [user_phone]
    ).fetchdf()


def remove_recurring_item(item_id: str):
    con.execute("UPDATE recurring_items SET is_active = FALSE WHERE item_id = ?", [item_id])


def update_recurring_item(item_id: str, **kwargs) -> bool:
    """Actualiza campos de un ítem recurrente. Retorna True si encontró el ítem."""
    allowed = {"name", "amount_clp", "category", "income_type", "due_day", "frequency"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [item_id]
    con.execute(f"UPDATE recurring_items SET {sets} WHERE item_id = ? AND is_active = TRUE", values)
    return True


def clear_all_user_data(user_phone: str = None) -> dict:
    """Borra transacciones, ingresos, ítems recurrentes y cargos pendientes.
    Si user_phone es None, limpia todos los usuarios."""
    where = "WHERE user_phone = ?" if user_phone else ""
    params = [user_phone] if user_phone else []

    tx = con.execute(f"SELECT COUNT(*) FROM transactions {where}", params).fetchone()[0]
    con.execute(f"DELETE FROM transactions {where}", params)

    inc = con.execute(f"SELECT COUNT(*) FROM incomes {where}", params).fetchone()[0]
    con.execute(f"DELETE FROM incomes {where}", params)

    rec = con.execute(f"SELECT COUNT(*) FROM recurring_items {where}", params).fetchone()[0]
    con.execute(f"UPDATE recurring_items SET is_active = FALSE {where}", params)

    chg = con.execute(f"SELECT COUNT(*) FROM pending_charges {where}", params).fetchone()[0]
    con.execute(f"UPDATE pending_charges SET is_paid = TRUE {where}", params)

    return {"transactions": tx, "incomes": inc, "recurring": rec, "charges": chg}


def clear_recurring_items(user_phone: str) -> int:
    result = con.execute(
        "SELECT COUNT(*) FROM recurring_items WHERE user_phone = ? AND is_active = TRUE",
        [user_phone]
    ).fetchone()[0]
    con.execute("UPDATE recurring_items SET is_active = FALSE WHERE user_phone = ?", [user_phone])
    return result


# ----------------- Cargos pendientes -----------------

def add_pending_charge(user_phone: str, description: str, amount_clp: float,
                       due_date: str, charge_type: str = "otro") -> str:
    from datetime import datetime as dt
    import uuid
    charge_id = f"chg-{int(dt.now().timestamp() * 1000000)}-{uuid.uuid4().hex[:6]}"
    con.execute("""
        INSERT INTO pending_charges (charge_id, user_phone, description, amount_clp, due_date, charge_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [charge_id, user_phone, description, abs(amount_clp), due_date, charge_type])
    return charge_id


def get_pending_charges(user_phone: str, include_paid: bool = False) -> pd.DataFrame:
    paid_filter = "" if include_paid else "AND is_paid = FALSE"
    return con.execute(
        f"SELECT * FROM pending_charges WHERE user_phone = ? {paid_filter} ORDER BY due_date",
        [user_phone]
    ).fetchdf()


def mark_charge_paid(charge_id: str):
    con.execute("UPDATE pending_charges SET is_paid = TRUE WHERE charge_id = ?", [charge_id])


def clear_pending_charges(user_phone: str) -> int:
    result = con.execute(
        "SELECT COUNT(*) FROM pending_charges WHERE user_phone = ? AND is_paid = FALSE",
        [user_phone]
    ).fetchone()[0]
    con.execute("UPDATE pending_charges SET is_paid = TRUE WHERE user_phone = ?", [user_phone])
    return result


# ----------------- Proyección financiera -----------------

def get_financial_projection(user_phone: str, month: int, year: int) -> dict:
    """
    Proyección financiera basada en ítems recurrentes y cargos pendientes del mes.

    Fórmula: ingreso_recurrente - gastos_recurrentes - cargos_pendientes_del_mes = disponible

    No usa real_income ni real_expenses para evitar doble conteo.
    """
    # Ítems recurrentes configurados por el usuario
    rec_df = get_recurring_items(user_phone)
    rec_income_total = 0.0
    rec_expense_total = 0.0
    rec_income_items = []
    rec_expense_items = []

    for _, row in rec_df.iterrows():
        if row.frequency == "annual":
            continue
        if row.item_type == "income":
            rec_income_total += row.amount_clp
            rec_income_items.append({
                "name": row["name"], "amount": row.amount_clp, "due_day": row.due_day,
            })
        else:
            rec_expense_total += row.amount_clp
            rec_expense_items.append({
                "name": row["name"], "amount": row.amount_clp, "due_day": row.due_day,
                "category": row.get("category"),
            })

    # Cargos pendientes con vencimiento en el mes solicitado
    charges_df = get_pending_charges(user_phone)
    if not charges_df.empty:
        month_mask = pd.to_datetime(charges_df["due_date"]).dt.month == month
        year_mask  = pd.to_datetime(charges_df["due_date"]).dt.year  == year
        month_charges = charges_df[month_mask & year_mask]
    else:
        month_charges = pd.DataFrame()

    pending_total = float(month_charges["amount_clp"].sum()) if not month_charges.empty else 0.0
    pending_items = month_charges.to_dict(orient="records") if not month_charges.empty else []

    # Fórmula limpia: recurrente_entrada - recurrente_salida - cargos_puntuales
    projected_balance = rec_income_total - rec_expense_total - pending_total

    return {
        "month": month, "year": year,
        "rec_income_total": rec_income_total,
        "rec_income_items": rec_income_items,
        "rec_expense_total": rec_expense_total,
        "rec_expense_items": rec_expense_items,
        "pending_total": pending_total,
        "pending_items": pending_items,
        "projected_balance": projected_balance,
    }
