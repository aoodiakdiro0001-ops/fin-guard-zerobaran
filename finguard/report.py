"""مولّد التقرير: لوحة HTML عربية واحدة تعمل بلا إنترنت (بلا CDN وبلا تتبّع)."""

from __future__ import annotations

import csv
import html
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, config
from .models import ACCOUNTS, Batch, Transaction
from .privacy import redact

SEV_COLORS = {"high": "#ff4d6d", "medium": "#f7c948", "low": "#4dabf7", "info": "#868e96"}
SEV_LABEL = {"high": "حرج", "medium": "متوسط", "low": "منخفض", "info": "معلومة"}

SUPPORT = {
    "email": "baranavisat@gmail.com",
    "phone": "+90 531 326 3722",
    "store": "https://baranavi.gumroad.com/",
    "tr_iban": "TR10 0001 0090 1008 4013 0050 01",
    "usd_iban": "TR80 0001 0090 1008 4013 0050 02",
    "btc": "bc1q8dhtdrndxsl70e97t8grydfe6pjue37zrhzf6c",
    "holder": "Baran Avisat",
}


def esc(value: Any) -> str:
    text, _ = redact(str(value if value is not None else ""))
    return html.escape(text, quote=True)


def totals_of(txns: List[Transaction], base: Optional[str] = None) -> Dict[str, Any]:
    """إجماليات مجمّعة بالعملة الأساسية — ولا نخلط عملتين معاً أبداً.

    كل عملة لها عمود خاص (`by_currency`). العملات التي لا سعر صرف لها
    تبقى معروضة منفردة وتُعلَّم في `unconverted` بدل أن تُضم سراً.
    """
    base = (base or config.base_currency()).upper()
    rates = config.exchange_rates()
    by: Dict[str, Dict[str, Any]] = {}
    expense_count: Dict[str, int] = {}
    for t in txns:
        slot = by.setdefault(t.currency, {"income": 0.0, "expense": 0.0, "tax": 0.0, "count": 0.0})
        slot["income" if t.kind == "income" else "expense"] += t.amount
        slot["tax"] += t.tax
        slot["count"] += 1
        if t.kind == "expense":
            expense_count[t.currency] = expense_count.get(t.currency, 0) + 1

    merged = {"income": 0.0, "expense": 0.0, "tax": 0.0, "count": 0, "expense_count": 0}
    unconverted: List[str] = []
    for currency, slot in by.items():
        slot["income"] = round(slot["income"], 2)
        slot["expense"] = round(slot["expense"], 2)
        slot["tax"] = round(slot["tax"], 2)
        slot["net"] = round(slot["income"] - slot["expense"], 2)
        slot["count"] = int(slot["count"])
        if currency == base:
            factor = 1.0
        elif currency in rates:
            factor = rates[currency]
        else:
            unconverted.append(currency)
            continue
        merged["income"] += slot["income"] * factor
        merged["expense"] += slot["expense"] * factor
        merged["tax"] += slot["tax"] * factor
        merged["count"] += int(slot["count"])
        merged["expense_count"] += expense_count.get(currency, 0)

    income = round(merged["income"], 2)
    expense = round(merged["expense"], 2)
    return {
        "base": base,
        "income": income,
        "expense": expense,
        "net": round(income - expense, 2),
        "tax": round(merged["tax"], 2),
        "count": int(merged["count"]),
        "avg": round(expense / max(1, merged["expense_count"]), 2),
        "saving_rate": round(100.0 * (income - expense) / income, 1) if income else 0.0,
        "by_currency": by,
        "unconverted": sorted(unconverted),
        "mixed": len(by) > 1,
    }


def by_category(txns: List[Transaction]) -> List[Dict[str, Any]]:
    """تجميع لكل (تصنيف × عملة) — لا نخلط USD مع TRY في عمود واحد أبداً."""
    buckets: Dict[tuple, float] = {}
    counts: Dict[tuple, int] = {}
    for t in txns:
        if t.kind != "expense":
            continue
        key = (t.category, t.currency)
        buckets[key] = round(buckets.get(key, 0.0) + t.amount, 2)
        counts[key] = counts.get(key, 0) + 1
    totals: Dict[str, float] = {}
    for (_, currency), amount in buckets.items():
        totals[currency] = totals.get(currency, 0.0) + amount
    rows = [
        {"category": category, "currency": currency, "amount": amount, "count": counts[(category, currency)]}
        for (category, currency), amount in buckets.items()
    ]
    for currency in totals:
        same = [r for r in rows if r["currency"] == currency]
        peak = max(r["amount"] for r in same) if same else 1
        for row in same:
            row["pct"] = round(100.0 * row["amount"] / peak, 1) if peak else 0
            row["share"] = round(100.0 * row["amount"] / totals[currency], 1) if totals[currency] else 0
    return sorted(rows, key=lambda r: (r["currency"], -r["amount"]))


