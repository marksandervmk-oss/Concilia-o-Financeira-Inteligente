from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from financial_reconciliation.config import ReconciliationConfig
from financial_reconciliation.fuzzy import confidence_level, text_similarity
from financial_reconciliation.models import ensure_canonical


@dataclass(slots=True)
class ReconciliationResult:
    bank_transactions: pd.DataFrame
    ledger_transactions: pd.DataFrame
    matches: pd.DataFrame
    bank_pending: pd.DataFrame
    ledger_pending: pd.DataFrame
    duplicates: pd.DataFrame
    summary: dict[str, Any]


def _date_diff_days(left: pd.Timestamp, right: pd.Timestamp) -> int:
    return abs((pd.Timestamp(left).normalize() - pd.Timestamp(right).normalize()).days)


def _value_score(diff: float, amount: float, config: ReconciliationConfig) -> float:
    if diff <= config.value_tolerance:
        return 1.0
    review_window = max(config.value_review_window(amount), config.value_tolerance)
    return max(0.0, 1.0 - ((diff - config.value_tolerance) / review_window))


def _date_score(diff_days: int, config: ReconciliationConfig) -> float:
    if diff_days <= config.date_tolerance_days:
        return 1.0 - (diff_days / max(config.date_tolerance_days + 1, 1)) * 0.20
    overflow = diff_days - config.date_tolerance_days
    window = max(config.partial_date_window_days - config.date_tolerance_days, 1)
    return max(0.0, 0.80 - (overflow / window) * 0.80)


def _type_score(bank_direction: str, ledger_direction: str) -> float:
    if not bank_direction or not ledger_direction or "unknown" in {bank_direction, ledger_direction}:
        return 0.70
    return 1.0 if bank_direction == ledger_direction else 0.15


def _candidate_status(
    score: float,
    date_diff: int,
    value_diff: float,
    text_score: float,
    config: ReconciliationConfig,
    has_duplicate_risk: bool,
) -> tuple[str, str]:
    value_close = value_diff <= config.value_tolerance
    date_close = date_diff <= config.date_tolerance_days
    if score >= config.high_confidence_threshold and value_close and date_close and text_score >= 0.90:
        return "Conciliado", "Valor e data batem exatamente; historico compativel."
    if has_duplicate_risk:
        return "Possivel duplicidade", "Ha mais de um candidato muito proximo para o mesmo lancamento."
    if score >= config.high_confidence_threshold and value_close and date_close:
        return "Conciliado", "Valor e data batem exatamente; historico compativel."
    if not value_close and date_close and text_score >= 0.50:
        return "Divergencia de valor", "Historico e data sugerem equivalencia, mas o valor nao bate exatamente."
    if value_close and not date_close and text_score >= 0.45:
        return "Divergencia de data", "Valor e historico sugerem equivalencia, mas a data nao bate exatamente."
    if score >= config.medium_confidence_threshold:
        return "Correspondencia parcial", "Match provavel, mas algum criterio ficou abaixo do ideal."
    return "Baixa confianca", "Candidato fraco; revisar manualmente antes de aceitar."


def _build_candidates(
    bank: pd.DataFrame,
    ledger: pd.DataFrame,
    config: ReconciliationConfig,
    alias_memory: dict[str, str] | None = None,
) -> pd.DataFrame:
    alias_memory = alias_memory or {}
    candidates: list[dict[str, Any]] = []
    if bank.empty or ledger.empty:
        return pd.DataFrame()

    ledger = ledger.copy()
    ledger["_date_only"] = ledger["date"].dt.normalize()
    ledger_by_date = {date: group for date, group in ledger.groupby("_date_only", sort=False)}

    for bank_idx, bank_row in bank.iterrows():
        bank_date = pd.Timestamp(bank_row["date"]).normalize()
        max_window = config.partial_date_window_days
        frames = [
            ledger_by_date.get(bank_date + pd.Timedelta(days=offset))
            for offset in range(-max_window, max_window + 1)
        ]
        frames = [frame for frame in frames if frame is not None and not frame.empty]
        if not frames:
            continue
        scoped = pd.concat(frames)
        date_diff_series = (scoped["_date_only"] - bank_date).abs().dt.days
        signed_diff_series = (scoped["amount"].astype(float) - float(bank_row["amount"])).abs()
        abs_diff_series = (scoped["abs_amount"].astype(float) - abs(float(bank_row["amount"]))).abs()
        scoped = scoped.assign(
            _date_diff=date_diff_series,
            _signed_diff=signed_diff_series.round(2),
            _value_diff=pd.concat([signed_diff_series, abs_diff_series], axis=1).min(axis=1).round(2),
        )
        review_window = config.value_review_window(float(bank_row["amount"]))
        review = scoped[scoped["_value_diff"] <= review_window]
        if review.empty:
            continue

        exact = review[
            (review["_date_diff"] <= config.date_tolerance_days)
            & (review["_value_diff"] <= config.value_tolerance)
        ]
        remaining_slots = max(config.max_candidates_per_transaction - len(exact), 0)
        if exact.empty:
            pool = review.nsmallest(
                config.max_candidates_per_transaction,
                ["_value_diff", "_date_diff"],
            )
        elif remaining_slots:
            extras = review.drop(index=exact.index, errors="ignore").nsmallest(
                remaining_slots,
                ["_value_diff", "_date_diff"],
            )
            pool = pd.concat([exact, extras])
        else:
            pool = exact

        for ledger_idx, ledger_row in pool.iterrows():
            signed_diff = float(ledger_row["_signed_diff"])
            value_diff = float(ledger_row["_value_diff"])
            date_diff = int(ledger_row["_date_diff"])
            text_score = text_similarity(bank_row["description"], ledger_row["description"])
            value_component = _value_score(value_diff, float(bank_row["amount"]), config)
            date_component = _date_score(date_diff, config)
            type_component = _type_score(str(bank_row["direction"]), str(ledger_row["direction"]))

            memory_bonus = 0.0
            bank_norm = str(bank_row.get("normalized_counterparty") or bank_row.get("normalized_description") or "")
            ledger_norm = str(ledger_row.get("normalized_counterparty") or ledger_row.get("normalized_description") or "")
            remembered = alias_memory.get(bank_norm)
            if remembered and remembered == ledger_norm:
                memory_bonus = 0.06

            score = (
                0.34 * value_component
                + 0.24 * date_component
                + 0.32 * text_score
                + 0.10 * type_component
                + memory_bonus
            )
            score = min(score, 1.0)
            candidates.append(
                {
                    "bank_index": bank_idx,
                    "ledger_index": ledger_idx,
                    "score": score,
                    "value_score": value_component,
                    "date_score": date_component,
                    "text_score": text_score,
                    "type_score": type_component,
                    "date_diff_days": date_diff,
                    "value_diff": value_diff,
                    "signed_value_diff": signed_diff,
                    "memory_bonus": memory_bonus,
                }
            )
    return pd.DataFrame(candidates)


