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
        source           TEXT DEFAULT 'manual'
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

    # Migración: agregar telegram_chat_id si no existe
    user_cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
    ).fetchall()]
    if "telegram_chat_id" not in user_cols:
        logger.info("Migrando schema: agregando telegram_chat_id a users")
        con.execute("ALTER TABLE users ADD COLUMN telegram_chat_id TEXT")
    if "nickname" not in user_cols:
        con.execute("ALTER TABLE users ADD COLUMN nickname TEXT")

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
             category, intent, needs_review, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
