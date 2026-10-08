"""
Auth utilities — password hashing + JWT-style tokens using stdlib only.
No external deps needed (hashlib + hmac are built-in).
"""
import hashlib, hmac, base64, json, time, secrets, os
from .config import settings

SECRET = settings.SECRET_KEY.encode()
PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 260_000

# ── Password hashing (PBKDF2-SHA256 via hashlib) ─────────────────────────────
def hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(PBKDF2_ITERATIONS, salt, base64.b64encode(dk).decode())

def verify_password(plain: str, hashed: str) -> bool:
    try:
        parts = hashed.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            _, iterations, salt, stored = parts
            iterations = int(iterations)
        else:
            salt, stored = hashed.split("$", 1)
            iterations = LEGACY_PBKDF2_ITERATIONS
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), iterations)
        return hmac.compare_digest(base64.b64encode(dk).decode(), stored)
    except Exception:
        return False

def needs_rehash(hashed: str) -> bool:
    try:
        parts = hashed.split("$")
        return not (len(parts) == 4 and parts[0] == "pbkdf2_sha256" and int(parts[1]) >= PBKDF2_ITERATIONS)
    except Exception:
        return True

# ── Token (HS256 JWT-lite) ────────────────────────────────────────────────────
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64url(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * (pad % 4))

def create_token(payload: dict, expires_in: int = 60 * 60 * 24 * 7) -> str:
    header = _b64url(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
    payload = {**payload, "exp": int(time.time()) + expires_in, "iat": int(time.time())}
    body    = _b64url(json.dumps(payload).encode())
    sig     = _b64url(hmac.new(SECRET, f"{header}.{body}".encode(), "sha256").digest())
    return f"{header}.{body}.{sig}"

def decode_token(token: str) -> dict | None:
    try:
        header, body, sig = token.split(".")
        expected = _b64url(hmac.new(SECRET, f"{header}.{body}".encode(), "sha256").digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64url(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None