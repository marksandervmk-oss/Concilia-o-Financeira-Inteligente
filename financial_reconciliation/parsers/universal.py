from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from financial_reconciliation.models import empty_transactions, ensure_canonical
from financial_reconciliation.parsers.csv_parser import load_csv
from financial_reconciliation.parsers.excel_parser import load_excel
from financial_reconciliation.parsers.ofx_parser import load_ofx
from financial_reconciliation.parsers.pdf_ledger_parser import load_pdf_ledger
from financial_reconciliation.parsers.txt_parser import load_txt


def load_transactions(path: str | Path, source_type: str) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return load_csv(path, source_type)
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return load_excel(path, source_type)
    if suffix == ".pdf":
        return load_pdf_ledger(path, source_type)
    if suffix == ".ofx":
        return load_ofx(path, source_type)
    if suffix in {".txt", ".ret", ".cnab"}:
        return load_txt(path, source_type)
    return empty_transactions()


def load_many(paths: Iterable[str | Path], source_type: str) -> pd.DataFrame:
    frames = [load_transactions(path, source_type) for path in paths]
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return empty_transactions()
    return ensure_canonical(pd.concat(frames, ignore_index=True))
