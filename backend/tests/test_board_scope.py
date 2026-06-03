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
    assert resolve_board_id("board-default") == "board-default"


def test_assert_board_id_allowed_passes_for_default():
    assert_board_id_allowed("board-default")  # does not raise


def test_assert_board_id_allowed_raises_for_unknown():
    with pytest.raises(LookupError):
        assert_board_id_allowed("some-other-board")
