from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from financial_reconciliation.models import ensure_canonical, make_transaction_id, row_to_json
from financial_reconciliation.normalization import normalize_column_name, normalize_text, searchable_text

DATE_HINTS = ("data", "date", "dt", "emissao", "lancamento", "movimento")
AMOUNT_HINTS = ("valor", "amount", "vlr", "total")
DEBIT_HINTS = ("debito", "debit", "saida", "pagamento")
CREDIT_HINTS = ("credito", "credit", "entrada", "recebimento")
DESCRIPTION_HINTS = (
    "descricao",
    "historico",
    "history",
    "memo",
    "nome",
    "name",
    "fornecedor",
    "cliente",
    "favorecido",
    "beneficiario",
    "observacao",
)
TYPE_HINTS = ("tipo", "type", "categoria", "natureza", "operacao")
ID_HINTS = ("id", "identificador", "documento", "numero", "sequencia", "transacao")
ACCOUNT_HINTS = ("conta", "account", "banco")


def detect_encoding(path: str | Path) -> str:
    candidates = ("utf-8-sig", "utf-8", "cp1252", "latin1")
    raw = Path(path).read_bytes()
    for encoding in candidates:
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin1"


def detect_separator(sample: str) -> str | None:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
        return dialect.delimiter
    except csv.Error:
        counts = {sep: sample.count(sep) for sep in (";", ",", "\t", "|")}
        sep, count = max(counts.items(), key=lambda item: item[1])
        return sep if count else None


def parse_money(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
    if "-" in text:
        negative = True
    text = text.upper().replace("R$", "").replace("BRL", "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[^0-9,.\-DC]", "", text)
    text = text.rstrip("DC")
    text = text.replace("-", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def parse_date(value: object) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" as ", " ")
    text = text.replace(" \u00e0s ", " ")
    text = text.replace(" \u00e0s ", " ")
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def first_column(columns: Iterable[str], hints: Iterable[str]) -> str | None:
    normalized_hints = tuple(normalize_column_name(hint) for hint in hints)
    for column in columns:
        name = normalize_column_name(column)
        if any(hint in name for hint in normalized_hints):
            return column
    return None


def all_columns(columns: Iterable[str], hints: Iterable[str]) -> list[str]:
    normalized_hints = tuple(normalize_column_name(hint) for hint in hints)
    return [
        column
        for column in columns
        if any(hint in normalize_column_name(column) for hint in normalized_hints)
    ]


def infer_direction(amount: float | None, text: object = "") -> str:
    if amount is not None and amount < 0:
        return "outflow"
    if amount is not None and amount > 0:
        return "inflow"
    normalized = searchable_text(text)
    compact = normalized.replace(" ", "")
    if any(word in normalized or word in compact for word in ("PAGAMENTO", "ENVIADA", "TARIFA", "DEBITO", "SAIDA")):
        return "outflow"
    if any(word in normalized or word in compact for word in ("RECEBIDA", "CREDITO", "ENTRADA", "RECEBIMENTO")):
        return "inflow"
    return "unknown"


def canonicalize_dataframe(
    df: pd.DataFrame,
    *,
    source_type: str,
    source_file: str,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return ensure_canonical(pd.DataFrame())

    frame = df.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    columns = list(frame.columns)

    date_col = first_column(columns, DATE_HINTS)
    amount_col = first_column(columns, AMOUNT_HINTS)
    debit_col = first_column(columns, DEBIT_HINTS)
    credit_col = first_column(columns, CREDIT_HINTS)
    type_col = first_column(columns, TYPE_HINTS)
    id_col = first_column(columns, ID_HINTS)
    account_col = first_column(columns, ACCOUNT_HINTS)

    description_columns = all_columns(columns, DESCRIPTION_HINTS)
    if not description_columns and type_col:
        description_columns = [type_col]
    if not description_columns:
        description_columns = [column for column in columns if column not in {date_col, amount_col}]

    records: list[dict[str, object]] = []
    for index, row in frame.iterrows():
        row_dict = row.to_dict()
        date = parse_date(row_dict.get(date_col)) if date_col else None
        if amount_col:
            amount = parse_money(row_dict.get(amount_col))
        else:
            debit = parse_money(row_dict.get(debit_col)) if debit_col else None
            credit = parse_money(row_dict.get(credit_col)) if credit_col else None
            amount = None
            if debit is not None and debit != 0:
                amount = -abs(debit)
            if credit is not None and credit != 0:
                amount = abs(credit)
        if date is None or amount is None:
            continue

        description_parts = [row_dict.get(column) for column in description_columns]
        transaction_type = row_dict.get(type_col) if type_col else ""
        if transaction_type and transaction_type not in description_parts:
            description_parts.insert(0, transaction_type)
        description = " ".join(str(part) for part in description_parts if part is not None and str(part) != "nan")
        counterparty = " ".join(
            str(row_dict.get(column))
            for column in description_columns
            if row_dict.get(column) is not None and str(row_dict.get(column)) != "nan"
        )
        account = str(row_dict.get(account_col, "") or "")
        external_id = str(row_dict.get(id_col, "") or "")
        direction = infer_direction(amount, f"{transaction_type} {description}")
        record = {
            "transaction_id": make_transaction_id(source_file, source_type, sheet_name, index, date, amount, description),
            "source_type": source_type,
            "source_file": source_file,
            "source_row": int(index) + 1,
            "date": date,
            "amount": amount,
            "abs_amount": abs(amount),
            "direction": direction,
            "description": description.strip(),
            "counterparty": counterparty.strip(),
            "transaction_type": str(transaction_type or "").strip(),
            "account": account.strip(),
            "external_id": external_id.strip(),
            "normalized_description": normalize_text(description),
            "normalized_counterparty": normalize_text(counterparty),
            "raw_data": row_to_json(row_dict),
        }
        records.append(record)

    return ensure_canonical(pd.DataFrame(records))
