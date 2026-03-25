"""
Cifrado simétrico por usuario (Fernet / AES-128).

Cada usuario tiene su propia clave derivada de GASTAI_SECRET_KEY + user_id.
El que accede directamente a la DB ve strings cifrados.
"""
import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SECRET = os.getenv("GASTAI_SECRET_KEY", "dev-secret-change-in-prod").encode()


def _fernet(user_id: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=user_id.encode(),
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(_SECRET))
    return Fernet(key)


def encrypt(user_id: str, value: str) -> str:
    return _fernet(user_id).encrypt(value.encode()).decode()


def decrypt(user_id: str, value: str) -> str:
    return _fernet(user_id).decrypt(value.encode()).decode()


def encrypt_amount(user_id: str, amount: float) -> str:
    return encrypt(user_id, str(amount))


def decrypt_amount(user_id: str, enc: str) -> float:
    return float(decrypt(user_id, enc))
