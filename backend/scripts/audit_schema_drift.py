#!/usr/bin/env python3
"""
Schema drift auditor for the kanban backend.

Compares the SQLAlchemy models in ``backend/db/models.py`` against the
actual columns present on the running database. Catches the failure
mode where a model field is added or renamed but no Alembic migration
is written to match — leaving ORM queries to explode at runtime with
``UndefinedColumnError`` on the first request that touches the table.

This script is intentionally import-free: it parses ``models.py`` with
the ``ast`` module instead of importing it. Importing ``db.models``
would also instantiate the application's async engine, which fails in
environments that only have a sync driver. For an audit we only need
to read static metadata; we never run application code.

Usage:
    python scripts/audit_schema_drift.py            # full audit, exit 1 on drift
    python scripts/audit_schema_drift.py --json     # machine-readable output
    python scripts/audit_schema_drift.py --table=issue_artifacts  # one table
    AUDIT_DATABASE_URL=postgres://... python scripts/audit_schema_drift.py

Run this in CI alongside the test suite. A non-zero exit code means
"there is drift, do not deploy".
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
MODELS_PATH = BACKEND_DIR / "db" / "models.py"

# Read the database URL directly from the environment. We never
# touch the application's async engine — see module docstring.
_DATABASE_URL = os.getenv(
    "AUDIT_DATABASE_URL",
    os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://devflow:devflow_secret@postgres:5432/devflow",
    ),
)


@dataclass
class Drift:
    table: str
    kind: str          # "missing_in_db" | "extra_in_db" | "table_missing"
    column: str
    detail: str

    def __str__(self) -> str:
        return f"  [{self.kind:>15}] {self.table}.{self.column}  ({self.detail})"


def _first_call_arg_name(node: ast.AST) -> str | None:
    """Return the source-text name of the first argument to a Call node.

    Used to extract the underlying SQLAlchemy type from ``Column(TYPE, ...)``
    assignments. Handles simple names (``String``), attribute access
    (``postgresql.JSONB``), call wrappers (``String(64)``), and the
    most common alias form (``sa.String``). Returns ``None`` for
    things we don't recognise.
    """
    if not isinstance(node, ast.Call):
        return None
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute):
        return first.attr
    if isinstance(first, ast.Call):
        # ``String(64)`` -> unwrap to ``String``.
        return _first_call_arg_name(first) or ast.unparse(first.func)
    return None


def _coarse_type(type_expr: str) -> str:
    """Strip length/precision args and return a coarse upper-cased label."""
    head = type_expr.split("(")[0].strip()
    # Map common SQLAlchemy types to their SQL-family name so the
    # comparison is "JSON == JSON" rather than "JSON == JSONB".
    aliases = {
        "JSONB": "JSON",
        "JSON": "JSON",
        "VARCHAR": "STRING",
        "String": "STRING",
        "TEXT": "TEXT",
        "Text": "TEXT",
        "DATETIME": "DATETIME",
        "DateTime": "DATETIME",
        "TIMESTAMP": "DATETIME",
        "Timestamp": "DATETIME",
        "INTEGER": "INTEGER",
        "Integer": "INTEGER",
        "INT": "INTEGER",
        "BOOLEAN": "BOOLEAN",
        "Boolean": "BOOLEAN",
        "BIGINT": "INTEGER",
        "BigInteger": "INTEGER",
        "FLOAT": "FLOAT",
        "Float": "FLOAT",
        "LARGEBINARY": "BINARY",
        "LargeBinary": "BINARY",
        "BYTEA": "BINARY",
    }
    return aliases.get(head, head.upper())


def _parse_model_columns() -> dict[str, dict[str, str]]:
    """Parse ``models.py`` and return ``{table_name: {column_name: type}}``.

    The script only handles the common patterns we actually use in
    this codebase — ``__tablename__ = "..."`` followed by ``name = Column(TYPE, ...)``
    assignments. Anything more exotic is skipped (and would have been
    a problem for SQLAlchemy too).
    """
    source = MODELS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    result: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        table_name: str | None = None
        columns: dict[str, str] = {}
        for stmt in node.body:
            # Both ``name = Column(...)`` (un-annotated) and
            # ``name: type = Column(...)`` (annotated) are valid
            # SQLAlchemy declarative styles. Handle both.
            target_name: str | None = None
            rhs: ast.AST | None = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                tgt = stmt.targets[0]
                if isinstance(tgt, ast.Name):
                    target_name = tgt.id
                    rhs = stmt.value
                    # Special case: __tablename__ = "x" — store the
                    # table name, don't treat as a column.
                    if target_name == "__tablename__" and isinstance(rhs, ast.Constant) and isinstance(rhs.value, str):
                        table_name = rhs.value
                        continue
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target_name = stmt.target.id
                rhs = stmt.value
            else:
                continue

            if target_name is None or rhs is None:
                continue
            if target_name.startswith("_"):
                continue
            if target_name in {"to_dict", "__table_args__", "__mapper_args__"}:
                continue

            type_str = ast.unparse(rhs)
            # Heuristic: a column assignment is a ``Column(...)`` call.
            # The space matters — ``Mapped[Column(...)]`` is not a column.
            if "Column(" in type_str and not type_str.startswith("Mapped"):
                # Pull the first positional argument out of ``Column(TYPE, ...)``
                # to capture the actual type name, not the wrapper.
                inner = _first_call_arg_name(rhs)
                columns[target_name] = _coarse_type(inner) if inner else _coarse_type(type_str)
        if table_name:
            result[table_name] = columns
    return result


def _reflect_table(sync_engine, table_name: str) -> dict[str, str]:
    """Return ``{column_name: coarse_type}`` for the live database."""
    import sqlalchemy as sa
    insp = sa.inspect(sync_engine)
    if not insp.has_table(table_name):
        return {}
    return {
        col["name"]: _coarse_type(str(col["type"]))
        for col in insp.get_columns(table_name)
    }


def audit(table_filter: str | None = None) -> tuple[list[Drift], list[str]]:
    """Compare parsed model columns against the live database."""
    import sqlalchemy as sa

    sync_url = _DATABASE_URL
    if sync_url.startswith("postgresql+asyncpg://"):
        sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    elif sync_url.startswith("sqlite+aiosqlite:///"):
        sync_url = sync_url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)

    sync_engine = sa.create_engine(sync_url, future=True)
    drifts: list[Drift] = []
    checked: list[str] = []

    try:
        all_models = _parse_model_columns()
        for table_name in sorted(all_models):
            if table_filter and table_name != table_filter:
                continue
            checked.append(table_name)

            model_cols = all_models[table_name]
            db_cols = _reflect_table(sync_engine, table_name)

            if not db_cols:
                drifts.append(Drift(
                    table=table_name,
                    kind="table_missing",
                    column="*",
                    detail="no such table in the live database — run alembic upgrade head",
                ))
                continue

            model_set = set(model_cols)
            db_set = set(db_cols)

            for missing in sorted(model_set - db_set):
                drifts.append(Drift(
                    table=table_name,
                    kind="missing_in_db",
                    column=missing,
                    detail=f"model declares {model_cols[missing]} but DB has no such column",
                ))

            for extra in sorted(db_set - model_set):
                drifts.append(Drift(
                    table=table_name,
                    kind="extra_in_db",
                    column=extra,
                    detail=f"DB column not referenced in the model — left over from a previous migration?",
                ))

            # Type mismatch is informational, not a blocker. The DB
            # is the source of truth at runtime, and adding a
            # ``length``/``precision`` change to a model without a
            # migration is harmless if the DB is the looser type.
            for col in model_set & db_set:
                if model_cols[col] != db_cols[col]:
                    drifts.append(Drift(
                        table=table_name,
                        kind="type_mismatch",
                        column=col,
                        detail=f"model says {model_cols[col]} but DB has {db_cols[col]}",
                    ))
    finally:
        sync_engine.dispose()

    return drifts, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of human-readable text")
    parser.add_argument("--table", help="audit a single table by name")
    args = parser.parse_args()

    try:
        drifts, checked = audit(args.table)
    except Exception as exc:  # pragma: no cover - top-level guard
        print(f"audit aborted: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "tables_checked": checked,
            "drift": [asdict(d) for d in drifts],
        }, indent=2))
    else:
        print(f"checked {len(checked)} table(s): {', '.join(checked) or '(none)'}")
        if not drifts:
            print("\nOK — no model/migration drift detected.")
        else:
            print(f"\nFOUND {len(drifts)} drift item(s):")
            for d in drifts:
                print(str(d))
            print(
                "\nFix: write an Alembic migration that aligns the DB with the model, "
                "or rename the model column to match the DB. Do not deploy until clean."
            )

    return 1 if drifts else 0

    # Unreachable — kept for clarity that the function returns an int.
    return 0


if __name__ == "__main__":
    sys.exit(main())
