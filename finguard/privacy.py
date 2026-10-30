"""إخفاء البيانات الحسّاسة قبل أن تصل إلى أي تقرير أو رسالة.

قاعدة صارمة: رقم البطاقة/الآيبان/الرقم الضريبي لا يظهر كاملاً في أي مخرج.
"""

from __future__ import annotations

import re
from typing import Tuple

PATTERNS = [
    ("iban", re.compile(r"\b(?:TR|DE|GB|FR|US|SA|AE)\d{2}(?:[ ]?\d{4}){2,8}\b")),
    ("card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("tax-id", re.compile(r"(?i)\b(?:VAT|KDV|TCKN|TC\s*No|Tax\s*Id|الرقم\s*الضريبي)\s*[:#]?\s*\d{8,15}")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?\d[\d -]{7,15}\d)(?!\d)")),
]

# التواريخ (YYYY-MM-DD أو DD/MM/YYYY) تبقى ظاهرة دائماً في التقارير المالية.
DATE_RX = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b")


def mask_value(kind: str, value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if kind == "card" and len(digits) >= 12:
        return "•••• •••• •••• " + digits[-4:]
    if kind == "iban" and len(digits) >= 6:
        return value[:4] + " " + "•" * 4 + " " + digits[-4:]
    if kind == "tax-id" and len(digits) >= 4:
        return digits[:2] + "•" * (len(digits) - 4) + digits[-2:]
    if kind == "email":
        name, _, dom = value.partition("@")
        return (name[:2] + "•••@" + dom) if name and dom else "•••"
    if kind == "phone" and len(digits) >= 6:
        return "+" + "•" * (len(digits) - 3) + digits[-3:]
    return "•" * max(4, len(value) - 4)


def redact(text: str) -> Tuple[str, int]:
    """تعقيم نص كامل — يُطبَّق على كل سطر يدخل تقريراً أو رسالة تليجرام.

    التواريخ لا تُقنَّع أبداً: العمود الزمني هو جوهر التقرير المالي.
    """
    if not text:
        return text, 0
    protected: list = []

    def _keep(m: "re.Match[str]") -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1:03d}\x00"

    work = DATE_RX.sub(_keep, text) if any(ch.isdigit() for ch in text) else text
    count = 0
    out = work
    for kind, rx in PATTERNS:
        def _sub(m: "re.Match[str]") -> str:
            nonlocal count
            count += 1
            return mask_value(kind, m.group(0))

        out = rx.sub(_sub, out)
    for i, value in enumerate(protected):
        out = out.replace(f"\x00{i:03d}\x00", value)
    return out, count
