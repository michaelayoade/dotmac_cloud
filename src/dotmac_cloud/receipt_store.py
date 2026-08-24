"""PostgreSQL implementation of Cloud's tenant-scoped ReceiptLedger seam.

The append path does NOT decide at-most-once for itself. It delegates to
``dotmac_kernel.idempotency.execute_once``, the single owner of that decision
fleet-wide (Starter ADR-0014), and supplies only what an assembly is entitled
to supply: the identity of the hand-off and a fingerprint of what was handled.

Before the kernel was composed this module carried its own lookup, savepoint
insert, ``IntegrityError`` replay and divergence refusal. That is the same
mechanism under a different name — a second engine answering "has this been
done" inside an assembly, which is exactly the parallel authority this
composition exists to prevent. It is now one ledger row in
``idempotency_records`` and one receipt row written in the SAME transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from dotmac_kernel.fingerprints import fingerprint_of
from dotmac_kernel.idempotency import IdempotencyConflict, execute_once
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from dotmac_cloud.models import AdapterReceiptRow
from dotmac_cloud.receipts import AdapterReceipt, FactKey

__all__ = ["RECEIPT_SCOPE", "IdempotencyConflict", "SqlAlchemyReceiptLedger"]

# The operation family this ledger spends idempotency keys on. An open string,
# not an enum, per the kernel's registry principle (ADR-0008). Deliberately not
# an endpoint or a transport name: the same hand-off reached through a poll, a
# webhook or a repair job must land on the same ledger entry.
RECEIPT_SCOPE = "cloud.adapter_receipt"


def _identity_key(receipt: AdapterReceipt) -> str:
    """Return the idempotency key for one exact adapter hand-off.

    A digest rather than a readable composite because the parts are unbounded
    against the kernel's 200-character key limit — ``source_ref`` alone may be
    255. Truncating a readable key would silently merge two distinct facts into
    one ledger entry, which is the precise failure the ledger exists to stop.
    ``operation_name`` carries the human-readable "what was this key spent on".
    """
    return fingerprint_of(
        {
            "adapter": receipt.adapter,
            "source_owner": receipt.fact.key.source_owner,
            "source_ref": receipt.fact.key.source_ref,
            "source_version": receipt.fact.source_version,
        }
    )


def _handled_fingerprint(receipt: AdapterReceipt) -> str:
    """Return a digest of WHAT was handled, so a replay of something else fails.

    It covers the publisher's own content digest AND this application's outcome.
    The content digest alone would let the same fact version be recorded first
    as applied and later as refused without complaint, and an adapter that
    changed its mind about a fact it already acted on is a defect, not a
    duplicate.
    """
    return fingerprint_of(
        {"content": receipt.fact.fingerprint, "outcome": receipt.outcome.value}
    )


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
        """Append once, replay identical evidence, and refuse divergence.

        Raises ``IdempotencyConflict`` — the kernel's verdict, not one this
        module reproduces — when the same hand-off identity comes back carrying
        different content or a different outcome.
        """
        if not isinstance(receipt, AdapterReceipt):
            raise ValueError("receipt must be an AdapterReceipt")

        def _write(db: Session) -> Mapping[str, object]:
            row = AdapterReceiptRow.from_receipt(
                tenant_id=self._tenant_id,
                receipt=receipt,
            )
            db.add(row)
            db.flush()
            return {"receipt_id": str(row.id)}

        execute_once(
            self._db,
            tenant_id=self._tenant_id,
            scope=RECEIPT_SCOPE,
            key=_identity_key(receipt),
            operation=_write,
            operation_name=f"receipt:{receipt.adapter}",
            fingerprint=_handled_fingerprint(receipt),
        )
