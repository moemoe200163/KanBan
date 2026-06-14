"""API key encryption utilities for LLM provider configs.

Uses Fernet symmetric encryption (from the ``cryptography`` package) when
``LLM_KEY_ENCRYPTION_KEY`` is set.  Falls back to plaintext storage when
the env var is absent so that development / CI environments work without
extra setup.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Lazily initialized Fernet instance
_fernet = None


def _get_fernet():
    """Get or initialize Fernet with server-side key.

    Returns ``None`` when the env var is missing or the key is invalid so
    callers can fall back to plaintext storage.
    """
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.environ.get("LLM_KEY_ENCRYPTION_KEY", "")
    if not key:
        logger.warning("LLM_KEY_ENCRYPTION_KEY not set -- storing API keys in plaintext")
        return None

    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:
        logger.error(f"Failed to initialize Fernet: {e}")
        return None


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key. Returns plaintext if no encryption key is set."""
    if not plaintext:
        return ""
    f = _get_fernet()
    if f is None:
        return plaintext  # Fallback: store plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt an API key. Returns as-is if decryption fails (plaintext fallback)."""
    if not encrypted:
        return ""
    f = _get_fernet()
    if f is None:
        return encrypted  # Assume plaintext
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted  # Assume plaintext (backward compat)


def mask_api_key(key: str) -> tuple[str, str]:
    """Return (prefix, last4) for display. Never return the full key."""
    if not key:
        return ("", "")
    prefix = key[:8] if len(key) > 8 else key[: len(key) // 2]
    last4 = key[-4:] if len(key) >= 4 else key
    return (prefix, last4)


def reset_fernet():
    """Reset the lazily-initialized Fernet instance.

    Intended for test isolation only -- allows re-reading the env var
    after ``monkeypatch.setenv``.
    """
    global _fernet
    _fernet = None
