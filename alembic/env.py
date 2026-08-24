"""Cloud assembly migration environment."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from dotmac_cloud.models import Base

config = context.config

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
