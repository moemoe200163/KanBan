"""Scope guard — tripwire against out-of-scope work patterns.

This is NOT a substitute for code review. It refuses handoff payloads that
contain keys associated with archived security work, so the archived work
cannot easily leak back into the mainline through the Kanban Protocol API.
"""
from typing import Any, Iterable, Set

DENIED_PAYLOAD_KEYS: Set[str] = {
    "sandbox_egress",
    "iptables_rules",
    "admin_keys",
    "pentest_findings",
}


class ScopeDeniedError(Exception):
    """Raised when a payload contains keys reserved for out-of-scope work."""

    def __init__(self, offending_keys: Iterable[str]):
        self.offending_keys = sorted(set(offending_keys))
        super().__init__(
            "Scope denied: payload contains reserved keys "
            f"{self.offending_keys}"
        )


def find_denied_keys(payload: Any) -> Set[str]:
    """Recursively walk a JSON-shaped payload and return any denied keys."""
    found: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in DENIED_PAYLOAD_KEYS:
                    found.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def check_payload(payload: Any) -> None:
    """Raise ``ScopeDeniedError`` if the payload contains any denied key."""
    denied = find_denied_keys(payload)
    if denied:
        raise ScopeDeniedError(denied)
