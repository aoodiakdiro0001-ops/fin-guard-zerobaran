"""طبقة الالتقاط والقراءة (Ingestion & OCR).

تقبل: PDF · صور (OCR) · نص · CSV · JSON · إيميل · HTML — عربي وإنجليزي وتركي.
كل المحرّكات اختيارية: إن لم يوجد Tesseract أو PyMuPDF ينتقل إلى البدائل تلقائياً.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import zlib
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import parse
from .models import Batch, Transaction

TEXT_EXT = {".txt", ".md", ".log", ".tsv", ".xml", ".rst"}
TABULAR_EXT = {".csv", ".tsv"}
EMAIL_EXT = {".eml", ".msg"}
HTML_EXT = {".html", ".htm"}
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "reports", ".next", "dist", "build"}
MAX_BYTES = 12 * 1024 * 1024
MAX_FILES = 4000

AMOUNT_KEYS = ("amount", "total", "مبلغ", "قيمة", "total_amount", "price", "المبلغ")
DATE_KEYS = ("date", "تاريخ", "invoice_date", "issued_at", "tx_date")
VENDOR_KEYS = ("vendor", "seller", "supplier", "merchant", "المورد", "الجهة", "payee")
CAT_KEYS = ("category", "تصنيف", "نوع", "type", "account")


# --------------------------------------------------------------------------- PDF
def _pdf_text_builtin(data: bytes) -> str:
    """مستخرج PDF خفيف (zlib + كائنات النص) بلا أي تبعية."""
    chunks: List[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass  # مسار غير مضغوط — نُكمل قراءته كما هو
        if b"BT" not in raw and b"Tj" not in raw and b"TJ" not in raw:
            continue
        for token in re.finditer(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>", raw):
            piece = token.group(0)
            if piece.startswith(b"("):
                body = piece[1:-1]
                body = re.sub(rb"\\([nrtbf()\\])", lambda mm: {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}[mm.group(1)], body)
                body = re.sub(rb"\\([0-7]{1,3})", lambda mm: bytes([int(mm.group(1), 8) & 0xFF]), body)
                chunks.append(body.decode("latin-1", "replace") + "\n")
            else:
                hexed = re.sub(rb"\s", b"", piece[1:-1])
                try:
                    blob = bytes.fromhex(hexed.decode("ascii"))
                except ValueError:
                    continue
                if blob.startswith(b"\xfe\xff"):
                    chunks.append(blob[2:].decode("utf-16-be", "replace") + "\n")
                else:
                    chunks.append(blob.decode("latin-1", "replace") + "\n")
        chunks.append("\n")
    return re.sub(r"[ \t]+", " ", "".join(chunks))


def extract_pdf(path: Path) -> Tuple[str, str]:
    try:
        import fitz  # type: ignore  # PyMuPDF — اختياري

        with fitz.open(str(path)) as doc:
            return "\n".join(page.get_text() for page in doc), "pdf"
    except Exception:
        pass
    if shutil.which("pdftotext"):
        try:
            out = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                 capture_output=True, text=True, timeout=60)
            if out.stdout.strip():
                return out.stdout, "pdf"
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        text = _pdf_text_builtin(path.read_bytes())
    except OSError:
        return "", "pdf"
    return text, "pdf"


def extract_image(path: Path) -> Tuple[str, str]:
    """OCR عبر Tesseract إن وُجد (ara+eng) — وإلّا رسالة توضيحية."""
    binary = shutil.which("tesseract")
    if not binary:
        return "", "ocr-missing"
    langs = "ara+eng"
    probe = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, timeout=30)
    available = set(probe.stdout.split())
    if "ara" not in available and "eng" in available:
        langs = "eng"
    try:
        out = subprocess.run([binary, str(path), "stdout", "-l", langs],
                             capture_output=True, text=True, timeout=120)
        return out.stdout, "ocr"
    except (subprocess.SubprocessError, OSError):
        return "", "ocr"


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\n{2,}", "\n", text)


def read_email(path: Path) -> Tuple[str, str]:
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    subject = str(msg.get("subject", ""))
    sender = str(msg.get("from", ""))
    date = str(msg.get("date", ""))
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_content()
                    break
                except Exception:
                    continue
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    try:
                        body = strip_html(str(part.get_content()))
                        break
                    except Exception:
                        continue
    else:
        try:
            raw = str(msg.get_content())
            body = strip_html(raw) if "html" in str(msg.get_content_type()) else raw
        except Exception:
            body = ""
    return f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body}", "email"


def extract_text(path: Path) -> Tuple[str, str, str]:
    """(النص، المحرّك، الخطأ) — ينتقل بين البدائل تلقائياً."""
    suffix = path.suffix.lower()
    try:
        if suffix in PDF_EXT:
            text, engine = extract_pdf(path)
            if not text.strip():
                return "", engine, "تعذّر استخراج نص من PDF (جرّب تثبيت PyMuPDF أو Tesseract)"
            return text, engine, ""
        if suffix in IMAGE_EXT:
            text, engine = extract_image(path)
            if engine == "ocr-missing":
                return "", engine, "Tesseract غير مثبّت — ثبّته لقراءة صور الفواتير (brew install tesseract)"
            if not text.strip():
                return "", engine, "لم يعثِر OCR على نص واضح في الصورة"
            return text, engine, ""
        if suffix in EMAIL_EXT:
            text, engine = read_email(path)
            return text, engine, ""
        data = path.read_bytes()
        if len(data) > MAX_BYTES:
            return "", "text", "الملف أكبر من الحد المسموح (12MB)"
        text = data.decode("utf-8", "replace")
        if suffix in HTML_EXT:
            text = strip_html(text)
        return text, "text", ""
    except OSError as exc:
        return "", "text", f"تعذّر قراءة الملف: {exc}"


# ----------------------------------------------------------------- tabular rows
def _rows_from_tabular(path: Path) -> List[Dict[str, str]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    sample = raw[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample.strip() else delimiter
    except csv.Error:
        dialect = delimiter  # type: ignore[assignment]
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    rows: List[Dict[str, str]] = []
    for row in reader:
        if row and any((v or "").strip() for v in row.values()):
            rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k})
    return rows


def _pick(row: Dict[str, str], keys: tuple) -> str:
    for key in keys:
        if key in row and row[key]:
            return row[key]
    for k, v in row.items():
        if any(key in k for key in keys) and v:
            return v
    return ""


def transaction_from_row(row: Dict[str, str], source: str, extractor: str) -> Optional[Transaction]:
    amount_raw = _pick(row, AMOUNT_KEYS)
    if not amount_raw:
        return None
    amounts = parse.find_amounts(amount_raw) or [(0.0, "")]
    amount = amounts[0][0] if amounts and amounts[0][0] else 0.0
    if amount <= 0:
        return None
    currency = amounts[0][1] if amounts and amounts[0][1] else parse.detect_currency(str(row))
    date = _pick(row, DATE_KEYS)
    date = parse.best_date(date, source) if date else parse.best_date("", source)
    vendor = _pick(row, VENDOR_KEYS) or parse.find_vendor(str(row), source)
    category = _pick(row, CAT_KEYS)
    tax_raw = _pick(row, ("tax", "vat", "kdv", "ضريبة"))
    tax = 0.0
    if tax_raw:
        found = parse.find_amounts(tax_raw)
        tax = found[0][0] if found else 0.0
    text = " ".join(f"{k} {v}" for k, v in row.items())
    kind = parse.guess_kind(text, source)
    return Transaction(
        date=date, vendor=vendor, description=str(row.get("description") or row.get("وصف") or text[:120]),
        currency=currency, amount=round(amount, 2), tax=round(min(tax, amount), 2),
        kind=kind, category=category or "", source=source, extractor=extractor,
        confidence=parse.guess_confidence(text, amount, date),
    )


# ---------------------------------------------------------------------- ingest
def iter_files(root: Path) -> List[Path]:
    if root.is_file():
        return [root]
    files: List[Path] = []
    for dirpath, dirnames, filenames in root.walk() if hasattr(root, "walk") else _os_walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            files.append(p)
            if len(files) >= MAX_FILES:
                return files
    return files


def _os_walk(root: Path):
    import os

    for dirpath, dirnames, filenames in os.walk(root):
        yield Path(dirpath), dirnames, filenames


def ingest(path: str, budget_hint: Optional[dict] = None) -> Batch:
    """يقرأ كل ملف داخل `path` (ملف أو مجلد) ويحوّله إلى قيود مالية."""
    batch = Batch()
    root = Path(path).expanduser()
    if not root.exists():
        batch.errors.append(f"المسار غير موجود: {path}")
        return batch.close()

    for file in iter_files(root):
        suffix = file.suffix.lower()
        if suffix in TABULAR_EXT:
            rows = _rows_from_tabular(file)
            if not rows:
                batch.skipped.append(str(file))
                continue
            for row in rows:
                txn = transaction_from_row(row, str(file), "csv")
                if txn:
                    if not txn.category:
                        txn.category = ""
                    batch.transactions.append(txn)
            continue
        if suffix == ".json":
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                batch.errors.append(f"{file.name}: JSON غير صالح ({exc})")
                continue
            items = data if isinstance(data, list) else data.get("transactions") or data.get("records") or []
            for row in items:
                if isinstance(row, dict):
                    txn = transaction_from_row({str(k).lower(): str(v) for k, v in row.items()}, str(file), "json")
                    if txn:
                        batch.transactions.append(txn)
            continue

        text, engine, error = extract_text(file)
        if error:
            batch.skipped.append(f"{file.name}: {error}")
            continue
        if len(text.strip()) < 8:
            batch.skipped.append(f"{file.name}: لا نص كافٍ للقراءة")
            continue
        batch.transactions.append(_transaction_from_text(text, str(file), engine))

    return batch.close()


def _transaction_from_text(text: str, source: str, engine: str) -> Transaction:
    from . import classify

    kind = parse.guess_kind(text, source)
    amount, currency, tax = parse.pick_total(text, kind)
    date = parse.best_date(text, source)
    vendor = parse.find_vendor(text, source)
    txn = Transaction(
        date=date, vendor=vendor,
        description=next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:140],
        currency=currency, amount=amount, tax=tax, kind=kind,
        source=source, extractor=engine,
        invoice_no=parse.find_invoice_no(text, source),
        confidence=parse.guess_confidence(text, amount, date),
    )
    return classify.apply_local(txn, text)
