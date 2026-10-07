import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import DeclarationStatus, EntryKind, ExpenseMethod


class TaxpayerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(pattern=r"^[A-Z]{2}\d{8,10}$", examples=["CZ8001011234"])
    data_box_id: str | None = Field(default=None, pattern=r"^[a-z0-9]{7}$")


class TaxpayerOut(TaxpayerIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class EntryIn(BaseModel):
    kind: EntryKind
    amount_cents: int = Field(gt=0, le=10_000_000_000)
    occurred_on: date
    category: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class EntryOut(EntryIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class Totals(BaseModel):
    income_cents: int
    actual_expenses_cents: int
    claimed_expenses_cents: int
    tax_base_cents: int
    tax_before_credit_cents: int
    credit_cents: int
    tax_due_cents: int


class DeclarationIn(BaseModel):
    tax_year: int = Field(ge=2000, le=2100)
    expense_method: ExpenseMethod = ExpenseMethod.actual


class DeclarationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    taxpayer_id: uuid.UUID
    tax_year: int
    expense_method: ExpenseMethod
    status: DeclarationStatus
    totals: Totals
    xml_sha256: str
    receipt_id: str | None
    submitted_at: datetime | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: str
    details: dict
    created_at: datetime
