import logging
import duckdb
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "finanzas.duckdb"
con = duckdb.connect(str(DB_PATH))


def init_db():
    con.execute("""
    CREATE TABLE IF NOT EXISTS users (
        phone       TEXT PRIMARY KEY,
        name        TEXT,
        gmail_query TEXT,
        bank        TEXT,
        created_at  TIMESTAMP DEFAULT NOW()
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
        tx_id       TEXT PRIMARY KEY,
        user_phone  TEXT,
        ts          TIMESTAMP,
        description TEXT,
        amount_clp  DOUBLE,
        category    TEXT,
        intent      TEXT,
        needs_review BOOLEAN,
        source      TEXT DEFAULT 'manual'
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

def upsert_user(phone: str, name: str):
    con.execute("""
        INSERT INTO users (phone, name)
        VALUES (?, ?)
        ON CONFLICT (phone) DO UPDATE SET name = excluded.name
    """, [phone, name])


def get_user(phone: str) -> Optional[Dict]:
    df = con.execute("SELECT * FROM users WHERE phone = ?", [phone]).fetchdf()
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
        con.execute("""
            INSERT INTO transactions
            (tx_id, user_phone, ts, description, amount_clp, category, intent, needs_review, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            r["tx_id"],
            r["user_phone"],
            r["timestamp"],
            r["description"],
            r["amount_clp"],
            r.get("category"),
            r.get("intent"),
            r.get("needs_review", True),
            r.get("source", "manual"),
        ])
        new_ids.append(r["tx_id"])
    return new_ids


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
    limit = int(limit)  # evita inyección
    if user_phone is None:
        return con.execute(
            f"SELECT * FROM transactions WHERE needs_review = TRUE ORDER BY ts ASC LIMIT {limit}"
        ).fetchdf()
    return con.execute(
        f"SELECT * FROM transactions WHERE needs_review = TRUE AND user_phone = ? ORDER BY ts ASC LIMIT {limit}",
        [user_phone]
    ).fetchdf()


def get_transaction(tx_id: str) -> Optional[Dict]:
    df = con.execute("SELECT * FROM transactions WHERE tx_id = ?", [tx_id]).fetchdf()
    return df.to_dict(orient="records")[0] if not df.empty else None


def get_spend_by_category(user_phone: Optional[str] = None, days_back: int = 7) -> pd.DataFrame:
    days_back = int(days_back)  # evita inyección
    base = f"""
        SELECT
            COALESCE(category, 'sin categoría') AS category,
            SUM(ABS(amount_clp)) AS spent_clp
        FROM transactions
        WHERE ts >= NOW() - INTERVAL {days_back} DAY
    """
    if user_phone:
        return con.execute(base + " AND user_phone = ? GROUP BY category ORDER BY spent_clp DESC",
                           [user_phone]).fetchdf()
    return con.execute(base + " GROUP BY category ORDER BY spent_clp DESC").fetchdf()
