#!/usr/bin/env python3
"""
Registra un usuario y autoriza su Gmail.

Uso:
    python scripts/add_user.py --phone +56912345678 --name "Bruno"

El sistema detecta automáticamente los emails bancarios —
no necesitas especificar qué bancos usa el usuario.

Flags:
    --skip-gmail   Registra sin hacer el OAuth ahora
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow
from src.ingestion.gmail_client import CREDS_FILE, SCOPES, _sanitize_phone, TOKENS_DIR
from src.db.storage import upsert_user, get_user


def main():
    parser = argparse.ArgumentParser(description="Registrar usuario en GastAI")
    parser.add_argument("--phone",      required=True, help="Ej: +56912345678")
    parser.add_argument("--name",       default=None,  help="Nombre (requerido para usuario nuevo)")
    parser.add_argument("--skip-gmail", action="store_true", help="No hacer OAuth ahora")
    args = parser.parse_args()

    phone = args.phone

    # Registrar/actualizar usuario
    existing = get_user(phone)
    if existing:
        if args.name:
            upsert_user(phone, args.name)
            print(f"✓ Usuario actualizado: {args.name} ({phone})")
        else:
            print(f"✓ Usuario existente: {existing['name']} ({phone})")
    else:
        if not args.name:
            print("ERROR: --name es requerido para un usuario nuevo.")
            sys.exit(1)
        upsert_user(phone, args.name)
        print(f"✓ Usuario registrado: {args.name} ({phone})")

    # OAuth Gmail
    if args.skip_gmail:
        print(f"\nGmail pendiente. Cuando quieras autorizar:")
        print(f"  python scripts/add_user.py --phone {phone}")
        return

    token_file = TOKENS_DIR / f"{_sanitize_phone(phone)}.json"
    if token_file.exists():
        print(f"✓ Gmail ya autorizado ({token_file.name})")
        return

    print("\nAbriendo browser para autorizar Gmail...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    with token_file.open("w") as f:
        f.write(creds.to_json())

    print(f"✓ Token guardado: {token_file.name}")
    print(f"\nListo. El sistema detectará automáticamente los emails de todos tus bancos.")
    print(f"Verifica en: http://localhost:8000/admin/users")


if __name__ == "__main__":
    main()
