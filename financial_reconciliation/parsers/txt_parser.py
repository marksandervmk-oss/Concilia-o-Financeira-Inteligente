from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from financial_reconciliation.models import ensure_canonical, make_transaction_id
from financial_reconciliation.normalization import normalize_text
from financial_reconciliation.parsers.common import (
    canonicalize_dataframe,
    detect_encoding,
    detect_separator,
    infer_direction,
    parse_money,
)

LINE_RE = re.compile(
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<history>.*?)\s+(?P<amount>-?(?:R\$)?\s*\d[\d.]*,\d{2})\s*$"
)


def load_txt(path: str | Path, source_type: str) -> pd.DataFrame:
    path = Path(path)
    encoding = detect_encoding(path)
    text = path.read_text(encoding=encoding, errors="replace")
    separator = detect_separator(text[:4096])
    if separator:
        rows = [line.split(separator) for line in text.splitlines() if line.strip()]
        if len(rows) > 1:
            frame = pd.DataFrame(rows[1:], columns=rows[0])
            parsed = canonicalize_dataframe(frame, source_type=source_type, source_file=str(path))
            if not parsed.empty:
                return parsed

    records = []
    for index, line in enumerate(text.splitlines(), start=1):
        match = LINE_RE.search(line.strip())
        if not match:
            continue
        date = pd.to_datetime(match.group("date"), dayfirst=True, errors="coerce")
        amount = parse_money(match.group("amount"))
        if pd.isna(date) or amount is None:
            continue
        history = match.group("history")
        records.append(
            {
                "transaction_id": make_transaction_id(path, index, line),
                "source_type": source_type,
                "source_file": str(path),
                "source_row": index,
                "date": pd.Timestamp(date),
                "amount": amount,
                "abs_amount": abs(amount),
                "direction": infer_direction(amount, history),
                "description": history,
                "counterparty": history,
                "transaction_type": "TXT",
                "account": "",
                "external_id": "",
                "normalized_description": normalize_text(history),
                "normalized_counterparty": normalize_text(history),
                "raw_data": line.strip(),
            }
        )
    return ensure_canonical(pd.DataFrame(records))
