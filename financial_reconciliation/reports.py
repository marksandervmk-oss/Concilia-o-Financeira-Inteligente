from __future__ import annotations

from pathlib import Path

import pandas as pd

from financial_reconciliation.matching import ReconciliationResult


def summary_frame(summary: dict[str, object]) -> pd.DataFrame:
    labels = {
        "quantidade_extrato": "Quantidade no extrato",
        "quantidade_razao": "Quantidade no razao",
        "quantidade_conciliada": "Quantidade conciliada",
        "quantidade_pendente": "Quantidade pendente",
        "total_conciliado": "Total conciliado",
        "total_pendente": "Total pendente",
        "percentual_conciliacao": "Percentual de conciliacao",
    }
    return pd.DataFrame(
        [{"Indicador": labels.get(key, key), "Valor": value} for key, value in summary.items()]
    )


def export_excel(result: ReconciliationResult, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_frame(result.summary).to_excel(writer, sheet_name="Resumo", index=False)
        result.bank_pending.to_excel(writer, sheet_name="Pendencias extrato", index=False)
        result.ledger_pending.to_excel(writer, sheet_name="Pendencias razao", index=False)
        result.matches.to_excel(writer, sheet_name="Matches", index=False)
        result.duplicates.to_excel(writer, sheet_name="Duplicidades", index=False)
        result.bank_transactions.to_excel(writer, sheet_name="Base extrato", index=False)
        result.ledger_transactions.to_excel(writer, sheet_name="Base razao", index=False)

        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                max_len = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
                sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 12), 60)
            for cell in sheet[1]:
                cell.style = "Headline 4"
    return output_path