def _select_matches(candidates: pd.DataFrame, config: ReconciliationConfig) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    candidates = candidates.sort_values("score", ascending=False).reset_index(drop=True)
    used_bank: set[int] = set()
    used_ledger: set[int] = set()
    selected: list[dict[str, Any]] = []

    duplicate_risk_by_bank: dict[int, bool] = {}
    for bank_idx, group in candidates.groupby("bank_index", sort=False):
        top = group.nlargest(2, "score")
        if len(top) < 2:
            duplicate_risk_by_bank[int(bank_idx)] = False
            continue
        first = top.iloc[0]
        second = top.iloc[1]
        duplicate_risk_by_bank[int(bank_idx)] = bool(
            (float(first["score"]) - float(second["score"])) <= config.duplicate_score_gap
            and float(second["score"]) >= config.medium_confidence_threshold
            and float(first["text_score"]) >= 0.90
            and float(second["text_score"]) >= 0.90
            and float(first["value_diff"]) <= config.value_tolerance
            and float(second["value_diff"]) <= config.value_tolerance
            and int(first["date_diff_days"]) <= config.date_tolerance_days
            and int(second["date_diff_days"]) <= config.date_tolerance_days
        )

    for row in candidates.to_dict("records"):
        if row["score"] < config.minimum_match_score:
            continue
        if row["bank_index"] in used_bank or row["ledger_index"] in used_ledger:
            continue
        row["duplicate_risk"] = duplicate_risk_by_bank.get(int(row["bank_index"]), False)
        selected.append(row)
        used_bank.add(row["bank_index"])
        used_ledger.add(row["ledger_index"])
    return pd.DataFrame(selected)


