from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from financial_reconciliation.models import ensure_canonical, make_transaction_id
from financial_reconciliation.normalization import normalize_text
from financial_reconciliation.parsers.common import infer_direction, parse_money

try:
    from ofxparse import OfxParser
except Exception:  # pragma: no cover - optional dependency
    OfxParser = None


def _load_with_ofxparse(path: Path, source_type: str) -> pd.DataFrame | None:
    if OfxParser is None:
        return None
    try:
        with path.open("rb") as handle:
            ofx = OfxParser.parse(handle)
    except Exception:
        return None
    records = []
    for account in ofx.accounts:
        account_id = getattr(account, "account_id", "")
        for index, transaction in enumerate(account.statement.transactions):
            amount = float(transaction.amount)
            description = " ".join(
                part
                for part in (
                    getattr(transaction, "payee", ""),
                    getattr(transaction, "memo", ""),
                    getattr(transaction, "type", ""),
                )
                if part
            )
            date = pd.Timestamp(transaction.date)
            records.append(
                {
                    "transaction_id": make_transaction_id(path, account_id, transaction.id, index),
                    "source_type": source_type,
                    "source_file": str(path),
                    "source_row": index + 1,
                    "date": date,
                    "amount": amount,
                    "abs_amount": abs(amount),
                    "direction": infer_direction(amount, description),
                    "description": description,
                    "counterparty": description,
                    "transaction_type": str(getattr(transaction, "type", "")),
                    "account": str(account_id),
                    "external_id": str(getattr(transaction, "id", "")),
                    "normalized_description": normalize_text(description),
                    "normalized_counterparty": normalize_text(description),
                    "raw_data": str(transaction),
                }
            )
    return ensure_canonical(pd.DataFrame(records))


def _load_with_regex(path: Path, source_type: str) -> pd.DataFrame:
    text = path.read_text(encoding="latin1", errors="ignore")
    blocks = re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>)", text, flags=re.S | re.I)
    records = []
    for index, block in enumerate(blocks):
        def tag(name: str) -> str:
            match = re.search(rf"<{name}>([^\r\n<]+)", block, flags=re.I)
            return match.group(1).strip() if match else ""

        date_text = tag("DTPOSTED")[:8]
        amount = parse_money(tag("TRNAMT"))
        if not date_text or amount is None:
            continue
        date = pd.to_datetime(date_text, format="%Y%m%d", errors="coerce")
        if pd.isna(date):
            continue
        description = " ".join(part for part in (tag("NAME"), tag("MEMO"), tag("TRNTYPE")) if part)
        records.append(
            {
                "transaction_id": make_transaction_id(path, tag("FITID"), index),
                "source_type": source_type,
                "source_file": str(path),
                "source_row": index + 1,
                "date": pd.Timestamp(date),
                "amount": amount,
                "abs_amount": abs(amount),
                "direction": infer_direction(amount, description),
                "description": description,
                "counterparty": description,
                "transaction_type": tag("TRNTYPE"),
                "account": "",
                "external_id": tag("FITID"),
                "normalized_description": normalize_text(description),
                "normalized_counterparty": normalize_text(description),
                "raw_data": block.strip(),
            }
        )
    return ensure_canonical(pd.DataFrame(records))


def load_ofx(path: str | Path, source_type: str) -> pd.DataFrame:
    path = Path(path)
    parsed = _load_with_ofxparse(path, source_type)
    if parsed is not None:
        return parsed
    return _load_with_regex(path, source_type)
