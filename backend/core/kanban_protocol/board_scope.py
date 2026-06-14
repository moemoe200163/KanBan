"""Board isolation helpers.

Boards are derived from ``Issue.distinct(board_id)`` — there is no
dedicated ``boards`` table. The selector in the UI lists whatever the
issues carry, so any non-empty string is a valid board id. The default
``DEFAULT_BOARD_ID`` is what we fall back to when an endpoint is called
without an explicit ``board_id``.

The allowlist was relaxed from a hard-coded single-entry set to "any
non-empty string" so the new ``GET /api/v1/boards`` endpoint and the
sidebar selector work end-to-end. The default-id constant and the
``resolve_board_id`` helper are unchanged so existing callers stay
green.
"""
from typing import Optional

DEFAULT_BOARD_ID = "board-default"


def resolve_board_id(explicit: Optional[str]) -> str:
    """Return the board id to use for a request.

    An unspecified board id falls back to ``DEFAULT_BOARD_ID``.
    """
    return explicit or DEFAULT_BOARD_ID


def assert_board_id_allowed(board_id: str) -> None:
    """Validate that ``board_id`` is a syntactically acceptable board id.

    Boards are not centrally registered — they are inferred from
    ``Issue.distinct(board_id)``. The only contract is that the id is
    a non-empty trimmed string and at most 64 characters (matching
    the ``board_id`` column width on every model that stores it).
    """
    if not isinstance(board_id, str):
        raise LookupError(f"Board id must be a string, got {type(board_id).__name__}")
    candidate = board_id.strip()
    if not candidate:
        raise LookupError("Board id must be a non-empty string")
    if len(candidate) > 64:
        raise LookupError(
            f"Board id '{board_id[:32]}...' exceeds 64 characters"
        )
