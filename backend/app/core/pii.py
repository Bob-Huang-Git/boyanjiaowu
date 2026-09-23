import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_DEVELOPMENT_KEY = hashlib.sha256(b"boyan-development-key-not-for-production").digest()


def _key(value: str, label: str) -> bytes:
    settings = get_settings()
    if not value:
        if settings.app_env == "production":
            raise RuntimeError(f"{label} is required in production")
        return _DEVELOPMENT_KEY
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as error:
        raise ValueError(f"{label} must be base64 encoded") from error
    if len(decoded) != 32:
        raise ValueError(f"{label} must decode to 32 bytes")
    return decoded


def encrypt(value: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key(get_settings().pii_encryption_key, "PII_ENCRYPTION_KEY")).encrypt(
        nonce, value.encode(), None
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt(value: str) -> str:
    payload = base64.urlsafe_b64decode(value.encode())
    return (
        AESGCM(_key(get_settings().pii_encryption_key, "PII_ENCRYPTION_KEY"))
        .decrypt(payload[:12], payload[12:], None)
        .decode()
    )


def blind_index(value: str) -> str:
    key = _key(get_settings().pii_blind_index_key, "PII_BLIND_INDEX_KEY")
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def normalize_document(document_type: str, number: str) -> str:
    normalized = number.strip()
    if document_type == "PRC_ID":
        return normalized.upper()
    return normalized


def normalize_phone(phone: str) -> str:
    return "".join(
        character for character in phone.strip() if character.isdigit() or character == "+"
    )


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "****"


def mask_document(last4: str, document_type: str) -> str:
    return f"{document_type} ****{last4}"