def by_month(txns: List[Transaction]) -> List[Dict[str, Any]]:
    months: Dict[str, Dict[str, float]] = {}
    for t in txns:
        key = t.year_month or "غير مؤرخ"
        slot = months.setdefault(key, {"month": key, "income": 0.0, "expense": 0.0})
        slot["income" if t.kind == "income" else "expense"] += t.amount
    rows = [dict(v, net=round(v["income"] - v["expense"], 2)) for v in months.values()]
    for row in rows:
        row["income"] = round(row["income"], 2)
        row["expense"] = round(row["expense"], 2)
    return sorted(rows, key=lambda r: r["month"])


def _budget_rows(txns: List[Transaction], budgets: Dict[str, float]) -> List[Dict[str, Any]]:
    base = config.base_currency().upper()
    rates = config.exchange_rates()
    spend: Dict[str, float] = {}
    for t in txns:
        if t.kind != "expense":
            continue
        cur = (t.currency or base).upper()
        factor = 1.0 if cur == base else rates.get(cur)
        if not factor:      # عملة بلا سعر صرف لا تُدمج في الميزانية
            continue
        spend[t.category] = round(spend.get(t.category, 0.0) + t.amount * factor, 2)
    rows = []
    for category, limit in sorted(budgets.items()):
        if category.startswith("__") or limit <= 0:
            continue
        used = spend.get(category, 0.0)
        rows.append({
            "category": category, "budget": round(limit, 2), "used": used, "currency": base,
            "pct": round(100.0 * used / limit, 1),
        })
    return rows


CSS = """
:root{--bg:#070b14;--panel:#0e1524;--line:#1d2740;--fg:#e8edf7;--muted:#8b97b3;--accent:#5b8cff;--good:#3ddc84;--bad:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 85% -10%,#16233f 0%,var(--bg) 60%);color:var(--fg);
font:15px/1.7 -apple-system,"Segoe UI",Tahoma,"Noto Sans Arabic",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:34px 22px 70px}
header.top{display:flex;flex-wrap:wrap;gap:24px;align-items:center;justify-content:space-between;
border:1px solid var(--line);background:linear-gradient(180deg,#111a2e,#0b111f);border-radius:18px;padding:26px 28px}
h1{margin:0;font-size:25px;letter-spacing:-.3px}
.sub{color:var(--muted);font-size:13.5px;margin-top:6px}
.badge{display:inline-block;margin-top:12px;padding:5px 12px;border-radius:999px;background:#0f2a1e;border:1px solid #1f4d38;color:#8ef0bd;font-size:12.5px}
.ring{width:150px;height:150px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-top:18px}
.card{border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:16px 18px}
.card .label{color:var(--muted);font-size:12.5px}
.card .value{font-size:26px;font-weight:700;margin-top:6px;letter-spacing:-.5px}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--f7c948)}
.grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;margin-top:16px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.panel{border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:18px 20px}
.panel h2{margin:0 0 14px;font-size:16.5px}
.bar-row{display:grid;grid-template-columns:150px 1fr 110px;gap:10px;align-items:center;margin:9px 0;font-size:13.5px}
.bar-track{background:#131c30;border-radius:99px;height:12px;overflow:hidden}
.bar-fill{height:100%;border-radius:99px;background:var(--accent)}
.bar-n{text-align:left;color:var(--muted);font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:9px 8px;border-bottom:1px solid #16203a;text-align:right;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12.5px;position:sticky;top:0;background:var(--panel)}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;border:1px solid;white-space:nowrap}
.sev-high{color:#ff8fa3;border-color:#7a2436;background:#2a1020}
.sev-medium{color:#ffd97a;border-color:#6b5312;background:#2a2110}
.sev-low{color:#9fd4ff;border-color:#1c4a72;background:#0f2033}
.sev-info{color:#c9cfdb;border-color:#2b3550;background:#131a2b}
.anom{border:1px solid var(--line);border-right:3px solid var(--accent);border-radius:12px;padding:12px 14px;margin-bottom:10px;background:#0c1322}
.anom.high{border-right-color:#ff4d6d}.anom.medium{border-right-color:#f7c948}.anom.low{border-right-color:#4dabf7}
.anom .t{font-weight:700;font-size:14.5px}
.anom .d{color:var(--muted);font-size:13px;margin-top:4px}
.anom .r{font-size:13px;margin-top:6px;color:#bfe3ff}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filters button{background:#131c30;color:var(--fg);border:1px solid var(--line);border-radius:999px;padding:5px 14px;font-size:12.5px;cursor:pointer}
.filters button.active{background:#1b2a4a;border-color:#2f4d8a}
.muted{color:var(--muted)}
svg.spark{width:100%;height:120px}
footer{margin-top:26px;border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:12.8px}
footer a{color:#9fd4ff}
.scroll{max-height:520px;overflow:auto}
.foot-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
"""


