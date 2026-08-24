"""The contract translation itself — pure, no session, no database.

`to_command` is where two owners' vocabularies meet, and a mistranslation here
is a wrong charge rather than a crash. These assert the mappings that are NOT
obvious field copies, and the refusals that stop the adapter inventing a value
Billing requires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from dotmac_billing.contracts import AppliedTaxSnapshotV1, ServicePeriodStatus
from dotmac_kernel.cache import TenantScope
from dotmac_kernel.money import Currency, Money
from dotmac_subscriptions import (
    CollectionTiming,
    ExactAmount,
    IntervalUnit,
    ProrationPolicy,
    RateBasis,
    RatedObligationOutputV1,
    occurrence_idempotency_key,
    rating_input_fingerprint,
)

from dotmac_cloud.adapters.subscriptions_to_billing import (
    SOURCE_OWNER,
    TaxOutcome,
    UnmappableObligation,
    to_command,
)

TENANT = TenantScope(tenant_id=UUID("11111111-1111-4111-8111-111111111111"))
NGN = Currency(code="NGN", minor_units=2)
PERIOD_START = datetime(2026, 8, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 9, 1, tzinfo=UTC)
COVERAGE_START = datetime(2026, 8, 15, tzinfo=UTC)
COVERAGE_END = datetime(2026, 9, 1, tzinfo=UTC)


def _no_tax() -> TaxOutcome:
    return TaxOutcome(
        amount=Money(amount=Decimal("0.00"), currency=NGN),
        not_assessed_reason="no tax owner is composed in this assembly",
    )


def _output(
    *,
    generation: int = 1,
    source_version: int = 1,
    subscription_contract_id: UUID | None = None,
    contract_line_key: UUID | None = None,
) -> RatedObligationOutputV1:
    """Build a legitimate rated obligation.

    The output validates its OWN fingerprint and idempotency key against its
    rating inputs, so neither can be fabricated. Deriving them here is not test
    convenience — it is the only way to construct one, and it is why a
    mistranslated field cannot hide behind a hand-written fixture.
    """
    scope = TENANT
    contract_id = subscription_contract_id or uuid4()
    line_key = contract_line_key or uuid4()
    contract_version_id = uuid4()
    charge_model_code = "recurring.flat"
    source_code = "service"
    source_id = uuid4()
    currency = "NGN"
    unit_price = ExactAmount(amount=Decimal("10000.00"), currency=currency, scale=2)
    quantity = Decimal("1")
    rate_basis = RateBasis.per_rate_unit
    rate_unit = IntervalUnit.month
    rate_quantity = Decimal("1")
    rate_units = Decimal("1")
    proration_policy = ProrationPolicy.actual_calendar_days
    proration_factor = Decimal("0.5")
    timezone_name = "Africa/Lagos"
    rating_policy_version = "fixed.v1"
    offer_version_ref = "offer-v3"

    return RatedObligationOutputV1(
        occurrence_id=uuid4(),
        emitted_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
        generation=generation,
        scope=scope,
        subscription_contract_id=contract_id,
        contract_version_id=contract_version_id,
        contract_line_key=line_key,
        charge_model_code=charge_model_code,
        source_code=source_code,
        source_id=source_id,
        source_version=source_version,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        currency=currency,
        pre_tax_amount=ExactAmount(
            amount=Decimal("5000.00"), currency=currency, scale=2
        ),
        collection_timing=CollectionTiming.advance,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
        unit_price=unit_price,
        quantity=quantity,
        rate_basis=rate_basis,
        rate_unit=rate_unit,
        rate_quantity=rate_quantity,
        rate_units=rate_units,
        proration_policy=proration_policy,
        proration_factor=proration_factor,
        timezone_name=timezone_name,
        rating_policy_version=rating_policy_version,
        offer_version_ref=offer_version_ref,
        request_fingerprint=rating_input_fingerprint(
            unit_price=unit_price,
            quantity=quantity,
            rate_basis=rate_basis,
            rate_unit=rate_unit,
            rate_quantity=rate_quantity,
            rate_units=rate_units,
            proration_policy=proration_policy,
            proration_factor=proration_factor,
            coverage_start=COVERAGE_START,
            coverage_end=COVERAGE_END,
            currency=currency,
            timezone_name=timezone_name,
            rating_policy_version=rating_policy_version,
            offer_version_ref=offer_version_ref,
        ),
        idempotency_key=occurrence_idempotency_key(
            scope=scope,
            contract_line_key=line_key,
            contract_version_id=contract_version_id,
            charge_model_code=charge_model_code,
            source_code=source_code,
            source_id=source_id,
            source_version=source_version,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            currency=currency,
        ),
    )


def test_the_service_period_is_the_coverage_window_not_the_billing_window() -> None:
    """A prorated half-month must not be presented to Billing as a full one."""
    command = to_command(
        _output(),
        scope=TENANT,
        billing_account_id=uuid4(),
        tax=_no_tax(),
    )

    assert command.service_period.starts_at == COVERAGE_START
    assert command.service_period.ends_at == COVERAGE_END
    assert command.service_period.starts_at != PERIOD_START
    assert command.service_period.status is ServicePeriodStatus.VERIFIED


def test_the_billable_identity_is_the_contract_LINE_not_the_contract() -> None:
    """Two lines on one subscription must not collapse into one obligation."""
    contract = uuid4()
    first = _output(subscription_contract_id=contract, contract_line_key=uuid4())
    second = _output(subscription_contract_id=contract, contract_line_key=uuid4())

    commands = [
        to_command(item, scope=TENANT, billing_account_id=uuid4(), tax=_no_tax())
        for item in (first, second)
    ]

    assert commands[0].subject_ref == commands[1].subject_ref
    assert commands[0].contract_line_ref != commands[1].contract_line_ref


def test_generation_is_the_source_fact_version_billing_compares_on() -> None:
    """Re-rating advances `generation`; `source_version` is a different number."""
    command = to_command(
        _output(generation=4, source_version=1),
        scope=TENANT,
        billing_account_id=uuid4(),
        tax=_no_tax(),
    )

    assert command.source_fact_version == "4"
    assert command.source_system == SOURCE_OWNER
    assert command.source_kind == "subscriptions.rated_obligation"


def test_the_total_is_pre_tax_plus_the_supplied_tax() -> None:
    snapshot = AppliedTaxSnapshotV1(
        treatment_code="vat.standard",
        jurisdiction_code="NG",
        policy_id="ng-vat",
        policy_version="2026.1",
        rate=Decimal("0.075"),
        taxable_basis=Money(amount=Decimal("5000.00"), currency=NGN),
        tax_amount=Money(amount=Decimal("375.00"), currency=NGN),
    )
    command = to_command(
        _output(),
        scope=TENANT,
        billing_account_id=uuid4(),
        tax=TaxOutcome(
            amount=Money(amount=Decimal("375.00"), currency=NGN),
            snapshots=(snapshot,),
        ),
    )

    assert command.pre_tax_amount.amount == Decimal("5000.00")
    assert command.tax_amount.amount == Decimal("375.00")
    assert command.total_amount.amount == Decimal("5375.00")
    assert command.tax_snapshots == (snapshot,)


def test_a_currency_mismatch_between_rating_and_tax_is_refused() -> None:
    with pytest.raises(UnmappableObligation, match="different currency"):
        to_command(
            _output(),
            scope=TENANT,
            billing_account_id=uuid4(),
            tax=TaxOutcome(
                amount=Money(
                    amount=Decimal("0.00"), currency=Currency(code="USD", minor_units=2)
                ),
                not_assessed_reason="none",
            ),
        )


def test_tax_outcome_refuses_every_incoherent_shape() -> None:
    """An unexplained zero is the dangerous one: it looks like a decision."""
    with pytest.raises(ValueError, match="why it was not assessed"):
        TaxOutcome(amount=Money(amount=Decimal("0.00"), currency=NGN))

    with pytest.raises(ValueError, match="requires applied tax snapshots"):
        TaxOutcome(amount=Money(amount=Decimal("375.00"), currency=NGN))

    snapshot = AppliedTaxSnapshotV1(
        treatment_code="vat.standard",
        jurisdiction_code="NG",
        policy_id="ng-vat",
        policy_version="2026.1",
        rate=Decimal("0.075"),
        taxable_basis=Money(amount=Decimal("5000.00"), currency=NGN),
        tax_amount=Money(amount=Decimal("375.00"), currency=NGN),
    )
    with pytest.raises(ValueError, match="contradicts"):
        TaxOutcome(
            amount=Money(amount=Decimal("375.00"), currency=NGN),
            snapshots=(snapshot,),
            not_assessed_reason="but it was",
        )
