"""The first commercial hand-off, end to end, on real PostgreSQL.

Subscriptions rates a real contract line; the adapter hands the result to
Billing; Cloud records the receipt. Nothing here is a stand-in for the owners —
both are the exact released artifacts this assembly pins, driven through their
published surfaces.

The five canaries ADR-0030's Cloud programme requires of a composed hand-off:
replay, changed-fingerprint conflict, rollback atomicity, missed-delivery
repair, and cross-tenant isolation.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from dotmac_billing.service import create_billing_account
from dotmac_kernel.cache import TenantScope
from dotmac_kernel.idempotency import IdempotencyConflict
from dotmac_kernel.money import Currency, Money
from dotmac_subscriptions import (
    BillingCadence,
    CadenceAlignment,
    CollectionTiming,
    ContractLineInput,
    EndOfMonthRule,
    ExactAmount,
    IntervalUnit,
    OfferPriceInput,
    OfferPricingMode,
    ProrationPolicy,
    RateBasis,
    SubscriptionVocabularyRegistry,
    TimerCancelResult,
    TimerScheduleResult,
)
from dotmac_subscriptions.commands import (
    GenerateRecurringChargeCommand,
    PublishOfferVersionCommand,
    RecordSubscriptionContractVersionCommand,
)
from dotmac_subscriptions.contracts import RatedObligationOutputV1
from dotmac_subscriptions.service import (
    generate_recurring_charge,
    publish_offer_version,
    record_contract_version,
    unacknowledged_outputs,
)
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dotmac_cloud.adapters.subscriptions_to_billing import (
    ADAPTER_NAME,
    SOURCE_OWNER,
    BillingAccountResolver,
    TaxOutcome,
    apply_rated_obligation,
    drain_rated_obligations,
)
from dotmac_cloud.database import DatabaseRuntime
from dotmac_cloud.receipt_store import SqlAlchemyReceiptLedger
from dotmac_cloud.receipts import FactKey, ReceiptOutcome

NGN = Currency(code="NGN", minor_units=2)
NOW = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
STARTS = datetime(2026, 9, 1, tzinfo=UTC)


class _StubTimer:
    """A durable-timer stand-in.

    `dotmac-durable-timers` is released and NOT composed by this assembly, so a
    real one is deliberately absent. The port is injected, so this substitutes
    for the port rather than for a composed owner — nothing here claims timers
    work, and the dunning slice that composes them will replace it.
    """

    def schedule(
        self,
        db: Session,
        *,
        scope: object,
        contract_line_key: UUID,
        due_at: datetime,
        recorded_at: datetime,
    ) -> TimerScheduleResult:
        return TimerScheduleResult(generation=1, due_at=due_at)

    def cancel(
        self,
        db: Session,
        *,
        scope: object,
        contract_line_key: UUID,
        recorded_at: datetime,
    ) -> TimerCancelResult:
        return TimerCancelResult(canceled=True)


REGISTRY = SubscriptionVocabularyRegistry(
    charge_models={"recurring.flat": "A flat recurring charge"},
    obligation_sources={"service": "A provisioned service"},
)


def _no_tax() -> TaxOutcome:
    return TaxOutcome(
        amount=Money(amount=Decimal("0.00"), currency=NGN),
        not_assessed_reason="no tax owner is composed in this assembly",
    )


def _cadence() -> BillingCadence:
    return BillingCadence(
        rate_basis=RateBasis.per_rate_unit,
        rate_unit=IntervalUnit.month,
        rate_quantity=Decimal("1"),
        service_interval_unit=IntervalUnit.month,
        service_interval_count=1,
        invoice_interval_unit=IntervalUnit.month,
        invoice_interval_count=1,
        collection_timing=CollectionTiming.advance,
        alignment=CadenceAlignment.contract_anniversary,
        timezone_name="Africa/Lagos",
        end_of_month_rule=EndOfMonthRule.clamp_to_month_end,
        proration_policy=ProrationPolicy.actual_calendar_days,
        anchor_day=None,
    )


@pytest.fixture
def runtime(app_database_url: str) -> Generator[DatabaseRuntime, None, None]:
    installed = DatabaseRuntime(app_database_url)
    yield installed
    installed.dispose()


def _new_tenant(admin_engine: Engine) -> UUID:
    tenant_id = uuid4()
    with admin_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :slug)"),
            {"id": tenant_id, "slug": f"canary-{tenant_id.hex[:12]}"},
        )
    return tenant_id


@pytest.fixture
def other_tenant(admin_engine: Engine) -> UUID:
    """A second tenant, for the isolation canary."""
    return _new_tenant(admin_engine)


@pytest.fixture
def fresh_tenant(admin_engine: Engine) -> UUID:
    """A tenant of this test's own.

    `drain_rated_obligations` correctly drains everything the tenant has left
    unacknowledged, including what an earlier canary deliberately refused. That
    is the behaviour under test, so the isolation has to come from the tenant
    rather than from truncating the owners' tables — which would also destroy
    the accumulated state a composed assembly actually runs against.
    """
    tenant_id = uuid4()
    with admin_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :slug)"),
            {"id": tenant_id, "slug": f"canary-{tenant_id.hex[:12]}"},
        )
    return tenant_id


def _seed_subscription(db: Session, scope: TenantScope) -> tuple[UUID, UUID]:
    """Publish an offer, record a contract version, return (version_id, line_key)."""
    source_id = uuid4()
    # A distinct offer code per seed. Subscriptions correctly refuses to publish
    # the same (offer_code, version) twice, and these canaries deliberately do
    # not truncate the owners' tables between tests — a shared database is the
    # condition a composed assembly actually runs in.
    offer_code = f"broadband.basic.{uuid4().hex[:8]}"
    offer = publish_offer_version(
        db,
        PublishOfferVersionCommand(
            scope=scope,
            offer_id=None,
            offer_code=offer_code,
            offer_name="Broadband Basic",
            charge_model_code="recurring.flat",
            pricing_mode=OfferPricingMode.catalog_price,
            version=1,
            prices=(
                OfferPriceInput(
                    price_key="monthly",
                    charge_model_code="recurring.flat",
                    unit_price=ExactAmount(
                        amount=Decimal("10000.00"), currency="NGN", scale=2
                    ),
                    quantity=Decimal("1"),
                ),
            ),
            effective_from=STARTS,
            effective_until=None,
            source_code="service",
            source_id=source_id,
            source_version=1,
            command_id=uuid4(),
        ),
        registry=REGISTRY,
    )
    line_key = uuid4()
    version = record_contract_version(
        db,
        RecordSubscriptionContractVersionCommand(
            scope=scope,
            contract_id=None,
            source_code="service",
            source_id=source_id,
            source_version=1,
            starts_at=STARTS,
            ends_at=None,
            currency="NGN",
            cadence=_cadence(),
            lines=(
                ContractLineInput(
                    contract_line_key=line_key,
                    charge_model_code="recurring.flat",
                    source_code="service",
                    source_id=source_id,
                    source_version=1,
                    description="Broadband Basic",
                    product_link_ref="offer:broadband.basic",
                    quantity=Decimal("1"),
                    unit_price=ExactAmount(
                        amount=Decimal("10000.00"), currency="NGN", scale=2
                    ),
                    offer_version_id=offer.offer_version_id,
                    offer_version=1,
                    entitlement_codes=(),
                ),
            ),
            actor="cloud-canary",
            reason="canary",
            recorded_at=NOW,
            command_id=uuid4(),
            correlation_id=uuid4(),
            idempotency_key=f"canary-{line_key}",
        ),
        registry=REGISTRY,
        timer=_StubTimer(),
    )
    return version.version_id, line_key


def _rate_one_period(
    db: Session, scope: TenantScope, contract_version_id: UUID, line_key: UUID
) -> None:
    generate_recurring_charge(
        db,
        GenerateRecurringChargeCommand(
            scope=scope,
            contract_version_id=contract_version_id,
            contract_line_key=line_key,
            period_index=0,
            generation=1,
            emitted_at=NOW,
            command_id=uuid4(),
            correlation_id=uuid4(),
            coverage=None,
            corrects_occurrence_id=None,
        ),
        registry=REGISTRY,
        timer=_StubTimer(),
    )


def _account(db: Session, scope: TenantScope) -> UUID:
    row = create_billing_account(
        db,
        scope=scope,
        external_account_ref=f"cloud-canary-{uuid4()}",
        currency="NGN",
        minor_units=2,
    )
    return UUID(str(row.id))


def _fixed_account(account_id: UUID) -> BillingAccountResolver:
    """A resolver that always answers with one account."""

    def _resolve(_scope: TenantScope, _output: RatedObligationOutputV1) -> UUID | None:
        return account_id

    return _resolve


def _obligation_count(db: Session, account_id: UUID) -> int:
    """Count obligations for ONE account, not for the whole schema.

    These canaries share a database and deliberately do not truncate the owners'
    tables — a composed assembly runs against accumulated state, and a test that
    only passes on an empty schema proves less. Scoping the count to the account
    this test created is what makes it independent.
    """
    return int(
        db.execute(
            text(
                "SELECT count(*) FROM mod_billing.rated_obligations "
                "WHERE billing_account_id = :account"
            ),
            {"account": account_id},
        ).scalar_one()
    )


def test_the_hand_off_applies_once_and_replays(
    runtime: DatabaseRuntime, fresh_tenant: UUID
) -> None:
    """First drain charges; a second drain must not charge again."""
    scope = TenantScope(tenant_id=fresh_tenant)
    with runtime.tenant_session(fresh_tenant) as db:
        version_id, line_key = _seed_subscription(db, scope)
        _rate_one_period(db, scope, version_id, line_key)
        account_id = _account(db, scope)

    with runtime.tenant_session(fresh_tenant) as db:
        pending = unacknowledged_outputs(db, scope=scope)
        assert len(pending) == 1
        occurrence_id = pending[0].occurrence_id
        outcomes = drain_rated_obligations(
            db,
            scope=scope,
            ledger=SqlAlchemyReceiptLedger(db, fresh_tenant),
            tax_for=lambda _output: _no_tax(),
            resolve_billing_account=lambda _scope, _output: account_id,
            observed_at=NOW,
        )
    assert outcomes == (ReceiptOutcome.APPLIED,)

    with runtime.tenant_session(fresh_tenant) as db:
        assert _obligation_count(db, account_id) == 1
        # Acknowledged, so the owner stops offering it.
        assert unacknowledged_outputs(db, scope=scope) == ()
        receipts = SqlAlchemyReceiptLedger(db, fresh_tenant).receipts_for(
            ADAPTER_NAME,
            (FactKey(source_owner=SOURCE_OWNER, source_ref=str(occurrence_id)),),
        )
    assert len(receipts) == 1
    assert receipts[0].outcome is ReceiptOutcome.APPLIED

    with runtime.tenant_session(fresh_tenant) as db:
        again = drain_rated_obligations(
            db,
            scope=scope,
            ledger=SqlAlchemyReceiptLedger(db, fresh_tenant),
            tax_for=lambda _output: _no_tax(),
            resolve_billing_account=lambda _scope, _output: account_id,
            observed_at=NOW + timedelta(minutes=5),
        )
    assert again == ()

    with runtime.tenant_session(fresh_tenant) as db:
        assert _obligation_count(db, account_id) == 1


def test_a_failed_effect_rolls_back_its_receipt_and_is_repaired_next_drain(
    runtime: DatabaseRuntime, fresh_tenant: UUID
) -> None:
    """Atomicity, then missed-delivery repair — the same canary from both ends.

    An interrupted run must leave NO obligation, NO receipt and NO
    acknowledgement, or the hand-off becomes unrepairable: Subscriptions would
    believe it was handled while Billing never saw it. Because the
    acknowledgement is written last and in the same transaction, the next drain
    re-offers the output and completes it exactly once.
    """
    scope = TenantScope(tenant_id=fresh_tenant)
    with runtime.tenant_session(fresh_tenant) as db:
        version_id, line_key = _seed_subscription(db, scope)
        _rate_one_period(db, scope, version_id, line_key)
        account_id = _account(db, scope)

    with (
        pytest.raises(RuntimeError, match="interrupted"),
        runtime.tenant_session(fresh_tenant) as db,
    ):
        outputs = unacknowledged_outputs(db, scope=scope)
        assert len(outputs) == 1
        apply_rated_obligation(
            db,
            scope=scope,
            ledger=SqlAlchemyReceiptLedger(db, fresh_tenant),
            output=outputs[0],
            tax=_no_tax(),
            resolve_billing_account=lambda _scope, _output: account_id,
            observed_at=NOW,
        )
        raise RuntimeError("interrupted before commit")

    with runtime.tenant_session(fresh_tenant) as db:
        assert _obligation_count(db, account_id) == 0
        assert len(unacknowledged_outputs(db, scope=scope)) == 1

    with runtime.tenant_session(fresh_tenant) as db:
        repaired = drain_rated_obligations(
            db,
            scope=scope,
            ledger=SqlAlchemyReceiptLedger(db, fresh_tenant),
            tax_for=lambda _output: _no_tax(),
            resolve_billing_account=lambda _scope, _output: account_id,
            observed_at=NOW + timedelta(hours=1),
        )
    assert repaired == (ReceiptOutcome.APPLIED,)

    with runtime.tenant_session(fresh_tenant) as db:
        assert _obligation_count(db, account_id) == 1
        assert unacknowledged_outputs(db, scope=scope) == ()


def test_an_unresolvable_billing_account_is_refused_and_left_unacknowledged(
    runtime: DatabaseRuntime, fresh_tenant: UUID
) -> None:
    """A subscription with no linked account is never charged to a guess.

    The refusal is recorded so reconciliation does not read it as never
    delivered, and deliberately NOT acknowledged so it stays visible as
    unfinished work.
    """
    scope = TenantScope(tenant_id=fresh_tenant)
    with runtime.tenant_session(fresh_tenant) as db:
        version_id, line_key = _seed_subscription(db, scope)
        _rate_one_period(db, scope, version_id, line_key)
        # An account EXISTS; it is simply not linked to this subscription. That
        # is the dangerous case — charging it would look entirely plausible.
        account_id = _account(db, scope)

    with runtime.tenant_session(fresh_tenant) as db:
        outcomes = drain_rated_obligations(
            db,
            scope=scope,
            ledger=SqlAlchemyReceiptLedger(db, fresh_tenant),
            tax_for=lambda _output: _no_tax(),
            resolve_billing_account=lambda _scope, _output: None,
            observed_at=NOW,
        )
    assert outcomes == (ReceiptOutcome.REFUSED,)

    with runtime.tenant_session(fresh_tenant) as db:
        assert _obligation_count(db, account_id) == 0
        assert len(unacknowledged_outputs(db, scope=scope)) == 1


def test_the_same_fact_recorded_with_different_evidence_is_a_conflict(
    runtime: DatabaseRuntime, fresh_tenant: UUID
) -> None:
    """Two different outcomes for one exact fact version is a defect, not a replay."""
    scope = TenantScope(tenant_id=fresh_tenant)
    with runtime.tenant_session(fresh_tenant) as db:
        version_id, line_key = _seed_subscription(db, scope)
        _rate_one_period(db, scope, version_id, line_key)
        account_id = _account(db, scope)

    with runtime.tenant_session(fresh_tenant) as db:
        pending = unacknowledged_outputs(db, scope=scope)
        assert len(pending) == 1
        occurrence_id = pending[0].occurrence_id
        drain_rated_obligations(
            db,
            scope=scope,
            ledger=SqlAlchemyReceiptLedger(db, fresh_tenant),
            tax_for=lambda _output: _no_tax(),
            resolve_billing_account=lambda _scope, _output: account_id,
            observed_at=NOW,
        )

    with runtime.tenant_session(fresh_tenant) as db:
        applied = SqlAlchemyReceiptLedger(db, fresh_tenant).receipts_for(
            ADAPTER_NAME,
            (FactKey(source_owner=SOURCE_OWNER, source_ref=str(occurrence_id)),),
        )
    assert len(applied) == 1
    original = applied[0]

    from dataclasses import replace

    from dotmac_cloud.receipts import AdapterReceipt

    forged = AdapterReceipt(
        adapter=original.adapter,
        fact=replace(original.fact, fingerprint="sha256:not-what-was-published"),
        outcome=original.outcome,
        observed_at=original.observed_at,
    )
    with (
        pytest.raises(IdempotencyConflict, match="different request"),
        runtime.tenant_session(fresh_tenant) as db,
    ):
        SqlAlchemyReceiptLedger(db, fresh_tenant).append(forged)


def test_neither_owners_rows_cross_the_tenant_boundary(
    runtime: DatabaseRuntime,
    admin_engine: Engine,
    fresh_tenant: UUID,
    other_tenant: UUID,
) -> None:
    """Composing two owners must not weaken the isolation either one carries."""
    accounts: dict[UUID, UUID] = {}
    for tenant_id in (fresh_tenant, other_tenant):
        scope = TenantScope(tenant_id=tenant_id)
        with runtime.tenant_session(tenant_id) as db:
            version_id, line_key = _seed_subscription(db, scope)
            _rate_one_period(db, scope, version_id, line_key)
            accounts[tenant_id] = _account(db, scope)
        with runtime.tenant_session(tenant_id) as db:
            drain_rated_obligations(
                db,
                scope=scope,
                ledger=SqlAlchemyReceiptLedger(db, tenant_id),
                tax_for=lambda _output: _no_tax(),
                resolve_billing_account=_fixed_account(accounts[tenant_id]),
                observed_at=NOW,
            )

    with runtime.tenant_session(fresh_tenant) as db:
        assert _obligation_count(db, accounts[fresh_tenant]) == 1
        # Asking tenant A for tenant B's ACCOUNT ID directly. A count scoped by
        # account would pass without any policy at all; naming the other
        # tenant's account is what actually exercises row-level security.
        assert _obligation_count(db, accounts[other_tenant]) == 0
    with runtime.tenant_session(other_tenant) as db:
        assert _obligation_count(db, accounts[other_tenant]) == 1
        assert _obligation_count(db, accounts[fresh_tenant]) == 0

    # The migration role bypasses RLS and sees both, which is what makes the two
    # zeroes above evidence of isolation rather than evidence of absence.
    with admin_engine.connect() as connection:
        both = connection.execute(
            text(
                "SELECT count(*) FROM mod_billing.rated_obligations "
                "WHERE billing_account_id = ANY(:accounts)"
            ),
            {"accounts": [accounts[fresh_tenant], accounts[other_tenant]]},
        ).scalar_one()
    assert both == 2
