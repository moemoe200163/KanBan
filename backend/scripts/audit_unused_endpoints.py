#!/usr/bin/env python3
"""
Audit for endpoints defined in the backend that no caller uses.

Reads every ``@router.<method>("<path>")`` decorator under
``backend/api/v1/endpoints/`` and every URL literal the frontend
references (``api/v1/...``) under ``src/``. An endpoint is "unused"
when the backend declares it and the frontend never references the
same path. Backend-to-backend callers (one endpoint internally
calling another via ``httpx.AsyncClient``) are not considered.

The output is meant for a CI gate, but the script also supports a
"warn-only" mode for staged cleanups: pass ``--strict`` to fail on
unused endpoints, otherwise the exit is zero and the report is
informational.

Usage:
    python scripts/audit_unused_endpoints.py            # list + summary, exit 0
    python scripts/audit_unused_endpoints.py --strict   # exit 1 if any unused
    python scripts/audit_unused_endpoints.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ENDPOINTS_DIR = BACKEND_DIR / "api" / "v1" / "endpoints"
FRONTEND_DIR = REPO_ROOT / "src"


@dataclass
class Endpoint:
    method: str
    path: str
    file: str
    line: int


def _extract_backend_endpoints() -> list[Endpoint]:
    """Parse every endpoint router file and pull @router.<method>("path") calls."""
    out: list[Endpoint] = []
    for py in ENDPOINTS_DIR.glob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                # We only care about @router.<method>("path", ...) — the
                # ``func`` is an Attribute access on a Name whose value
                # is ``router``. That's the convention in this codebase.
                if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                        and func.value.id == "router"):
                    continue
                if not dec.args:
                    continue
                first = dec.args[0]
                if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue
                out.append(Endpoint(
                    method=func.attr.upper(),
                    path=first.value,
                    file=py.name,
                    line=node.lineno,
                ))
    return out


def _normalize_path(path: str) -> str:
    """Turn a router path like ``/issues/{issue_id}/cycle-reports/{report_id}``
    into a regex that matches any concrete URL with literal segments
    for the placeholders.
    """
    return re.sub(r"\{[^}]+\}", r"[^/]+", path)


def _extract_frontend_paths() -> set[tuple[str, str]]:
    """Find every backend path the frontend references.

    The frontend builds URLs in one of two patterns:

    - ``${apiBase}/board`` — apiBase already ends in ``/api/v1``
      (``http://localhost:8000/api/v1`` from nuxt.config.ts), so
      the path is the literal segment after ``apiBase}``.
    - ``/api/v1/board`` — a fully literal URL, typically in the
      e2e helpers or constants.

    We collect every literal path segment following either
    pattern, drop template-literal interpolation (``${...}``),
    and tag it with the HTTP method used at the call site.
    """
    refs: set[tuple[str, str]] = set()
    sources: list[Path] = []
    sources.extend(FRONTEND_DIR.rglob("*.ts"))
    sources.extend(FRONTEND_DIR.rglob("*.vue"))
    sources.extend(FRONTEND_DIR.rglob("*.js"))

    # Match either ``apiBase}/<path>`` (most calls) or the
    # fully-literal ``/api/v1/<path>`` (constants, e2e). The path
    # may contain ``${...}`` placeholders for parameters.
    api_base_pattern = re.compile(
        r"""apiBase\s*\}?[/'`]\s*['"`]?([A-Za-z0-9_\-/${}\.]+)['"`]"""
    )
    api_v1_pattern = re.compile(
        r"""/api/v1/([A-Za-z0-9_\-/${}\.]+)['"`]"""
    )

    for src in sources:
        text = src.read_text(encoding="utf-8", errors="ignore")
        for m in api_base_pattern.finditer(text):
            _collect(text, m, refs, leading_slash=False)
        for m in api_v1_pattern.finditer(text):
            _collect(text, m, refs, leading_slash=True)

    return refs


def _collect(text: str, m: re.Match, refs: set[tuple[str, str]], *, leading_slash: bool) -> None:
    """Trim a matched URL down to its static prefix and record it."""
    raw = m.group(1)
    # Drop anything past a template-literal interpolation marker.
    static = raw.split("${", 1)[0]
    static = static.rstrip("/")
    if not static:
        return
    method = _guess_method(text, m.start())
    prefix = "/" if leading_slash else ""
    refs.add((method, prefix + static))


def _guess_method(text: str, offset: int) -> str:
    """Heuristic: look backwards from the URL for the closest ``$fetch.`` or
    ``fetch(`` to decide which HTTP method the URL is being used with.
    Defaults to GET.
    """
    window = text[max(0, offset - 240):offset]
    # Look for an explicit method indicator in the call options
    # (e.g. ``method: 'PATCH'`` or ``$fetch.patch(``) closest to
    # the URL literal.
    method_call = re.search(
        r"\$fetch\.(get|post|put|patch|delete)\b|\bmethod\s*:\s*['\"](get|post|put|patch|delete)['\"]",
        window,
        re.IGNORECASE,
    )
    if method_call:
        verb = method_call.group(1) or method_call.group(2)
        return verb.upper()
    return "GET"


def _is_referenced(endpoint: Endpoint, refs: set[tuple[str, str]]) -> bool:
    """An endpoint is referenced when the frontend mentions a path that
    could be the same route (modulo ``{param}`` placeholders) under
    the same method.

    Matching: a frontend path literal like ``/boards/board-default/issues``
    matches any router path that *starts* with the same literal segment
    sequence, after we've collapsed ``{param}`` placeholders to
    wildcards on the router side. So:
        router:  /boards/{board_id}/issues/{issue_id}/handoffs
        frontend: /boards/board-default/issues/<id>/handoffs
    match — because the static prefix ``/boards/board-default/issues``
    lines up with the first two segments of the router's normalised
    form, and any deeper segments on the router side are params
    (one or more) and the frontend may or may not have spelled them
    out.
    """
    needle = _normalize_path(endpoint.path).lstrip("/")
    segments_needle = needle.split("/")
    for method, path in refs:
        if method != endpoint.method:
            continue
        frontend = path.lstrip("/")
        if not frontend:
            continue
        segments_fe = frontend.split("/")
        # Static prefix match: every segment the frontend mentioned
        # must equal the corresponding segment of the normalised
        # router path.
        match = True
        for i, seg in enumerate(segments_fe):
            if i >= len(segments_needle):
                match = False
                break
            if segments_needle[i] != seg:
                match = False
                break
        if match:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any unused endpoints are found (CI gate)",
    )
    args = parser.parse_args()

    endpoints = _extract_backend_endpoints()
    refs = _extract_frontend_paths()

    by_method: dict[str, list[Endpoint]] = defaultdict(list)
    for ep in endpoints:
        by_method[ep.method].append(ep)

    unused = [ep for ep in endpoints if not _is_referenced(ep, refs)]
    used = [ep for ep in endpoints if ep not in unused]

    summary = {
        "endpoint_total": len(endpoints),
        "endpoint_used": len(used),
        "endpoint_unused": len(unused),
        "by_method": {m: len(eps) for m, eps in by_method.items()},
        "unused": [
            {"method": ep.method, "path": ep.path, "file": ep.file, "line": ep.line}
            for ep in sorted(unused, key=lambda e: (e.path, e.method))
        ],
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"checked {len(endpoints)} backend endpoints "
            f"({len(refs)} distinct frontend path references)"
        )
        print(f"  used:   {len(used)}")
        print(f"  unused: {len(unused)}")
        print(f"  by method: {', '.join(f'{m}={c}' for m, c in summary['by_method'].items())}")
        if unused:
            print("\nUnused endpoints (defined but never called from src/):")
            for ep in sorted(unused, key=lambda e: (e.path, e.method)):
                print(f"  {ep.method:6s} {ep.path:50s}  {ep.file}:{ep.line}")

    if args.strict and unused:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
