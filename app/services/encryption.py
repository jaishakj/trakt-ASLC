"""Token and sensitive data encryption using Fernet symmetric encryption."""

import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from app.core.config import settings

def _get_fernet() -> Fernet:
    secret = settings.SECRET_KEY.encode()
    # Ensure 32-byte urlsafe base64 key
    try:
        # If secret is already a valid 32-byte urlsafe base64 string
        f = Fernet(secret)
        return f
    except Exception:
        # Derive a 32-byte key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"trakt-letterboxd-sync-salt",
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(secret))
        return Fernet(derived_key)


def encrypt_token(plain_token: str | None) -> str | None:
    if plain_token is None:
        return None
    f = _get_fernet()
    return f.encrypt(plain_token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str | None) -> str | None:
    if encrypted_token is None:
        return None
    try:
        f = _get_fernet()
        return f.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except Exception:
        return None
