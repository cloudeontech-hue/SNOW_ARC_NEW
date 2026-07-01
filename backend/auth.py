import re
import uuid
import secrets
import hashlib
from backend.store import load_json, save_json

# In-memory session store: token -> {user_id, email, portal}
SESSIONS = {}

def hash_password(password: str, salt: bytes = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        200000
    )
    return pw_hash.hex(), salt.hex()

def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        pw_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            200000
        )
        return pw_hash.hex() == stored_hash
    except Exception:
        return False

def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))

def register_user(email: str, password: str, portal: str) -> tuple[bool, str]:
    if portal not in ("servicenow", "freshdesk"):
        return False, "Invalid portal specified"
    if not validate_email(email):
        return False, "Invalid email format"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    users = load_json("users.json")
    if portal not in users:
        users[portal] = {}
        
    email_lower = email.lower().strip()
    if email_lower in users[portal]:
        return False, "An account with this email already exists for this portal"
        
    pw_hash, salt_hex = hash_password(password)
    user_id = str(uuid.uuid4())
    
    users[portal][email_lower] = {
        "user_id": user_id,
        "password_hash": pw_hash,
        "salt": salt_hex,
        "email": email
    }
    save_json("users.json", users)
    return True, "User registered successfully"

def login_user(email: str, password: str, portal: str) -> tuple[str | None, str]:
    if portal not in ("servicenow", "freshdesk"):
        return None, "Invalid portal specified"
        
    users = load_json("users.json")
    if portal not in users:
        return None, "Invalid credentials"
        
    email_lower = email.lower().strip()
    if email_lower not in users[portal]:
        return None, "Invalid credentials"
        
    user_data = users[portal][email_lower]
    if verify_password(password, user_data["password_hash"], user_data["salt"]):
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {
            "user_id": user_data["user_id"],
            "email": user_data["email"],
            "portal": portal
        }
        return token, "Login successful"
    return None, "Invalid credentials"

def logout_user(token: str):
    if token in SESSIONS:
        del SESSIONS[token]

def get_session(token: str) -> dict | None:
    return SESSIONS.get(token)
