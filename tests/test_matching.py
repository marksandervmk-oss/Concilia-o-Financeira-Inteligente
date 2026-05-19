import unittest

import pandas as pd

from financial_reconciliation.config import ReconciliationConfig
from financial_reconciliation.matching import reconcile
from financial_reconciliation.models import ensure_canonical, make_transaction_id
from financial_reconciliation.normalization import normalize_text


def txn(source_type, date, amount, description):
    return {
        "transaction_id": make_transaction_id(source_type, date, amount, description),
        "source_type": source_type,
        "source_file": "memory",
        "source_row": 1,
        "date": pd.Timestamp(date),
        "amount": amount,
        "abs_amount": abs(amount),
        "direction": "inflow" if amount > 0 else "outflow",
        "description": description,
        "counterparty": description,
        "transaction_type": "PIX",
        "account": "",
        "external_id": "",
        "normalized_description": normalize_text(description),
        "normalized_counterparty": normalize_text(description),
        "raw_data": description,
    }


class MatchingTests(unittest.TestCase):
    def test_fuzzy_match_with_date_tolerance(self):
        bank = ensure_canonical(
            pd.DataFrame([txn("bank", "2026-05-05", 1250.00, "PIX MERCADO BH")])
        )
        ledger = ensure_canonical(
            pd.DataFrame([txn("ledger", "2026-05-06", 1250.00, "SUPERMERCADO BH LTDA")])
        )
        result = reconcile(bank, ledger, ReconciliationConfig(date_tolerance_days=2))
        self.assertEqual(result.summary["quantidade_conciliada"], 1)
        self.assertEqual(result.matches.iloc[0]["nivel_confianca"], "Alta confianca")

    def test_pending_when_not_found(self):
        bank = ensure_canonical(pd.DataFrame([txn("bank", "2026-05-05", 99.00, "NETFLIX")]))
        ledger = ensure_canonical(pd.DataFrame([txn("ledger", "2026-05-05", 120.00, "ALUGUEL")]))
        result = reconcile(bank, ledger, ReconciliationConfig())
        self.assertEqual(result.bank_pending.iloc[0]["Status"], "Nao encontrado no razao")


if __name__ == "__main__":
    unittest.main()