def render(batch: Batch, anomalies: List[Any], budgets: Optional[Dict[str, float]] = None,
           ai_note: Optional[str] = None) -> str:
    txns = sorted(batch.transactions, key=lambda t: (t.date or "", t.vendor))
    totals = totals_of(txns)
    cats = by_category(txns)
    months = by_month(txns)
    budgets = budgets or {}
    budget_rows = _budget_rows(txns, budgets)
    total_budget = budgets.get("__total__")
    generated = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    score = _health_score(totals, anomalies)

    cur = totals.get("base", config.base_currency())
    kpis = [
        (f"الإيرادات ({cur})", f"{totals['income']:,.2f}", "good" if totals["income"] >= 0 else ""),
        (f"المصروفات ({cur})", f"{totals['expense']:,.2f}", "bad"),
        (f"صافي التدفق ({cur})", f"{totals['net']:,.2f}", "good" if totals["net"] >= 0 else "bad"),
        ("ضريبة قابلة للخصم", f"{totals['tax']:,.2f}", ""),
        ("عدد الفواتير", f"{int(totals['count'])}", ""),
        ("متوسط الفاتورة", f"{totals['avg']:,.2f}", ""),
    ]
    extra_badge = ""
    if totals.get("unconverted"):
        extra_badge = (f'<div class="sub">⚠️ عملات لم تُحوَّل: '
                       + ", ".join(totals["unconverted"]) + " (أضف rates.json لدمجها)</div>")
    if totals.get("by_currency") and len(totals["by_currency"]) > 1:
        parts = [f"{code}: {slot['income']:,.0f} دخل / {slot['expense']:,.0f} مصروف"
                 for code, slot in totals["by_currency"].items()]
        extra_badge += '<div class="sub">تفصيل: ' + " · ".join(parts) + "</div>"

    rows_html = []
    for t in txns:
        rows_html.append(
            f'<tr data-sev="{esc(t.kind)}">'
            f'<td class="num">{html.escape(str(t.date))}</td>'
            f'<td><b>{esc(t.vendor or "غير محدد")}</b><div class="muted" style="font-size:12px">{esc(t.description[:70])}</div></td>'
            f'<td>{esc(t.category)}</td>'
            f'<td class="num">{t.amount:,.2f} {esc(t.currency)}</td>'
            f'<td class="num">{t.tax:,.2f}</td>'
            f'<td><span class="pill sev-{"low" if t.kind == "income" else "info"}">{"دخل" if t.kind == "income" else "مصروف"}</span>'
            f'<div class="muted" style="font-size:11.5px">{esc(Path(t.source).name if t.source else "—")}</div></td>'
            f"</tr>"
        )

    cat_html = "".join(
        f'<div class="bar-row"><span>{esc(c["category"])} <span class="muted">({c["count"]}) {esc(c["currency"])}</span></span>'
        f'<span class="bar-track"><span class="bar-fill" style="width:{c["pct"]}%"></span></span>'
        f'<span class="bar-n">{c["amount"]:,.2f} · {c["share"]}%</span></div>'
        for c in cats
    ) or '<p class="muted">لا مصروفات مصنّفة بعد.</p>'

    anom_html = ""
    for a in anomalies:
        sev = getattr(a, "severity", "info")
        anom_html += (
            f'<div class="anom {sev}"><div class="t">{SEV_LABEL.get(sev, sev)} · {esc(getattr(a, "title", ""))}</div>'
            f'<div class="d">{esc(getattr(a, "detail", ""))}</div>'
            f'<div class="r">🛠 {esc(getattr(a, "remediation", ""))}</div></div>'
        )
    if not anom_html:
        anom_html = '<p class="muted">✅ لا تنبيهات — السجلات متوازنة ولا تكرار ولا تجاوز ميزانية.</p>'

    budget_html = ""
    if budget_rows:
        for row in budget_rows:
            color = "#ff4d6d" if row["pct"] > 100 else ("#f7c948" if row["pct"] > 85 else "#3ddc84")
            budget_html += (
                f'<div class="bar-row"><span>{esc(row["category"])}</span>'
                f'<span class="bar-track"><span class="bar-fill" style="width:{min(row["pct"], 100)}%;background:{color}"></span></span>'
                f'<span class="bar-n">{row["used"]:,.0f} / {row["budget"]:,.0f} · {row["pct"]}%</span></div>'
            )
    elif total_budget:
        used = totals["expense"]
        pct = round(100.0 * used / total_budget, 1)
        color = "#ff4d6d" if pct > 100 else ("#f7c948" if pct > 85 else "#3ddc84")
        budget_html = (
            f'<div class="bar-row"><span>الميزانية الشهرية</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{min(pct, 100)}%;background:{color}"></span></span>'
            f'<span class="bar-n">{used:,.0f} / {total_budget:,.0f} · {pct}%</span></div>'
        )
    if not budget_html:
        budget_html = '<p class="muted">أضف <code>budget.json</code> لعرض تنبيهات تجاوز الميزانية.</p>'

    month_html = _months_svg(months)
    ai_block = f'<p class="muted">🤖 {esc(ai_note)}</p>' if ai_note else ""

    JS = (
        "document.querySelectorAll('.filters button').forEach(function(btn){"
        "btn.addEventListener('click',function(){"
        "document.querySelectorAll('.filters button').forEach(function(b){b.classList.remove('active')});"
        "btn.classList.add('active');var sev=btn.dataset.sev;"
        "document.querySelectorAll('#rows tr').forEach(function(tr){"
        "tr.style.display=(sev==='all'||tr.dataset.sev===sev)?'':'none'});});});"
    )

    period = " — ".join(sorted({t.year_month for t in txns if t.year_month})) or "غير مؤرخ"
    html_doc = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fin-Guard ZeroBaran — التقرير المالي</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <h1>💳 Fin-Guard ZeroBaran</h1>
      <div class="sub">التقرير المالي الآلي — الفترة: {esc(period)} · وُلِّد {generated}</div>
      <span class="badge">الصحة المالية: {score}/100 · {esc(config.base_currency())} · محرّك محلي</span>
      {extra_badge}
    </div>
    {'' if not months else _ring_svg(score)}
  </header>

  <section class="kpis">
    {''.join(f'<div class="card"><div class="label">{k}</div><div class="value {cls}">{v}</div></div>' for k, v, cls in kpis)}
  </section>

  <div class="grid2">
    <section class="panel">
      <h2>📊 المصروفات حسب التصنيف</h2>
      {cat_html}
      <h2 style="margin-top:22px">🗓 التدفق الشهري (دخل مقابل مصروف)</h2>
      {month_html}
    </section>
    <section class="panel">
      <h2>🧾 الميزانية مقابل التنفيذ</h2>
      {budget_html}
      <h2 style="margin-top:22px">🔎 تنبيهات التدقيق</h2>
      {anom_html}
      {ai_block}
    </section>
  </div>

  <section class="panel" style="margin-top:16px">
    <h2>🗂 سجل الفواتير والقيود ({len(txns)})</h2>
    <div class="filters">
      <button data-sev="all" class="active">الكل</button>
      <button data-sev="expense">مصروفات</button>
      <button data-sev="income">إيرادات</button>
    </div>
    <div class="scroll">
      <table>
        <thead><tr><th>التاريخ</th><th>الجهة / البيان</th><th>التصنيف</th><th>المبلغ</th><th>الضريبة</th><th>النوع والمصدر</th></tr></thead>
        <tbody id="rows">{''.join(rows_html)}</tbody>
      </table>
    </div>
  </section>

  <footer>
    <div class="foot-grid">
      <div><b>📞 الدعم الفني</b><br>{SUPPORT['email']}<br>{SUPPORT['phone']}</div>
      <div><b>💳 الدفع (اختياري)</b><br>ليرة: {SUPPORT['tr_iban']}<br>دولار: {SUPPORT['usd_iban']}<br>بيتكوين: {SUPPORT['btc']}</div>
      <div><b>📜 الملكية</b><br>MIT © 2026 {SUPPORT['holder']} — جميع الحقوق محفوظة<br><a href="{SUPPORT['store']}">المتجر الرسمي</a></div>
      <div><b>🔒 الخصوصية</b><br>كل الأرقام الحسّاسة مُقنّعة تلقائياً · v{__version__}</div>
    </div>
  </footer>
