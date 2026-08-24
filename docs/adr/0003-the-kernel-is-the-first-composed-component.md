# ADR-0003 — The kernel is the first composed component

- Status: accepted
- Date: 2026-08-24
- Supersedes: nothing
- Related: ADR-0001 (fail-closed foundation), ADR-0002 (tenant runtime and
  receipt ledger), Starter ADR-0014 (at-most-once has one owner), Starter
  ADR-0030 (Cloud V1 bill of materials)

## Context

Fifteen of the nineteen V1 owners now carry immutable release evidence, and none
were composed. The obvious next step read as "exact-pin the released packages",
as though pinning were a preparatory step that could land ahead of the adapter
work.

It cannot. `tests/architecture/test_cloud_boundaries.py` asserts that the set of
exact Dotmac dependencies in `project.dependencies` equals the set of components
marked `composed`, and that the set of `dotmac_*` imports under `src/` equals
that same set. In this repository, pinning IS composing. A pin-only change would
have to either mark a component adopted that nothing uses, or hide the pins in a
non-runtime dependency group to slip past the guard. The first is the false
positive the ledger exists to prevent; the second is weakening the gate, which
hard rule 8 forbids.

So the question was never "which packages do we pin" but "which owner do we
genuinely adopt first".

## Decision

**`dotmac-kernel==0.1.0a94` is composed, alone.**

The kernel is the only V1 component whose adoption this application can prove
today, because it is the only one Cloud already had a designed use for. ADR-0002
and `docs/ARCHITECTURE.md` both state that at-most-once execution belongs to
`dotmac_kernel.idempotency` and that the receipt write path delegates to it once
the kernel is composed. That promise is now kept rather than restated.

Concretely:

1. The exact pin is declared in `project.dependencies` and resolved from the
   private Dotmac index, which is configured `explicit` so PyPI resolution for
   third-party packages is unchanged and no public typosquat can shadow a
   Dotmac distribution.
2. `SqlAlchemyReceiptLedger.append` calls `execute_once`. Cloud supplies the
   hand-off identity and a fingerprint of what was handled; the kernel decides
   whether a returning key is a replay or a conflict.
3. The kernel base migration lineage runs in Cloud's database, composed into the
   revision graph by `alembic/env.py` and ordered by a `depends_on` declared on
   Cloud's own migration.
4. `dotmac-kernel` moves to `activation: composed` in the BOM. Nothing else
   does.

## Why the whole kernel lineage, and not just a table

`IdempotencyRecord.tenant_id` carries a FOREIGN KEY to `tenants`. Using
`execute_once` therefore requires the kernel's tenant schema, and the lineage is
linear, so it is all of it or none of it. Copying the one table into Cloud's own
lineage was rejected: a hand-copied schema is a fork that drifts from the owner
that defines it, and the BOM already declares the kernel's persistence as
`foundation` — a foundation is precisely something an assembly runs, not
something it re-implements.

The two systems already agreed on the tenant scope. The kernel's RLS reads
`current_setting('app.current_tenant')`, which is the setting Cloud's
`tenant_session` installs, so no adapter, shim or translation was needed.

The cost is real and accepted: the kernel brings FastAPI, Starlette, Pydantic,
Jinja2 and argon2 into a runtime that previously carried only SQLAlchemy,
Alembic and psycopg, and it creates tenant, party, RBAC, auth and settings
tables this application does not yet read. That is what adopting a foundation
means. It is not evidence that those tables have owners here — they do not, and
none may be written by this application without its own decision.

## What this deliberately does NOT claim

- **No other owner is adopted.** Fourteen released artifacts remain `pending`.
- **Production readiness stays closed.** Eighteen blockers remain and `ready` is
  false; four owners are still unavailable at source.
- **No authority moved and no writer was retired in any product.** Sub and
  Vendor CP are untouched by this change.
- **Nothing is deployed.** No host has been named.

## Consequences

`ReceiptConflict` is gone. Cloud no longer owns a verdict on whether a returning
identity is the same request — that was a second engine in all but name, and its
removal is the measurable result of this decision rather than a side effect.

The integration canaries now seed `tenants`, because a receipt for a tenant this
database has never heard of is correctly refused by a foreign key. A new canary
asserts the kernel ledger row itself, not merely that duplicates are absent: the
receipt table's own unique constraint could produce that behaviour, so evidence
of deduplication is not evidence of delegation.

CI resolves the private index with an operator-installed read-only
`FORGEJO_READ_TOKEN`. The next kernel upgrade is now a real, reviewable event
for this application: a version bump, a lock change, and a migration lineage
that moves.
