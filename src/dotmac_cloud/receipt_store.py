"""PostgreSQL implementation of Cloud's tenant-scoped ReceiptLedger seam."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dotmac_cloud.models import AdapterReceiptRow
from dotmac_cloud.receipts import AdapterReceipt, FactKey

__all__ = ["ReceiptConflict", "SqlAlchemyReceiptLedger"]


class ReceiptConflict(ValueError):
    """One exact fact identity was reused with different evidence."""


class SqlAlchemyReceiptLedger:
    """Append and read receipts inside the caller-owned transaction."""

    def __init__(self, db: Session, tenant_id: UUID) -> None:
        if not isinstance(db, Session):
            raise ValueError("db must be a SQLAlchemy Session")
        if not isinstance(tenant_id, UUID):
            raise ValueError("tenant_id must be a UUID")
        self._db = db
        self._tenant_id = tenant_id

    def receipts_for(
        self, adapter: str, keys: Iterable[FactKey]
    ) -> tuple[AdapterReceipt, ...]:
        """Read this tenant's receipt history for the requested identities."""
        if not isinstance(adapter, str) or not adapter.strip():
            raise ValueError("adapter must be a non-empty string")
        identities = sorted({(key.source_owner, key.source_ref) for key in keys})
        if not identities:
            return ()
        rows = self._db.scalars(
            select(AdapterReceiptRow)
            .where(
                AdapterReceiptRow.tenant_id == self._tenant_id,
                AdapterReceiptRow.adapter == adapter,
                tuple_(
                    AdapterReceiptRow.source_owner,
                    AdapterReceiptRow.source_ref,
                ).in_(identities),
            )
            .order_by(
                AdapterReceiptRow.source_owner,
                AdapterReceiptRow.source_ref,
                AdapterReceiptRow.source_version,
            )
        )
        return tuple(row.to_receipt() for row in rows)

    def append(self, receipt: AdapterReceipt) -> None:
        """Append once, replay identical evidence, and refuse divergence."""
        if not isinstance(receipt, AdapterReceipt):
            raise ValueError("receipt must be an AdapterReceipt")
        existing = self._exact(receipt)
        if existing is not None:
            self._require_same(existing, receipt)
            return

        try:
            with self._db.begin_nested():
                self._db.add(
                    AdapterReceiptRow.from_receipt(
                        tenant_id=self._tenant_id,
                        receipt=receipt,
                    )
                )
                self._db.flush()
        except IntegrityError:
            winner = self._exact(receipt)
            if winner is None:
                raise
            self._require_same(winner, receipt)

    def _exact(self, receipt: AdapterReceipt) -> AdapterReceiptRow | None:
        return self._db.scalar(
            select(AdapterReceiptRow).where(
                AdapterReceiptRow.tenant_id == self._tenant_id,
                AdapterReceiptRow.adapter == receipt.adapter,
                AdapterReceiptRow.source_owner == receipt.fact.key.source_owner,
                AdapterReceiptRow.source_ref == receipt.fact.key.source_ref,
                AdapterReceiptRow.source_version == receipt.fact.source_version,
            )
        )

    @staticmethod
    def _require_same(existing: AdapterReceiptRow, receipt: AdapterReceipt) -> None:
        if existing.fingerprint != receipt.fact.fingerprint:
            raise ReceiptConflict(
                "the exact adapter fact version already has a different fingerprint"
            )
        if existing.outcome != receipt.outcome.value:
            raise ReceiptConflict(
                "the exact adapter fact version already has a different outcome"
            )
