"""المستخرج اللغوي: مبالغ، تواريخ، جهة، رقم فاتورة، ضريبة — عربي/إنجليزي/تركي."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import List, Optional, Tuple

from . import config

ARABIC_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
PERSIAN_DIGITS = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}

CURRENCY_SYMBOLS = {
    "₺": "TRY", "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP",
    "₽": "RUB", "﷼": "SAR", "ر.س": "SAR", "د.إ": "AED", "د.ك": "KWD",
    "₽".replace("₽", "₹"): "INR",
}
CURRENCY_CODES = ["USD", "EUR", "GBP", "TRY", "SAR", "AED", "CAD", "AUD", "JPY", "CHF", "INR", "RUB", "TL", "TRY"]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5,
    "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10,
    "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}

AMOUNT_RE = re.compile(
    r"(?<![\d.,])(?<![-\w])(?:"
    r"[₺$€£₹]\s*\d[\d.,]*"
    r"|\d[\d.,]*\s*(?:TL|TRY|USD|EUR|GBP|SAR|AED|₺|ر\.س|د\.إ)"
    r"|\d{1,3}(?:[.,\s]\d{3})+[.,]\d{2}"
    r"|\d+[.,]\d{2}(?!\d)"
    r"|\d{2,9}(?![\d.,])(?![\-/]\d)"
    r")"
)
# مبلغ «مؤكَّد»: عملة صريحة أو فاصل آلاف أو من ثلاث خانات عشرية
STRONG_HINT = re.compile(r"[₺$€£₹]|\b(?:TL|TRY|USD|EUR|GBP|SAR|AED)\b|ر\.س|د\.إ|\d[.,]\d{2}\b")
TOTAL_WORDS = re.compile(
    r"(?i)(grand\s*total|net\s*payout|total\s*due|amount\s*due|total\s*amount|total|"
    r"genel\s*toplam|odenecek|net\s*tutar|الإجمالي|المستحق|صافي\s*الدفع|المبلغ\s*الإجمالي|المجموع\s*الكلي)"
)
SUBTOTAL_WORDS = re.compile(
    r"(?i)(subtotal|sub-total|before\s*tax|excl|ara\s*toplam|قبل\s*الضريبة|قبل\s*الضريبه|بدون\s*الضريبة)"
)
DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"
    r"|(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})(?!\d)"
)
VAT_WORDS = re.compile(
    r"(?i)(vat|kdv|tv[sş]|gst|hst|tax|sales\s*tax|withhold|ضريبة|ضريبت|القيمة\s*المضافة|ض\.ق\.م|زكاة)"
)
INVOICE_NO_RE = re.compile(
    r"(?i)(?:invoice\s*(?:no|number|#)|fatura\s*(?:no|numaras[ıi])|رقم\s*الفاتورة|فاتورة\s*رقم|ب Zahlung|order\s*(?:no|#)|No\.?)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{1,24})"
)
VENDOR_RE = re.compile(
    r"(?im)^(?:vendor|seller|supplier|supplier|from|bill\s*from|satıcı|satici|seller|المورد|الجهة|المورد\s*المصدر|من)\s*[:\-]\s*(.+)$"
)
INCOME_WORDS = re.compile(r"(?i)(payment\s*received|salary|refund|credit\s*note|revenue|sales\s*report|إيراد|دخل|مردود|راتب|دفعه\s*مستلمة)")
EXPENSE_WORDS = re.compile(r"(?i)(invoice|bill|receipt|order|purchase|fatura|makbuz|فاتورة|إيصال|فاتورة\s*شراء|شراء)")


def normalize_digits(text: str) -> str:
    """حوّل الأرقام العربية/الفارسية إلى إنجليزية ووحّد فواصل الآلاف."""
    if not text:
        return ""
    text = text.translate(ARABIC_DIGITS).translate(PERSIAN_DIGITS)
    text = unicodedata.normalize("NFKC", text)
    # ٫ (عشري) و ٬ (آلاف) و فاصلة عربية
    text = text.replace("٫", ".").replace("٬", ",").replace("،", ",")
    return text


def _clean_number(token: str) -> Optional[float]:
    token = token.strip().replace(" ", "")
    if not token or not re.search(r"\d", token):
        return None
    token = re.sub(r"[^\d.,+-]", "", token)
    if not token:
        return None
    last_dot, last_comma = token.rfind("."), token.rfind(",")
    if last_dot > -1 and last_comma > -1:
        sep = "." if last_dot > last_comma else ","
        other = "," if sep == "." else "."
        token = token.replace(other, "").replace(sep, ".")
    elif last_comma > -1:
        # فاصلة واحدة تفصل كسوراً، أمّا 1,234 فآلاف
        tail = token.rsplit(",", 1)[-1]
        token = token.replace(",", "") if len(tail) == 3 else token.replace(",", ".")
    elif last_dot > -1:
        tail = token.rsplit(".", 1)[-1]
        if len(tail) == 3 and token.count(".") > 1:
            token = token.replace(".", "")
        elif len(tail) == 3 and token.count(".") == 1 and len(token.split(".")[0]) <= 3 and len(token) >= 7:
            token = token.replace(".", "")   # 1.234.567-style single group
    try:
        value = float(token)
    except ValueError:
        return None
    return value if value == value else None


def detect_currency(text: str, default: Optional[str] = None) -> str:
    upper = text.upper()
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym and sym in text:
            return code
    for code in CURRENCY_CODES:
        if re.search(r"(?<![A-Z])" + code + r"(?![A-Z])", upper):
            return "TRY" if code == "TL" else code
    if re.search(r"(?i)(turkish\s*lira|türk\s*liras[ıi]|liras[ıi])", text):
        return "TRY"
    return (default or config.base_currency()).upper()


def find_amounts(text: str, strong_only: bool = False) -> List[Tuple[float, str]]:
    """كل مبلغ في النص مع عملته. `strong_only` يُخرج المبالغ المؤكدة فقط
    (عملة صريحة أو فاصل آلاف أو من ثلاث خانات عشرية) بدل الأرقام العشوائية."""
    text = normalize_digits(text)
    out: List[Tuple[float, str]] = []
    for match in AMOUNT_RE.finditer(text):
        token = match.group(0)
        value = _clean_number(re.sub(r"[^\d.,+-]", "", token) or token)
        if value is None or value <= 0:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token.strip()):
            continue                      # سنة ليست مبلغاً
        strong = bool(STRONG_HINT.search(token))
        if strong_only and not strong:
            continue
        win = text[max(0, match.start() - 18):match.end() + 18]
        out.append((round(value, 2), detect_currency(win)))
    return out


def find_tax_amount(text: str) -> float:
    """قيمة الضريبة من السطر الذي يذكر فيها اسمها (وبلا أرقام المجموع الفرعي)."""
    text_n = normalize_digits(text)
    best = 0.0
    for line in text_n.splitlines():
        if not VAT_WORDS.search(line) or SUBTOTAL_WORDS.search(line):
            continue
        amounts = [v for v, _ in find_amounts(line, strong_only=True)]
        if not amounts:
            amounts = [v for v, _ in find_amounts(line)]
        if amounts:
            best = max(best, max(amounts))
    return round(best, 2)


def pick_total(text: str, kind_hint: str = "expense") -> Tuple[float, str, float]:
    """(الإجمالي، العملة، الضريبة) مع تفضيل أسطر الإجمالي الصريحة."""
    lines = normalize_digits(text).splitlines()
    currency = detect_currency(text)

    def _pick_from(rows: List[str], strong: bool) -> List[float]:
        values: List[float] = []
        for row in rows:
            values += [v for v, c in find_amounts(row, strong_only=strong) if c == currency] or \
                      [v for v, _ in find_amounts(row, strong_only=strong)]
        return values

    hinted = [ln for ln in lines if TOTAL_WORDS.search(ln) and not SUBTOTAL_WORDS.search(ln)]
    total = 0.0
    for rows in (hinted, lines):
        strong = _pick_from(rows, True)
        if strong:
            total = max(strong)
            break
        weak = _pick_from(rows, False)
        if weak:
            total = max(weak)
            break
    if not total:
        return 0.0, config.base_currency().upper(), 0.0
    tax = find_tax_amount(text)
    if tax >= total:
        tax = 0.0
    return round(total, 2), currency, round(tax, 2)


def find_dates(text: str) -> List[str]:
    text = normalize_digits(text)
    found: List[str] = []
    for m in DATE_RE.finditer(text):
        if m.group(1):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            d, mo, y = int(m.group(4)), int(m.group(5)), int(m.group(6))
        if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
            try:
                found.append(datetime(y, mo, d).strftime("%Y-%m-%d"))
            except ValueError:
                continue
    if found:
        return found
    # "12 January 2026" / "12 Ocak 2026" / "يناير 2026"
    words = re.compile(r"(?i)(\d{1,2})\s+([A-Za-zأ-ي]{3,12})\s+(20\d{2})")
    for m in words.finditer(text):
        month = MONTHS.get(m.group(2).lower())
        if not month:
            continue
        try:
            found.append(datetime(int(m.group(3)), month, min(int(m.group(1)), 31)).strftime("%Y-%m-%d"))
        except ValueError:
            continue
    if found:
        return found
    for name, num in MONTHS.items():
        if re.search(r"(?i)\b" + re.escape(name) + r"\s+(20\d{2})", text):
            m = re.search(r"(?i)" + re.escape(name) + r"\s+(20\d{2})", text)
            assert m
            found.append(f"{m.group(1)}-{num:02d}-01")
            break
    return found


def best_date(text: str, source: str = "") -> str:
    labelled = [ln for ln in normalize_digits(text).splitlines()
                if re.match(r"(?i)^\s*(date|tarih|invoice\s*date|التاريخ|تاريخ)\s*[:#]", ln)]
    for block in (labelled, [text]):
        dates = find_dates("\n".join(block))
        if dates:
            return dates[0]
    for pattern in (r"(20\d{6})", r"(\d{8})"):
        m = re.search(pattern, normalize_digits(source or ""))
        if m:
            raw = m.group(1)
            try:
                return datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return datetime.utcnow().strftime("%Y-%m-%d")


def find_vendor(text: str, source: str = "") -> str:
    m = VENDOR_RE.search(normalize_digits(text))
    if m:
        value = m.group(1).strip(" .:-")
        if 2 <= len(value) <= 80:
            return value
    for line in text.splitlines():
        line = line.strip()
        if 3 <= len(line) <= 60 and not re.search(r"[\d]{4,}", line) and not VAT_WORDS.search(line):
            if re.search(r"[A-Za-zأ-ي]{3,}", line) and not re.match(r"(?i)(invoice|bill|receipt|date|total|subtotal|tax|vat|kdv)", line):
                return line
    stem = re.sub(r"[_\-.]+", " ", Path_name(source))
    return stem.strip()[:60] or "غير محدد"


def Path_name(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").split("/")[-1].rsplit(".", 1)[0]


def find_invoice_no(text: str, source: str = "") -> str:
    m = INVOICE_NO_RE.search(normalize_digits(text))
    if m:
        return m.group(1)
    stem = Path_name(source)
    m = re.search(r"([A-Za-z]{1,6}-?\d{2,10})", stem)
    return m.group(1) if m else ""


def guess_kind(text: str, filename: str = "") -> str:
    blob = normalize_digits(text + " " + filename)
    if INCOME_WORDS.search(blob):
        return "income"
    if EXPENSE_WORDS.search(blob):
        return "expense"
    return "expense"


def guess_confidence(text: str, amount: float, date: str) -> float:
    score = 0.35
    if amount > 0:
        score += 0.3
    if date:
        score += 0.15
    if re.search(r"(?i)(total|subtotal|grand\s*total|المجموع|الإجمالي|genel\s*toplam|KDV|VAT|ضريبة)", text):
        score += 0.15
    if len(text) > 120:
        score += 0.05
    return round(min(score, 0.99), 2)
