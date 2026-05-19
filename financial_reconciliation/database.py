from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from financial_reconciliation.config import ReconciliationConfig


class ReconciliationStore:
    def __init__(self, db_path: str | Path = "data/reconciliation.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    name TEXT,
                    config_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
                );

                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER NOT NULL,
                    bank_transaction_id TEXT,
                    ledger_transaction_id TEXT,
                    status TEXT,
                    confidence_score REAL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
                );

                CREATE TABLE IF NOT EXISTS alias_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bank_normalized TEXT NOT NULL,
                    ledger_normalized TEXT NOT NULL,
                    label TEXT,
                    confidence_score REAL NOT NULL,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE (bank_normalized, ledger_normalized)
                );
                """
            )

    def load_alias_memory(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT bank_normalized, ledger_normalized FROM alias_memory"
            ).fetchall()
        return {bank: ledger for bank, ledger in rows}

    def upsert_alias(self, bank_normalized: str, ledger_normalized: str, label: str, score: float) -> None:
        if not bank_normalized or not ledger_normalized:
            return
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alias_memory
                    (bank_normalized, ledger_normalized, label, confidence_score, occurrences, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(bank_normalized, ledger_normalized)
                DO UPDATE SET
                    confidence_score = max(alias_memory.confidence_score, excluded.confidence_score),
                    occurrences = alias_memory.occurrences + 1,
                    label = excluded.label,
                    updated_at = excluded.updated_at
                """,
                (bank_normalized, ledger_normalized, label, score, now),
            )

    def learn_from_matches(self, bank: pd.DataFrame, ledger: pd.DataFrame, matches: pd.DataFrame, min_score: float) -> None:
        if matches.empty:
            return
        for row in matches.itertuples():
            if float(row.score) < min_score:
                continue
            bank_row = bank.loc[int(row.bank_index)]
            ledger_row = ledger.loc[int(row.ledger_index)]
            self.upsert_alias(
                str(bank_row.get("normalized_counterparty") or bank_row.get("normalized_description") or ""),
                str(ledger_row.get("normalized_counterparty") or ledger_row.get("normalized_description") or ""),
                str(ledger_row.get("counterparty") or ledger_row.get("description") or ""),
                float(row.score),
            )

    def save_analysis(
        self,
        *,
        name: str,
        config: ReconciliationConfig,
        summary: dict[str, Any],
        bank: pd.DataFrame,
        ledger: pd.DataFrame,
        matches: pd.DataFrame,
    ) -> int:
        now = datetime.utcnow().isoformat(timespec="seconds")
        config_json = json.dumps(asdict(config), ensure_ascii=False)
        summary_json = json.dumps(summary, ensure_ascii=False)
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO analyses (created_at, name, config_json, summary_json) VALUES (?, ?, ?, ?)",
                (now, name, config_json, summary_json),
            )
            analysis_id = int(cursor.lastrowid)
            for frame in (bank, ledger):
                for record in frame.to_dict("records"):
                    conn.execute(
                        """
                        INSERT INTO transactions
                            (analysis_id, source_type, transaction_id, data_json)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            analysis_id,
                            record.get("source_type", ""),
                            record.get("transaction_id", ""),
                            json.dumps(record, ensure_ascii=False, default=str),
                        ),
                    )
            for record in matches.to_dict("records"):
                conn.execute(
                    """
                    INSERT INTO matches
                        (analysis_id, bank_transaction_id, ledger_transaction_id, status, confidence_score, data_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        record.get("bank_transaction_id", ""),
                        record.get("ledger_transaction_id", ""),
                        record.get("status", ""),
                        float(record.get("score", 0) or 0),
                        json.dumps(record, ensure_ascii=False, default=str),
                    ),
                )
        return analysis_id
