"""Explicit installation of the Cloud runtime.

Configuration is read only when the assembly is installed, never at import
time. The database URL is held as process material and excluded from repr so a
diagnostic cannot accidentally disclose it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from dotmac_cloud.database import DatabaseRuntime

__all__ = [
    "CloudRuntime",
    "DatabaseConfiguration",
    "RuntimeConfigurationError",
    "install_runtime",
]


class RuntimeConfigurationError(ValueError):
    """The process was not given a complete, usable runtime configuration."""


@dataclass(frozen=True, slots=True)
class DatabaseConfiguration:
    """Held database connection material for one installed process."""

    database_url: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise RuntimeConfigurationError("database_url must be a non-empty string")

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> DatabaseConfiguration:
        """Install the database material supplied to this process.

        This is a loader, not a settings precedence layer: there is no default,
        fallback, remote lookup or secret-reference dereference.
        """
        source = os.environ if environ is None else environ
        value = source.get("DOTMAC_CLOUD_DATABASE_URL")
        if value is None or not value.strip():
            raise RuntimeConfigurationError(
                "DOTMAC_CLOUD_DATABASE_URL must be installed for this process"
            )
        return cls(database_url=value)


@dataclass(slots=True)
class CloudRuntime:
    """Resources owned by one running Cloud process."""

    database: DatabaseRuntime

    def close(self) -> None:
        """Release process-owned resources."""
        self.database.dispose()


def install_runtime(
    configuration: DatabaseConfiguration | None = None,
) -> CloudRuntime:
    """Install one runtime from explicit or process-provided material."""
    selected = configuration or DatabaseConfiguration.from_environment()
    return CloudRuntime(database=DatabaseRuntime(selected.database_url))
