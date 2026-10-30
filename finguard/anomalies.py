"""مدقيق الشذوذ المالي: تكرار، طفرة، تجاوز ميزانية، بيانات ناقصة.

حتمي بالكامل وبلا إنترنت — كل إشارة مفسَّرة ومربوطة بالقيود التي أدّت إليها.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import config
from .models import Transaction


@dataclass
class Anomaly:
    severity: str          # high | medium | low | info
    title: str
    detail: str
    remediation: str
    refs: List[str] = field(default_factory=list)
    amount: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _to_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value or "", "%Y-%m-%d")
    except ValueError:
        return None


def _median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def _to_base(amount: float, currency: str, base: str, rates: Dict[str, float]) -> float:
    """تحويل مبلغ إلى العملة الأساسية — وبصفر لعملة بلا سعر صرف (لا نخلط عملتين)."""
    cur = (currency or base).upper()
    if cur == base:
        return amount
    factor = rates.get(cur)
    return amount * factor if factor else 0.0


def check_duplicates(txns: List[Transaction], window_days: int = 7) -> List[Anomaly]:
    """نفس الجهة + نفس المبلغ + تواريخ متقاربة (≤ أسبوع) = تكرار محتمل.

    الدفعات الشهرية المتكرّرة (إيجار/اشتراك) ليست تكراراً — لذلك نافذة زمنية.
    """
    out: List[Anomaly] = []
    seen: Dict[tuple, List[Transaction]] = {}
    for t in txns:
        if t.kind != "expense" or t.amount <= 0:
            continue
        key = (t.vendor.strip().lower(), round(t.amount, 2), t.currency)
        seen.setdefault(key, []).append(t)
    for key, group in seen.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda g: g.date or "")
        clusters: List[List[Transaction]] = [[ordered[0]]]
        for row in ordered[1:]:
            prev = _to_date(clusters[-1][-1].date)
            curr = _to_date(row.date)
            if prev and curr and abs((curr - prev).days) <= window_days:
                clusters[-1].append(row)
            else:
                clusters.append([row])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            out.append(Anomaly(
                severity="high",
                title=f"فاتورة مكرّرة ×{len(cluster)} — {cluster[0].vendor or 'جهة غير محددة'}",
                detail=f"نفس المبلغ ({cluster[0].amount:,.2f} {cluster[0].currency}) ونفس الجهة في تواريخ: "
                       + ", ".join(sorted(x.date for x in cluster)),
                remediation="راجع الدفعة المكرّرة قبل السداد واستبعاد النسخة المكرّرة من السجل.",
                refs=[g.id for g in cluster],
                amount=round(sum(g.amount for g in cluster[1:]), 2),
            ))
    return out


def check_spikes(txns: List[Transaction]) -> List[Anomaly]:
    out: List[Anomaly] = []
    by_cat: Dict[tuple, List[Transaction]] = {}
    for t in txns:
        if t.kind == "expense" and t.amount > 0:
            by_cat.setdefault((t.category, t.currency), []).append(t)
    for (category, currency), rows in by_cat.items():
        if len(rows) < 4:
            continue
        amounts = [r.amount for r in rows]
        med = _median(amounts)
        if med <= 0:
            continue
        spread = _median([abs(a - med) for a in amounts]) or med * 0.25
        for row in rows:
            if row.amount > med + 4 * spread and row.amount > med * 2:
                out.append(Anomaly(
                    severity="medium",
                    title=f"مبلغ طافئ في «{category}» — {row.vendor or 'جهة غير محددة'}",
                    detail=f"{row.amount:,.2f} {row.currency} مقابل وسيط {med:,.2f} {currency} للتصنيف نفسه ({row.date})",
                    remediation="تأكد من صحة المبلغ ومن عدم إدخال مبلغ بقيمة مضاعفة (رقم عشري مفقود مثلاً).",
                    refs=[row.id],
                    amount=round(row.amount, 2),
                ))
    return out


def check_budget(txns: List[Transaction], budgets: Dict[str, float]) -> List[Anomaly]:
    out: List[Anomaly] = []
    if not budgets:
        return out
    base = config.base_currency().upper()
    rates = config.exchange_rates()
    spend: Dict[str, float] = {}
    for t in txns:
        if t.kind == "expense":
            value = _to_base(t.amount, t.currency, base, rates)
            if value:
                spend[t.category] = spend.get(t.category, 0.0) + value
    total_budget = budgets.get("__total__")
    for category, budget in budgets.items():
        if category.startswith("__") or budget <= 0:
            continue
        used = spend.get(category, 0.0)
        if used > budget:
            pct = 100.0 * used / budget
            out.append(Anomaly(
                severity="high" if pct >= 120 else "medium",
                title=f"تجاوز ميزانية «{category}» بنسبة {pct - 100:.0f}%",
                detail=f"المصروف {used:,.2f} {base} مقابل ميزانية {budget:,.2f} {base}",
                remediation="أعد توزيع الميزانية أو أخّر أي مصروف جديد في هذا التصنيف حتى نهاية الشهر.",
                refs=[t.id for t in txns if t.kind == "expense" and t.category == category],
                amount=round(used - budget, 2),
            ))
    if total_budget:
        used = sum(spend.values())
        if used > total_budget:
            out.append(Anomaly(
                severity="high",
                title=f"تجاوز الميزانية الشهرية الإجمالية ({used - total_budget:,.2f})",
                detail=f"المصروف {used:,.2f} {base} مقابل ميزانية {total_budget:,.2f} {base}",
                remediation="أوقف المصروفات غير الحرجة وراجع أعلى ثلاثة تصنيفات إنفاقاً.",
                amount=round(used - total_budget, 2),
            ))
    return out


def check_data_quality(txns: List[Transaction]) -> List[Anomaly]:
    out: List[Anomaly] = []
    for t in txns:
        problems = []
        if t.amount <= 0:
            problems.append("مبلغ غير مُستخرج")
        if not t.date:
            problems.append("تاريخ مفقود")
        if not t.vendor or t.vendor == "غير محدد":
            problems.append("جهة غير محددة")
        if t.tax > t.amount > 0:
            problems.append("ضريبة أكبر من الإجمالي")
        if problems:
            out.append(Anomaly(
                severity="low",
                title=f"بيانات ناقصة في {t.source or t.id}",
                detail=" · ".join(problems) + (f" — {t.vendor}" if t.vendor else ""),
                remediation="راجع الملف الأصلي وأعد المعالجة بعد إكمال الحقول الناقصة.",
                refs=[t.id],
                amount=round(t.amount, 2),
            ))
    return out


def check_cash_runway(txns: List[Transaction], opening_balance: float = 0.0) -> List[Anomaly]:
    base = config.base_currency().upper()
    rates = config.exchange_rates()
    income = sum(_to_base(t.amount, t.currency, base, rates) for t in txns if t.kind == "income")
    expense = sum(_to_base(t.amount, t.currency, base, rates) for t in txns if t.kind == "expense")
    if income <= 0 or expense <= 0:
        return []
    net = income - expense
    if net < 0:
        return [Anomaly(
            severity="high",
            title="التدفق النقدي سالب — المصروفات تفوق الإيرادات",
            detail=f"إيراد {income:,.2f} {base} مقابل مصروف {expense:,.2f} {base} (عجز {abs(net):,.2f})",
            remediation="خفّض المصروفات غير الحرجة أو أعد جدولة الدفعات القادمة.",
            amount=round(abs(net), 2),
        )]
    ratio = expense / income if income else 0
    if ratio > 0.9:
        return [Anomaly(
            severity="medium",
            title="هامش الربح أقل من 10%",
            detail=f"المصروف يبتلع {ratio * 100:.0f}% من الإيراد — صافي {net:,.2f} {base}",
            remediation="راجع بنود المصروفات الأعلى وحدّد ما يمكن تخفيضه هذا الشهر.",
            amount=round(net, 2),
        )]
    return []


def check_currencies(txns: List[Transaction], base: str, rates: Dict[str, float]) -> List[Anomaly]:
    """لا ندمج عملتين بلا سعر صرف — نُنبّه بدل أن نُظهر رقماً مُختلَقاً."""
    currencies = sorted({t.currency for t in txns if t.currency})
    missing = [c for c in currencies if c != base and c not in rates]
    if len(currencies) <= 1 or not missing:
        return []
    detail = " · ".join(
        f"{c}: {sum(t.amount for t in txns if t.currency == c and t.kind == 'expense'):,.2f} مصروف"
        for c in missing)
    return [Anomaly(
        severity="info",
        title=f"تعدد عملات دون سعر صرف ({', '.join(missing)})",
        detail=detail + f" — الإجماليات المجمّعة تُحسب بعملة {base} فقط.",
        remediation="أنشئ rates.json بأسعار الصرف (مثلاً {\"TRY\": 0.03}) لتُضم كل العملات في إجمالي واحد.",
    )]


def detect(txns: List[Transaction], budgets: Optional[Dict[str, float]] = None,
           opening_balance: float = 0.0) -> List[Anomaly]:
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    items = []
    items += check_duplicates(txns)
    items += check_budget(txns, budgets or {})
    items += check_cash_runway(txns, opening_balance)
    items += check_spikes(txns)
    items += check_currencies(txns, config.base_currency().upper(), config.exchange_rates())
    items += check_data_quality(txns)
    items.sort(key=lambda a: (order.get(a.severity, 9), -a.amount))
    return items
