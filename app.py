from __future__ import annotations

import tempfile
from datetime import datetime
import hashlib
import html
from pathlib import Path

import pandas as pd
import streamlit as st

from financial_reconciliation.config import ReconciliationConfig
from financial_reconciliation.matching import reconcile
from financial_reconciliation.parsers import load_many
from financial_reconciliation.reports import export_excel


st.set_page_config(page_title="Conciliação Financeira Inteligente", layout="wide")

st.markdown(
    """
    <style>
    :root {
        --surface: #ffffff;
        --surface-soft: #f8fafc;
        --border: #dbe3ef;
        --ink: #172033;
        --muted: #667085;
        --blue: #1d4ed8;
        --green: #047857;
        --red: #dc2626;
        --amber: #b45309;
    }
    .stApp {
        background: #f4f7fb;
    }
    .block-container {
        max-width: 1480px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
        border-right: 1px solid #273244;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p {
        color: #f9fafb !important;
    }
    section[data-testid="stSidebar"] small {
        color: #cbd5e1 !important;
    }
    div[data-testid="stFileUploader"] section {
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(255, 255, 255, 0.22);
        border-radius: 8px;
    }
    div[data-testid="stFileUploader"] small,
    div[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] {
        color: #e5e7eb !important;
    }
    div[data-testid="stFileUploader"] button {
        border-radius: 8px;
    }
    .stButton > button,
    div[data-testid="stDownloadButton"] > button {
        width: 100%;
        border-radius: 8px;
        border: 0;
        background: #2563eb;
        color: #ffffff;
        font-weight: 700;
        min-height: 44px;
    }
    .stButton > button:hover,
    div[data-testid="stDownloadButton"] > button:hover {
        background: #1d4ed8;
        color: #ffffff;
    }
    .hero {
        background: linear-gradient(135deg, #ffffff 0%, #eef6ff 100%);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 26px 28px;
        margin-bottom: 18px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }
    .hero-kicker {
        color: #1d4ed8;
        font-size: 12px;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .hero-title {
        color: var(--ink);
        font-size: 36px;
        line-height: 1.15;
        font-weight: 800;
        margin: 0;
    }
    .hero-subtitle {
        color: #475467;
        font-size: 15px;
        margin-top: 8px;
    }
    .metric-card {
        background: #ffffff;
        border: 1px solid var(--border);
        border-top: 4px solid var(--accent);
        border-radius: 8px;
        padding: 14px 16px;
        min-height: 102px;
        box-shadow: 0 4px 14px rgba(16, 24, 40, 0.06);
    }
    .metric-label {
        color: var(--muted);
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .04em;
        margin-bottom: 8px;
    }
    .metric-value {
        color: var(--ink);
        font-size: 24px;
        line-height: 1.2;
        font-weight: 800;
    }
    .metric-help {
        color: #475467;
        font-size: 12px;
        margin-top: 6px;
    }
    .section-title {
        color: var(--ink);
        font-size: 18px;
        font-weight: 800;
        margin: 18px 0 8px;
    }
    .export-panel {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
        border-radius: 8px;
        padding: 16px;
        margin-top: 18px;
        color: #ffffff;
    }
    .export-panel strong {
        display: block;
        font-size: 16px;
        margin-bottom: 4px;
    }
    .export-panel span {
        color: #cbd5e1;
        font-size: 13px;
    }
    div[data-testid="stTabs"] button {
        font-weight: 700;
    }
    div[data-testid="stTabs"] [role="tablist"] {
        gap: 6px;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--border);
        border-radius: 8px;
        overflow: hidden;
    }
    .note-card {
        background: #ffffff;
        border: 1px solid var(--border);
        border-left: 4px solid #1d4ed8;
        border-radius: 8px;
        padding: 14px 16px;
        color: #475467;
        margin-top: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def _format_money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_count(value: float | int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _page_header() -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">Auditoria financeira</div>
            <h1 class="hero-title">Conciliação Financeira Inteligente</h1>
            <div class="hero-subtitle">Extrato bancário x razão contábil com revisão por entradas, saídas e pendências.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: str, help_text: str = "", color: str = "#2563eb") -> None:
    st.markdown(
        f"""
        <div class="metric-card" style="--accent: {html.escape(color)};">
            <div class="metric-label">{html.escape(label)}</div>
            <div class="metric-value">{html.escape(value)}</div>
            <div class="metric-help">{html.escape(help_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_summary_cards(metrics: dict[str, float]) -> None:
    columns = st.columns(5)
    with columns[0]:
        _metric_card("Conciliados", _format_count(metrics["quantidade_conciliada"]), "correspondências exatas", "#047857")
    with columns[1]:
        _metric_card("Pendentes", _format_count(metrics["quantidade_pendente"]), "revisar lançamentos", "#dc2626")
    with columns[2]:
        _metric_card("Total conciliado", _format_money(metrics["total_conciliado"]), "valor absoluto", "#2563eb")
    with columns[3]:
        _metric_card("Total pendente", _format_money(metrics["total_pendente"]), "valor absoluto", "#d97706")
    with columns[4]:
        _metric_card("Percentual", f"{metrics['percentual_conciliacao']:.1%}", "consolidado", "#4f46e5")


def _filter_amount(df: pd.DataFrame, column: str, kind: str) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df
    values = pd.to_numeric(df[column], errors="coerce").fillna(0)
    if kind == "entrada":
        return df[values > 0]
    return df[values < 0]


def _direction_metrics(result, kind: str) -> dict[str, float]:
    bank = _filter_amount(result.bank_transactions, "amount", kind)
    matches = _filter_amount(result.matches, "valor_extrato", kind)
    pending = _filter_amount(result.bank_pending, "Valor", kind)
    reconciled = matches[matches["status"] == "Conciliado"] if not matches.empty else matches
    total_bank = float(bank["amount"].abs().sum()) if not bank.empty else 0.0
    total_reconciled = float(reconciled["valor_extrato"].abs().sum()) if not reconciled.empty else 0.0
    total_pending = float(pending["Valor"].abs().sum()) if not pending.empty else 0.0
    return {
        "quantidade_extrato": len(bank),
        "quantidade_conciliada": len(reconciled),
        "quantidade_pendente": len(pending),
        "total_extrato": total_bank,
        "total_conciliado": total_reconciled,
        "total_pendente": total_pending,
        "percentual_conciliacao": (len(reconciled) / len(bank)) if len(bank) else 0.0,
    }


def _render_metric_row(metrics: dict[str, float]) -> None:
    columns = st.columns(5)
    with columns[0]:
        _metric_card("Extrato", _format_count(metrics["quantidade_extrato"]), "lançamentos", "#1d4ed8")
    with columns[1]:
        _metric_card("Conciliados", _format_count(metrics["quantidade_conciliada"]), "status conciliado", "#047857")
    with columns[2]:
        _metric_card("Pendentes", _format_count(metrics["quantidade_pendente"]), "em aberto", "#dc2626")
    with columns[3]:
        _metric_card("Total pendente", _format_money(metrics["total_pendente"]), "valor absoluto", "#d97706")
    with columns[4]:
        _metric_card("Percentual", f"{metrics['percentual_conciliacao']:.1%}", "por quantidade", "#4f46e5")


def _row_style(row: pd.Series) -> list[str]:
    status = str(row.get("Status", row.get("status", ""))).lower()
    if "conciliado" in status:
        color = "background-color: #ecfdf3"
    elif "nao encontrado" in status or "não encontrado" in status or "baixa" in status:
        color = "background-color: #fef2f2"
    elif "divergencia" in status or "parcial" in status:
        color = "background-color: #fff7ed"
    elif "duplicidade" in status:
        color = "background-color: #eef2ff"
    else:
        color = ""
    return [color for _ in row]


def _render_table(df: pd.DataFrame, height: int = 360) -> None:
    if df.empty:
        st.info("Sem registros para exibir.")
        return
    if len(df) > 5000:
        st.dataframe(df, use_container_width=True, height=height)
        return
    styled = df.style.apply(_row_style, axis=1)
    st.dataframe(styled, use_container_width=True, height=height)


def _render_direction_tab(result, kind: str) -> None:
    _render_metric_row(_direction_metrics(result, kind))
    pending = _filter_amount(result.bank_pending, "Valor", kind)
    matches = _filter_amount(result.matches, "valor_extrato", kind)
    ledger_pending = _filter_amount(result.ledger_pending, "Valor", kind)

    st.markdown('<div class="section-title">Pendências no extrato</div>', unsafe_allow_html=True)
    _render_table(pending, height=320)
    st.markdown('<div class="section-title">Correspondências</div>', unsafe_allow_html=True)
    _render_table(matches, height=320)
    st.markdown('<div class="section-title">Pendências no razão</div>', unsafe_allow_html=True)
    _render_table(ledger_pending, height=260)


_page_header()

with st.sidebar:
    st.header("Arquivos")
    st.caption("Envie o extrato bancário e o razão contábil para executar a conciliação.")
    bank_uploads = st.file_uploader(
        "Extrato bancário",
        type=["csv", "xlsx", "xls", "pdf", "ofx", "txt"],
        accept_multiple_files=True,
    )
    ledger_uploads = st.file_uploader(
        "Razão contábil / financeiro",
        type=["csv", "xlsx", "xls", "pdf", "ofx", "txt"],
        accept_multiple_files=True,
    )

    run = st.button("Executar conciliação", type="primary", use_container_width=True)


if run:
    config = ReconciliationConfig(
        date_tolerance_days=0,
        value_tolerance=0.0,
        partial_date_window_days=0,
        partial_value_window=0.0,
        partial_value_percent=0.0,
    ).normalized()
    bank_paths = _save_uploads(bank_uploads, "bank_")
    ledger_paths = _save_uploads(ledger_uploads, "ledger_")

    if not bank_paths or not ledger_paths:
        st.error("Envie pelo menos um extrato e um razão.")
        st.stop()

    with st.status("Processando arquivos...", expanded=True) as status:
        st.write("Lendo extrato bancário...")
        bank = load_many(bank_paths, "bank")
        st.write(f"Extrato carregado: {len(bank):,} lançamentos.".replace(",", "."))

        st.write("Lendo razão contábil/financeiro...")
        ledger = load_many(ledger_paths, "ledger")
        st.write(f"Razão carregado: {len(ledger):,} lançamentos.".replace(",", "."))

        st.write("Executando conciliação...")
        result = reconcile(bank, ledger, config=config)
        st.write("Gerando relatório Excel...")
        status.update(label="Conciliação concluída.", state="complete", expanded=False)

    metrics = result.summary
    _render_summary_cards(metrics)

    tab_entries, tab_exits, tab_pending, tab_ledger, tab_matches, tab_duplicates, tab_base = st.tabs(
        [
            "Entradas",
            "Saídas",
            "Pendências extrato",
            "Pendências razão",
            "Matches",
            "Duplicidades",
            "Bases",
        ]
    )
    with tab_entries:
        _render_direction_tab(result, "entrada")
    with tab_exits:
        _render_direction_tab(result, "saida")
    with tab_pending:
        _render_table(result.bank_pending, height=460)
    with tab_ledger:
        _render_table(result.ledger_pending, height=460)
    with tab_matches:
        _render_table(result.matches, height=460)
    with tab_duplicates:
        _render_table(result.duplicates, height=460)
    with tab_base:
        left, right = st.columns(2)
        with left:
            st.markdown('<div class="section-title">Extrato</div>', unsafe_allow_html=True)
            _render_table(result.bank_transactions, height=420)
        with right:
            st.markdown('<div class="section-title">Razão</div>', unsafe_allow_html=True)
            _render_table(result.ledger_transactions, height=420)

    output_dir = Path("outputs")
    output_path = output_dir / f"relatorio_conciliacao_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    export_excel(result, output_path)
    st.markdown(
        """
        <div class="export-panel">
            <strong>Relatório pronto para Excel</strong>
            <span>Baixe o arquivo XLSX com resumo, entradas, saídas, pendências, correspondências e bases normalizadas.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.download_button(
        "Exportar XLSX",
        data=output_path.read_bytes(),
        file_name=output_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.markdown(
        """
        <div class="note-card">
            Configure os arquivos no painel lateral e execute a conciliação para visualizar os indicadores.
        </div>
        """,
        unsafe_allow_html=True,
    )
