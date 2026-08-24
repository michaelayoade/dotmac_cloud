"""Cloud assembly-owned persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from dotmac_cloud.receipts import (
    AdapterReceipt,
    FactKey,
    ReceiptOutcome,
    SourceFact,
)

__all__ = ["AdapterReceiptRow", "Base"]


class Base(DeclarativeBase):
    """Declarative base for Cloud assembly-owned tables."""


class AdapterReceiptRow(Base):
    """Append-only durable evidence for one exact adapter hand-off."""

    __tablename__ = "cloud_adapter_receipts"
    __table_args__ = (
        CheckConstraint("source_version > 0", name="ck_cloud_receipt_version_positive"),
        CheckConstraint(
            "outcome IN ('applied', 'refused')",
            name="ck_cloud_receipt_outcome",
        ),
        UniqueConstraint(
            "tenant_id",
            "adapter",
            "source_owner",
            "source_ref",
            "source_version",
            name="uq_cloud_receipt_exact_fact",
        ),
        Index(
            "ix_cloud_receipt_reconciliation",
            "tenant_id",
            "adapter",
            "source_owner",
            "source_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    adapter: Mapped[str] = mapped_column(String(120), nullable=False)
    source_owner: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    @classmethod
    def from_receipt(cls, *, tenant_id: UUID, receipt: AdapterReceipt) -> Self:
        """Build the persistence row without changing transaction state."""
        return cls(
            tenant_id=tenant_id,
            adapter=receipt.adapter,
            source_owner=receipt.fact.key.source_owner,
            source_ref=receipt.fact.key.source_ref,
            source_version=receipt.fact.source_version,
            fingerprint=receipt.fact.fingerprint,
            outcome=receipt.outcome.value,
            observed_at=receipt.observed_at,
        )

    def to_receipt(self) -> AdapterReceipt:
        """Return the published persistence-neutral receipt contract."""
        return AdapterReceipt(
            adapter=self.adapter,
            fact=SourceFact(
                key=FactKey(
                    source_owner=self.source_owner,
                    source_ref=self.source_ref,
                ),
                source_version=self.source_version,
                fingerprint=self.fingerprint,
            ),
            outcome=ReceiptOutcome(self.outcome),
            observed_at=self.observed_at,
        )