</div>
<script>{JS}</script>
</body>
</html>"""
    return html_doc


def _ring_svg(score: int) -> str:
    pct = max(0, min(100, score))
    circumference = 2 * 3.14159 * 62
    dash = circumference * pct / 100.0
    color = "#3ddc84" if pct >= 80 else ("#f7c948" if pct >= 55 else "#ff4d6d")
    return (
        f'<svg class="ring" viewBox="0 0 150 150">'
        f'<circle class="ring-bg" cx="75" cy="75" r="62"/>'
        f'<circle class="ring-fg" cx="75" cy="75" r="62" stroke="{color}" '
        f'stroke-dasharray="{dash:.1f} {circumference - dash:.1f}" '
        f'transform="rotate(-90 75 75)"/>'
        f'<text class="ring-num" x="75" y="82" text-anchor="middle">{pct}</text>'
        f'<text class="ring-cap" x="75" y="104" text-anchor="middle">الصحة المالية</text>'
        f'</svg>'
    )


def _months_svg(months: List[Dict[str, Any]]) -> str:
    if not months:
        return '<p class="muted">لا بيانات شهرية بعد.</p>'
    width, height = 520, 150
    peak = max(max(m["income"], m["expense"]) for m in months) or 1
    group = width / max(1, len(months))
    parts = [f'<svg viewBox="0 0 {width} {height}" class="spark">']
    for i, m in enumerate(months):
        x = i * group + group * 0.18
        bw = group * 0.28
        hi = (height - 40) * m["income"] / peak
        he = (height - 40) * m["expense"] / peak
        parts.append(f'<rect x="{x:.1f}" y="{height - 30 - hi:.1f}" width="{bw:.1f}" height="{hi:.1f}" rx="3" fill="#3ddc84"/>')
        parts.append(f'<rect x="{x + bw + 4:.1f}" y="{height - 30 - he:.1f}" width="{bw:.1f}" height="{he:.1f}" rx="3" fill="#ff6b6b"/>')
        parts.append(f'<text x="{x + bw:.1f}" y="{height - 10}" fill="#8b97b3" font-size="11" text-anchor="middle">{esc(m["month"][5:] or m["month"])}</text>')
    parts.append('<text x="8" y="14" fill="#8ef0bd" font-size="11">■ دخل</text>')
    parts.append('<text x="60" y="14" fill="#ff9d9d" font-size="11">■ مصروف</text>')
    parts.append('</svg>')
    return "".join(parts)


def _health_score(totals: Dict[str, float], anomalies: List[Any]) -> int:
    """0–100: صافي موجب يرفعها، والتنبيهات الحرجة تخفضها."""
    score = 70.0
    income, expense = totals.get("income", 0), totals.get("expense", 0)
    if income > 0:
        score += max(-35, min(30, 30.0 * (income - expense) / income))
    for a in anomalies:
        sev = getattr(a, "severity", "info")
        score -= {"high": 14, "medium": 7, "low": 3, "info": 1}.get(sev, 1)
    return int(max(5, min(99, round(score))))


def write(batch: Batch, anomalies: List[Any], budgets: Optional[Dict[str, float]] = None,
          ai_note: Optional[str] = None, out_dir: str = "reports") -> Dict[str, str]:
    """يكتب HTML + JSON + CSV في مجلد الإخراج ويعود المسارات."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    txns = batch.transactions
    doc = render(batch, anomalies, budgets, ai_note)
    html_path = target / "report.html"
    html_path.write_text(doc, encoding="utf-8")

    totals = totals_of(txns)
    payload = {
        "generated_at": time.time(),
        "version": __version__,
        "currency": config.base_currency(),
        "totals": totals,
        "categories": by_category(txns),
        "months": by_month(txns),
        "budgets": budgets or {},
        "anomalies": [a.to_dict() for a in anomalies],
        "transactions": [t.to_dict() for t in txns],
        "errors": batch.errors,
        "skipped": batch.skipped,
        "duration": batch.duration,
    }
    json_path = target / "report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    csv_path = target / "transactions.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "vendor", "kind", "category", "account", "amount", "tax", "currency", "invoice_no", "source"])
        for t in txns:
            writer.writerow([t.date, t.vendor, t.kind, t.category, t.account, f"{t.amount:.2f}",
                             f"{t.tax:.2f}", t.currency, t.invoice_no, Path(t.source).name if t.source else ""])
    return {"html": str(html_path), "json": str(json_path), "csv": str(csv_path)}
