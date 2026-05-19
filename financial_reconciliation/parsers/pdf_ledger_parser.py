from __future__ import annotations

import re
import hashlib
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional fast PDF engine
    fitz = None

from financial_reconciliation.models import ensure_canonical, make_transaction_id
from financial_reconciliation.normalization import normalize_text, searchable_text
from financial_reconciliation.parsers.common import infer_direction, parse_money

DATE_START_RE = re.compile(r"^(?P<date>\d{2}/\d{2}/\d{4})(?!\s+\d{2}:\d{2})")
DATE_ONLY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
AMOUNT_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}[DC]?(?!\d)")
ACCOUNT_RE = re.compile(r"^Conta:\s*(.+)$", re.IGNORECASE)
CODE_RE = re.compile(r"^\d{1,10}$")
BRANCH_RE = re.compile(r"^(?:Matriz|Filial)$", re.IGNORECASE)
TRAILING_CODES_RE = re.compile(r"\s*\d{1,10}\s+\d{1,10}\s+(?:Matriz|Filial).*$", re.IGNORECASE)
SINGLE_CODE_RE = re.compile(r"\s*\d{1,10}\s+(?:Matriz|Filial).*$", re.IGNORECASE)
CACHE_VERSION = "pdf-ledger-v3"


def _cache_path(path: Path, max_pages: int | None) -> Path:
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:20]
    key = "|".join(
        [
            CACHE_VERSION,
            digest,
            str(max_pages or "all"),
        ]
    )
    cache_key = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:20]
    return Path.cwd() / "data" / "cache" / f"{cache_key}.pkl"


