import duckdb
from pathlib import Path
from typing import List, Dict
import pandas as pd

# 1) aseguramos que exista la carpeta data/
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "finanzas.duckdb"
con = duckdb.connect(str(DB_PATH))


def init_db():
    """
    Crea las tablas necesarias si no existen.
    """
    con.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        tx_id TEXT PRIMARY KEY,
        ts TIMESTAMP,
        description TEXT,
        amount_clp DOUBLE,
        account_id TEXT,
        category TEXT,
        intent TEXT,
        needs_review BOOLEAN
    );
    """)


init_db()

# ----------------- Insertar / actualizar -----------------

def insert_transactions(rows: List[Dict]):
    if not rows:
        return

    for r in rows:
        con.execute("""
            INSERT OR IGNORE INTO transactions
            (tx_id, ts, description, amount_clp, account_id, category, intent, needs_review)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                r["tx_id"],
                r["timestamp"],
                r["description"],
                r["amount_clp"],
                r["account_id"],
                r.get("category"),
                r.get("intent"),
                r.get("needs_review", True),
            ],
        )


def set_transaction_category(tx_id: str, category: str):
    con.execute(
        "UPDATE transactions SET category = ? WHERE tx_id = ?",
        [category, tx_id],
    )


def set_transaction_intent(tx_id: str, intent: str):
    # actualiza intención y marca revisado si ya hay categoría
    con.execute("""
        UPDATE transactions
        SET intent = ?, 
            needs_review = CASE WHEN category IS NOT NULL THEN FALSE ELSE needs_review END
        WHERE tx_id = ?
    """, [intent, tx_id])


# ----------------- Consultas -----------------

def get_pending_transactions(account_id:str|None=None,
                             limit: int = 5) -> pd.DataFrame:
    if account_id is None:
        return con.execute(f"""
        SELECT *
        FROM transactions
        WHERE needs_review = TRUE
        ORDER BY ts ASC
        LIMIT {limit}
        """).fetchdf()
    
    return con.execute(f"""
        SELECT *
        FROM transactions
        WHERE needs_review = TRUE and account_id = ?
        ORDER BY ts ASC
        LIMIT {limit}
        """,[account_id]).fetchdf()


def get_transaction(tx_id: str) -> Dict:
    df = con.execute("SELECT * FROM transactions WHERE tx_id = ?", [tx_id]).fetchdf()
    return df.to_dict(orient="records")[0] if not df.empty else None


def get_spend_by_category(days_back: int = 7) -> pd.DataFrame:
    return con.execute(f"""
        SELECT
            COALESCE(category, 'Sin categoría') AS category,
            SUM(ABS(amount_clp)) AS spent_clp
        FROM transactions
        WHERE ts >= NOW() - INTERVAL {days_back} DAY
        GROUP BY category
        ORDER BY spent_clp DESC
    """).fetchdf()