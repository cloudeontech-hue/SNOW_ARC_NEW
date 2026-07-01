import os
import hashlib
import base64
from cryptography.fernet import Fernet

def get_fernet_key() -> bytes:
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key:
        raise ValueError("SECRET_KEY environment variable is required")
    # Derive key: SECRET_KEY -> SHA-256 -> urlsafe_b64encode -> Fernet key
    h = hashlib.sha256(secret_key.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(h)

def encrypt_value(value: str) -> str:
    if not value:
        return ""
    key = get_fernet_key()
    f = Fernet(key)
    return f.encrypt(value.encode('utf-8')).decode('utf-8')

def decrypt_value(value: str) -> str:
    if not value:
        return ""
    key = get_fernet_key()
    f = Fernet(key)
    return f.decrypt(value.encode('utf-8')).decode('utf-8')
