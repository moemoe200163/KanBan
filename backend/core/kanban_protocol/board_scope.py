"""Board isolation helpers.

In MVP, only the default board is allowed. This module centralizes the
rule so future multi-board work only needs to swap the implementation.
"""
from typing import Optional

DEFAULT_BOARD_ID = "board-default"
_KNOWN_BOARD_IDS = frozenset({DEFAULT_BOARD_ID})


def resolve_board_id(explicit: Optional[str]) -> str:
    """Return the board id to use for a request.

    In MVP, an unspecified board id falls back to ``DEFAULT_BOARD_ID``.
    """
    return explicit or DEFAULT_BOARD_ID


def assert_board_id_allowed(board_id: str) -> None:
    """Raise ``LookupError`` if ``board_id`` is not allowed in MVP."""
    if board_id not in _KNOWN_BOARD_IDS:
        raise LookupError(
            f"Board '{board_id}' is not available in MVP. "
            f"Allowed: {sorted(_KNOWN_BOARD_IDS)}"
        )
