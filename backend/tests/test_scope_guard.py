import pytest

from core.kanban_protocol.scope_guard import (
    DENIED_PAYLOAD_KEYS,
    check_payload,
    find_denied_keys,
)


def test_denied_payload_keys_includes_security_work():
    assert "sandbox_egress" in DENIED_PAYLOAD_KEYS
    assert "iptables_rules" in DENIED_PAYLOAD_KEYS
    assert "admin_keys" in DENIED_PAYLOAD_KEYS
    assert "pentest_findings" in DENIED_PAYLOAD_KEYS


def test_find_denied_keys_returns_empty_for_clean_payload():
    payload = {"diff_summary": "ok", "test_results": "ok"}
    assert find_denied_keys(payload) == set()


def test_find_denied_keys_finds_nested_denied_keys():
    payload = {
        "diff_summary": "ok",
        "metadata": {"sandbox_egress": "10.0.0.0/8"},
    }
    assert find_denied_keys(payload) == {"sandbox_egress"}


def test_find_denied_keys_finds_denied_in_lists():
    payload = {"steps": ["run", {"iptables_rules": "ACCEPT"}]}
    assert find_denied_keys(payload) == {"iptables_rules"}


def test_check_payload_passes_for_clean_payload():
    check_payload({"diff_summary": "ok"})  # does not raise


def test_check_payload_raises_scope_denied_error():
    from core.kanban_protocol.scope_guard import ScopeDeniedError
    with pytest.raises(ScopeDeniedError) as exc_info:
        check_payload({"admin_keys": "supersecret"})
    assert "admin_keys" in exc_info.value.offending_keys
