from __future__ import annotations

import re
import hashlib
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from financial_reconciliation.models import ensure_canonical, make_transaction_id
from financial_reconciliation.normalization import normalize_text, searchable_text
from financial_reconciliation.parsers.common import infer_direction, parse_money

DATE_START_RE = re.compile(r"^(?P<date>\d{2}/\d{2}/\d{4})(?!\s+\d{2}:\d{2})")
AMOUNT_RE = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}[DC]?(?!\d)")
ACCOUNT_RE = re.compile(r"^Conta:\s*(.+)$", re.IGNORECASE)
TRAILING_CODES_RE = re.compile(r"\s*\d{1,10}\s+\d{1,10}\s+(?:Matriz|Filial).*$", re.IGNORECASE)
SINGLE_CODE_RE = re.compile(r"\s*\d{1,10}\s+(?:Matriz|Filial).*$", re.IGNORECASE)
CACHE_VERSION = "pdf-ledger-v1"


def _cache_path(path: Path, max_pages: int | None) -> Path:
    stat = path.stat()
    key = "|".join(
        [
            CACHE_VERSION,
            str(path.resolve()),
            str(stat.st_size),
            str(int(stat.st_mtime)),
            str(max_pages or "all"),
        ]
    )
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:20]
    return Path.cwd() / "data" / "cache" / f"{digest}.pkl"


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

    reader = PdfReader(str(path))
    records: list[dict[str, object]] = []
    current_account = ""
    pages = reader.pages if max_pages is None else reader.pages[:max_pages]

    for page_index, page in enumerate(pages, start=1):
        text = page.extract_text() or ""
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
