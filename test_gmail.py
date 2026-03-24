import logging
logging.basicConfig(level=logging.INFO)

from src.ingestion.gmail_ingest import ingest_gmail_expenses

user = {
    "phone": "+56912345678",
    "gmail_query": 'from:(@bancochile.cl) "compra"',
    "bank": "bancochile",
}
new = ingest_gmail_expenses(user)
print("Nuevas tx:", new)
