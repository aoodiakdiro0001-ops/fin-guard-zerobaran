"""Configuration: stdlib .env reader + process environment (no dependencies)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

# كل مفتاح هنا له طبقة مجانية — ولا واحد منها إلزامي.
OPTIONAL_KEYS = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "OLLAMA_URL",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "BASE_CURRENCY",
    "BUDGET_MONTHLY",
    "TAX_RATE",
    "INBOX_DIR",
]


def load_dotenv(path: str = ".env") -> Dict[str, str]:
    """قارئ .env صغير بلا تبعيات. المتغيّرات الموجودة في البيئة تفوز دائماً."""
    p = Path(path)
    if not p.is_file():
        return {}
    out: Dict[str, str] = {}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        out[key] = value
        os.environ.setdefault(key, value)
    return out


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default


def has(key: str) -> bool:
    return bool(os.environ.get(key))


def base_currency() -> str:
    return (get("BASE_CURRENCY", "USD") or "USD").upper()


def tax_rate() -> float:
    try:
        return max(0.0, float(get("TAX_RATE", "0") or 0))
    except ValueError:
        return 0.0


def budget_monthly() -> Optional[float]:
    raw = get("BUDGET_MONTHLY", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def inbox_dir() -> Path:
    return Path(get("INBOX_DIR", "finance/inbox"))


def supabase_cfg() -> Optional[Dict[str, str]]:
    url = get("SUPABASE_URL")
    key = get("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return {"url": url.rstrip("/"), "key": key}
    return None


def telegram_cfg() -> Optional[Dict[str, str]]:
    token = get("TELEGRAM_BOT_TOKEN")
    chat = get("TELEGRAM_CHAT_ID")
    if token and chat:
        return {"token": token, "chat_id": chat}
    return None


def ai_provider() -> Optional[str]:
    """المحرّك الذكي إن وُجد — والاكتفاء بالمحرّك المحلي الحتمي دائماً ممكن."""
    if has("GEMINI_API_KEY"):
        return "gemini"
    if has("GROQ_API_KEY"):
        return "groq"
    if has("OPENROUTER_API_KEY"):
        return "openrouter"
    if has("OLLAMA_URL"):
        return "ollama"
    return None


def exchange_rates() -> Dict[str, float]:
    """أسعار صرف إلى العملة الأساسية — من `rates.json` أو EXCHANGE_RATES (JSON).

    بلا أسعارٍ لا نُحوِّل شيئاً: نعرض كل عملة على حدة ولا نخلط إجماليات
    عملتين ببعضهما (الخلط أخطر من عدم التحويل).
    """
    data: Dict[str, object] = {}
    raw = get("EXCHANGE_RATES", "")
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                data.update(loaded)
        except ValueError:
            pass
    p = Path("rates.json")
    if p.is_file():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (OSError, ValueError):
            pass
    out: Dict[str, float] = {}
    for key, value in data.items():
        try:
            out[str(key).upper()] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def budgets_from(path: str = "budget.json") -> Dict[str, float]:
    """ميزانية شهريّة لكل فئة: {"تسويق": 1500, "استضافة": 300}"""
    p = Path(path)
    if not p.is_file():
        monthly = budget_monthly()
        return {"__total__": monthly} if monthly else {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, float] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            try:
                out[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    return out


def configured_summary() -> Dict[str, bool]:
    return {
        "gemini": has("GEMINI_API_KEY"),
        "groq": has("GROQ_API_KEY"),
        "openrouter": has("OPENROUTER_API_KEY"),
        "ollama": has("OLLAMA_URL"),
        "supabase": bool(supabase_cfg()),
        "telegram": bool(telegram_cfg()),
        "budget": bool(budgets_from()),
        "inbox": inbox_dir().exists(),
    }


def list_env_keys() -> List[str]:
    return list(OPTIONAL_KEYS)
