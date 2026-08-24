"""Runtime installation errors with secret-safe messages."""

from __future__ import annotations

__all__ = ["DatabaseInstallationError"]


class DatabaseInstallationError(RuntimeError):
    """The process cannot install its PostgreSQL runtime."""
