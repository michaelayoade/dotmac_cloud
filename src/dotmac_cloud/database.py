"""The sole runtime database and transaction authority for Dotmac Cloud."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from dotmac_cloud.runtime_errors import DatabaseInstallationError

__all__ = ["DatabaseInstallationError", "DatabaseRuntime"]


class DatabaseRuntime:
    """Own the engine, sessions, transaction boundary and tenant scope."""

    def __init__(self, database_url: str) -> None:
        try:
            url = make_url(database_url)
        except ArgumentError:
            raise DatabaseInstallationError(
                "DOTMAC_CLOUD_DATABASE_URL is not a valid SQLAlchemy URL"
            ) from None
        if url.get_backend_name() != "postgresql":
            raise DatabaseInstallationError(
                "Dotmac Cloud requires PostgreSQL for tenant RLS enforcement"
            )
        self._engine: Engine = create_engine(url, pool_pre_ping=True)
        self._sessions: sessionmaker[Session] = sessionmaker(
            bind=self._engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @contextmanager
    def tenant_session(self, tenant_id: UUID) -> Generator[Session, None, None]:
        """Yield one transaction scoped to exactly one tenant.

        ``SET LOCAL`` expires with this transaction. A pooled connection can
        therefore never carry one tenant's scope into the next request or job.
        The boundary commits on success and rolls back on an exception;
        services only add and flush.
        """
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        db = self._sessions()
        try:
            with db.begin():
                db.execute(
                    text(
                        "SELECT set_config(" "'app.current_tenant', :tenant_id, true)"
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                yield db
        finally:
            db.close()

    def dispose(self) -> None:
        """Release this process's connection pool."""
        self._engine.dispose()
