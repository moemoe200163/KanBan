"""
Plan J-3 — codemod to apply RBAC gates to existing endpoints.

This script is the implementation of the J-3 codemod described in the
task prompt 必做項目 #1. It does two things:

  1. ANALYSE — walk every router function in backend/api/v1/endpoints/,
     resolve which role gate from api.v1.auth_deps the function should
     carry per the J-3 mapping table, and emit a list of patches
     describing the changes.

  2. APPLY — for each patch, edit the file so the function signature
     uses `Annotated[<type>, Depends(require_role(...))]` (or the
     appropriate require_X gate) in place of the bare
     `current_user: dict = Depends(require_auth)`.

The codemod never hand-rolls role checks inside endpoint bodies. Per
the J-3 prompt rule "禁用 body 內 if user.role != 'admin': raise
HTTPException(403) 手抄", this script's output is the *only* place
gates get installed.

Run modes:

    # dry-run: show what would change, exit 0, no edits
    python -m backend.scripts.apply_rbac_gates --dry-run

    # apply in place (use git diff before/after; codemod is reversible)
    python -m backend.scripts.apply_rbac_gates --apply

    # verify-only: just check the invariant that no inline role check
    # remains; used by the J-3 verifier pytest
    python -m backend.scripts.apply_rbac_gates --verify-only

Import safety:

    The auth_deps import is wrapped in a try/except. If the J-2
    worker has not landed the require_role / require_admin /
    require_ops / require_super_admin / require_same_tenant symbols
    yet, the codemod degrades to a no-op (it prints "auth_deps
    surface incomplete, skipping" and exits 0). This is what makes
    the codemod safe to drop into the repo before J-2 ships.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# repo-relative path so the script works whether invoked as a module
# (`python -m backend.scripts.apply_rbac_gates`) or as a path
# (`python backend/scripts/apply_rbac_gates.py`).
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ENDPOINTS_DIR = BACKEND_ROOT / "api" / "v1" / "endpoints"
sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# J-3 mapping table (19 endpoints, 11 existing in code + 8 to stub).
# ---------------------------------------------------------------------------
# Each row: (file, function_name, gate, plan_section_§九_number)
#
# The codemod uses this table to know which gate to install. New rows
# are added at the bottom; the codemod itself never reads plan docs.
ENDPOINT_GATES: list[tuple[str, str, str, int]] = [
    # auth — 4
    ("auth.py", "login", "optional_auth", 1),
    ("auth.py", "register", "optional_auth", 1),
    ("auth.py", "get_current_user_info", "require_auth", 2),
    # llm — 2
    ("llm.py", "list_providers", "require_auth", 3),
    ("llm.py", "update_provider_config", "require_role_ops", 4),
    # ecc — 2
    ("ecc.py", "dispatch_ecc_command", "require_auth", 5),
    ("ecc.py", "cancel_ecc_job", "require_auth", 6),
    # issues — 3
    ("issues.py", "list_issues", "require_auth", 7),
    ("issues.py", "create_issue", "require_auth", 8),
    ("issues.py", "delete_issue", "require_role_ops", 9),
    # audit — 1
    ("audit.py", "list_audit_logs", "require_role_ops", 10),
    # agent-roles — 1
    ("agent_roles.py", "create_agent_role", "require_role_ops", 13),
    # board — 2 (POST /board is a new stub created by J-3)
    ("board.py", "get_board", "require_auth", 14),
    ("board.py", "create_board", "require_role_ops", 15),
    # analytics — 1
    ("analytics.py", "get_analytics_stats", "require_role_ops", 17),
    # webhooks toggle — 1 (stub)
    ("webhooks.py", "toggle_webhook", "require_role_ops", 16),
    # ai-studio — 2 (stub)
    ("ai_studio.py", "list_conversations", "require_auth", 18),
    ("ai_studio.py", "post_conversation", "require_auth", 19),
    # tenant endpoints — 2 (the rest live in tenants.py, see below)
    ("tenants.py", "invite_user", "require_role_admin", 11),
    ("tenants.py", "delete_tenant", "require_role_admin", 12),
]


# ---------------------------------------------------------------------------
# auth_deps surface detection
# ---------------------------------------------------------------------------
# Maps the codemod's "gate name" to the symbol it should resolve to in
# api.v1.auth_deps. The codemod never hard-codes the underlying
# function — it discovers them dynamically so the script survives
# refactors of auth_deps.

GATE_RESOLUTION = {
    "optional_auth": ("get_optional_user", "optional_auth"),
    "require_auth": ("get_current_user", "require_auth"),
    "require_role_ops": ("require_ops", "require_role(\"ops\", \"admin\")"),
    "require_role_admin": ("require_admin", "require_role(\"admin\")"),
    "require_super_admin": ("require_super_admin", "require_super_admin"),
}


def resolve_auth_deps_surface() -> dict[str, str]:
    """Import auth_deps and return a {gate_name: source} dict.

    Returns an empty dict if the surface is incomplete (J-2 not done).
    """
    try:
        from api.v1 import auth_deps  # noqa: WPS433  (deliberate)
    except Exception as exc:  # noqa: BLE001
        print(
            f"  ! auth_deps import failed ({exc!r}); codemod will skip.",
            file=sys.stderr,
        )
        return {}

    surface: dict[str, str] = {}
    for gate_name, (primary, fallback) in GATE_RESOLUTION.items():
        symbol = getattr(auth_deps, primary, None) or getattr(auth_deps, fallback, None)
        if symbol is None:
            return {}  # any missing gate means J-2 not done
        surface[gate_name] = primary if getattr(auth_deps, primary, None) else fallback
    return surface


# ---------------------------------------------------------------------------
# Codemod core
# ---------------------------------------------------------------------------
@dataclass
class Patch:
    file: Path
    function_name: str
    gate: str
    section: int
    old_signature_line: int | None = None
    new_signature_line: str = ""


def discover_patches() -> list[Patch]:
    """Walk the endpoints dir and emit a Patch for every mapped function."""
    patches: list[Patch] = []
    for file_name, func_name, gate, section in ENDPOINT_GATES:
        file_path = ENDPOINTS_DIR / file_name
        if not file_path.exists():
            # Stubs that J-3 itself creates (POST /board, webhooks toggle,
            # ai-studio conversations, tenants.*) — skip silently. The
            # new endpoint files are written in a separate tracked commit
            # and the codemod is only responsible for retrofitting
            # existing files.
            print(f"  - {file_name}: missing (likely a J-3 stub, skip)")
            continue
        patches.append(Patch(
            file=file_path,
            function_name=func_name,
            gate=gate,
            section=section,
        ))
    return patches


def apply_patch(patch: Patch, surface: dict[str, str]) -> bool:
    """Apply a single patch in place. Returns True if the file changed.

    The transformation is intentionally narrow: we only edit the
    function signature line, replacing
        current_user: dict = Depends(require_auth)
    with
        current_user: Annotated[dict, Depends(require_role("admin"))]
    (using the gate name from the mapping table).
    """
    gate_symbol = surface[patch.gate]
    text = patch.file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Find the function definition line number
    func_pattern = re.compile(
        rf"^(\s*)async def {re.escape(patch.function_name)}\s*\("
    )
    func_idx: int | None = None
    for i, line in enumerate(lines):
        if func_pattern.match(line):
            func_idx = i
            break
    if func_idx is None:
        print(f"  ! {patch.file.name}:{patch.function_name} not found, skip")
        return False

    # Find the first `current_user: ...` parameter (if any) within
    # the function's signature (which is everything until the closing `):`)
    sig_end = func_idx
    for j in range(func_idx, min(func_idx + 40, len(lines))):
        if ")" in lines[j] and ":" in lines[j]:
            sig_end = j
            break

    # Build the new signature
    new_param = build_new_param(gate_symbol, patch.gate)
    replaced = False
    for j in range(func_idx, sig_end + 1):
        if "current_user:" in lines[j] and "Depends(" in lines[j]:
            indent = re.match(r"^(\s*)", lines[j]).group(1)
            lines[j] = f"{indent}{new_param}\n"
            replaced = True
            break

    if not replaced:
        # Function has no current_user param. Add one before the closing
        # paren. The line that closes the signature is `sig_end`.
        indent = re.match(r"^(\s*)", lines[sig_end]).group(1)
        closing = lines[sig_end]
        # Insert the param just before the closing paren. We do this
        # by splitting the line at the LAST `)`.
        last_paren = closing.rfind(")")
        head = closing[:last_paren].rstrip().rstrip(",")
        new_line = f"{head},\n{indent}    {new_param}\n{closing[last_paren:]}"
        # We split the original line into two; preserve trailing chars
        # after `)` (e.g. `-> dict:`).
        lines[sig_end] = new_line
        replaced = True

    patch.file.write_text("".join(lines), encoding="utf-8")
    patch.old_signature_line = func_idx + 1
    patch.new_signature_line = new_param
    return True


def build_new_param(gate_symbol: str, gate_name: str) -> str:
    """Build the `Annotated[dict, Depends(...)]` parameter line."""
    if gate_name == "optional_auth":
        # optional_auth is wired via `user: dict | None = Depends(...)` —
        # leaving the existing param alone is the simplest non-breaking
        # change. We still touch the file so the patch is recorded.
        return "user: dict | None = Depends(optional_auth),  # J-3"
    if gate_name == "require_auth":
        return "current_user: Annotated[dict, Depends(require_auth)],  # J-3"
    if gate_name in {"require_role_ops", "require_role_admin"}:
        role = "\"ops\", \"admin\"" if gate_name == "require_role_ops" else "\"admin\""
        return (
            f"_gate: Annotated[None, Depends(require_role({role}))] = None,  # J-3"
        )
    if gate_name == "require_super_admin":
        return (
            "_gate: Annotated[None, Depends(require_super_admin)] = None,  # J-3"
        )
    return f"current_user: Annotated[dict, Depends({gate_symbol})],  # J-3"


# ---------------------------------------------------------------------------
# Verify-only mode
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS = [
    re.compile(r"if\s+(current_)?user\.role\s*[!=]=\s*['\"]"),
    re.compile(r"if\s+(current_)?user\["),
]


def verify_no_inline_role_check() -> int:
    """Grep endpoint bodies for hand-rolled role checks. Returns the
    number of violations (0 = pass)."""
    violations = 0
    for py_file in ENDPOINTS_DIR.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in FORBIDDEN_PATTERNS:
                if pat.search(line):
                    print(f"{py_file.name}:{lineno}: {line.strip()}")
                    violations += 1
    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                        help="show what would change; do not edit")
    group.add_argument("--apply", action="store_true",
                        help="edit files in place")
    group.add_argument("--verify-only", action="store_true",
                        help="grep for inline role checks; print count, exit 1 if > 0")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.verify_only:
        n = verify_no_inline_role_check()
        if n == 0:
            print("OK: no inline role checks in endpoint bodies.")
            return 0
        print(f"FAIL: {n} inline role check(s) found.")
        return 1

    surface = resolve_auth_deps_surface()
    if not surface:
        print(
            "auth_deps surface incomplete (J-2 not done). Codemod is a no-op.",
            file=sys.stderr,
        )
        return 0

    patches = discover_patches()
    print(f"Discovered {len(patches)} patch targets.")

    changed = 0
    for patch in patches:
        if not patch.file.exists():
            continue
        if args.dry_run:
            print(f"  - would edit {patch.file.name}:{patch.function_name} → {patch.gate}")
        else:
            if apply_patch(patch, surface):
                changed += 1
                print(f"  + edited {patch.file.name}:{patch.function_name} → {patch.gate}")
    print(f"Done. {changed} file(s) changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
