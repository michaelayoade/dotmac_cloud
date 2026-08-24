# ADR-0002: Cloud owns its tenant runtime and durable adapter receipts

Status: Accepted

Date: 2026-08-24

## Context

ADR-0001 established a fail-closed application boundary. PR #2 then defined a
pure `ReceiptLedger` seam and reconciliation rules, but deliberately supplied
no database implementation. A real cross-owner adapter cannot bind its effect
and receipt in one transaction until Cloud owns a runnable transaction boundary
and tenant-isolated receipt table.

The publication of Billing, Collections, Subscriptions and Fulfillment removes
their artifact-availability block. It does not compose them here, move authority
in any product or relax their adoption gates.

## Decision

Cloud owns one application database and one transaction authority:
`dotmac_cloud.database.DatabaseRuntime`. A tenant session is one transaction,
sets `app.current_tenant` with `SET LOCAL` before yielding and commits or rolls
back only at the boundary. Persistence services only mutate and flush.

Cloud owns `public.cloud_adapter_receipts` as append-only evidence. Its creating
migration also creates tenant-aware uniqueness, ENABLE + FORCE RLS, the tenant
policy and grants. `app_user` can SELECT and INSERT but cannot update, delete,
truncate, reference or trigger the table. A missing scope fails closed.

`SqlAlchemyReceiptLedger` implements the existing persistence-neutral protocol.
An identical delivery replays without another row; reuse of the same exact fact
identity with a different fingerprint or outcome is a conflict. The receipt and
the local effect share the caller's transaction.

This is not an idempotency engine. When `dotmac-kernel` is composed, its
idempotency owner executes the effect; Cloud's ledger records cross-owner
delivery evidence. It defines no reserve, claim or lease state.

Migration credentials and online credentials are separately installed process
material with no defaults. Runtime code never migrates the database, and no
credential value is stored in Git, fixtures, logs or documentation.

## Consequences

PostgreSQL CI, rather than SQLite or an in-memory substitute, is required to
prove the boundary. The canaries cover replay, fingerprint conflict, atomic
rollback, cross-tenant read isolation, cross-tenant write refusal, missing-scope
failure and append-only role grants.

All nineteen BOM activations remain `pending`. A later change may mark an owner
`composed` only with its exact dependency, explicit tenant-plane selection,
migration bindings, real adapter and green CI proof in the same review.
