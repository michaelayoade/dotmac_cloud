from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from dotmac_kernel.idempotency import IdempotencyConflict
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from dotmac_cloud.database import DatabaseRuntime
from dotmac_cloud.models import AdapterReceiptRow
from dotmac_cloud.receipt_store import RECEIPT_SCOPE, SqlAlchemyReceiptLedger
from dotmac_cloud.receipts import (
    AdapterReceipt,
    FactKey,
    ReceiptOutcome,
    SourceFact,
)

# Kept in step with `conftest.py`, which seeds these two tenants: `tests` is not
# an importable package, so the canary states its own subjects and the seeding
# fixture states the same two. `test_the_seeded_tenants_match_the_canaries`
# fails if they ever drift.
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

    # The refusal is now the KERNEL's verdict. Cloud supplies the identity and
    # a digest of what it handled; whether a returning key carries the same
    # request is decided in one place fleet-wide.
    with (
        pytest.raises(IdempotencyConflict, match="different request"),
        runtime.tenant_session(TENANT_A) as db,
    ):
        SqlAlchemyReceiptLedger(db, TENANT_A).append(
            _receipt(fingerprint="sha256:changed")
        )

    # A changed OUTCOME for the same fact version is divergence too, not a
    # duplicate: an adapter that already acted cannot un-decide.
    with (
        pytest.raises(IdempotencyConflict, match="different request"),
        runtime.tenant_session(TENANT_A) as db,
    ):
        SqlAlchemyReceiptLedger(db, TENANT_A).append(
            _receipt(outcome=ReceiptOutcome.REFUSED)
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


def test_the_seeded_tenants_match_the_canaries(admin_engine: Engine) -> None:
    """The seeding fixture and this module must name the same two tenants.

    `idempotency_records.tenant_id` is a FOREIGN KEY to `tenants`, so a canary
    whose tenant was never seeded fails deep inside a flush with a constraint
    error that reads like a product defect. This says so directly instead.
    """
    with admin_engine.connect() as connection:
        seeded = set(
            connection.scalars(
                text("SELECT id FROM tenants WHERE id = ANY(:ids)"),
                {"ids": [TENANT_A, TENANT_B]},
            )
        )

    assert seeded == {TENANT_A, TENANT_B}


def test_the_write_path_spends_a_kernel_idempotency_key(
    runtime: DatabaseRuntime,
    admin_engine: Engine,
) -> None:
    """Proof of delegation, not just of behaviour.

    Deduplication could be produced by the receipt table's own unique
    constraint, so an assertion about receipt counts alone would still pass if
    this module quietly kept a second engine. This asserts the KERNEL ledger
    row exists and that a replay spends no second key.
    """
    receipt = _receipt(source_ref="delegated")

    with runtime.tenant_session(TENANT_A) as db:
        SqlAlchemyReceiptLedger(db, TENANT_A).append(receipt)
    with runtime.tenant_session(TENANT_A) as db:
        SqlAlchemyReceiptLedger(db, TENANT_A).append(receipt)

    with admin_engine.connect() as connection:
        ledger = connection.execute(
            text(
                "SELECT scope, operation, status, fingerprint FROM "
                "idempotency_records WHERE tenant_id = :tenant"
            ),
            {"tenant": TENANT_A},
        ).all()
        receipts = connection.scalar(
            text(
                "SELECT count(*) FROM cloud_adapter_receipts "
                "WHERE tenant_id = :tenant"
            ),
            {"tenant": TENANT_A},
        )

    assert len(ledger) == 1
    scope, operation, status, fingerprint = ledger[0]
    assert scope == RECEIPT_SCOPE
    assert operation == f"receipt:{receipt.adapter}"
    assert status == "executed"
    assert fingerprint is not None
    assert receipts == 1
