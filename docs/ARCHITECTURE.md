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

Fifteen of the nineteen V1 owners have immutable release evidence and exactly
THREE — `dotmac-kernel`, `dotmac-subscriptions`, and `dotmac-billing` — are
`composed`. The other twelve releases are published artifacts, not adoption;
production readiness remains false with sixteen blockers, and the four
still-unavailable owners keep it that way regardless.

Each composed owner is exact-pinned in `project.dependencies`, resolved from
the private index, imported by real application code, and runs its own migration
lineage in this database. The kernel is pinned at `0.1.0a94`, Subscriptions at
`0.1.0a2`, and Billing at `0.1.0a1`. Composition is not a label. The two guards in
`tests/architecture/test_cloud_boundaries.py` make `composed`, the exact pin and
the real import one indivisible fact: the set of exact Dotmac dependencies must
equal the composed set, and so must the recursively discovered set of Dotmac
imports in `src/`. No component can be marked adopted without being used, and
none can be quietly installed without being declared.

src/dotmac_cloud/cloud_v1_bom.json is a fail-closed construction ledger:

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
| Runtime engine, sessions, transaction completion and tenant database scope | `dotmac_cloud.database` |
| Durable adapter receipt rows | `dotmac_cloud.receipt_store` over `public.cloud_adapter_receipts` |
| At-most-once execution of one effect | `dotmac_kernel.idempotency`, never this application — composed and in use |
| Tenant identity, database roles, `app.current_tenant` scope and the idempotency ledger schema | The kernel base migration lineage, run in this database |
| Offer versions, subscription contract versions, rating cadence and rated-obligation outputs | `dotmac-subscriptions` |
| Billing accounts and acceptance of operational receivables | `dotmac-billing` |
| Subscription-to-billing-account association | Cloud, through the `BillingAccountResolver` port; neither module may infer it |
| Tax outcome for one rated obligation | The caller-supplied `TaxOutcome` pending composition of `dotmac-tax`; an unexplained zero is refused |
| Order, payment, tax-policy, dunning, fulfillment, domain, and hosting decisions | Their reusable owner modules; still uncomposed here |
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

`ReceiptLedger` is the persistence seam. It exposes no reserve operation.
`SqlAlchemyReceiptLedger` implements it against Cloud's own tenant-scoped,
RLS-enforced `public.cloud_adapter_receipts` table.

Its append path now delegates the at-most-once decision to
`dotmac_kernel.idempotency.execute_once`, as this document said it would once
the kernel became composed. Cloud supplies two things and decides neither: the
identity of the hand-off (a digest over adapter, owner, ref and version, because
`source_ref` alone can exceed the kernel's key limit and a truncated key would
merge two distinct facts) and a fingerprint of what was handled (the publisher's
content digest together with this application's outcome). The receipt row and
the ledger row are written in the same transaction. What was retired is the
point: the previous hand-rolled lookup, savepoint insert, `IntegrityError`
replay and divergence refusal were the same mechanism under a different name,
and `ReceiptConflict` — an assembly-owned verdict on a question the kernel owns
— no longer exists.

## Subscriptions to Billing hand-off

`dotmac_cloud.adapters.subscriptions_to_billing` is the first composed
commercial hand-off. It consumes Subscriptions'
`RatedObligationOutputV1`, translates it into Billing's
`AcceptRatedObligationV1`, asks Billing to accept it, records Cloud's adapter
receipt, and acknowledges the output back to Subscriptions in one caller-owned
transaction. The modules remain peers and never import each other; only the
Cloud adapter imports their published surfaces.

The adapter refuses to invent two missing facts. The billing account is a
Cloud-owned local association resolved through an injected
`BillingAccountResolver`; no association produces a recorded refusal. Tax is an
explicit `TaxOutcome`; zero tax without a reason, non-zero tax without applied
snapshots, and a currency mismatch are all refused. A refusal is not
acknowledged, so it stays visible to Subscriptions' repair reader while the
receipt prevents the same observation from masquerading as unseen work.

`drain_rated_obligations` is both the delivery and repair path. Subscriptions
keeps an output visible until acknowledgement, while the kernel-owned
at-most-once ledger turns a repeated identical receipt into a replay and rejects
a changed fingerprint. PostgreSQL canaries prove replay, conflict, transaction
rollback, missed-delivery repair, and tenant isolation against the exact
released packages. This is local application composition only: it moves no
authority or writer in Dotmac Sub and introduces no provider transport.

## Transaction and tenant authority

`dotmac_cloud.database.DatabaseRuntime` is the only runtime code that constructs
an engine or session factory. `tenant_session` owns transaction completion and
sets `app.current_tenant` with transaction-local scope before yielding the
session. Services add and flush; they never commit or roll back. Ending the
transaction removes the scope before the pooled connection can be reused.

Four lineages share one revision graph: the kernel foundation, Subscriptions,
Billing, and this assembly's own. `alembic/env.py` appends the installed
packages' locations to the live `ScriptDirectory` rather than rewriting
`version_locations` after Alembic has already read it. Cloud never edits a
foreign revision.

Modules declare the database effects they require, and
`dotmac_cloud.migration_bindings` binds those names to the exact kernel
revisions that make each effect whole. It does not bind to a moving head.
`dotmac_cloud.module_planes` explicitly selects the tenant plane for both
business modules before the graph is built. All four branches are applied with
`alembic upgrade heads`; missing distributions, bindings, plane selections or
lineages fail rather than being skipped.

Cloud and the kernel agree on the tenant scope by contract, not by coincidence:
the kernel's RLS reads `current_setting('app.current_tenant')`, which is exactly
the setting `tenant_session` installs.

The receipt table is created with `tenant_id UUID NOT NULL`, composite
tenant-aware uniqueness, ENABLED and FORCED RLS, and its tenant policy in the
same migration. The online `app_user` role receives only SELECT and INSERT;
UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER are revoked. The migration and
live PostgreSQL tests prove both catalog state and cross-tenant behavior. There
is intentionally no unscoped or platform runtime session in this slice.

The migration URL and online URL are installed separately. Migrations use
`DOTMAC_CLOUD_MIGRATION_DATABASE_URL`; application processes receive only
`DOTMAC_CLOUD_DATABASE_URL`. Neither has a code default and neither value may be
logged or committed.

## Next composition slice

The next commercial slice should compose the tax decision before exposing the
rating-to-billing hand-off through an online or scheduled entry point. The
current explicit `TaxOutcome` seam keeps that work honest: a production caller
cannot silently turn an absent tax owner into zero tax. Collections follows the
operational receivable owned by Billing; it does not redefine Billing's
receivable contract or become a second writer. Every added owner still requires
its exact pin, tenant-plane selection, lineage, binding, real adapter and
PostgreSQL proof in one reviewed change.

Cloud CI resolves the private index with an operator-installed read-only
`FORGEJO_READ_TOKEN`, held only as a repository secret. The value never belongs
in this repository, and `ci-reader` holds read access and nothing else.
