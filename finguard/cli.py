"""واجهة الأوامر: ingest · report · history · doctor · init · serve · send."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __project__, __version__, ai, alert, anomalies, classify, config, ledger, report, store
from .extract import ingest as run_ingest
from .models import Batch, Transaction

BANNER = r"""
  ╔═══════════════════════════════════════════════════════════════╗
  ║   Fin-Guard ZeroBaran — إدارة الحسابات والفواتير والتدقيق    ║
  ║   الذاتية الذكية · مجاني بالكامل · © 2026 Baran Avisat       ║
  ╚═══════════════════════════════════════════════════════════════╝
"""
MARKER = "." * 62


def _label(txns: List[Transaction]) -> str:
    months = sorted({t.year_month for t in txns if t.year_month})
    if not months:
        return "فترة غير مؤرخة"
    return months[0] if len(months) == 1 else f"{months[0]} → {months[-1]}"


def _prepare(txns: List[Transaction], use_ai: bool) -> int:
    """تصنيف محلي دائماً + تحسين ذكي اختياري."""
    for txn in txns:
        classify.apply_local(txn)
    if not use_ai:
        return 0
    return ai.enrich(txns)


def _finalise(batch: Batch, budgets: dict, label: str, out_dir: str,
              notify: bool, use_ai: bool) -> int:
    enriched = _prepare(batch.transactions, use_ai)
    anomalies_list = anomalies.detect(batch.transactions, budgets)
    entries = ledger.post(batch.transactions)
    ledger_errors = ledger.validate(entries)
    ledger.save(entries, f"{out_dir}/ledger.jsonl")
    store.save_transactions(batch.transactions, f"{out_dir}/transactions.json")

    totals = report.totals_of(batch.transactions)
    ai_note = None
    if use_ai:
        lines = [f"{t.date} {t.vendor} {t.amount} {t.currency} {t.category}"
                 for t in batch.transactions[:25]]
        ai_note = ai.summary(lines)

    paths = report.write(batch, anomalies_list, budgets, ai_note, out_dir=out_dir)
    label = label or _label(batch.transactions)
    store.record_run({
        "label": label, "income": totals["income"], "expense": totals["expense"],
        "net": totals["net"], "count": totals["count"],
        "anomalies": len(anomalies_list), "source": str(len(batch.transactions)),
    })

    print(BANNER)
    if batch.errors:
        for err in batch.errors:
            print(f"  ✖ {err}")
    if batch.skipped:
        for note in batch.skipped[:8]:
            print(f"  ⚠ {note}")
    print(f"\n🧾 {len(batch.transactions)} قيداً · {batch.duration} ثانية"
          + (f" · حسّنها الذكاء الاصطناعي: {enriched}" if enriched else ""))
    print(f"💰 الإيراد {totals['income']:,.2f} · المصروف {totals['expense']:,.2f} · "
          f"الصافي {totals['net']:,.2f} · ضريبة قابلة للخصم {totals['tax']:,.2f}")
    print(f"🔎 تنبيهات: {len(anomalies_list)}"
          + (f" · أخطاء دفتر: {len(ledger_errors)}" if ledger_errors else ""))
    for item in anomalies_list[:6]:
        print(f"   [{item.severity}] {item.title}")
    print(f"📊 التقرير: {paths['html']}")
    print(f"📄 JSON: {paths['json']}  ·  CSV: {paths['csv']}")

    print("  " + store.push_supabase(batch.transactions, label))
    if notify:
        print("  " + alert.send_summary(totals, anomalies_list, label, ai_note))
    else:
        print("ℹ️  تنبيهات تليجرام غير مضبوطة (اختياري): TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    config.load_dotenv(args.env)
    budgets = config.budgets_from(args.budget)
    target = args.path or str(config.inbox_dir())
    batch = run_ingest(target)
    return _finalise(batch, budgets, args.label, args.out, args.notify, not args.no_ai)


def cmd_report(args: argparse.Namespace) -> int:
    """إعادة بناء التقرير من قيود محفوظة دون إعادة قراءة الفواتير."""
    config.load_dotenv(args.env)
    txns = store.load_transactions(args.input)
    if not txns:
        print("✖ لا قيود محفوظة — نفّذ `ingest` أولاً.")
        return 2
    batch = Batch(transactions=txns).close()
    budgets = config.budgets_from(args.budget)
    anomalies_list = anomalies.detect(txns, budgets)
    paths = report.write(batch, anomalies_list, budgets, None, out_dir=args.out)
    print(f"📊 أُعيد بناء التقرير: {paths['html']}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    config.load_dotenv(args.env)
    rows = store.history(args.limit)
    if not rows:
        print("لا سجلات بعد — نفّذ دفعة `ingest` واحدة أولاً.")
        return 0
    print(f"{'التاريخ':<21}{'الإيراد':>14}{'المصروف':>14}{'الصافي':>14}  الفترة")
    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(row.get("ts", 0)))
        print(f"{when:<21}{row.get('income', 0):>14,.2f}{row.get('expense', 0):>14,.2f}"
              f"{row.get('net', 0):>14,.2f}  {row.get('label', '')}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    loaded = config.load_dotenv(args.env)
    print(BANNER)
    print(f"📄 ملف البيئة: {'قُرئ (' + str(len(loaded)) + ' متغيّر)' if loaded else 'غير موجود — يعمل بالمحرّك المحلي'}")
    summary = config.configured_summary()
    for name, ok in summary.items():
        print(f"  {'✅' if ok else '⚪'} {name}")
    inbox = config.inbox_dir()
    print(f"📁 صندوق الفواتير: {inbox} {'(موجود)' if inbox.exists() else '(سيُنشأ عند init)'}")
    budgets = config.budgets_from()
    if budgets:
        print(f"🧾 الميزانية: {', '.join(f'{k}={v:,.0f}' for k, v in budgets.items() if not k.startswith('__'))}")
    import shutil
    print(f"  {'✅' if shutil.which('tesseract') else '⚪'} tesseract (OCR للصور — اختياري)")
    pdf_engine = "PyMuPDF" if _has_pymupdf() else ("pdftotext" if shutil.which("pdftotext") else "المستخرج المدمج")
    print(f"  ✅ pdf-engine ({pdf_engine})")
    print("المحرّك الذكي: " + (config.ai_provider() or "محلي حتمي (بلا مفاتيح)"))
    return 0


def _has_pymupdf() -> bool:
    try:
        import fitz  # noqa: F401
        return True
    except Exception:
        return False


def cmd_init(args: argparse.Namespace) -> int:
    env = Path(args.env)
    if not env.exists() and Path(".env.example").is_file():
        env.write_text(Path(".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print(f"📄 أُنشئ {env} من النموذج — ضع مفاتيحك فيه (أو اتركه فارغاً).")
    inbox = config.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "README.txt").write_text(
        "ضع هنا فواتيرك: PDF · صور · CSV · TXT · EML · HTML\n"
        "ثم نفّذ: python3 -m finguard ingest\n", encoding="utf-8")
    budget = Path("budget.json")
    if not budget.exists():
        sample = Path("budget.example.json")
        if sample.is_file():
            budget.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            budget.write_text(json.dumps(
                {"__total__": 30000, "تسويق وإعلانات": 10000, "خدمات مهنية": 7000,
                 "مشتريات ومخزون": 5000, "إيجارات ومرافق": 4500, "أخرى": 500},
                ensure_ascii=False, indent=2), encoding="utf-8")
        print("🧾 أُنشئ budget.json (عدّل الحسب حاجتك).")
    print("✅ التهيئة اكتملت — ضع فواتيرك في " + str(inbox))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """خادم محلي صغير (مكتبة Python القياسية فقط) لعرض التقارير."""
    import functools
    import http.server

    root = Path(args.out).resolve()
    if not (root / "report.html").is_file():
        print(f"✖ لا يوجد تقرير في {root} — نفّذ `ingest` أولاً.")
        return 2
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"🖥  http://{args.host}:{args.port}/report.html  (Ctrl+C للإيقاف)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nتم الإيقاف.")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    config.load_dotenv(args.env)
    txns = store.load_transactions(args.input)
    if not txns:
        print("✖ لا قيود محفوظة.")
        return 2
    batch = Batch(transactions=txns).close()
    totals = report.totals_of(txns)
    items = anomalies.detect(txns, config.budgets_from(args.budget))
    print(alert.send_summary(totals, items, _label(txns)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="finguard",
        description=f"{__project__} v{__version__} — إدارة مالية آلية بموارد مجانية",
    )
    p.add_argument("--env", default=".env", help="ملف البيئة (افتراضي .env)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="قراءة وتصنيف فواتير من ملف أو مجلد")
    ing.add_argument("path", nargs="?", help="ملف/مجلد (افتراضي finance/inbox)")
    ing.add_argument("--out", default="reports", help="مجلد إخراج التقارير")
    ing.add_argument("--label", default="", help="اسم الفترة في السجل")
    ing.add_argument("--budget", default="budget.json", help="ملف الميزانية")
    ing.add_argument("--notify", action="store_true", help="إرسال تقرير تليجرام")
    ing.add_argument("--no-ai", action="store_true", help="تعطيل المزوّد الذكي والاكتفاء بالمحرّك المحلي")
    ing.set_defaults(func=cmd_ingest)

    rep = sub.add_parser("report", help="إعادة بناء التقرير من قيود محفوظة")
    rep.add_argument("--input", default="reports/transactions.json")
    rep.add_argument("--out", default="reports")
    rep.add_argument("--budget", default="budget.json")
    rep.set_defaults(func=cmd_report)

    his = sub.add_parser("history", help="عرض سجل الدفعات")
    his.add_argument("--limit", type=int, default=24)
    his.set_defaults(func=cmd_history)

    doc = sub.add_parser("doctor", help="تشخيص التهيئة والمحرّكات")
    doc.set_defaults(func=cmd_doctor)

    ini = sub.add_parser("init", help="تهيئة مجلدات وملفات المشروع")
    ini.add_argument("--env", dest="env", default=".env")
    ini.set_defaults(func=cmd_init)

    srv = sub.add_parser("serve", help="تشغيل خادم محلي لعرض التقرير")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8501)
    srv.add_argument("--out", default="reports")
    srv.set_defaults(func=cmd_serve)

    snd = sub.add_parser("send", help="إرسال التقرير الحالي إلى تليجرام")
    snd.add_argument("--input", default="reports/transactions.json")
    snd.add_argument("--budget", default="budget.json")
    snd.set_defaults(func=cmd_send)

    for name in ("ingest", "report", "history", "send"):
        sub.choices[name].add_argument("--env", default=".env", help=argparse.SUPPRESS)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "env"):
        args.env = ".env"
    return args.func(args)
