from __future__ import annotations

import os
from collections.abc import Generator
from uuid import UUID

import pytest
from dotmac_kernel.idempotency_models import IdempotencyRecord
from sqlalchemy import create_engine, delete, text
from sqlalchemy.engine import Connection, Engine

from dotmac_cloud.models import AdapterReceiptRow

# Composing the kernel makes `tenants` real in this database, and
# `idempotency_records.tenant_id` carries a FOREIGN KEY to it. A receipt can no
# longer be written for a tenant this application has never heard of — which is
# the point — so the canaries seed the two tenants they isolate between.
TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = UUID("22222222-2222-4222-8222-222222222222")


def _required_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def app_database_url() -> str:
    return _required_url("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def admin_engine() -> Generator[Engine, None, None]:
    engine = create_engine(_required_url("TEST_MIGRATION_DATABASE_URL"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def seeded_tenants(admin_engine: Engine) -> None:
    """Make the isolation canaries' tenants exist, without owning tenancy."""
    with admin_engine.begin() as connection:
        for tenant_id, slug in ((TENANT_A, "canary-a"), (TENANT_B, "canary-b")):
            connection.execute(
                text(
                    "INSERT INTO tenants (id, slug, name) "
                    "VALUES (:id, :slug, :name) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": tenant_id, "slug": slug, "name": slug},
            )


@pytest.fixture(autouse=True)
def clean_receipts(admin_engine: Engine) -> Generator[None, None, None]:
    """Reset BOTH the receipt rows and the ledger entries that gate them.

    Clearing only the receipts would leave the idempotency records behind, and
    the next test appending the same identity would correctly REPLAY instead of
    writing — a green suite that proved nothing.
    """

    def _reset(connection: Connection) -> None:
        connection.execute(delete(AdapterReceiptRow))
        connection.execute(delete(IdempotencyRecord))

    with admin_engine.begin() as connection:
        _reset(connection)
    yield
    with admin_engine.begin() as connection:
        _reset(connection)
