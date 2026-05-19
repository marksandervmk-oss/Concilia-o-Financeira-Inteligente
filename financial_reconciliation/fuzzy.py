from __future__ import annotations

from difflib import SequenceMatcher

from financial_reconciliation.normalization import common_token_ratio, compact_text, normalize_text

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency
    fuzz = None


def _fallback_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def text_similarity(left: object, right: object) -> float:
    """Return a 0-1 contextual similarity score for vendor/history text."""

    norm_left = normalize_text(left)
    norm_right = normalize_text(right)
    if not norm_left or not norm_right:
        return 0.0

    compact_left = compact_text(left)
    compact_right = compact_text(right)
    token_overlap = common_token_ratio(norm_left, norm_right)

    if fuzz is not None:
        token_score = fuzz.token_set_ratio(norm_left, norm_right) / 100.0
        weighted = fuzz.WRatio(norm_left, norm_right) / 100.0
        partial = fuzz.partial_ratio(norm_left, norm_right) / 100.0
        compact = fuzz.ratio(compact_left, compact_right) / 100.0
    else:
        token_score = _fallback_ratio(" ".join(sorted(norm_left.split())), " ".join(sorted(norm_right.split())))
        weighted = _fallback_ratio(norm_left, norm_right)
        partial = max(
            _fallback_ratio(norm_left, norm_right),
            _fallback_ratio(compact_left, compact_right),
        )
        compact = _fallback_ratio(compact_left, compact_right)

    return max(
        0.35 * token_score + 0.25 * weighted + 0.20 * partial + 0.20 * compact,
        0.70 * token_overlap + 0.30 * compact,
    )


def confidence_level(score: float, high: float = 0.82, medium: float = 0.62) -> str:
    if score >= high:
        return "Alta confianca"
    if score >= medium:
        return "Media confianca"
    return "Baixa confianca"
