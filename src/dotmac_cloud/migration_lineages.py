"""Which module lineages this assembly composes, and how to make them visible.

Composing a module means running its migrations from inside its installed
distribution. Alembic will not find them on its own, and the way it fails is
silent: this assembly's own revisions never depend on a module revision, so a
missing lineage raises nothing and `alembic upgrade heads` reports success
against a database that never got the module's schema.

## Why the live ScriptDirectory, and not `version_locations`

Alembic reads `version_locations` in `ScriptDirectory.from_config`, which
`command.upgrade` calls BEFORE `script.run_env()`. Setting it from `env.py` is
therefore read by nobody. The `ScriptDirectory` object is still mutable — its
revision map is lazy and is not materialized until the migrations run — so
appending there is read by the object that actually walks the graph.

## Why the list has one owner

Any code that builds a revision map answers a different question and must choose
deliberately whether composed lineages belong in its answer. Keeping the list
here means those callers cannot drift apart, which is the failure mode that hid
the same defect in Dotmac Sub: `env.py` and the CI head-contract were blind in
exactly the same way, so expectation and reality agreed while the module's
schema was never created.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Final

from dotmac_kernel.migrations import versions_dir as kernel_versions_dir

if TYPE_CHECKING:
    from alembic.script import ScriptDirectory

#: Import names of every composed module distribution, in the order their
#: lineages are appended. The kernel is deliberately absent — it is the
#: foundation lineage, appended first and unconditionally by `_locations`.
COMPOSED_MODULE_LINEAGES: Final[tuple[str, ...]] = (
    "dotmac_subscriptions",
    "dotmac_billing",
)


def _locations() -> tuple[str, ...]:
    """Return the foundation lineage followed by each composed module's.

    A module absent from the environment raises `ModuleNotFoundError` rather
    than being skipped: the exact pin says it is installed, and continuing
    without its lineage is the silent failure this module exists to prevent.
    """
    return (str(kernel_versions_dir()),) + tuple(
        str(import_module(f"{import_name}.migrations").versions_dir())
        for import_name in COMPOSED_MODULE_LINEAGES
    )


def compose_lineages(script: ScriptDirectory) -> None:
    """Append the foundation and every composed module lineage to `script`.

    Must be called before the revision map is materialized — that is, before any
    `get_heads()`, `walk_revisions()` or migration run.
    """
    for location in _locations():
        if location not in script.version_locations:
            script.version_locations.append(location)


__all__ = ["COMPOSED_MODULE_LINEAGES", "compose_lineages"]
