"""Reconciliation verdicts for the Cloud adapter receipt ledger.

Each convergence case here is one of the end-to-end canaries ADR-0030's Cloud
programme requires: duplicate delivery, out-of-order delivery, callback loss
repaired by polling, and the same provider identity arriving with a different
payload.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dotmac_cloud.receipts import (
    AdapterReceipt,
    FactKey,
    ReceiptOutcome,
    SourceFact,
    reconcile,
)

ADAPTER = "subscriptions-to-billing-obligations"
T0 = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _key(ref: str = "obligation-1", owner: str = "dotmac-subscriptions") -> FactKey:
    return FactKey(source_owner=owner, source_ref=ref)


def _fact(
    version: int = 1, fingerprint: str = "sha-a", ref: str = "obligation-1"
) -> SourceFact:
    return SourceFact(key=_key(ref), source_version=version, fingerprint=fingerprint)


def _receipt(
    fact: SourceFact,
    *,
    outcome: ReceiptOutcome = ReceiptOutcome.APPLIED,
    at: datetime = T0,
) -> AdapterReceipt:
    return AdapterReceipt(adapter=ADAPTER, fact=fact, outcome=outcome, observed_at=at)


def test_a_matched_fact_settles_and_the_report_converges() -> None:
    fact = _fact()
    report = reconcile(published=[fact], received=[_receipt(fact)])

    assert report.settled == (fact.key,)
    assert report.converged
    assert report.repairable_by_redelivery == ()


def test_a_lost_callback_is_reported_as_repairable_by_redelivery() -> None:
    """Canary: callback loss repaired by polling.

    The owner published it, this application has no receipt, so a poll or
    replay can still fix it.
    """
    fact = _fact()
    report = reconcile(published=[fact], received=[])

    assert report.missing == (fact,)
    assert report.repairable_by_redelivery == (fact,)
    assert not report.converged


def test_duplicate_delivery_of_the_same_version_settles_once() -> None:
    """Canary: duplicate delivery.

    Two receipts for one version must not produce two settled entries, and
    must never be mistaken for divergence.
    """
    fact = _fact()
    report = reconcile(
        published=[fact],
        received=[_receipt(fact), _receipt(fact, at=T0 + timedelta(minutes=5))],
    )

    assert report.settled == (fact.key,)
    assert report.divergent == ()
    assert report.converged


def test_acting_on_an_older_version_is_stale_not_missing() -> None:
    """Canary: out-of-order delivery.

    Something arrived, so the fact is not missing — but this application acted
    on a superseded version and must catch up. Naming that `missing` would send
    a repair job looking for a delivery that already happened.
    """
    report = reconcile(
        published=[_fact(version=3, fingerprint="sha-c")],
        received=[_receipt(_fact(version=1, fingerprint="sha-a"))],
    )

    assert report.missing == ()
    assert len(report.stale) == 1
    assert (report.stale[0].received_version, report.stale[0].published_version) == (
        1,
        3,
    )
    assert not report.converged


def test_a_later_receipt_than_the_published_version_still_settles() -> None:
    """A publisher read may lag the delivery that reached this application.

    Having acted on a NEWER version than the owner's read currently reports is
    not drift to repair; treating it as stale would make the two chase each
    other.
    """
    report = reconcile(
        published=[_fact(version=2, fingerprint="sha-b")],
        received=[_receipt(_fact(version=5, fingerprint="sha-e"))],
    )

    assert report.converged
    assert report.settled == (_key(),)


def test_same_identity_and_version_with_a_different_payload_is_divergent() -> None:
    """Canary: same provider identity, different payload.

    This is the case redelivery cannot repair, so it must never appear in
    `repairable_by_redelivery` — a repair loop there would spin forever.
    """
    report = reconcile(
        published=[_fact(version=2, fingerprint="sha-published")],
        received=[_receipt(_fact(version=2, fingerprint="sha-received"))],
    )

    assert len(report.divergent) == 1
    divergent = report.divergent[0]
    assert divergent.received_fingerprint == "sha-received"
    assert divergent.published_fingerprint == "sha-published"
    assert report.repairable_by_redelivery == ()
    assert not report.converged


def test_only_the_latest_receipt_decides_the_verdict() -> None:
    """Out-of-order RECEIPTS must not change the answer.

    Receipts are appended in arrival order, which is not version order. If the
    older row won, a redelivered stale copy would reopen a settled fact.
    """
    current = _fact(version=4, fingerprint="sha-d")
    report = reconcile(
        published=[current],
        received=[
            _receipt(current),
            _receipt(_fact(version=2, fingerprint="sha-b"), at=T0 + timedelta(hours=1)),
        ],
    )

    assert report.converged


def test_a_refused_fact_still_counts_as_delivered() -> None:
    """A refusal is evidence, not silence.

    Without this, a fact the adapter deliberately rejected would reconcile as
    never delivered and be re-fetched forever.
    """
    fact = _fact()
    report = reconcile(
        published=[fact],
        received=[_receipt(fact, outcome=ReceiptOutcome.REFUSED)],
    )

    assert report.missing == ()
    assert report.converged


def test_a_receipt_the_owner_no_longer_publishes_is_not_reported() -> None:
    """Cloud may not invent a retraction on an owner's behalf."""
    report = reconcile(
        published=[],
        received=[_receipt(_fact(ref="withdrawn"))],
    )

    assert report.converged
    assert report.settled == ()


def test_facts_from_different_owners_do_not_collide_on_one_ref() -> None:
    """`source_ref` is only unique within its owner."""
    billing = SourceFact(
        key=FactKey(source_owner="dotmac-billing", source_ref="shared-1"),
        source_version=1,
        fingerprint="sha-billing",
    )
    payments = SourceFact(
        key=FactKey(source_owner="dotmac-payments", source_ref="shared-1"),
        source_version=1,
        fingerprint="sha-payments",
    )
    report = reconcile(published=[billing, payments], received=[_receipt(billing)])

    assert report.divergent == ()
    assert report.missing == (payments,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_version", 0),
        ("source_version", -1),
        ("source_version", True),
        ("fingerprint", "   "),
    ],
)
def test_a_malformed_fact_is_refused_at_construction(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "key": _key(),
        "source_version": 1,
        "fingerprint": "sha-a",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        SourceFact(**kwargs)  # type: ignore[arg-type]


def test_a_naive_observation_time_is_refused() -> None:
    """A naive timestamp cannot be ordered against one from another host."""
    with pytest.raises(ValueError, match="timezone-aware"):
        AdapterReceipt(
            adapter=ADAPTER,
            fact=_fact(),
            outcome=ReceiptOutcome.APPLIED,
            observed_at=datetime(2026, 8, 23, 12, 0),  # noqa: DTZ001
        )


def test_an_empty_owner_or_ref_is_refused() -> None:
    with pytest.raises(ValueError):
        FactKey(source_owner="", source_ref="obligation-1")
    with pytest.raises(ValueError):
        FactKey(source_owner="dotmac-billing", source_ref=" ")
