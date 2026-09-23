import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except VerifyMismatchError:
        return False


def random_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(value: str) -> str:
    return hmac.new(
        get_settings().session_secret.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def csrf_digest(value: str) -> str:
    return hmac.new(get_settings().csrf_secret.encode(), value.encode(), hashlib.sha256).hexdigest()
