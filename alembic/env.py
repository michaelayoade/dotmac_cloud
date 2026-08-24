"""Cloud assembly migration environment.

Several lineages share one revision graph here: the KERNEL base lineage, every
composed module's lineage, and this assembly's own ``alembic/versions``. Each
ships inside its own exact-pinned distribution and stays separately owned —
Cloud never edits a foreign revision. Ordering is declared, never renumbered: an
assembly migration says what it depends on, and a module resolves the effects it
requires through ``src/dotmac_cloud/migration_bindings.py``.

The foreign lineages are appended HERE rather than named in ``alembic.ini``
because their paths depend on the virtualenv layout and the interpreter version,
which differ between a checkout, the container and CI. A missing lineage is a
composition error rather than something to skip: the exact pins in
``pyproject.toml`` say those distributions are installed, and continuing without
one would run ``alembic upgrade heads`` against a database missing that owner's
schema while reporting success.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotmac_kernel.planes import install_module_plane_selections
from dotmac_kernel.prerequisites import install_prerequisite_bindings
from sqlalchemy import create_engine, pool

from dotmac_cloud.migration_bindings import ASSEMBLY_PREREQUISITE_BINDINGS
from dotmac_cloud.migration_lineages import compose_lineages
from dotmac_cloud.module_planes import MODULE_PLANE_SELECTIONS
from dotmac_cloud.models import Base

config = context.config


# Installed BEFORE the revision map is built. A composed module's migration
# resolves the effects it declares from these bindings at script-load time, so
# an assembly that composes a module without answering what it requires fails
# loudly here rather than ordering wrongly.
install_prerequisite_bindings(ASSEMBLY_PREREQUISITE_BINDINGS)

# Every composed module here is dual-plane and the kernel refuses to build a
# graph until this assembly says which plane it installs. Cloud always says
# tenant — see `src/dotmac_cloud/module_planes.py`.
install_module_plane_selections(MODULE_PLANE_SELECTIONS)

# `src/dotmac_cloud/migration_lineages.py` owns WHICH lineages are composed and
# WHY appending to the live `ScriptDirectory` is the only thing that works here.
compose_lineages(context.script)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_url() -> str:
    value = os.environ.get("DOTMAC_CLOUD_MIGRATION_DATABASE_URL")
    if value is None or not value.strip():
        raise RuntimeError(
            "DOTMAC_CLOUD_MIGRATION_DATABASE_URL must be installed for migrations"
        )
    return value


def run_migrations_offline() -> None:
    """Emit SQL without opening a database connection."""
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through the separately supplied admin connection."""
    connectable = create_engine(_migration_url(), poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
