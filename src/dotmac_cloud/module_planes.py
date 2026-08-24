"""This assembly's explicit persistence-plane selection for each module.

`dotmac-subscriptions` and `dotmac-billing` are DUAL-PLANE: each declares a
tenant plane (`tenant_id NOT NULL`, FORCEd row-level security) and a control
plane (no tenant column, no RLS, isolated by a revoked `app_user` grant), and
each supports being installed as either. The kernel refuses to build the
revision graph until an assembly says which — `selected_module_planes` raises
`ModulePlaneSelectionError` rather than defaulting, so a plane is never chosen
by accident.

**Cloud selects the TENANT plane for every module, always.** Cloud is a
multi-tenant product runtime: every obligation, subscription and receivable here
belongs to exactly one tenant, and a control-plane table has no tenant column
for it to belong to. Selecting the platform plane would put customer commercial
state in a table whose isolation is a role grant rather than a row policy, which
is Cloud hard rule 6 read backwards.

The selection is data, not a default: adding a module without adding it here
fails the migration, and `tests/architecture/test_cloud_boundaries.py` fails if
any composed module's selection is anything but the tenant plane.
"""

from __future__ import annotations

from typing import Final

from dotmac_kernel.planes import ModulePlane, ModulePlaneSelection

#: Keyed by the module's short code, which is what `resolve_depends_on` looks up
#: — deliberately not the distribution or import name.
MODULE_PLANE_SELECTIONS: Final[tuple[ModulePlaneSelection, ...]] = (
    ModulePlaneSelection(module="subscriptions", planes=(ModulePlane.TENANT,)),
    ModulePlaneSelection(module="billing", planes=(ModulePlane.TENANT,)),
)

__all__ = ["MODULE_PLANE_SELECTIONS"]
