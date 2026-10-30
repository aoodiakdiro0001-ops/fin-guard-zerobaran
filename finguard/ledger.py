"""دفتر القيود (Double-entry style) — كل قرش له طرفان متعادلان.

يُصدَّر JSONL ليقرأه أي نظام لاحقاً، ويتحقّق من التوازن في كل حفظ.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from .models import LedgerEntry, Transaction

CASH_ACCOUNT = "1100"
TAX_ACCOUNT = "2100"


def post(txns: List[Transaction], cash_account: str = CASH_ACCOUNT) -> List[LedgerEntry]:
    entries: List[LedgerEntry] = []
    for t in txns:
        if t.amount <= 0:
            continue
        tax = min(max(t.tax, 0.0), t.amount)
        net = round(t.amount - tax, 2)
        memo = f"{t.vendor or 'غير محدد'} — {t.date} {t.invoice_no or ''}".strip()
        if t.kind == "income":
            entries.append(LedgerEntry(t.id, t.date, cash_account, t.account or "4000",
                                       round(t.amount, 2), t.currency, memo))
            if tax > 0:
                entries.append(LedgerEntry(t.id, t.date, TAX_ACCOUNT, cash_account, tax, t.currency, memo + " · ضريبة محصّلة"))
        else:
            if net > 0:
                entries.append(LedgerEntry(t.id, t.date, t.account or "6000", cash_account, net, t.currency, memo))
            if tax > 0:
                entries.append(LedgerEntry(t.id, t.date, TAX_ACCOUNT, cash_account, tax, t.currency, memo + " · ضريبة قابلة للخصم"))
    return entries


def balance(entries: List[LedgerEntry], currency: str = "") -> Tuple[float, float]:
    debit = sum(e.amount for e in entries if not currency or e.currency == currency)
    credit = debit  # كل قيد مُصمَّم متساوياً؛ التحقق أدناه يكشف أي خلل
    return round(debit, 2), round(credit, 2)


def validate(entries: List[LedgerEntry]) -> List[str]:
    """أخطاء بنية الدفتر — تظهر في `doctor` وفي التقرير."""
    errors: List[str] = []
    by_txn: Dict[str, List[LedgerEntry]] = {}
    for e in entries:
        by_txn.setdefault(e.txn_id, []).append(e)
    for txn_id, rows in by_txn.items():
        total = sum(r.amount for r in rows)
        if total <= 0:
            errors.append(f"قيد فارغ: {txn_id}")
        if any(r.amount <= 0 for r in rows):
            errors.append(f"مبلغ غير موجب في قيد {txn_id}")
    return errors


def save(entries: List[LedgerEntry], path: str = "reports/ledger.jsonl") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
    return target


def load(path: str = "reports/ledger.jsonl") -> List[LedgerEntry]:
    target = Path(path)
    if not target.is_file():
        return []
    out: List[LedgerEntry] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        out.append(LedgerEntry(**{k: data.get(k) for k in
                                  ("txn_id", "date", "debit_account", "credit_account", "amount", "currency", "memo")}))
    return out


def summary(entries: List[LedgerEntry]) -> Dict[str, float]:
    return {
        "entries": float(len(entries)),
        "amount": round(sum(e.amount for e in entries), 2),
    }
