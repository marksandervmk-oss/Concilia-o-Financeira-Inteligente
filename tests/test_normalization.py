import unittest

from financial_reconciliation.normalization import normalize_text
from financial_reconciliation.parsers.common import parse_money


class NormalizationTests(unittest.TestCase):
    def test_removes_accents_and_noise(self):
        self.assertEqual(normalize_text("PAGAMENTO PIX JOAO LTDA"), "JOAO")
        self.assertEqual(normalize_text("Supermercado BH S/A"), "SUPERMERCADO BH")

    def test_parse_brazilian_money(self):
        self.assertEqual(parse_money("R$ 1.250,30"), 1250.30)
        self.assertEqual(parse_money("R$ -89,90"), -89.90)


if __name__ == "__main__":
    unittest.main()
