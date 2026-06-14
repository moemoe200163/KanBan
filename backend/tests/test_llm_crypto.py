"""Tests for core.llm.crypto -- Fernet encryption round-trip and masking."""

import pytest
from unittest.mock import patch

from core.llm import crypto


# ---------------------------------------------------------------------------
# Test isolation: reset the lazily-initialized Fernet instance between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_fernet():
    """Ensure each test starts with a clean Fernet state."""
    crypto.reset_fernet()
    yield
    crypto.reset_fernet()


# ---------------------------------------------------------------------------
# encrypt / decrypt round-trip
# ---------------------------------------------------------------------------

def _valid_fernet_key():
    """Generate a valid 32-byte base64-encoded Fernet key for testing."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns the original plaintext."""
    fernet_key = _valid_fernet_key()
    with patch.dict("os.environ", {"LLM_KEY_ENCRYPTION_KEY": fernet_key}):
        crypto.reset_fernet()
        plaintext = "test-api-key-12345678"
        encrypted = crypto.encrypt_api_key(plaintext)
        decrypted = crypto.decrypt_api_key(encrypted)
        assert decrypted == plaintext
        # Encrypted value must differ from plaintext
        assert encrypted != plaintext


def test_encrypt_empty_string():
    """Encrypting an empty string returns empty."""
    assert crypto.encrypt_api_key("") == ""


def test_decrypt_empty_string():
    """Decrypting an empty string returns empty."""
    assert crypto.decrypt_api_key("") == ""


def test_encrypt_with_no_encryption_key():
    """Without LLM_KEY_ENCRYPTION_KEY set, encrypt returns plaintext."""
    with patch.dict("os.environ", {}, clear=True):
        crypto.reset_fernet()
        plaintext = "my-secret-key"
        result = crypto.encrypt_api_key(plaintext)
        assert result == plaintext


def test_decrypt_with_no_encryption_key():
    """Without LLM_KEY_ENCRYPTION_KEY set, decrypt returns as-is."""
    with patch.dict("os.environ", {}, clear=True):
        crypto.reset_fernet()
        value = "my-plaintext-key"
        result = crypto.decrypt_api_key(value)
        assert result == value


# ---------------------------------------------------------------------------
# mask_api_key
# ---------------------------------------------------------------------------

def test_mask_api_key_normal():
    """mask_api_key returns (prefix, last4) for a normal-length key."""
    key = "sk-cp-mOxYzAbCdEfGhIjKlPqRsTuVwX"
    prefix, last4 = crypto.mask_api_key(key)
    assert prefix == "sk-cp-mO"
    assert last4 == "uVwX"


def test_mask_api_key_short():
    """mask_api_key handles keys shorter than 8 characters."""
    key = "abc123"
    prefix, last4 = crypto.mask_api_key(key)
    # prefix should be first half: "abc"
    assert prefix == "abc"
    # last4 should be the full key since len < 4 is handled, but 6 >= 4
    assert last4 == "c123"


def test_mask_api_key_very_short():
    """mask_api_key handles keys with fewer than 4 characters."""
    key = "ab"
    prefix, last4 = crypto.mask_api_key(key)
    assert prefix == "a"
    assert last4 == "ab"


def test_mask_api_key_empty():
    """mask_api_key returns empty strings for empty input."""
    prefix, last4 = crypto.mask_api_key("")
    assert prefix == ""
    assert last4 == ""


# ---------------------------------------------------------------------------
# decrypt garbage returns as-is (plaintext fallback)
# ---------------------------------------------------------------------------

def test_decrypt_garbage_returns_as_is():
    """Decrypting a non-Fernet string returns it unchanged (backward compat)."""
    garbage = "this-is-not-encrypted"
    result = crypto.decrypt_api_key(garbage)
    assert result == garbage


def test_decrypt_partial_garbage():
    """Decrypting a partially corrupted Fernet token returns as-is."""
    # A valid Fernet token is base64 with specific prefix; this is not.
    result = crypto.decrypt_api_key("not-a-valid-token!!!")
    assert result == "not-a-valid-token!!!"


# ---------------------------------------------------------------------------
# reset_fernet
# ---------------------------------------------------------------------------

def test_reset_fernet_clears_cached_instance():
    """After reset, next call re-reads the env var."""
    fernet_key = _valid_fernet_key()
    # First call initializes
    with patch.dict("os.environ", {"LLM_KEY_ENCRYPTION_KEY": fernet_key}):
        crypto.reset_fernet()
        f1 = crypto._get_fernet()
        assert f1 is not None

    # Reset and change env -- should pick up new state
    crypto.reset_fernet()
    with patch.dict("os.environ", {}, clear=True):
        f2 = crypto._get_fernet()
        assert f2 is None