def _detect_duplicates(df: pd.DataFrame, source_label: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["_date"] = work["date"].dt.date.astype(str)
    work["_amount_key"] = work["amount"].round(2)
    work["_text_key"] = work["normalized_counterparty"].fillna(work["normalized_description"])
    dup_mask = work.duplicated(["_date", "_amount_key", "_text_key"], keep=False)
    duplicates = work[dup_mask].copy()
    if duplicates.empty:
        return pd.DataFrame()
    duplicates["origem"] = source_label
    return duplicates[
        [
            "origem",
            "date",
            "amount",
            "description",
            "counterparty",
            "source_file",
            "source_row",
            "transaction_id",
        ]
    ].sort_values(["date", "amount", "description"])


def _match_rows(
    selected: pd.DataFrame,
    bank: pd.DataFrame,
    ledger: pd.DataFrame,
    config: ReconciliationConfig,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if selected.empty:
        return pd.DataFrame()
    for match in selected.to_dict("records"):
        bank_row = bank.loc[match["bank_index"]]
        ledger_row = ledger.loc[match["ledger_index"]]
        status, reason = _candidate_status(
            float(match["score"]),
            int(match["date_diff_days"]),
            float(match["value_diff"]),
            float(match["text_score"]),
            config,
            bool(match.get("duplicate_risk")),
        )
        rows.append(
            {
                "bank_index": match["bank_index"],
                "ledger_index": match["ledger_index"],
                "bank_transaction_id": bank_row["transaction_id"],
                "ledger_transaction_id": ledger_row["transaction_id"],
                "data_extrato": bank_row["date"],
                "valor_extrato": bank_row["amount"],
                "historico_banco": bank_row["description"],
                "data_razao": ledger_row["date"],
                "valor_razao": ledger_row["amount"],
                "historico_razao": ledger_row["description"],
                "possivel_fornecedor": ledger_row["counterparty"],
                "status": status,
                "motivo": reason,
                "nivel_confianca": confidence_level(
                    float(match["score"]),
                    config.high_confidence_threshold,
                    config.medium_confidence_threshold,
                ),
                "score": round(float(match["score"]), 4),
                "score_texto": round(float(match["text_score"]), 4),
                "score_data": round(float(match["date_score"]), 4),
                "score_valor": round(float(match["value_score"]), 4),
                "diferenca_dias": int(match["date_diff_days"]),
                "diferenca_valor": round(float(match["value_diff"]), 2),
            }
        )
    return pd.DataFrame(rows)


def _build_bank_pending(bank: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    if bank.empty:
        return pd.DataFrame()
    matched_by_bank = {}
    if not matches.empty:
        matched_by_bank = {int(row.bank_index): row for row in matches.itertuples()}
    rows: list[dict[str, Any]] = []
    for index, bank_row in bank.iterrows():
        match = matched_by_bank.get(index)
        if match is None:
            rows.append(
                {
                    "Data do extrato": bank_row["date"],
                    "Valor": bank_row["amount"],
                    "Historico do banco": bank_row["description"],
                    "Possivel fornecedor": "",
                    "Motivo da divergencia": "Nenhum candidato no razao dentro dos criterios de revisao.",
                    "Nivel de confianca": "Baixa confianca",
                    "Status": "Nao encontrado no razao",
                    "Score": 0.0,
                }
            )
        elif match.status != "Conciliado":
            rows.append(
                {
                    "Data do extrato": match.data_extrato,
                    "Valor": match.valor_extrato,
                    "Historico do banco": match.historico_banco,
                    "Possivel fornecedor": match.possivel_fornecedor,
                    "Motivo da divergencia": match.motivo,
                    "Nivel de confianca": match.nivel_confianca,
                    "Status": match.status,
                    "Score": match.score,
                }
            )
    return pd.DataFrame(rows)


def _build_ledger_pending(ledger: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame()
    matched_ledger = set(matches["ledger_index"].astype(int).tolist()) if not matches.empty else set()
    rows: list[dict[str, Any]] = []
    for index, ledger_row in ledger.iterrows():
        if index in matched_ledger:
            continue
        rows.append(
            {
                "Data do razao": ledger_row["date"],
                "Valor": ledger_row["amount"],
                "Historico do razao": ledger_row["description"],
                "Conta": ledger_row["account"],
                "Motivo": "Lancamento do razao sem correspondente no extrato.",
                "Status": "Nao encontrado no extrato",
            }
        )
    return pd.DataFrame(rows)


def _summary(bank: pd.DataFrame, ledger: pd.DataFrame, matches: pd.DataFrame, bank_pending: pd.DataFrame) -> dict[str, Any]:
    total_bank = len(bank)
    reconciled = matches[matches["status"] == "Conciliado"] if not matches.empty else pd.DataFrame()
    pending_count = len(bank_pending)
    total_reconciled = float(reconciled["valor_extrato"].abs().sum()) if not reconciled.empty else 0.0
    total_pending = float(bank_pending["Valor"].abs().sum()) if not bank_pending.empty else 0.0
    return {
        "quantidade_extrato": total_bank,
        "quantidade_razao": len(ledger),
        "quantidade_conciliada": int(len(reconciled)),
        "quantidade_pendente": int(pending_count),
        "total_conciliado": total_reconciled,
        "total_pendente": total_pending,
        "percentual_conciliacao": (len(reconciled) / total_bank) if total_bank else 0.0,
    }


def reconcile(
    bank_transactions: pd.DataFrame,
    ledger_transactions: pd.DataFrame,
    config: ReconciliationConfig | None = None,
    alias_memory: dict[str, str] | None = None,
) -> ReconciliationResult:
    config = (config or ReconciliationConfig()).normalized()
    bank = ensure_canonical(bank_transactions).reset_index(drop=True)
    ledger = ensure_canonical(ledger_transactions).reset_index(drop=True)

    candidates = _build_candidates(bank, ledger, config, alias_memory=alias_memory)
    selected = _select_matches(candidates, config)
    matches = _match_rows(selected, bank, ledger, config)
    bank_pending = _build_bank_pending(bank, matches)
    ledger_pending = _build_ledger_pending(ledger, matches)
    duplicates = pd.concat(
        [_detect_duplicates(bank, "extrato"), _detect_duplicates(ledger, "razao")],
        ignore_index=True,
    )
    summary = _summary(bank, ledger, matches, bank_pending)
    return ReconciliationResult(
        bank_transactions=bank,
        ledger_transactions=ledger,
        matches=matches,
        bank_pending=bank_pending,
        ledger_pending=ledger_pending,
        duplicates=duplicates,
        summary=summary,
    )
