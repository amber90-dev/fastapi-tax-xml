import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_session
from app.models import AuditLog, Declaration, DeclarationStatus, ExpenseMethod, LedgerEntry, Taxpayer
from app.schemas import (
    AuditOut,
    DeclarationIn,
    DeclarationOut,
    EntryIn,
    EntryOut,
    TaxpayerIn,
    TaxpayerOut,
    Totals,
)
from app.services.submission import SubmissionGateway, get_gateway
from app.services.tax import compute_totals
from app.services.xml_builder import XmlValidationError, build_declaration_xml, sha256, validate_xml


@asynccontextmanager
async def lifespan(_: FastAPI):
    # For the demo the tables are created on start-up; a production deploy would run migrations.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Tax Declaration XML API",
    description="Record income and expenses, generate an XSD-validated tax declaration, "
    "approve it, and submit it through a pluggable gateway.",
    version="1.0.0",
    lifespan=lifespan,
)

SessionDep = Annotated[Session, Depends(get_session)]
LOCKED = {DeclarationStatus.approved, DeclarationStatus.submitted}


def audit(session: Session, entity: str, entity_id: uuid.UUID, action: str, **details) -> None:
    session.add(AuditLog(entity=entity, entity_id=str(entity_id), action=action, details=details))


def get_taxpayer(session: Session, taxpayer_id: uuid.UUID) -> Taxpayer:
    taxpayer = session.get(Taxpayer, taxpayer_id)
    if not taxpayer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Taxpayer not found")
    return taxpayer


def get_declaration(session: Session, declaration_id: uuid.UUID) -> Declaration:
    declaration = session.get(Declaration, declaration_id)
    if not declaration:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Declaration not found")
    return declaration


def year_entries(session: Session, taxpayer_id: uuid.UUID, year: int) -> list[LedgerEntry]:
    return list(
        session.scalars(
            select(LedgerEntry)
            .where(
                LedgerEntry.taxpayer_id == taxpayer_id,
                LedgerEntry.occurred_on >= date(year, 1, 1),
                LedgerEntry.occurred_on <= date(year, 12, 31),
            )
            .order_by(LedgerEntry.occurred_on)
        )
    )


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


# --- Taxpayers and ledger -------------------------------------------------------------------


@app.post("/taxpayers", response_model=TaxpayerOut, status_code=201, tags=["taxpayers"])
def create_taxpayer(payload: TaxpayerIn, session: SessionDep):
    taxpayer = Taxpayer(**payload.model_dump())
    session.add(taxpayer)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A taxpayer with this tax ID already exists")
    audit(session, "taxpayer", taxpayer.id, "created")
    session.commit()
    return taxpayer


@app.get("/taxpayers/{taxpayer_id}", response_model=TaxpayerOut, tags=["taxpayers"])
def read_taxpayer(taxpayer_id: uuid.UUID, session: SessionDep):
    return get_taxpayer(session, taxpayer_id)


@app.post("/taxpayers/{taxpayer_id}/entries", response_model=EntryOut, status_code=201, tags=["ledger"])
def add_entry(taxpayer_id: uuid.UUID, payload: EntryIn, session: SessionDep):
    get_taxpayer(session, taxpayer_id)
    locked = session.scalar(
        select(Declaration).where(
            Declaration.taxpayer_id == taxpayer_id,
            Declaration.tax_year == payload.occurred_on.year,
            Declaration.status.in_(LOCKED),
        )
    )
    if locked:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The {payload.occurred_on.year} declaration is {locked.status.value}; that year is closed",
        )
    entry = LedgerEntry(taxpayer_id=taxpayer_id, **payload.model_dump())
    session.add(entry)
    session.flush()
    audit(session, "ledger_entry", entry.id, "created", kind=entry.kind.value, amount_cents=entry.amount_cents)
    session.commit()
    return entry


@app.get("/taxpayers/{taxpayer_id}/entries", response_model=list[EntryOut], tags=["ledger"])
def list_entries(taxpayer_id: uuid.UUID, session: SessionDep, year: int = Query(ge=2000, le=2100)):
    get_taxpayer(session, taxpayer_id)
    return year_entries(session, taxpayer_id, year)


@app.get("/taxpayers/{taxpayer_id}/summary", response_model=Totals, tags=["ledger"])
def preview_totals(
    taxpayer_id: uuid.UUID,
    session: SessionDep,
    year: int = Query(ge=2000, le=2100),
    expense_method: ExpenseMethod = ExpenseMethod.actual,
):
    get_taxpayer(session, taxpayer_id)
    return compute_totals(year_entries(session, taxpayer_id, year), expense_method, settings)


# --- Declarations ---------------------------------------------------------------------------


