from __future__ import annotations

from pathlib import Path

import pandas as pd

from financial_reconciliation.models import empty_transactions
from financial_reconciliation.parsers.common import canonicalize_dataframe, detect_encoding, detect_separator


def read_delimited(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    encoding = detect_encoding(path)
    sample = path.read_text(encoding=encoding, errors="replace")[:4096]
    separator = detect_separator(sample)
    kwargs = {"encoding": encoding, "dtype": str, "keep_default_na": False}
    if separator:
        return pd.read_csv(path, sep=separator, **kwargs)
    return pd.read_csv(path, sep=None, engine="python", **kwargs)


def load_csv(path: str | Path, source_type: str) -> pd.DataFrame:
    try:
        df = read_delimited(path)
    except Exception:
        return empty_transactions()
    return canonicalize_dataframe(df, source_type=source_type, source_file=str(Path(path)))
