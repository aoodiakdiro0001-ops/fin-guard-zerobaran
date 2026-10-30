"""العقل المحاسبي المحلي: تصنيف حتمي بلا إنترنت وبلا مفتاح.

كل قاعدة تُطابَق على النص الخام للفاتورة (عربي/إنجليزي/تركي) وتُسند
لحساب من دليل الحسابات. ثقة التصنيف تُسجَّل مع القيد.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import CATEGORIES, Transaction

RULES: List[Tuple[str, str, str]] = [
    ("برمجيات واشتراكات",
     r"(?i)(saas|subscription|licence|license|software|monthly\s*plan|annual\s*plan|"
     r"github|gitlab|notion|figma|slack|zoom|adobe|jetbrains|openai|anthropic|api\s*usage|"
     r"اشتراك|اشتراكات|رخصة|ترخيص|برنامج|برمجيات|اشتراك سنوي|abonelik|lisans|yazılım)"),
    ("استضافة وتقنية",
     r"(?i)(hosting|domain|server|vps|dedicated|cloud|aws|gcp|azure|digitalocean|hetzner|"
     r"cloudflare|godaddy|namecheap|bandwidth|storage|ssl|"
     r"استضافة|نطاق|سيرفر|خادم|تخزين|شهادة ssl|sunucu|alan\s*adı)"),
    ("تسويق وإعلانات",
     r"(?i)(ad[s]?|advertis|campaign|marketing|google\s*ads|meta\s*ads|facebook|instagram|"
     r"tiktok\s*ads|seo|sponsor|referral|إعلان|اعلان|تسويق|حملة|راعي|reklam|kampanya)"),
    ("رواتب ومكافآت",
     r"(?i)(salary|payroll|wage|bonus|stipend|net\s*pay|"
     r"راتب|رواتب|أجر|مكافأة|صافي\s*راتب|maaş|prim)"),
    ("إيجارات ومرافق",
     r"(?i)(rent|lease|electric|water|gas|utility|utilities|internet\s*bill|phone\s*bill|"
     r"إيجار|كهربا|كهرباء|مياه|غاز|مرافق|فاتورة\s*انترنت|kira|elektrik|su\s*faturası)"),
    ("مواصلات وشحن",
     r"(?i)(taxi|uber|bolt|cargo|shipping|delivery|freight|fuel|petrol|mileage|flight|"
     r"مواصلات|توصيل|شحن|وقود|بنزين|طيران|تذكرة|yakıt|kargo|taksi)"),
    ("مشتريات ومخزون",
     r"(?i)(purchase|supplies|inventory|equipment|hardware|furniture|stationery|raw\s*material|"
     r"مشتريات|مستلزمات|معدات|أثاث|قرطاسية|خامات|malzeme|ekipman)"),
    ("ضرائب ورسوم",
     r"(?i)(\btax\b|vat|kdv|gst|duty|tariff|municipality|government\s*fee|license\s*fee|"
     r"ضريبة|ضرايب|رسوم|بلدية|جمارك|جمرك|vergi|harç)"),
    ("خدمات مهنية",
     r"(?i)(lawyer|legal|attorney|consult|consulting|accounting|bookkeep|audit|agency|"
     r"freelance|contractor|design\s*service|"
     r"محامي|استشارة|استشارات|محاسبة|تدقيق|وكالة|مستقل|サービス)"),
    ("صحة وتأمين",
     r"(?i)(insurance|clinic|hospital|pharmacy|dental|health|medical|"
     r"تأمين|عيادة|مستشفى|صيدلية|صحة|sigorta|sağlık)"),
    ("تعليم وتدريب",
     r"(?i)(course|training|workshop|tuition|book|udemy|coursera|"
     r"دورة|تدريب|ورشة|كتاب|رسوم\s*دراسة|eğitim|kurs)"),
]

CATEGORY_PATTERNS = [(cat, re.compile(pattern)) for cat, pattern in RULES]
INCOME_RE = re.compile(r"(?i)(payment\s*received|revenue|sales|income|refund|credit\s*note|"
                       r"إيراد|إيرادات|دخل|مبيعات|مردود|استرداد|gelir|satış)")
VAT_LINE_RE = re.compile(
    r"(?i)(\bvat\b|\bkdv\b|ضريبة|القيمة\s*المضافة|subtotal|قبل\s*الضريبة|ara\s*toplam)"
)
TAX_SUBJECT_RE = re.compile(
    r"(?i)(tax\s*authority|tax\s*office|government|municipality|customs|"
    r"مكتب\s*الضرائب|الهيئة\s*الضريبية|رسوم\s*حكومية|جمارك|بلدية|"
    r"vergi\s*dairesi|vergi\s*ödemesi|resmî\s*(harç|ödeme))"
)


def strip_boilerplate(text: str) -> str:
    """يشطّ أسطر الضريبة والمجموع الفرعي — ثوابت في كل فاتورة وتُشوِّه التصنيف.

    ما لم يُشطَّ: فاتورة ضريبة حقيقية يظهر فيها اسم الجهة الضريبية نفسها.
    """
    kept = []
    for line in (text or "").splitlines():
        if VAT_LINE_RE.search(line) and not TAX_SUBJECT_RE.search(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def classify_text(text: str) -> Optional[str]:
    text = strip_boilerplate(text)
    scores: Dict[str, int] = {}
    for category, rx in CATEGORY_PATTERNS:
        hits = len(rx.findall(text or ""))
        if hits:
            scores[category] = scores.get(category, 0) + hits
    if not scores:
        return None
    return max(scores.items(), key=lambda kv: (kv[1], -CATEGORIES.index(kv[0]) if kv[0] in CATEGORIES else 0))[0]


def apply_local(txn: Transaction, raw_text: str = "") -> Transaction:
    """يصنّف المعاملة محلياً ويضبط الحساب والثقة — بلا أي نداء شبكة."""
    if txn.kind == "income":
        txn.category = "إيرادات"
        txn.account = "4000"
        txn.confidence = max(txn.confidence, 0.7)
        return txn

    blob = strip_boilerplate(" ".join(x for x in (raw_text, txn.description, txn.vendor, txn.source) if x))
    if INCOME_RE.search(blob) and not re.search(r"(?i)(invoice|bill|فاتورة)", blob):
        txn.kind = "income"
        txn.category = "إيرادات"
        txn.account = "4000"
        return txn

    category = (txn.category if txn.category and txn.category in CATEGORIES
                and txn.category != "أخرى" else classify_text(blob))
    if category:
        txn.category = category
        txn.confidence = min(0.98, txn.confidence + 0.25)
    else:
        txn.category = "أخرى"
        txn.confidence = max(0.3, txn.confidence - 0.1)
    from .models import account_for

    txn.account = account_for(txn.category, txn.kind)
    return txn


def rule_report(text: str) -> List[str]:
    """أي القواعد التي انطبّقت — يُستخدم في شرح التصنيف داخل التقرير."""
    out = []
    for category, rx in CATEGORY_PATTERNS:
        for hit in rx.findall(text or ""):
            term = hit if isinstance(hit, str) else hit[0]
            out.append(f"{category} ← {term}")
    return out
