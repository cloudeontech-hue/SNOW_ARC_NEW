import os
import re
import time
import uuid
import secrets
import hashlib
from backend.store import load_json, save_json
from backend.mailer import send_verification_email

# In-memory session store: token -> {user_id, email, portal}
SESSIONS = {}

# In-memory pending email verifications: (email_lower, portal) -> {code, expires_at, attempts}
PENDING_VERIFICATIONS = {}
MAX_VERIFICATION_ATTEMPTS = 5

def _verification_ttl_seconds() -> int:
    # Configurable via VERIFICATION_CODE_TTL_MINUTES in .env; 15 minutes by default.
    try:
        minutes = int(os.environ.get("VERIFICATION_CODE_TTL_MINUTES", "15"))
    except ValueError:
        minutes = 15
    return max(minutes, 1) * 60

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

def _generate_verification_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"

def request_email_verification(email: str, portal: str) -> tuple[bool, str]:
    """Send a one-time code to `email` to prove it's a real, working inbox.

    Used both before registration (account doesn't exist yet) and to let an
    existing-but-unverified account (e.g. one predating this feature, or an
    interrupted registration) request a fresh code so it can get verified —
    see `verify_existing_account`. An already-verified account is rejected
    here since it doesn't need this and shouldn't allow duplicate creation.
    """
    if portal not in ("servicenow", "freshdesk"):
        return False, "Invalid portal specified"
    if not validate_email(email):
        return False, "Invalid email format"

    users = load_json("users.json")
    email_lower = email.lower().strip()
    existing = users.get(portal, {}).get(email_lower)
    if existing and existing.get("email_verified"):
        return False, "An account with this email already exists for this portal"

    code = _generate_verification_code()
    sent, msg = send_verification_email(email, code, ttl_minutes=_verification_ttl_seconds() // 60)
    if not sent:
        return False, msg

    PENDING_VERIFICATIONS[(email_lower, portal)] = {
        "code": code,
        "expires_at": time.time() + _verification_ttl_seconds(),
        "attempts": 0,
    }
    return True, "Verification code sent. Check your inbox."

def _check_verification_code(email: str, portal: str, code: str) -> tuple[bool, str]:
    key = (email.lower().strip(), portal)
    entry = PENDING_VERIFICATIONS.get(key)
    if not entry:
        return False, "This email could not be verified. Please request a new code."
    if time.time() > entry["expires_at"]:
        del PENDING_VERIFICATIONS[key]
        return False, "Verification code expired. Please request a new code."
    entry["attempts"] += 1
    if entry["attempts"] > MAX_VERIFICATION_ATTEMPTS:
        del PENDING_VERIFICATIONS[key]
        return False, "Too many incorrect attempts. Please request a new code."
    if not code or entry["code"] != code.strip():
        return False, "Incorrect verification code."
    return True, "Verified"

def register_user(email: str, password: str, portal: str, code: str) -> tuple[bool, str]:
    if portal not in ("servicenow", "freshdesk"):
        return False, "Invalid portal specified"
    if not validate_email(email):
        return False, "Invalid email format"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    ok, msg = _check_verification_code(email, portal, code)
    if not ok:
        return False, msg

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
        "email": email,
        "email_verified": True
    }
    save_json("users.json", users)
    del PENDING_VERIFICATIONS[(email_lower, portal)]
    return True, "User registered successfully"

def verify_existing_account(email: str, portal: str, code: str) -> tuple[bool, str]:
    """Mark an existing-but-unverified account as verified, using the same
    single-use/expiring code mechanism as registration. Covers accounts
    that predate this feature, or whose registration verification lapsed."""
    if portal not in ("servicenow", "freshdesk"):
        return False, "Invalid portal specified"
    if not validate_email(email):
        return False, "Invalid email format"

    users = load_json("users.json")
    email_lower = email.lower().strip()
    user_data = users.get(portal, {}).get(email_lower)
    if not user_data:
        return False, "No account found for this email. Please register first."
    if user_data.get("email_verified"):
        return False, "This account is already verified. Please log in."

    ok, msg = _check_verification_code(email, portal, code)
    if not ok:
        return False, msg

    user_data["email_verified"] = True
    save_json("users.json", users)
    del PENDING_VERIFICATIONS[(email_lower, portal)]
    return True, "Email verified. You can now log in."

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
        if not user_data.get("email_verified"):
            return None, "Please verify your email before logging in. Request a new verification code to continue."
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {
            "user_id": user_data["user_id"],
            "email": user_data["email"],
            "portal": portal
        }
        return token, "Login successful"
    return None, "Invalid credentials"

def login_or_register_google_user(email: str, portal: str) -> tuple[str | None, str]:
    """Find-or-create a user for a Google-authenticated email and start a session.

    Google has already verified the email at this point, so this both covers
    "login with Google" for an existing account and "sign up with Google" for
    a brand-new one, without requiring a password or a verification code.
    """
    if portal not in ("servicenow", "freshdesk"):
        return None, "Invalid portal specified"
    if not validate_email(email):
        return None, "Invalid email from Google account"

    users = load_json("users.json")
    if portal not in users:
        users[portal] = {}

    email_lower = email.lower().strip()
    user_data = users[portal].get(email_lower)
    if not user_data:
        user_data = {
            "user_id": str(uuid.uuid4()),
            "password_hash": None,
            "salt": None,
            "email": email,
            "email_verified": True,
            "auth_provider": "google",
        }
        users[portal][email_lower] = user_data
        save_json("users.json", users)
    elif not user_data.get("email_verified"):
        user_data["email_verified"] = True
        save_json("users.json", users)

    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "user_id": user_data["user_id"],
        "email": user_data["email"],
        "portal": portal
    }
    return token, "Login successful"

def logout_user(token: str):
    if token in SESSIONS:
        del SESSIONS[token]

def get_session(token: str) -> dict | None:
    return SESSIONS.get(token)
