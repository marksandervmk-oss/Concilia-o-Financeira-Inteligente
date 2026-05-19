from __future__ import annotations

import tempfile
from datetime import datetime
import hashlib
from pathlib import Path

import streamlit as st

from financial_reconciliation.config import ReconciliationConfig
from financial_reconciliation.matching import reconcile
from financial_reconciliation.parsers import load_many
from financial_reconciliation.reports import export_excel


st.set_page_config(page_title="Conciliacao Financeira Inteligente", layout="wide")


def _save_uploads(files: list, prefix: str) -> list[Path]:
    temp_dir = Path(tempfile.gettempdir()) / "financial_reconciliation_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for file in files or []:
        data = file.getbuffer()
        digest = hashlib.sha1(bytes(data)).hexdigest()[:20]
        suffix = Path(file.name).suffix.lower()
        path = temp_dir / f"{prefix}_{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        paths.append(path)
    return paths


def _sample_paths() -> tuple[list[Path], list[Path]]:
    downloads = Path.home() / "Downloads"
    bank_files: list[Path] = []
    main = next(iter(sorted(downloads.glob("AS S* 01 a 04.25.csv"))), None)
    odonto_candidates = sorted(downloads.glob("AS S*Odonto*.csv"))
    odonto = next((path for path in odonto_candidates if "(1)" in path.name), None)
    odonto = odonto or (odonto_candidates[0] if odonto_candidates else None)
    for path in (main, odonto):
        if path and path not in bank_files:
            bank_files.append(path)
    ledger_files = sorted(downloads.glob("Raz*trimestre 2025.pdf"))
    return bank_files, ledger_files


def _format_money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


st.title("Conciliacao Financeira Inteligente")

with st.sidebar:
    st.header("Arquivos")
    bank_uploads = st.file_uploader(
        "Extrato bancario",
        type=["csv", "xlsx", "xls", "pdf", "ofx", "txt"],
        accept_multiple_files=True,
    )
    ledger_uploads = st.file_uploader(
        "Razao contabil / financeiro",
        type=["csv", "xlsx", "xls", "pdf", "ofx", "txt"],
        accept_multiple_files=True,
    )
    sample_bank_paths, sample_ledger_paths = _sample_paths()
    use_samples = False
    if sample_bank_paths and sample_ledger_paths:
        use_samples = st.checkbox("Usar arquivos de exemplo da pasta Downloads", value=False)

    run = st.button("Executar conciliacao", type="primary", use_container_width=True)


if run:
    config = ReconciliationConfig(
        date_tolerance_days=0,
        value_tolerance=0.0,
        partial_date_window_days=0,
        partial_value_window=0.0,
        partial_value_percent=0.0,
    ).normalized()
    if use_samples:
        bank_paths, ledger_paths = sample_bank_paths, sample_ledger_paths
    else:
        bank_paths = _save_uploads(bank_uploads, "bank_")
        ledger_paths = _save_uploads(ledger_uploads, "ledger_")

    if not bank_paths or not ledger_paths:
        st.error("Envie pelo menos um extrato e um razao.")
        st.stop()

    with st.status("Processando arquivos...", expanded=True) as status:
        st.write("Lendo extrato bancario...")
        bank = load_many(bank_paths, "bank")
        st.write(f"Extrato carregado: {len(bank):,} lancamentos.".replace(",", "."))

        st.write("Lendo razao contabil/financeiro...")
        ledger = load_many(ledger_paths, "ledger")
        st.write(f"Razao carregado: {len(ledger):,} lancamentos.".replace(",", "."))

        st.write("Executando conciliacao...")
        result = reconcile(bank, ledger, config=config)
        st.write("Gerando relatorio Excel...")
        status.update(label="Conciliacao concluida.", state="complete", expanded=False)

    metrics = result.summary
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Conciliados", metrics["quantidade_conciliada"])
    col2.metric("Pendentes", metrics["quantidade_pendente"])
    col3.metric("Total conciliado", _format_money(metrics["total_conciliado"]))
    col4.metric("Total pendente", _format_money(metrics["total_pendente"]))
    col5.metric("Percentual", f"{metrics['percentual_conciliacao']:.1%}")

    tab_pending, tab_ledger, tab_matches, tab_duplicates, tab_base = st.tabs(
        ["Pendencias extrato", "Pendencias razao", "Matches", "Duplicidades", "Bases"]
    )
    with tab_pending:
        st.dataframe(result.bank_pending, use_container_width=True, height=460)
    with tab_ledger:
        st.dataframe(result.ledger_pending, use_container_width=True, height=460)
    with tab_matches:
        st.dataframe(result.matches, use_container_width=True, height=460)
    with tab_duplicates:
        st.dataframe(result.duplicates, use_container_width=True, height=460)
    with tab_base:
        left, right = st.columns(2)
        left.subheader("Extrato")
        left.dataframe(result.bank_transactions, use_container_width=True, height=420)
        right.subheader("Razao")
        right.dataframe(result.ledger_transactions, use_container_width=True, height=420)

    output_dir = Path("outputs")
    output_path = output_dir / f"relatorio_conciliacao_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    export_excel(result, output_path)
    st.download_button(
        "Baixar relatorio Excel",
        data=output_path.read_bytes(),
        file_name=output_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.info("Configure os arquivos e execute a conciliacao.")
