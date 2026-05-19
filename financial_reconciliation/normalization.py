from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable

CORPORATE_STOPWORDS = {
    "LTDA",
    "ME",
    "EIRELI",
    "EPP",
    "SA",
    "S",
    "A",
    "S/A",
    "SOCIEDADE",
    "EMPRESA",
    "COMERCIO",
    "COMERCIAL",
    "SERVICOS",
    "SERVICO",
    "CONSULTORIA",
    "CONSULTORIOS",
    "MEDICOS",
    "ODONTOLOGICOS",
}

TRANSACTION_STOPWORDS = {
    "PAGAMENTO",
    "PAG",
    "PAGTO",
    "PIX",
    "TED",
    "DOC",
    "BOLETO",
    "TRANSFERENCIA",
    "TRANSF",
    "RECEBIDA",
    "RECEBIDO",
    "RECEB",
    "ENVIADA",
    "ENVIADO",
    "ENVIA",
    "ENV",
    "VR",
    "REF",
    "A",
    "DE",
    "DA",
    "DO",
    "DAS",
    "DOS",
    "PARA",
    "CONTA",
    "BANCO",
    "BCO",
}

STOPWORDS = CORPORATE_STOPWORDS | TRANSACTION_STOPWORDS


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def maybe_fix_mojibake(value: str) -> str:
    """Best effort for common UTF-8 text shown as latin-1/cp1252."""

    if not value:
        return ""
    markers = ("\u00c3", "\u00c2", "\ufffd")
    if not any(marker in value for marker in markers):
        return value
    for encoding in ("latin1", "cp1252"):
        try:
            fixed = value.encode(encoding, errors="ignore").decode("utf-8", errors="ignore")
            if fixed and sum(ch.isalpha() for ch in fixed) >= sum(ch.isalpha() for ch in value) * 0.7:
                return fixed
        except UnicodeError:
            continue
    return value


@lru_cache(maxsize=100_000)
def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = maybe_fix_mojibake(text)
    text = strip_accents(text).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = [token for token in text.split() if token not in STOPWORDS and len(token) > 1]
    return " ".join(tokens)


@lru_cache(maxsize=100_000)
def searchable_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = maybe_fix_mojibake(text)
    text = strip_accents(text).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=100_000)
def compact_text(value: object) -> str:
    return normalize_text(value).replace(" ", "")


def normalize_column_name(value: object) -> str:
    text = strip_accents(maybe_fix_mojibake("" if value is None else str(value))).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def token_set(value: object) -> set[str]:
    return set(normalize_text(value).split())


def common_token_ratio(left: object, right: object) -> float:
    left_tokens = token_set(left)
    right_tokens = token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def best_counterparty_text(parts: Iterable[object]) -> str:
    text = " ".join(str(part) for part in parts if part is not None)
    normalized = normalize_text(text)
    return normalized or str(text).strip()
