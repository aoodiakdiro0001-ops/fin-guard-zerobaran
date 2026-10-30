"""طبقة التوصيل الفوري: تنبيهات تليجرام — مع تعقيم إلزامي قبل الإرسال.

كل رسالة تمرّ عبر privacy.redact: لا رقم بطاقة ولا آيبان يخرج كاملاً.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from . import config
from .models import Transaction
from .privacy import redact

SEV_ICON = {"high": "🚨", "medium": "⚠️", "low": "🔵", "info": "ℹ️"}
SEV_LABEL = {"high": "حرج", "medium": "متوسط", "low": "منخفض", "info": "معلومة"}


def _send(text: str) -> str:
    cfg = config.telegram_cfg()
    if not cfg:
        return "telegram: غير مضبوط (تخطّي)"
    clean, _ = redact(text)
    payload = urllib.parse.urlencode({
        "chat_id": cfg["chat_id"],
        "text": clean[:3900],
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
        data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data: Dict[str, Any] = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        return f"telegram: فشل الإرسال ({getattr(exc, 'code', 'شبكة')})"
    return "telegram: أُرسل" if data.get("ok") else f"telegram: {data.get('description', 'خطأ')}"


def expense_message(txn: Transaction) -> str:
    lines = [
        "💰 تم تسجيل مصروف جديد",
        f"• المبلغ: {txn.amount:,.2f} {txn.currency}",
        f"• الجهة: {txn.vendor or 'غير محدد'}",
        f"• التصنيف: {txn.category}",
        f"• التاريخ: {txn.date}",
    ]
    if txn.tax:
        lines.append(f"• منها ضريبة: {txn.tax:,.2f}")
    if txn.note:
        lines.append(f"• ملاحظة: {txn.note}")
    lines.append(f"• المصدر: {txn.source or '—'}")
    return "\n".join(lines)


def report_message(totals: Dict[str, float], anomalies: List[Any], label: str = "",
                   ai_note: Optional[str] = None) -> str:
    lines = ["📊 تقرير Fin-Guard المالي", f"الفترة: {label}" if label else ""]
    lines += [
        f"• الإيرادات: {totals.get('income', 0):,.2f}",
        f"• المصروفات: {totals.get('expense', 0):,.2f}",
        f"• صافي التدفق: {totals.get('net', 0):,.2f}",
        f"• عدد القيود: {int(totals.get('count', 0))}",
    ]
    if anomalies:
        lines.append("")
        lines.append(f"🔎 تنبيهات ({len(anomalies)}):")
        for item in anomalies[:5]:
            sev = getattr(item, "severity", "info")
            lines.append(f"{SEV_ICON.get(sev, '•')} [{SEV_LABEL.get(sev, sev)}] {getattr(item, 'title', str(item))}")
    if ai_note:
        lines += ["", f"🤖 {ai_note}"]
    return "\n".join(line for line in lines if line != "None")


def send_summary(totals: Dict[str, float], anomalies: List[Any], label: str = "",
                 ai_note: Optional[str] = None) -> str:
    return _send(report_message(totals, anomalies, label, ai_note))


def send_expense(txn: Transaction) -> str:
    return _send(expense_message(txn))
