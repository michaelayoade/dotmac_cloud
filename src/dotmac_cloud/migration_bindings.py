"""Which revision of this assembly supplies each effect a composed module needs.

A module declares the database effects it requires by NAME — never a foreign
revision id — and the assembly composing it answers which of its own revisions
supplies each one. That is the whole seam: a module stays portable across
assemblies, and an assembly that composes a module without answering what it
requires fails loudly before any DDL runs rather than ordering wrongly.

Every binding here answers `"kernel"`, because Cloud runs the kernel base
lineage as its foundation (ADR-0003) and the kernel is what creates `tenants`,
the database roles, the idempotency ledger and the outbox relay. Dotmac Sub
answers `"sub"` for the same effects, having supplied them from its own lineage
years before the kernel named them — that contrast is what the `provider_owner`
field exists to make visible in a review diff.

Each binding names the revision that makes the effect WHOLE, not the assembly's
head. A database stopped between that revision and head still satisfies the
prerequisite, and binding to the head would refuse a migration that could safely
run — and would silently re-order on the next kernel release.
"""

from __future__ import annotations

from typing import Final

from dotmac_kernel.prerequisites import (
    IDEMPOTENCY_LEDGER_V1,
    MODULE_DATABASE_ROLES_V1,
    OUTBOX_RELAY_V1,
    TENANT_SCOPE_CATALOG_V1,
    PrerequisiteBinding,
)

ASSEMBLY_PREREQUISITE_BINDINGS: Final[tuple[PrerequisiteBinding, ...]] = (
    # Kernel 0001 creates `public.tenants` with the column, key and index
    # contract the effect names, in the same revision that creates the roles.
    PrerequisiteBinding(
        prerequisite=TENANT_SCOPE_CATALOG_V1.name,
        provider_revision="0001_initial_tenant_schema",
        provider_owner="kernel",
    ),
    # `app_admin` (BYPASSRLS, offline), `app_user` (online, RLS-enforced) and
    # `platform_api` — created idempotently by the same kernel root revision.
    PrerequisiteBinding(
        prerequisite=MODULE_DATABASE_ROLES_V1.name,
        provider_revision="0001_initial_tenant_schema",
        provider_owner="kernel",
    ),
    # Kernel 0018 is where at-most-once execution got one owner (ADR-0014): it
    # renames the WS3 inbox tables into `idempotency_records` /
    # `platform_idempotency_records` and gives both planes the contract the
    # effect describes. Earlier revisions have the storage under the old name,
    # which is not the same effect.
    PrerequisiteBinding(
        prerequisite=IDEMPOTENCY_LEDGER_V1.name,
        provider_revision="0018_idempotency_one_owner",
        provider_owner="kernel",
    ),
    # The relay effect spans BOTH planes — the spec names the platform table,
    # its claim/settle pair and the platform dispatcher role — so it is whole
    # only at kernel 0012, which adds the platform outbox. Kernel 0011 supplies
    # the tenant half alone and would leave a consumer dying on its first
    # platform claim.
    PrerequisiteBinding(
        prerequisite=OUTBOX_RELAY_V1.name,
        provider_revision="0012_platform_outbox",
        provider_owner="kernel",
    ),
)

__all__ = ["ASSEMBLY_PREREQUISITE_BINDINGS"]
