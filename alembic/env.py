"""Cloud assembly migration environment.

Two lineages share one revision graph here: the KERNEL base lineage, shipped as
package data inside the exact-pinned ``dotmac-kernel`` distribution, and this
assembly's own ``alembic/versions``. They stay separately owned — Cloud never
edits a kernel revision — and are ordered by ``depends_on`` declared on the
assembly's own migrations, never by renumbering someone else's.

The kernel lineage is appended HERE rather than named in ``alembic.ini`` because
its path depends on the virtualenv layout and the interpreter version, which
differ between a checkout, the container and CI. A missing kernel lineage is a
composition error rather than something to skip: the exact pin in
``pyproject.toml`` says the distribution is installed, and continuing without it
would run ``alembic upgrade heads`` against a database with no ``tenants`` and
no idempotency ledger while reporting success.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotmac_kernel.migrations import versions_dir as kernel_versions_dir
from sqlalchemy import create_engine, pool

from dotmac_cloud.models import Base

config = context.config


def _compose_kernel_lineage() -> None:
    """Append the kernel's shipped revisions to the live script directory.

    Deliberately NOT `config.set_main_option("version_locations", ...)`: Alembic
    reads that key in `ScriptDirectory.from_config`, which has already run by the
    time this file executes, so rewriting the config here changes nothing and
    fails later with a `KeyError` on the kernel revision this assembly depends
    on. The `ScriptDirectory` itself is still mutable — its revision map is lazy
    and is not materialized until `run_migrations` — so the lineage is appended
    to the object that will actually be read.
    """
    script = context.script
    location = str(kernel_versions_dir())
    if location not in script.version_locations:
        script.version_locations.append(location)


_compose_kernel_lineage()

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
