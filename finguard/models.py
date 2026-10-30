"""Financial document models: invoice → normalized transaction → ledger entry."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

TYPES = ("expense", "income", "transfer")
CATEGORIES = (
    "استضافة وتقنية", "برمجيات واشتراكات", "تسويق وإعلانات", "رواتب ومكافآت",
    "إيجارات ومرافق", "مواصلات وشحن", "مشتريات ومخزون", "ضرائب ورسوم",
    "خدمات مهنية", "صحة وتأمين", "تعليم وتدريب", "أخرى",
)


def _now() -> float:
    return time.time()


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass
class Transaction:
    """قيمة مالية واحدة مستخرجة من فاتورة أو كشف أو إشعار بريدي."""

    date: str = ""                       # YYYY-MM-DD
    vendor: str = ""
    description: str = ""
    currency: str = "USD"
    amount: float = 0.0                  # الإجمالي شامل الضريبة
    tax: float = 0.0
    net: float = 0.0                     # amount - tax
    kind: str = "expense"                # expense | income | transfer
    category: str = "أخرى"
    account: str = "6000"                # حساب الدليل المحاسبي
    invoice_no: str = ""
    source: str = ""                     # اسم الملف المصدر
    extractor: str = "text"               # text | pdf | ocr | csv | email | ai
    confidence: float = 0.6
    note: str = ""
    ai_label: str = ""                   # تصنيف مقترح من الذكاء الاصطناعي
    flags: List[str] = field(default_factory=list)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.net:
            self.net = round(self.amount - self.tax, 2)
        if not self.id:
            self.id = stable_id(self.date, self.vendor, self.amount, self.invoice_no or self.description[:40])

    @property
    def year_month(self) -> str:
        return (self.date or "0000-00")[:7]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transaction":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class LedgerEntry:
    """قيد ازدواجي مبسّط: كل معاملة تُقيَّد بطرفين متعادلين."""

    txn_id: str
    date: str
    debit_account: str      # حساب يُخصم (مصروف/أصول)
    credit_account: str     # حساب يُخصم منه (نقدية/بنك/إيراد)
    amount: float
    currency: str = "USD"
    memo: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


ACCOUNTS = {
    "1000": "نقدية بالخزينة",
    "1100": "بنك — جاري",
    "1200": "ذمم مدينة (مستحقات)",
    "2000": "ذمم دائنة (مستحقات)",
    "2100": "ضريبة القيمة المضافة المستحقة",
    "4000": "إيرادات المبيعات",
    "4100": "إيرادات أخرى",
    "5000": "تكلفة البضاعة المباعة",
    "6000": "مصروفات تشغيلية",
    "6100": "برمجيات واستضافة",
    "6200": "تسويق وإعلانات",
    "6300": "رواتب ومكافآت",
    "6400": "إيجارات ومرافق",
    "6500": "مواصلات وشحن",
    "6600": "ضرائب ورسوم",
    "6700": "خدمات مهنية",
    "6800": "أخرى",
}

CATEGORY_ACCOUNT = {
    "برمجيات واشتراكات": "6100",
    "استضافة وتقنية": "6100",
    "تسويق وإعلانات": "6200",
    "رواتب ومكافآت": "6300",
    "إيجارات ومرافق": "6400",
    "مواصلات وشحن": "6500",
    "ضرائب ورسوم": "6600",
    "خدمات مهنية": "6700",
    "صحة وتأمين": "6000",
    "تعليم وتدريب": "6000",
    "مشتريات ومخزون": "5000",
    "أخرى": "6800",
}


def account_for(category: str, kind: str) -> str:
    if kind == "income":
        return "4000"
    return CATEGORY_ACCOUNT.get(category, "6000")


@dataclass
class Batch:
    """نتيجة دفعة معالجة واحدة (مجلد فواتير أو ملف)."""

    transactions: List[Transaction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=_now)
    finished_at: float = 0.0

    def close(self) -> "Batch":
        self.finished_at = _now()
        return self

    @property
    def duration(self) -> float:
        end = self.finished_at or _now()
        return round(end - self.started_at, 2)

    @property
    def expenses(self) -> List[Transaction]:
        return [t for t in self.transactions if t.kind == "expense"]

    @property
    def income(self) -> List[Transaction]:
        return [t for t in self.transactions if t.kind == "income"]

    def totals(self, currency: Optional[str] = None) -> Dict[str, float]:
        rows = [t for t in self.transactions if not currency or t.currency == currency]
        spent = sum(t.amount for t in rows if t.kind == "expense")
        earned = sum(t.amount for t in rows if t.kind == "income")
        tax = sum(t.tax for t in rows)
        return {
            "income": round(earned, 2),
            "expense": round(spent, 2),
            "net": round(earned - spent, 2),
            "tax": round(tax, 2),
            "count": len(rows),
        }
