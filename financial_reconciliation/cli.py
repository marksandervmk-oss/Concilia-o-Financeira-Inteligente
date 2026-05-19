from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from financial_reconciliation.config import ReconciliationConfig
from financial_reconciliation.database import ReconciliationStore
from financial_reconciliation.matching import reconcile
from financial_reconciliation.parsers import load_many
from financial_reconciliation.reports import export_excel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Intelligent financial reconciliation")
    parser.add_argument("--bank", nargs="+", required=True, help="Bank statement files")
    parser.add_argument("--ledger", nargs="+", required=True, help="Ledger/reason files")
    parser.add_argument("--output", default="outputs/reconciliation_report.xlsx", help="Excel report path")
    parser.add_argument("--db", default="data/reconciliation.db", help="SQLite database path")
    parser.add_argument("--name", default=None, help="Analysis name")
    parser.add_argument("--date-tolerance", type=int, default=0, help="Date tolerance in days")
    parser.add_argument("--value-tolerance", type=float, default=0.0, help="Value tolerance in currency units")
    parser.add_argument("--save", action="store_true", help="Save analysis and learn aliases in SQLite")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = ReconciliationConfig(
        date_tolerance_days=args.date_tolerance,
        value_tolerance=args.value_tolerance,
    ).normalized()
    store = ReconciliationStore(args.db)
    bank = load_many(args.bank, "bank")
    ledger = load_many(args.ledger, "ledger")
    result = reconcile(bank, ledger, config=config, alias_memory=store.load_alias_memory())
    output = export_excel(result, args.output)

    analysis_id = None
    if args.save:
        analysis_id = store.save_analysis(
            name=args.name or f"Analise {datetime.now():%Y-%m-%d %H:%M}",
            config=config,
            summary=result.summary,
            bank=result.bank_transactions,
            ledger=result.ledger_transactions,
            matches=result.matches,
        )
        store.learn_from_matches(result.bank_transactions, result.ledger_transactions, result.matches, config.learn_min_score)

    print("Reconciliation finished")
    print(f"Bank transactions: {result.summary['quantidade_extrato']}")
    print(f"Ledger transactions: {result.summary['quantidade_razao']}")
    print(f"Reconciled: {result.summary['quantidade_conciliada']}")
    print(f"Pending: {result.summary['quantidade_pendente']}")
    print(f"Report: {Path(output).resolve()}")
    if analysis_id:
        print(f"Saved analysis id: {analysis_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
