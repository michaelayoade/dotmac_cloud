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
ONE — `dotmac-kernel` — is `composed`. The other fourteen releases are published
artifacts, not adoption; production readiness remains false with eighteen
blockers, and the four still-unavailable owners keep it that way regardless.

The kernel is composed in the full sense the ledger requires: exact-pinned at
`0.1.0a94` in `project.dependencies`, resolved from the private index, imported
by real application code, and running its migration lineage in this database.
Composition is not a label. The two guards in
`tests/architecture/test_cloud_boundaries.py` make `composed`, the exact pin and
the real import one indivisible fact: the set of exact Dotmac dependencies must
equal the composed set, and so must the set of Dotmac imports in `src/`. No
component can be marked adopted without being used, and none can be quietly
installed without being declared.

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

## Transaction and tenant authority

`dotmac_cloud.database.DatabaseRuntime` is the only runtime code that constructs
an engine or session factory. `tenant_session` owns transaction completion and
sets `app.current_tenant` with transaction-local scope before yielding the
session. Services add and flush; they never commit or roll back. Ending the
transaction removes the scope before the pooled connection can be reused.

Two lineages share one revision graph: the kernel base lineage, shipped as
package data inside the exact-pinned distribution, and this assembly's own.
`alembic/env.py` appends the kernel's location rather than `alembic.ini` naming
it, because that path depends on the virtualenv layout and interpreter version.
Ordering is a declared `depends_on` from the assembly's own migration onto the
kernel ROOT revision that creates `app_user` — not onto the kernel head, which
would silently re-order on the next kernel release. Cloud never edits a kernel
revision. Both branches are applied with `alembic upgrade heads` and the CI
round trip unwinds them branch by branch, assembly first.

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

The next slice adds the first typed adapter against the published Billing,
Subscriptions and Collections contracts. It must keep modules as peers,
exact-pin each artifact it imports, select each stateful tenant plane, bind its
migration prerequisites, execute the effect through kernel idempotency and
write the receipt in the same transaction. Replay and missed-delivery repair
must pass against PostgreSQL. No component becomes composed merely because its
release now exists.

Cloud CI resolves the private index with an operator-installed read-only
`FORGEJO_READ_TOKEN`, held only as a repository secret. The value never belongs
in this repository, and `ci-reader` holds read access and nothing else.
