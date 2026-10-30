"""طبقة الأرشيف: سجلّ محلي (JSON) + Supabase اختياري عبر REST بلا مكتبات.

السجل المحلي هو الأساس — يعمل دون إنترنت تماماً. Supabase ميزة إضافية
تُفعَّل بمتغيّرين فقط.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from .models import Transaction

HISTORY = Path("reports/history.json")
RUNS = Path("reports/runs.json")


def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows[-400:], ensure_ascii=False, indent=1), encoding="utf-8")


def record_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    rows = _read(RUNS)
    row = {"ts": time.time(), **payload}
    rows.append(row)
    _write(RUNS, rows)
    return row


def history(limit: int = 24) -> List[Dict[str, Any]]:
    rows = sorted(_read(RUNS), key=lambda r: r.get("ts", 0))
    return rows[-limit:]


def trend() -> Optional[Dict[str, Any]]:
    rows = history(24)
    series = [{
        "label": str(r.get("label") or r.get("month") or "?"),
        "expense": float(r.get("expense") or 0),
        "income": float(r.get("income") or 0),
        "net": float(r.get("net") or 0),
    } for r in rows]
    if len(series) < 2:
        return None
    delta = round(series[-1]["expense"] - series[-2]["expense"], 2)
    return {"series": series, "delta": delta}


def save_transactions(txns: List[Transaction], path: str = "reports/transactions.json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [t.to_dict() for t in txns]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def load_transactions(path: str = "reports/transactions.json") -> List[Transaction]:
    target = Path(path)
    if not target.is_file():
        return []
    try:
        rows = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: List[Transaction] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            try:
                out.append(Transaction.from_dict(row))
            except TypeError:
                continue
    return out


def push_supabase(txns: List[Transaction], batch_label: str = "") -> str:
    """رفع القيود إلى Supabase (اختياري) — يرجع حالة مختصرة."""
    cfg = config.supabase_cfg()
    if not cfg:
        return "supabase: غير مضبوط (تخطّي)"
    rows = [{
        "txn_id": t.id, "date": t.date, "vendor": t.vendor, "description": t.description[:300],
        "currency": t.currency, "amount": t.amount, "tax": t.tax, "kind": t.kind,
        "category": t.category, "account": t.account, "invoice_no": t.invoice_no,
        "source": t.source, "confidence": t.confidence, "batch": batch_label,
    } for t in txns]
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        cfg["url"] + "/rest/v1/transactions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "apikey": cfg["key"],
            "Authorization": "Bearer " + cfg["key"],
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = resp.status
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        return f"supabase: فشل الرفع ({getattr(exc, 'code', 'شبكة')})"
    return f"supabase: {status} — {len(rows)} قيداً"