@app.post("/taxpayers/{taxpayer_id}/declarations", response_model=DeclarationOut, tags=["declarations"])
def generate_declaration(taxpayer_id: uuid.UUID, payload: DeclarationIn, session: SessionDep, response: Response):
    """Create the year's declaration, or regenerate it while it is still a draft."""
    taxpayer = get_taxpayer(session, taxpayer_id)
    entries = year_entries(session, taxpayer_id, payload.tax_year)
    if not entries:
        raise HTTPException(422, f"No entries recorded for {payload.tax_year}")

    declaration = session.scalar(
        select(Declaration).where(Declaration.taxpayer_id == taxpayer_id, Declaration.tax_year == payload.tax_year)
    )
    if declaration and declaration.status in LOCKED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Declaration is already {declaration.status.value}")

    created = declaration is None
    declaration = declaration or Declaration(id=uuid.uuid4(), taxpayer_id=taxpayer_id, tax_year=payload.tax_year)
    totals = compute_totals(entries, payload.expense_method, settings)
    try:
        xml = build_declaration_xml(
            declaration_id=str(declaration.id),
            tax_year=payload.tax_year,
            taxpayer=taxpayer,
            method=payload.expense_method,
            totals=totals,
        )
    except XmlValidationError as exc:
        raise HTTPException(422, {"xml_errors": exc.errors})

    declaration.expense_method = payload.expense_method
    declaration.status = DeclarationStatus.draft
    declaration.totals = totals.model_dump()
    declaration.xml = xml
    declaration.xml_sha256 = sha256(xml)
    session.add(declaration)
    audit(
        session,
        "declaration",
        declaration.id,
        "generated" if created else "regenerated",
        entries=len(entries),
        tax_due_cents=totals.tax_due_cents,
        xml_sha256=declaration.xml_sha256,
    )
    session.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return declaration


@app.get("/declarations/{declaration_id}", response_model=DeclarationOut, tags=["declarations"])
def read_declaration(declaration_id: uuid.UUID, session: SessionDep):
    return get_declaration(session, declaration_id)


@app.get("/declarations/{declaration_id}/xml", tags=["declarations"], response_class=Response)
def download_xml(declaration_id: uuid.UUID, session: SessionDep):
    declaration = get_declaration(session, declaration_id)
    filename = f"declaration-{declaration.tax_year}-{declaration.id}.xml"
    return Response(
        declaration.xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/declarations/{declaration_id}/approve", response_model=DeclarationOut, tags=["declarations"])
def approve_declaration(declaration_id: uuid.UUID, session: SessionDep):
    declaration = get_declaration(session, declaration_id)
    if declaration.status != DeclarationStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only drafts can be approved (status: {declaration.status.value})")
    declaration.status = DeclarationStatus.approved
    audit(session, "declaration", declaration.id, "approved", xml_sha256=declaration.xml_sha256)
    session.commit()
    return declaration


@app.post("/declarations/{declaration_id}/submit", response_model=DeclarationOut, tags=["declarations"])
def submit_declaration(
    declaration_id: uuid.UUID,
    session: SessionDep,
    gateway: Annotated[SubmissionGateway, Depends(get_gateway)],
):
    """Submit an approved declaration. Calling it again returns the stored receipt instead of resubmitting."""
    declaration = get_declaration(session, declaration_id)
    if declaration.status == DeclarationStatus.submitted:
        return declaration
    if declaration.status != DeclarationStatus.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, "Approve the declaration before submitting it")
    if sha256(declaration.xml) != declaration.xml_sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stored XML changed after approval; regenerate and approve again")

    receipt = gateway.submit(declaration_id=str(declaration.id), xml=declaration.xml)
    if not receipt.accepted:
        declaration.status = DeclarationStatus.rejected
        audit(session, "declaration", declaration.id, "rejected", message=receipt.message)
        session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, receipt.message)

    declaration.status = DeclarationStatus.submitted
    declaration.receipt_id = receipt.receipt_id
    declaration.submitted_at = datetime.now(timezone.utc)
    audit(session, "declaration", declaration.id, "submitted", receipt_id=receipt.receipt_id)
    session.commit()
    return declaration


@app.get("/declarations/{declaration_id}/audit", response_model=list[AuditOut], tags=["declarations"])
def declaration_audit(declaration_id: uuid.UUID, session: SessionDep):
    get_declaration(session, declaration_id)
    return list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "declaration", AuditLog.entity_id == str(declaration_id))
            .order_by(AuditLog.id)
        )
    )


@app.post("/xml/validate", tags=["xml"])
def validate_declaration_xml(xml: Annotated[str, Body(media_type="application/xml")]) -> dict:
    """Check any declaration XML against the schema and return every error found."""
    try:
        validate_xml(xml)
    except XmlValidationError as exc:
        return {"valid": False, "errors": exc.errors}
    return {"valid": True, "errors": []}
