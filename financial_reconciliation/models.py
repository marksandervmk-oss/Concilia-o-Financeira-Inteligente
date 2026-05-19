from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import pandas as pd

CANONICAL_COLUMNS = [
    "transaction_id",
    "source_type",
    "source_file",
    "source_row",
    "date",
    "amount",
    "abs_amount",
    "direction",
    "description",
    "counterparty",
    "transaction_type",
    "account",
    "external_id",
    "normalized_description",
    "normalized_counterparty",
    "raw_data",
]


def make_transaction_id(*parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def empty_transactions() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLUMNS)


def ensure_canonical(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_transactions()
    out = df.copy()
    for column in CANONICAL_COLUMNS:
        if column not in out.columns:
            out[column] = None
    out = out[CANONICAL_COLUMNS]
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    out["abs_amount"] = out["amount"].abs()
    out = out.dropna(subset=["date", "amount"]).reset_index(drop=True)
    return out


def row_to_json(row: dict[str, Any]) -> str:
    def default(value: Any) -> str:
        if isinstance(value, (datetime, pd.Timestamp)):
            return value.isoformat()
        return str(value)

    return json.dumps(row, ensure_ascii=False, default=default)
