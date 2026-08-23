"""Cloud-owned adapter receipts and cross-owner reconciliation.

## What this module owns, and what it deliberately does not

Cloud composes reusable owners that never import one another. Every hand-off
between two owners therefore passes through a Cloud adapter, and an adapter
that leaves no evidence cannot be repaired: after a lost callback, a duplicate
delivery, or an out-of-order one, nothing can say what this application already
acted on. This module owns that evidence and the verdict derived from it.

It owns exactly two things:

1. **Adapter receipts** — append-only evidence that one named adapter handled
   one exact version of one fact published by one owner.
2. **Reconciliation** — given what an owner says it published and what this
   ledger recorded, decide which facts never arrived, which arrived stale, and
   which arrived with the same identity but different content.

It owns neither of the two things it sits between:

- **At-most-once execution is NOT here.** ``dotmac_kernel.idempotency`` is the
  single owner of that decision fleet-wide, and a second engine inside an
  assembly is exactly the parallel authority this composition exists to
  prevent. When the kernel becomes a composed component the write path
  delegates to it; this module supplies the fingerprint and the identity, never
  a claim, lease or reservation of its own. That is enforced by
  ``test_cloud_declares_no_second_idempotency_engine``, with a sensitivity
  proof.
- **Business meaning is NOT here.** A fact's payload is opaque. Whether an
  obligation is due, a settlement covers it, or an exposure justifies dunning
  belongs to Billing, Payments and Collections respectively. This module
  compares identities and fingerprints and says nothing about what they mean.

## Why reconciliation is genuinely Cloud's

At-most-once is a property of a single effect, which is why one owner can hold
it. "Which of the facts I expected never arrived" is a property of a SET, held
across two owners that cannot see each other — only the assembly composing them
can ask it. No module can answer it without reading another module's tables,
which the application boundary forbids.

This module is pure: no clock read, no I/O, no database, no framework. The
caller supplies observation times, and ``ReceiptLedger`` is the seam a later
slice implements against Cloud's own database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

__all__ = [
    "AdapterReceipt",
    "DivergentFact",
    "FactKey",
    "ReceiptLedger",
    "ReceiptOutcome",
    "ReconciliationReport",
    "SourceFact",
    "StaleFact",
    "reconcile",
]


class ReceiptOutcome(StrEnum):
    """What the adapter did with one exact fact version.

    ``REFUSED`` is a recorded outcome rather than a raised exception on
    purpose: an adapter that refuses a malformed or unauthorized fact must
    still leave evidence, or reconciliation later reports that fact as never
    delivered and a repair job re-fetches it forever.
    """

    APPLIED = "applied"
    REFUSED = "refused"


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True, order=True)
class FactKey:
    """The identity of a published fact, without its version or content.

    Version is excluded deliberately. Reconciliation must be able to ask "did
    anything for this subject arrive, and was it current?", which is impossible
    if the identity already contains the version being tested.
    """

    source_owner: str
    source_ref: str

    def __post_init__(self) -> None:
        _require_text("source_owner", self.source_owner)
        _require_text("source_ref", self.source_ref)


@dataclass(frozen=True, slots=True)
class SourceFact:
    """One exact version of one fact published by one owner.

    ``fingerprint`` is the publisher's own content digest. It is carried rather
    than computed here because only the owner can say which fields are part of
    a fact's identity; a digest this module invented would disagree with the
    owner's own replay comparison.
    """

    key: FactKey
    source_version: int
    fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, FactKey):
            raise ValueError("key must be a FactKey")
        if isinstance(self.source_version, bool) or not isinstance(
            self.source_version, int
        ):
            raise ValueError("source_version must be an int")
        if self.source_version < 1:
            raise ValueError("source_version must be positive")
        _require_text("fingerprint", self.fingerprint)


@dataclass(frozen=True, slots=True)
class AdapterReceipt:
    """Append-only evidence that one adapter handled one exact fact version."""

    adapter: str
    fact: SourceFact
    outcome: ReceiptOutcome
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_text("adapter", self.adapter)
        if not isinstance(self.fact, SourceFact):
            raise ValueError("fact must be a SourceFact")
        if not isinstance(self.outcome, ReceiptOutcome):
            raise ValueError("outcome must be a ReceiptOutcome")
        _require_aware("observed_at", self.observed_at)


@dataclass(frozen=True, slots=True)
class StaleFact:
    """The owner has advanced past the version this application acted on."""

    key: FactKey
    received_version: int
    published_version: int


@dataclass(frozen=True, slots=True)
class DivergentFact:
    """Same owner, ref and version — different content.

    This is the most dangerous outcome and it never self-heals. Re-delivery
    cannot fix it, because the identity a repair would re-fetch is the identity
    that already disagrees. It always means a defect: a mutated immutable fact,
    a fingerprint computed over fields that keep changing, or two subjects
    colliding on one reference.
    """

    key: FactKey
    source_version: int
    received_fingerprint: str
    published_fingerprint: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """What this application must repair to agree with a publishing owner."""

    settled: tuple[FactKey, ...]
    missing: tuple[SourceFact, ...]
    stale: tuple[StaleFact, ...]
    divergent: tuple[DivergentFact, ...]

    @property
    def converged(self) -> bool:
        """Return true only when nothing is missing, stale or divergent."""
        return not (self.missing or self.stale or self.divergent)

    @property
    def repairable_by_redelivery(self) -> tuple[SourceFact, ...]:
        """Return the facts a poll or replay can fix.

        Divergence is excluded by construction — see ``DivergentFact``.
        """
        return self.missing


class ReceiptLedger(Protocol):
    """Durable append-only receipt store.

    The persistence seam. A later slice implements this against Cloud's own
    database with a tenant-scoped, RLS-enforced table. It deliberately exposes
    no claim, lease or reserve operation: at-most-once execution belongs to
    ``dotmac_kernel.idempotency``, and a ledger that could reserve would be a
    second engine.
    """

    def receipts_for(
        self, adapter: str, keys: Iterable[FactKey]
    ) -> tuple[AdapterReceipt, ...]:
        """Return every receipt this adapter holds for the given identities."""
        ...

    def append(self, receipt: AdapterReceipt) -> None:
        """Append one receipt. Never updates or deletes an existing row."""
        ...


def _latest_by_key(
    receipts: Iterable[AdapterReceipt],
) -> dict[FactKey, AdapterReceipt]:
    latest: dict[FactKey, AdapterReceipt] = {}
    for receipt in receipts:
        key = receipt.fact.key
        current = latest.get(key)
        if current is None or receipt.fact.source_version > current.fact.source_version:
            latest[key] = receipt
    return latest


def reconcile(
    *,
    published: Iterable[SourceFact],
    received: Iterable[AdapterReceipt],
) -> ReconciliationReport:
    """Compare what an owner published against what this application recorded.

    ``published`` is the owner's current truth, obtained through its versioned
    read — never by reading its tables. ``received`` is this application's own
    receipt evidence for one adapter.

    A receipt with no matching published fact is NOT reported. This application
    having acted on a fact the owner no longer lists is not drift it may
    repair: only the owner can retract, and inventing a retraction here would
    let an assembly delete another owner's history.
    """
    latest = _latest_by_key(received)
    settled: list[FactKey] = []
    missing: list[SourceFact] = []
    stale: list[StaleFact] = []
    divergent: list[DivergentFact] = []

    for fact in published:
        receipt = latest.get(fact.key)
        if receipt is None:
            missing.append(fact)
            continue
        acted = receipt.fact
        if acted.source_version < fact.source_version:
            stale.append(
                StaleFact(
                    key=fact.key,
                    received_version=acted.source_version,
                    published_version=fact.source_version,
                )
            )
            continue
        if (
            acted.source_version == fact.source_version
            and acted.fingerprint != fact.fingerprint
        ):
            divergent.append(
                DivergentFact(
                    key=fact.key,
                    source_version=fact.source_version,
                    received_fingerprint=acted.fingerprint,
                    published_fingerprint=fact.fingerprint,
                )
            )
            continue
        settled.append(fact.key)

    return ReconciliationReport(
        settled=tuple(sorted(settled)),
        missing=tuple(missing),
        stale=tuple(stale),
        divergent=tuple(divergent),
    )
