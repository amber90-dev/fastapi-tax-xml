"""Turns ledger entries into declaration totals.

The rules are deliberately simple and live in settings, so the calculation is easy to
test and to change per tax year. They are illustrative, not real tax law.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from app.config import Settings
from app.models import EntryKind, ExpenseMethod, LedgerEntry
from app.schemas import Totals


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_totals(entries: Iterable[LedgerEntry], method: ExpenseMethod, settings: Settings) -> Totals:
    income = sum(e.amount_cents for e in entries if e.kind == EntryKind.income)
    actual = sum(e.amount_cents for e in entries if e.kind == EntryKind.expense)

    if method == ExpenseMethod.flat_rate:
        claimed = min(
            _round_cents(Decimal(income) * settings.flat_rate_expense_share),
            settings.flat_rate_expense_cap_cents,
        )
    else:
        claimed = actual

    # Tax base is rounded down to whole currency units (100 cents), and never negative.
    base = max(income - claimed, 0) // 100 * 100
    before_credit = _round_cents(Decimal(base) * settings.income_tax_rate)
    credit = min(before_credit, settings.taxpayer_credit_cents)

    return Totals(
        income_cents=income,
        actual_expenses_cents=actual,
        claimed_expenses_cents=claimed,
        tax_base_cents=base,
        tax_before_credit_cents=before_credit,
        credit_cents=credit,
        tax_due_cents=before_credit - credit,
    )
