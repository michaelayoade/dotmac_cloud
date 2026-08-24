from __future__ import annotations

import pytest

from dotmac_cloud.runtime import DatabaseConfiguration, RuntimeConfigurationError


def test_database_configuration_is_loaded_explicitly() -> None:
    config = DatabaseConfiguration.from_environment(
        {"DOTMAC_CLOUD_DATABASE_URL": ("postgresql+psycopg://app_user:secret@db/cloud")}
    )

    assert config.database_url.endswith("@db/cloud")
    assert "secret" not in repr(config)


def test_database_configuration_has_no_implicit_default() -> None:
    with pytest.raises(RuntimeConfigurationError, match="DOTMAC_CLOUD_DATABASE_URL"):
        DatabaseConfiguration.from_environment({})
