"""لوحة Streamlit الاختيارية — رسوم بيانية للفواتير المسجّلة.

التشغيل:
    pip install streamlit          # مجاني
    streamlit run dashboard/app.py

تقرأ اللوحة نفس المخرجات المحلية (reports/transactions.json) فلا ترسل
أي رقم إلى أي خادم.
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("ثبّت Streamlit أولاً: pip install streamlit")

REPORT = Path("reports/transactions.json")

st.set_page_config(page_title="Fin-Guard ZeroBaran", page_icon="🧾", layout="wide")
st.title("🧾 Fin-Guard ZeroBaran")
st.caption("لوحة مالية محلية — تعمل على ملفاتك دون إرسال أي بيانات.")

if not REPORT.is_file():
    st.warning("لا يوجد تقرير بعد — نفّذ أولاً: `python3 -m finguard ingest`")
    st.stop()

data = json.loads(REPORT.read_text(encoding="utf-8"))
txns = data.get("transactions", [])
if not txns:
    st.info("لا قيود في التقرير.")
    st.stop()

income = sum(t["amount"] for t in txns if t["kind"] == "income")
expense = sum(t["amount"] for t in txns if t["kind"] == "expense")

c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 الإيرادات", f"{income:,.2f}")
c2.metric("💸 المصروفات", f"{expense:,.2f}")
c3.metric("📈 الصافي", f"{income - expense:,.2f}")
c4.metric("🧾 عدد القيود", len(txns))

st.subheader("الفئات")
cats: dict[str, float] = {}
for t in txns:
    if t["kind"] == "expense":
        cats[t["category"]] = cats.get(t["category"], 0.0) + float(t["amount"])
if cats:
    st.bar_chart(cats)

st.subheader("آخر القيود")
st.dataframe(
    [
        {
            "التاريخ": t["date"],
            "النوع": "مصروف" if t["kind"] == "expense" else "إيراد",
            "الفئة": t["category"],
            "الجهة": t["vendor"],
            "المبلغ": float(t["amount"]),
            "المصدر": t.get("source_file", ""),
        }
        for t in sorted(txns, key=lambda x: x["date"], reverse=True)
    ],
    use_container_width=True,
)