def _clean_history(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = TRAILING_CODES_RE.sub("", text)
    text = SINGLE_CODE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text


def _sign_from_history(history: str, amount: float) -> float:
    normalized = searchable_text(history)
    compact = normalized.replace(" ", "")
    out_words = ("ENVIADA", "PAGAMENTO", "PAGTO", "TARIFA", "DEBITO", "SAIDA")
    in_words = ("RECEBIDA", "RECEBIMENTO", "CREDITO", "ENTRADA")
    if any(word in normalized or word in compact for word in out_words):
        return -abs(amount)
    if any(word in normalized or word in compact for word in in_words):
        return abs(amount)
    return amount


def _parse_line(line: str, current_account: str, page_number: int, source_file: str) -> dict[str, object] | None:
    stripped = line.strip()
    if not stripped:
        return None
    date_match = DATE_START_RE.match(stripped)
    if not date_match:
        return None
    if "P\u00e1g" in stripped or "Pag:" in stripped or "Periodo" in stripped:
        return None
    if "Saldo anterior" in stripped or "Totais" in stripped:
        return None

    amount_matches = list(AMOUNT_RE.finditer(stripped))
    if len(amount_matches) < 2:
        return None

    transaction_match = None
    for match in reversed(amount_matches[:-1]):
        value = parse_money(match.group())
        if value is not None and abs(value) > 0:
            transaction_match = match
            break
    if transaction_match is None:
        return None

    raw_amount = transaction_match.group()
    amount = parse_money(raw_amount)
    if amount is None:
        return None

    date_text = date_match.group("date")
    date = pd.to_datetime(date_text, dayfirst=True, errors="coerce")
    if pd.isna(date):
        return None

    history_start = date_match.end()
    history = _clean_history(stripped[history_start : transaction_match.start()])
    if not history:
        return None

    signed_amount = _sign_from_history(history, amount)
    direction = infer_direction(signed_amount, history)
    source_row = f"page:{page_number}"
    return {
        "transaction_id": make_transaction_id(source_file, current_account, page_number, stripped),
        "source_type": "ledger",
        "source_file": source_file,
        "source_row": source_row,
        "date": pd.Timestamp(date),
        "amount": signed_amount,
        "abs_amount": abs(signed_amount),
        "direction": direction,
        "description": history,
        "counterparty": history,
        "transaction_type": "PDF ledger",
        "account": current_account,
        "external_id": "",
        "normalized_description": normalize_text(history),
        "normalized_counterparty": normalize_text(history),
        "raw_data": stripped,
    }


def _is_boundary(line: str) -> bool:
    stripped = line.strip()
    return bool(
        DATE_ONLY_RE.match(stripped)
        or ACCOUNT_RE.match(stripped)
        or stripped.startswith("***********")
        or stripped in {"Data", "Hist\u00f3rico", "Contrapart. Sequ\u00eanc.", "Filial"}
    )


def _structured_history(block: list[str]) -> str:
    if not block:
        return ""

    first_amount_index = None
    last_amount_index = None
    for index, line in enumerate(block):
        if AMOUNT_RE.search(line):
            first_amount_index = index if first_amount_index is None else first_amount_index
            last_amount_index = index

    prefix: list[str] = []
    for line in block[: first_amount_index or len(block)]:
        stripped = line.strip()
        if not stripped:
            continue
        if CODE_RE.match(stripped) or BRANCH_RE.match(stripped) or AMOUNT_RE.search(stripped):
            break
        prefix.append(stripped)

    suffix: list[str] = []
    if last_amount_index is not None:
        for line in block[last_amount_index + 1 :]:
            stripped = line.strip()
            if not stripped:
                continue
            if _is_boundary(stripped) or CODE_RE.match(stripped) or AMOUNT_RE.search(stripped):
                continue
            suffix.append(stripped)

    return _clean_history(" ".join(prefix + suffix))


def _parse_structured_record(
    date_text: str,
    block: list[str],
    current_account: str,
    page_number: int,
    source_file: str,
) -> dict[str, object] | None:
    if not block:
        return None
    if any("Saldo anterior" in line for line in block) or any("Totais" in line for line in block):
        return None

    amount_matches: list[str] = []
    for line in block:
        amount_matches.extend(match.group() for match in AMOUNT_RE.finditer(line))
    if len(amount_matches) < 2:
        return None

    amount = None
    for raw_amount in amount_matches[:-1]:
        parsed = parse_money(raw_amount)
        if parsed is not None and abs(parsed) > 0:
            amount = parsed
            break
    if amount is None:
        return None

    date = pd.to_datetime(date_text, dayfirst=True, errors="coerce")
    if pd.isna(date):
        return None

    history = _structured_history(block)
    if not history:
        return None

    signed_amount = _sign_from_history(history, amount)
    direction = infer_direction(signed_amount, history)
    raw_data = " ".join([date_text] + block)
    return {
        "transaction_id": make_transaction_id(source_file, current_account, page_number, raw_data),
        "source_type": "ledger",
        "source_file": source_file,
        "source_row": f"page:{page_number}",
        "date": pd.Timestamp(date),
        "amount": signed_amount,
        "abs_amount": abs(signed_amount),
        "direction": direction,
        "description": history,
        "counterparty": history,
        "transaction_type": "PDF ledger",
        "account": current_account,
        "external_id": "",
        "normalized_description": normalize_text(history),
        "normalized_counterparty": normalize_text(history),
        "raw_data": raw_data,
    }


def _parse_structured_page(
    text: str,
    current_account: str,
    page_number: int,
    source_file: str,
) -> tuple[list[dict[str, object]], str]:
    lines = [line.strip() for line in text.splitlines()]
    records: list[dict[str, object]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        account_match = ACCOUNT_RE.match(line)
        if account_match:
            account_parts = [account_match.group(1).strip()]
            lookahead = index + 1
            while lookahead < len(lines) and len(account_parts) < 5:
                candidate = lines[lookahead].strip()
                if not candidate:
                    lookahead += 1
                    continue
                if DATE_ONLY_RE.match(candidate) or ACCOUNT_RE.match(candidate) or candidate.startswith("***********"):
                    break
                if candidate in {
                    "Data",
                    "Hist\u00f3rico",
                    "Contrapart. Sequ\u00eanc.",
                    "Filial",
                    "D\u00e9bito",
                    "Cr\u00e9dito",
                    "Saldo",
                }:
                    break
                account_parts.append(candidate)
                lookahead += 1
            current_account = " ".join(account_parts)
            index += 1
            continue

        if not DATE_ONLY_RE.match(line):
            index += 1
            continue

        date_text = line
        block: list[str] = []
        index += 1
        while index < len(lines) and not _is_boundary(lines[index]):
            block.append(lines[index])
            index += 1
        record = _parse_structured_record(date_text, block, current_account, page_number, source_file)
        if record:
            records.append(record)

    return records, current_account


def _iter_pdf_text(path: Path, max_pages: int | None = None):
    if fitz is not None:
        with fitz.open(str(path)) as doc:
            limit = min(max_pages or len(doc), len(doc))
            for page_index in range(limit):
                yield page_index + 1, doc[page_index].get_text("text") or ""
        return

    reader = PdfReader(str(path))
    pages = reader.pages if max_pages is None else reader.pages[:max_pages]
    for page_index, page in enumerate(pages, start=1):
        yield page_index, page.extract_text() or ""


def load_pdf_ledger(path: str | Path, source_type: str = "ledger", max_pages: int | None = None) -> pd.DataFrame:
    path = Path(path)
    cache = _cache_path(path, max_pages)
    if cache.exists():
        try:
            cached = pd.read_pickle(cache)
            cached["source_type"] = source_type
            return ensure_canonical(cached)
        except Exception:
            cache.unlink(missing_ok=True)

    records: list[dict[str, object]] = []
    current_account = ""
    structured_mode = fitz is not None

    for page_index, text in _iter_pdf_text(path, max_pages=max_pages):
        if structured_mode:
            page_records, current_account = _parse_structured_page(
                text,
                current_account,
                page_index,
                str(path),
            )
            records.extend(page_records)
            continue

        for line in text.splitlines():
            account_match = ACCOUNT_RE.match(line.strip())
            if account_match:
                current_account = account_match.group(1).strip()
                continue
            record = _parse_line(line, current_account, page_index, str(path))
            if record:
                record["source_type"] = source_type
                records.append(record)
    result = ensure_canonical(pd.DataFrame(records))
    cache.parent.mkdir(parents=True, exist_ok=True)
    result.to_pickle(cache)
    return result
