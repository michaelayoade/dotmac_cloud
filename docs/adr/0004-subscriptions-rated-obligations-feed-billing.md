# ADR-0004 — Subscriptions rated obligations feed Billing

- Status: accepted
- Date: 2026-08-24
- Supersedes: nothing
- Related: ADR-0001 (fail-closed foundation), ADR-0002 (tenant runtime and
  receipts), ADR-0003 (kernel composition), Starter ADR-0030 (Cloud V1 bill of
  materials)

## Context

Cloud had a real tenant runtime, a kernel-owned at-most-once engine, and durable
adapter receipts, but no business owner was composed. Billing and Subscriptions
were released peers with compatible typed seams: Subscriptions publishes a
rated obligation, while Billing accepts a rated obligation and owns the
operational receivable.

The apparent field mapping had two gaps. Subscriptions cannot name the Cloud
billing account that bears a charge, and it does not make the tax decision that
Billing requires. Guessing either value would make the adapter a hidden business
owner.

The first composition attempt also proved why an application must run a module
under the application's real session policy. Cloud uses `autoflush=False`.
`dotmac-subscriptions==0.1.0a1` relied on incidental autoflush when inserting a
contract version before its lines, so a valid command failed its foreign key and
was misreported as an idempotency conflict. The source fix, an explicit flush
and its `autoflush=False` canary, is released as `0.1.0a2`; Cloud does not work
around the defect or pin source.

## Decision

Cloud composes `dotmac-subscriptions==0.1.0a2` and
`dotmac-billing==0.1.0a1` alongside `dotmac-kernel==0.1.0a94`.

`dotmac_cloud.adapters.subscriptions_to_billing` is the sole translator from
Subscriptions' `RatedObligationOutputV1` to Billing's
`AcceptRatedObligationV1`. It maps the served coverage window, not the nominal
billing window; uses the contract line as the billable identity; and uses the
rating generation as the source fact version.

The caller must provide:

- a Cloud-owned `BillingAccountResolver`; an unresolved association records a
  refusal and never guesses an account; and
- a `TaxOutcome`; an unexplained zero, a non-zero amount without evidence, or a
  currency mismatch is refused.

Acceptance, receipt, and Subscriptions acknowledgement share the caller's
transaction. A refused output is not acknowledged, so it remains visible for
repair. `drain_rated_obligations` re-reads unacknowledged outputs; kernel
idempotency makes an identical redelivery a replay and a changed fingerprint a
conflict.

Cloud appends the kernel, Subscriptions and Billing migration locations to the
live Alembic `ScriptDirectory`, installs the assembly's logical prerequisite
bindings, and explicitly selects the tenant plane for both modules before the
revision graph is materialized. Missing composition data fails closed.

## Consequences

Cloud now composes three of nineteen owners and remains not production-ready
with sixteen blockers. The change moves no authority and retires no writer in
Dotmac Sub or another product. It does not compose tax, Collections, a delivery
transport, or a scheduler.

PostgreSQL CI must prove replay, changed-fingerprint conflict, rollback
atomicity, missed-delivery repair, and cross-tenant isolation using the exact
released artifacts. The BOM records the immutable Subscriptions a2 release
oracle: release run `32775846933`, tag
`dotmac-subscriptions-v0.1.0a2`, peeled commit
`f91253d5e193918507e9f2e0768a76aefe5bbce0`.
