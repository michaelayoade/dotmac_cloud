"""Subscriptions' rated obligations become Billing's accepted obligations.

The first real commercial hand-off in this application. Subscriptions decides
WHAT is owed for a period and emits `RatedObligationOutputV1`; Billing decides
what that means for an account and accepts `AcceptRatedObligationV1`. Neither
imports the other. This module is the only place the two vocabularies meet.

## What it refuses to invent

Two fields Billing requires have no answer in the Subscriptions output, and
neither is defaulted:

- **`billing_account_id`** — which account bears the charge is a Cloud-owned
  local link, not something either owner can be asked. It is resolved through
  an injected port, and a subscription with no linked account is REFUSED rather
  than charged to a guessed account.
- **`tax_amount`** — Billing requires it and Cloud has composed no tax owner.
  Defaulting it to zero would be a silent tax decision made by an adapter, so
  the caller must supply a `TaxOutcome`, and a zero one must carry a stated
  reason. `TaxOutcome` refuses the incoherent combinations outright.

## Why a refusal is recorded rather than raised

An adapter that refuses a fact must still leave evidence. Without a receipt,
reconciliation later reports that fact as never delivered and a repair job
re-fetches it forever. So a refusal writes a `REFUSED` receipt and returns.

A refused output is deliberately NOT acknowledged back to Subscriptions.
Acknowledging would declare the hand-off finished, and it is not — it is
unfinished work needing a person. Leaving it unacknowledged keeps it visible in
`unacknowledged_outputs` while the receipt records exactly why it was refused.
Re-running the adapter over it is safe and changes nothing: the identical
receipt replays through the kernel ledger.

## Transaction shape

The Billing effect, the receipt and the acknowledgement are written in the
CALLER's transaction. They commit together or not at all — an accepted
obligation with no receipt would be unreconcilable, and a receipt with no
obligation would claim work that never happened.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from dotmac_billing.contracts import (
    AcceptRatedObligationV1,
    AppliedTaxSnapshotV1,
    ServicePeriodEvidenceV1,
    ServicePeriodStatus,
)
from dotmac_billing.errors import BillingRuleViolation
from dotmac_billing.service import accept_rated_obligation
from dotmac_kernel.cache import TenantScope
from dotmac_kernel.money import Currency, Money
from dotmac_subscriptions.contracts import RatedObligationOutputV1
from dotmac_subscriptions.service import acknowledge_output, unacknowledged_outputs
from sqlalchemy.orm import Session

from dotmac_cloud.receipts import (
    AdapterReceipt,
    FactKey,
    ReceiptLedger,
    ReceiptOutcome,
    SourceFact,
)

__all__ = [
    "ACCEPTED_SOURCE_KINDS",
    "ADAPTER_NAME",
    "SOURCE_OWNER",
    "BillingAccountResolver",
    "TaxOutcome",
    "UnmappableObligation",
    "apply_rated_obligation",
    "drain_rated_obligations",
]

#: Names this adapter in every receipt it writes. Stable: changing it would
#: orphan the receipt history that reconciliation reads.
ADAPTER_NAME = "subscriptions-rated-obligation-to-billing"

#: The owner whose facts this adapter consumes, as recorded in a receipt.
SOURCE_OWNER = "subscriptions"

#: Billing refuses a source kind the assembly has not declared. This is that
#: declaration, and it is deliberately the contract type Subscriptions stamps on
#: its own output rather than a name Cloud invented.
ACCEPTED_SOURCE_KINDS = frozenset({"subscriptions.rated_obligation"})

#: Resolves which billing account bears a subscription's charges. Cloud owns
#: this link; neither module can answer it.
BillingAccountResolver = Callable[[TenantScope, RatedObligationOutputV1], UUID | None]


class UnmappableObligation(Exception):
    """One output cannot be expressed as a Billing command, with the reason."""


@dataclass(frozen=True, slots=True)
class TaxOutcome:
    """The tax decision the caller is asserting for one obligation.

    Cloud composes no tax owner, so this is supplied rather than computed. The
    validation exists to make every incoherent shape unrepresentable:

    - tax with no snapshots is an amount with no evidence of how it arose;
    - zero tax with no stated reason is an unexamined default wearing the
      clothes of a decision;
    - a reason alongside a non-zero amount claims tax was not assessed while
      assessing it.
    """

    amount: Money
    snapshots: tuple[AppliedTaxSnapshotV1, ...] = ()
    not_assessed_reason: str | None = None

    def __post_init__(self) -> None:
        zero = self.amount.amount == Decimal(0)
        if not zero and not self.snapshots:
            raise ValueError("a non-zero tax amount requires applied tax snapshots")
        if not zero and self.not_assessed_reason is not None:
            raise ValueError("not_assessed_reason contradicts a non-zero tax amount")
        if zero and not self.snapshots and not (self.not_assessed_reason or "").strip():
            raise ValueError(
                "zero tax must state why it was not assessed; Cloud composes no "
                "tax owner and an unexplained zero is not a decision"
            )


def _service_period(output: RatedObligationOutputV1) -> ServicePeriodEvidenceV1:
    """The COVERAGE window, not the billing window.

    Subscriptions distinguishes the two: `period_start`/`period_end` is the
    billing period the charge belongs to, while `coverage_start`/`coverage_end`
    is the span actually served after proration. Billing's `service_period` is
    what its due-date and credit-note logic reasons about, so it must be the
    served span — a prorated mid-period start otherwise reads as a full period.

    The status is `VERIFIED` because Subscriptions derived the span from a
    recorded contract version and a stated proration policy. It is evidence, not
    an assumption, and claiming `UNKNOWN_UNVERIFIED` would understate it.
    """
    return ServicePeriodEvidenceV1(
        status=ServicePeriodStatus.VERIFIED,
        starts_at=output.coverage_start,
        ends_at=output.coverage_end,
    )


def _money(amount: Decimal, *, currency: str, scale: int) -> Money:
    return Money(amount=amount, currency=Currency(code=currency, minor_units=scale))


def to_command(
    output: RatedObligationOutputV1,
    *,
    scope: TenantScope,
    billing_account_id: UUID,
    tax: TaxOutcome,
) -> AcceptRatedObligationV1:
    """Translate one rated obligation into Billing's accept command.

    Pure: no session, no clock, no I/O. Every field is either carried from the
    output or supplied by the caller — nothing is derived from a default.
    """
    pre_tax = _money(
        output.pre_tax_amount.amount,
        currency=output.pre_tax_amount.currency,
        scale=output.pre_tax_amount.scale,
    )
    if tax.amount.currency != pre_tax.currency:
        raise UnmappableObligation(
            "the supplied tax is in a different currency from the rated amount"
        )
    total = Money(
        amount=pre_tax.amount + tax.amount.amount,
        currency=pre_tax.currency,
    )
    return AcceptRatedObligationV1(
        scope=scope,
        billing_account_id=billing_account_id,
        # The contract LINE is the billable thing, not the contract: two lines
        # on one subscription are two obligations that must not collapse into
        # one natural key.
        contract_line_ref=str(output.contract_line_key),
        contract_version=str(output.contract_version_id),
        charge_component=output.charge_model_code,
        source_system=SOURCE_OWNER,
        source_kind=output.contract_type,
        source_fact_id=str(output.occurrence_id),
        # Subscriptions' `generation` is what advances when it re-rates the same
        # occurrence, so it is the version Billing must compare on.
        source_fact_version=str(output.generation),
        subject_ref=str(output.subscription_contract_id),
        service_ref=f"{output.source_code}:{output.source_id}",
        service_period=_service_period(output),
        collection_timing=output.collection_timing.value,
        pre_tax_amount=pre_tax,
        tax_amount=tax.amount,
        total_amount=total,
        rated_at=output.emitted_at,
        price_version_id=output.offer_version_ref,
        tax_snapshots=tax.snapshots,
    )


def _fact(output: RatedObligationOutputV1) -> SourceFact:
    """Receipt identity for one exact version of one published output.

    The fingerprint is Subscriptions' OWN `request_fingerprint`, carried rather
    than recomputed: only the owner can say which fields make its fact identical,
    and a digest invented here would disagree with the owner's own comparison.
    """
    return SourceFact(
        key=FactKey(source_owner=SOURCE_OWNER, source_ref=str(output.occurrence_id)),
        source_version=output.generation,
        fingerprint=output.request_fingerprint,
    )


def apply_rated_obligation(
    db: Session,
    *,
    scope: TenantScope,
    ledger: ReceiptLedger,
    output: RatedObligationOutputV1,
    tax: TaxOutcome,
    resolve_billing_account: BillingAccountResolver,
    observed_at: datetime,
) -> ReceiptOutcome:
    """Hand one rated obligation to Billing and record what happened.

    Returns the recorded outcome. Raises only for faults that are NOT a property
    of this fact — a broken session, a missing table — because those must abort
    the caller's transaction rather than be recorded as a refusal.
    """
    fact = _fact(output)

    def _refuse() -> ReceiptOutcome:
        ledger.append(
            AdapterReceipt(
                adapter=ADAPTER_NAME,
                fact=fact,
                outcome=ReceiptOutcome.REFUSED,
                observed_at=observed_at,
            )
        )
        return ReceiptOutcome.REFUSED

    billing_account_id = resolve_billing_account(scope, output)
    if billing_account_id is None:
        return _refuse()

    try:
        command = to_command(
            output,
            scope=scope,
            billing_account_id=billing_account_id,
            tax=tax,
        )
    except (UnmappableObligation, ValueError):
        return _refuse()

    try:
        accept_rated_obligation(
            db,
            scope=scope,
            command=command,
            accepted_source_kinds=ACCEPTED_SOURCE_KINDS,
        )
    except BillingRuleViolation:
        # Billing's own refusal of this fact — a property of the fact, so it is
        # evidence rather than an error. A BillingConflict is deliberately NOT
        # caught: it means two different requests collided on one identity, and
        # recording that as a routine refusal would bury a defect.
        return _refuse()

    ledger.append(
        AdapterReceipt(
            adapter=ADAPTER_NAME,
            fact=fact,
            outcome=ReceiptOutcome.APPLIED,
            observed_at=observed_at,
        )
    )
    acknowledge_output(
        db,
        scope=scope,
        occurrence_id=output.occurrence_id,
        acknowledged_at=observed_at,
    )
    return ReceiptOutcome.APPLIED


def drain_rated_obligations(
    db: Session,
    *,
    scope: TenantScope,
    ledger: ReceiptLedger,
    tax_for: Callable[[RatedObligationOutputV1], TaxOutcome],
    resolve_billing_account: BillingAccountResolver,
    observed_at: datetime,
    limit: int = 100,
) -> tuple[ReceiptOutcome, ...]:
    """Apply every output Subscriptions has not seen acknowledged.

    This is also the missed-delivery repair path: Subscriptions keeps offering
    an output until it is acknowledged, and an acknowledgement is only written
    after the Billing effect and its receipt. A lost or half-finished run is
    therefore re-offered on the next drain, where the kernel ledger turns the
    repeat into a replay instead of a second charge.
    """
    return tuple(
        apply_rated_obligation(
            db,
            scope=scope,
            ledger=ledger,
            output=output,
            tax=tax_for(output),
            resolve_billing_account=resolve_billing_account,
            observed_at=observed_at,
        )
        for output in unacknowledged_outputs(db, scope=scope, limit=limit)
    )
