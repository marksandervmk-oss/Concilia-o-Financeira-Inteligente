from __future__ import annotations

from pathlib import Path

import pandas as pd

from financial_reconciliation.models import empty_transactions, ensure_canonical
from financial_reconciliation.parsers.common import canonicalize_dataframe


def load_excel(path: str | Path, source_type: str) -> pd.DataFrame:
    path = Path(path)
    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    except Exception:
        return empty_transactions()

    frames = [
        canonicalize_dataframe(
            df,
            source_type=source_type,
            source_file=str(path),
            sheet_name=sheet_name,
        )
        for sheet_name, df in sheets.items()
    ]
    if not frames:
        return empty_transactions()
    return ensure_canonical(pd.concat(frames, ignore_index=True))
