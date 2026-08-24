from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

from sqlalchemy import Table, UniqueConstraint

from dotmac_cloud.models import AdapterReceiptRow

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "dotmac_cloud"
MIGRATION = REPO / "alembic" / "versions" / "ca_0001_adapter_receipts.py"


def _session_authority_calls(text: str) -> tuple[str, ...]:
    tree = ast.parse(text)
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else ""
        )
        if name in {"create_engine", "sessionmaker"}:
            names.append(name)
    return tuple(sorted(names))


def test_database_module_is_the_only_runtime_session_authority() -> None:
    findings = {
        str(path.relative_to(REPO)): _session_authority_calls(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(SRC.rglob("*.py"))
        if _session_authority_calls(path.read_text(encoding="utf-8"))
    }

    assert findings == {
        "src/dotmac_cloud/database.py": ("create_engine", "sessionmaker")
    }


def test_session_authority_detector_has_a_sensitivity_proof() -> None:
    assert _session_authority_calls("db = sessionmaker(bind=create_engine(url))") == (
        "create_engine",
        "sessionmaker",
    )


def test_receipt_persistence_never_owns_transaction_completion() -> None:
    tree = ast.parse(
        (SRC / "receipt_store.py").read_text(encoding="utf-8"),
        filename="receipt_store.py",
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback"}
    }

    assert calls == set()


def test_receipt_model_is_tenant_scoped_and_unique_per_exact_fact() -> None:
    table = cast(Table, AdapterReceiptRow.__table__)
    tenant_id = table.c.tenant_id
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert tenant_id.nullable is False
    assert (
        "tenant_id",
        "adapter",
        "source_owner",
        "source_ref",
        "source_version",
    ) in unique_columns


def test_receipt_migration_creates_rls_policy_and_append_only_grants_together() -> None:
    text = MIGRATION.read_text(encoding="utf-8").lower()

    assert "create_table(" in text
    assert "enable row level security" in text
    assert "force row level security" in text
    assert "create policy" in text
    assert "grant select, insert" in text
    assert "revoke update, delete, truncate, references, trigger" in text
