"""Builds the declaration XML and validates it against the XSD before anything is stored."""

import hashlib
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from lxml import etree

from app.models import ExpenseMethod, Taxpayer
from app.schemas import Totals

NS = "urn:example:tax-declaration:v1"
XSD_PATH = Path(__file__).resolve().parent.parent / "xsd" / "declaration.xsd"


class XmlValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@lru_cache
def _schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(XSD_PATH)))


def _el(parent: etree._Element, name: str, text: str | int | None = None) -> etree._Element:
    child = etree.SubElement(parent, f"{{{NS}}}{name}")
    if text is not None:
        child.text = str(text)
    return child


def build_declaration_xml(
    *,
    declaration_id: str,
    tax_year: int,
    taxpayer: Taxpayer,
    method: ExpenseMethod,
    totals: Totals,
    generated_at: datetime | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    root = etree.Element(f"{{{NS}}}Declaration", nsmap={None: NS}, version="1.0")

    header = _el(root, "Header")
    _el(header, "TaxYear", tax_year)
    _el(header, "GeneratedAt", generated_at.replace(microsecond=0).isoformat())
    _el(header, "DeclarationId", declaration_id)

    person = _el(root, "Taxpayer")
    _el(person, "FullName", taxpayer.full_name)
    _el(person, "TaxId", taxpayer.tax_id)
    if taxpayer.data_box_id:
        _el(person, "DataBoxId", taxpayer.data_box_id)

    business = _el(root, "Business")
    _el(business, "ExpenseMethod", method.value)
    _el(business, "IncomeCents", totals.income_cents)
    _el(business, "ClaimedExpensesCents", totals.claimed_expenses_cents)

    calc = _el(root, "Calculation")
    _el(calc, "TaxBaseCents", totals.tax_base_cents)
    _el(calc, "TaxBeforeCreditCents", totals.tax_before_credit_cents)
    _el(calc, "CreditCents", totals.credit_cents)
    _el(calc, "TaxDueCents", totals.tax_due_cents)

    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True).decode()
    validate_xml(xml)
    return xml


def validate_xml(xml: str) -> None:
    """Raise XmlValidationError with every schema error, line by line."""
    try:
        doc = etree.fromstring(xml.encode())
    except etree.XMLSyntaxError as exc:
        raise XmlValidationError([f"Malformed XML: {exc}"]) from exc
    schema = _schema()
    if not schema.validate(doc):
        raise XmlValidationError([f"line {e.line}: {e.message}" for e in schema.error_log])


def sha256(xml: str) -> str:
    return hashlib.sha256(xml.encode()).hexdigest()
