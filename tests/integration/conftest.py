from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine

from dotmac_cloud.models import AdapterReceiptRow


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


@pytest.fixture(autouse=True)
def clean_receipts(admin_engine: Engine) -> Generator[None, None, None]:
    with admin_engine.begin() as connection:
        connection.execute(delete(AdapterReceiptRow))
    yield
    with admin_engine.begin() as connection:
        connection.execute(delete(AdapterReceiptRow))
