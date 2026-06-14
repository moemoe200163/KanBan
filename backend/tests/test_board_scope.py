import pytest

from core.kanban_protocol.board_scope import (
    DEFAULT_BOARD_ID,
    assert_board_id_allowed,
    resolve_board_id,
)


def test_default_board_id_is_board_default():
    assert DEFAULT_BOARD_ID == "board-default"


def test_resolve_board_id_returns_default_when_none():
    assert resolve_board_id(None) == DEFAULT_BOARD_ID


def test_resolve_board_id_returns_explicit_when_provided():
    assert resolve_board_id("board-default") == DEFAULT_BOARD_ID


def test_assert_board_id_allowed_passes_for_default():
    assert_board_id_allowed("board-default")  # does not raise


def test_assert_board_id_allowed_passes_for_known_aliases():
    # Multi-board work: any non-empty string is now a valid id. The
    # selector is sourced from Issue.distinct(board_id) at runtime,
    # so we don't need a hard-coded allowlist anymore.
    assert_board_id_allowed("board-dev")
    assert_board_id_allowed("board-staging")
    assert_board_id_allowed("board-demo")
    assert_board_id_allowed("custom-tenant-board")


def test_assert_board_id_allowed_rejects_empty_string():
    with pytest.raises(LookupError):
        assert_board_id_allowed("")


def test_assert_board_id_allowed_rejects_whitespace_only():
    with pytest.raises(LookupError):
        assert_board_id_allowed("   ")


def test_assert_board_id_allowed_rejects_overlong_string():
    with pytest.raises(LookupError):
        assert_board_id_allowed("a" * 65)


def test_assert_board_id_allowed_rejects_non_string():
    with pytest.raises(LookupError):
        assert_board_id_allowed(None)  # type: ignore[arg-type]
