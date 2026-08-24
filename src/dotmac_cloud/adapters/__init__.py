"""Cloud-owned adapters between composed owners.

Business modules are peers and never import one another. Every hand-off between
two owners therefore passes through an adapter here, which translates one
owner's published output into another owner's published command and records the
receipt that makes the hand-off repairable.

An adapter decides nothing. It maps declared fields, refuses what it cannot map
rather than inventing a value, and leaves evidence either way.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
