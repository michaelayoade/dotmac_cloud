from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from dotmac_cloud.database import DatabaseRuntime
from dotmac_cloud.models import AdapterReceiptRow
from dotmac_cloud.receipt_store import ReceiptConflict, SqlAlchemyReceiptLedger
from dotmac_cloud.receipts import (
    AdapterReceipt,
    FactKey,
    ReceiptOutcome,
    SourceFact,
)

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)


@pytest.fixture
def runtime(app_database_url: str) -> Generator[DatabaseRuntime, None, None]:
    installed = DatabaseRuntime(app_database_url)
    yield installed
    installed.dispose()


def _receipt(
    *,
    source_ref: str = "invoice-1",
    fingerprint: str = "sha256:first",
    outcome: ReceiptOutcome = ReceiptOutcome.APPLIED,
    observed_at: datetime = NOW,
) -> AdapterReceipt:
    return AdapterReceipt(
        adapter="billing-exposure-to-collections",
        fact=SourceFact(
            key=FactKey(source_owner="billing", source_ref=source_ref),
            source_version=1,
            fingerprint=fingerprint,
        ),
        outcome=outcome,
        observed_at=observed_at,
    )


def test_receipt_replay_is_deduplicated_and_conflicting_content_is_refused(
    runtime: DatabaseRuntime,
) -> None:
    original = _receipt()
    replay = _receipt(observed_at=NOW + timedelta(minutes=1))

    with runtime.tenant_session(TENANT_A) as db:
        SqlAlchemyReceiptLedger(db, TENANT_A).append(original)
    with runtime.tenant_session(TENANT_A) as db:
        SqlAlchemyReceiptLedger(db, TENANT_A).append(replay)

    with runtime.tenant_session(TENANT_A) as db:
        ledger = SqlAlchemyReceiptLedger(db, TENANT_A)
        rows = ledger.receipts_for(original.adapter, (original.fact.key,))
        assert rows == (original,)

    with (
        pytest.raises(ReceiptConflict, match="different fingerprint"),
        runtime.tenant_session(TENANT_A) as db,
    ):
        SqlAlchemyReceiptLedger(db, TENANT_A).append(
            _receipt(fingerprint="sha256:changed")
        )


def test_transaction_boundary_rolls_back_receipt_with_its_failed_effect(
    runtime: DatabaseRuntime,
) -> None:
    receipt = _receipt(source_ref="rolled-back")

    with (
        pytest.raises(RuntimeError, match="effect failed"),
        runtime.tenant_session(TENANT_A) as db,
    ):
        SqlAlchemyReceiptLedger(db, TENANT_A).append(receipt)
        raise RuntimeError("effect failed")

    with runtime.tenant_session(TENANT_A) as db:
        assert (
            SqlAlchemyReceiptLedger(db, TENANT_A).receipts_for(
                receipt.adapter, (receipt.fact.key,)
            )
            == ()
        )


def test_rls_isolates_reads_and_refuses_cross_tenant_writes(
    runtime: DatabaseRuntime,
) -> None:
    for tenant_id, source_ref in ((TENANT_A, "a"), (TENANT_B, "b")):
        with runtime.tenant_session(tenant_id) as db:
            SqlAlchemyReceiptLedger(db, tenant_id).append(
                _receipt(source_ref=source_ref)
            )

    with runtime.tenant_session(TENANT_A) as db:
        visible = tuple(db.scalars(select(AdapterReceiptRow.source_ref)))
    with runtime.tenant_session(TENANT_B) as db:
        visible_b = tuple(db.scalars(select(AdapterReceiptRow.source_ref)))

    assert visible == ("a",)
    assert visible_b == ("b",)

    with (
        pytest.raises(DBAPIError),
        runtime.tenant_session(TENANT_A) as db,
    ):
        db.add(
            AdapterReceiptRow.from_receipt(
                tenant_id=TENANT_B,
                receipt=_receipt(source_ref="forged"),
            )
        )
        db.flush()


def test_missing_tenant_scope_fails_closed(app_database_url: str) -> None:
    engine = create_engine(app_database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.count(AdapterReceiptRow.id))) == 0
            assert connection.scalar(
                text("SELECT current_setting('app.current_tenant', true)")
            ) in {
                None,
                "",
            }
    finally:
        engine.dispose()


def test_live_catalog_enforces_force_rls_and_append_only_role(
    admin_engine: Engine,
) -> None:
    with admin_engine.connect() as connection:
        rls = connection.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' "
                "AND c.relname = 'cloud_adapter_receipts'"
            )
        ).one()
        role = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = 'app_user'"
            )
        ).one()
        privileges = {
            privilege: connection.scalar(
                text(
                    "SELECT has_table_privilege("
                    "'app_user', 'public.cloud_adapter_receipts', :privilege)"
                ),
                {"privilege": privilege},
            )
            for privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
            )
        }

    assert tuple(rls) == (True, True)
    assert tuple(role) == (False, False)
    assert privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
        "REFERENCES": False,
        "TRIGGER": False,
    }
