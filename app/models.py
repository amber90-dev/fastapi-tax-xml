import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EntryKind(str, enum.Enum):
    income = "income"
    expense = "expense"


class ExpenseMethod(str, enum.Enum):
    actual = "actual"
    flat_rate = "flat_rate"


class DeclarationStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    submitted = "submitted"
    rejected = "rejected"


class Taxpayer(Base):
    __tablename__ = "taxpayers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str] = mapped_column(String(20), unique=True)
    data_box_id: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="taxpayer")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_entry_amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    kind: Mapped[EntryKind] = mapped_column(Enum(EntryKind, name="entry_kind"))
    # Money is stored in integer cents, never floats.
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    taxpayer: Mapped[Taxpayer] = relationship(back_populates="entries")


class Declaration(Base):
    __tablename__ = "declarations"
    # Only one declaration per taxpayer per year; regenerate it instead of creating duplicates.
    __table_args__ = (UniqueConstraint("taxpayer_id", "tax_year", name="uq_declaration_year"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    expense_method: Mapped[ExpenseMethod] = mapped_column(Enum(ExpenseMethod, name="expense_method"))
    status: Mapped[DeclarationStatus] = mapped_column(
        Enum(DeclarationStatus, name="declaration_status"), default=DeclarationStatus.draft
    )
    totals: Mapped[dict] = mapped_column(JSON)
    xml: Mapped[str] = mapped_column(Text)
    xml_sha256: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
