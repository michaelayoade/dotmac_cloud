# Dotmac Cloud architecture

## Application boundary

Dotmac Cloud is one independently deployed application with its own runtime,
database, migrations, sessions, authorization, local link rows, adapter receipt
ledger, and repair processes. Cross-application integration is only through
versioned APIs and webhooks. Cloud never reads Dotmac Sub, Vendor Control Plane,
ERP, CRM, or Integrator storage.

Reusable modules are installed locally as exact released artifacts. Stateful
Cloud modules select only their tenant plane. Provider transports are not
modules in this application: the separately deployed Integrator discovers and
runs connector plugins.

## Current construction state

The first foundation slice deliberately has no active Dotmac package
dependencies. src/dotmac_cloud/cloud_v1_bom.json is a fail-closed construction
ledger:

- released means an immutable tag and peeled commit are recorded;
- source-unreleased or source-missing names the actual blocker;
- pending means this application has not yet exact-pinned, migrated, wired, and
  proven the owner; and
- composed will be set only in the same reviewed change that adds the exact
  dependency, explicit plane, adapter, migration binding, and CI proof.

Source availability is not adoption, and this negative ledger is not a release
oracle. It records only the immutable release evidence already accepted by this
assembly and refuses every unsupported positive claim.

## Ownership map

| Fact or decision | Sole owner in this repository |
|---|---|
| Cloud V1 BOM parsing and production-readiness verdict | dotmac_cloud.composition |
| Product-local adapter receipts and cross-owner reconciliation | `dotmac_cloud.receipts` |
| At-most-once execution of one effect | `dotmac_kernel.idempotency`, never this application |
| Offer, subscription, order, payment, tax, receivable, dunning, fulfillment, domain, and hosting decisions | Their exact-pinned reusable owner modules |
| External transport, provider binding, secret materialization, retry, checkpoints, and delivery evidence | Independently deployed Dotmac Integrator |

## Adapter receipts and reconciliation

`dotmac_cloud.receipts` is the first real slice of the commerce adapter work.
It is pure — no clock, no I/O, no database, no framework — and depends on no
Dotmac package, because the composition gate correctly refuses an import of any
owner this application has not yet exact-pinned.

It owns two things and refuses a third:

- **Adapter receipts** — append-only evidence that one named adapter handled
  one exact version of one fact published by one owner. A refusal is recorded
  too: without it, a fact the adapter deliberately rejected reconciles as never
  delivered and is re-fetched forever.
- **Reconciliation** — comparing an owner's published facts against this
  application's receipts to classify `missing` (a lost callback, repairable by
  polling), `stale` (out-of-order or superseded), and `divergent` (the same
  owner, ref and version carrying different content).
- **Not at-most-once execution.** That has one owner fleet-wide,
  `dotmac_kernel.idempotency`. When the kernel becomes composed, the write path
  delegates to it; this module supplies identity and fingerprint and never
  claims, leases or reserves. `test_cloud_declares_no_second_idempotency_engine`
  enforces that over defined names, with a sensitivity proof.

Divergence is deliberately excluded from `repairable_by_redelivery`. It never
self-heals — the identity a repair would re-fetch is the identity that already
disagrees — so routing it to a retry loop would spin forever instead of
surfacing the defect.

Reconciliation is Cloud's rather than a module's for a structural reason:
at-most-once is a property of a single effect, which one owner can hold, but
"which of the facts I expected never arrived" is a property of a set spanning
two owners that cannot see each other. Only the assembly composing them can ask
it without reading another application's tables.

`ReceiptLedger` is the persistence seam. It exposes no reserve operation, and a
later slice implements it against Cloud's own tenant-scoped, RLS-enforced
table.

## Next composition slice

The next slice adds the first typed adapter against a reviewed module contract
and the durable `ReceiptLedger` behind it. It must keep modules as peers, add
the module's exact released dependency and tenant-plane selection, bind its
migration prerequisites, and prove replay and missed-delivery repair against a
real database. No component becomes composed merely because its source or
release exists.

Three of the first four commerce adapters are blocked on release, not on
design: Billing, Subscriptions and Collections are `source-unreleased`, so this
application cannot exact-pin them. `dotmac-payments` and `dotmac-kernel` are
released and are therefore the only owners a real adapter can bind today.
