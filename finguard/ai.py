"""العقل الذكي الاختياري — يُحسّن التصنيف ويكتب الملخّص المالي.

كل النداءات عبر مكتبة Python القياسية (urllib) بلا أي تبعية.
إن تعذّر الاتصال أو المفتاح غير مضبوط، يرجع `None` ويكمل المحرّك المحلي
الحتمي — النظام لا يعطَّل أبداً بسبب غياب الذكاء الاصطناعي.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from . import config
from .models import CATEGORIES, Transaction

TIMEOUT = 25
MODEL = {
    "gemini": "gemini-1.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "ollama": "llama3.2",
}


def _post(url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> Optional[str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None
    return json.dumps(data, ensure_ascii=False)


def chat(prompt: str) -> Optional[str]:
    """نص خام من مزوّد واحد متاح — أو None ليعود المسار المحلي."""
    provider = config.ai_provider()
    if not provider:
        return None
    if provider == "gemini":
        key = config.get("GEMINI_API_KEY")
        raw = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL['gemini']}:generateContent?key={key}",
            {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}},
            {},
        )
        if not raw:
            return None
        try:
            parts = json.loads(raw)["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts) or None
        except (KeyError, IndexError, TypeError, ValueError):
            return None
    if provider == "groq":
        raw = _post(
            "https://api.groq.com/openai/v1/chat/completions",
            {"model": MODEL["groq"], "temperature": 0.1, "response_format": {"type": "json_object"},
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": "Bearer " + config.get("GROQ_API_KEY")},
        )
    elif provider == "openrouter":
        raw = _post(
            "https://openrouter.ai/api/v1/chat/completions",
            {"model": MODEL["openrouter"], "temperature": 0.1,
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": "Bearer " + config.get("OPENROUTER_API_KEY")},
        )
    else:  # ollama محلي
        raw = _post(config.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/generate",
                    {"model": MODEL["ollama"], "prompt": prompt, "stream": False, "format": "json"}, {})
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if provider == "ollama":
            return data.get("response")
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def enrich(transactions: List[Transaction], limit: int = 25) -> int:
    """يطلب من المزوّد تصنيف دفعة معاملات وشرح أي شذوذ — يرجع العدد المُثرى."""
    if not transactions or not config.ai_provider():
        return 0
    rows = [{
        "id": t.id, "date": t.date, "vendor": t.vendor, "amount": t.amount,
        "currency": t.currency, "description": t.description[:120],
        "local_category": t.category,
    } for t in transactions[:limit]]
    prompt = (
        "أنت محاسب. صنّف كل معاملة في البيانات إلى إحدى الفئات التالية حرفياً: "
        + " | ".join(CATEGORIES)
        + ". أعد JSON بالشكل: {\"items\":[{\"id\":\"...\",\"category\":\"...\",\"note\":\"سبب مختصر بالعربية\"}]} "
        "ولا تُدخل أي مفاتيح أخرى."
    )
    data = _json(chat(prompt + "\n" + json.dumps(rows, ensure_ascii=False)))
    if not data or not isinstance(data.get("items"), list):
        return 0
    by_id = {str(item.get("id")): item for item in data["items"] if isinstance(item, dict)}
    done = 0
    for txn in transactions:
        item = by_id.get(txn.id)
        if not item:
            continue
        category = str(item.get("category") or "")
        if category in CATEGORIES and txn.kind == "expense":
            txn.category = category
            txn.confidence = min(0.99, txn.confidence + 0.15)
        note = str(item.get("note") or "").strip()
        if note:
            txn.note = note[:220]
            txn.extractor = (txn.extractor + "+ai").replace("ai+ai", "ai")
        done += 1
    return done


def summary(lines: List[str], tone: str = "ملخّص مالي مختصر بالعربية") -> Optional[str]:
    """فقرة تحليلية للتقرير/تليجرام — اختيارية تماماً."""
    if not config.ai_provider():
        return None
    prompt = (tone + " مع إشارة واضحة لأي هدر أو مبلغ غير متوقع. أعد نصاً فقط بلا Markdown.\n"
              + "\n".join(lines[:30]))
    text = chat(prompt)
    return text.strip()[:600] if text else None
