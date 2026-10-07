from datetime import date
from decimal import Decimal

from app.config import Settings
from app.models import EntryKind, ExpenseMethod, LedgerEntry
from app.services.tax import compute_totals

RULES = Settings(
    income_tax_rate=Decimal("0.15"),
    taxpayer_credit_cents=3_084_000,
    flat_rate_expense_share=Decimal("0.60"),
    flat_rate_expense_cap_cents=120_000_000,
)


def entry(kind, cents):
    return LedgerEntry(kind=kind, amount_cents=cents, occurred_on=date(2025, 5, 1), category="x")


def test_actual_expenses():
    entries = [entry(EntryKind.income, 100_000_000), entry(EntryKind.expense, 20_000_050)]
    t = compute_totals(entries, ExpenseMethod.actual, RULES)
    assert t.claimed_expenses_cents == 20_000_050
    assert t.tax_base_cents == 79_999_900  # rounded down to whole units
    assert t.tax_before_credit_cents == 11_999_985
    assert t.tax_due_cents == 11_999_985 - 3_084_000


def test_flat_rate_ignores_actual_expenses_and_respects_cap():
    entries = [entry(EntryKind.income, 300_000_000), entry(EntryKind.expense, 1_000)]
    t = compute_totals(entries, ExpenseMethod.flat_rate, RULES)
    assert t.actual_expenses_cents == 1_000
    assert t.claimed_expenses_cents == 120_000_000  # 60% would be 180M, capped


def test_loss_never_produces_negative_tax():
    entries = [entry(EntryKind.income, 1_000_000), entry(EntryKind.expense, 5_000_000)]
    t = compute_totals(entries, ExpenseMethod.actual, RULES)
    assert t.tax_base_cents == 0
    assert t.tax_due_cents == 0


def test_credit_cannot_exceed_tax():
    entries = [entry(EntryKind.income, 10_000_000)]
    t = compute_totals(entries, ExpenseMethod.actual, RULES)
    assert t.credit_cents == t.tax_before_credit_cents
    assert t.tax_due_cents == 0
