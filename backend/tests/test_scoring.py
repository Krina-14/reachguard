"""
Tests for backend/app/scoring.py.

Table-driven tests covering:
- Every verdict x severity combination
- Exposure edge cases (0 total, reaching > total clamped, negative values)
- Score bounds 0 to 100
- Specific contract assertions (reachable CRITICAL with full exposure = 100, no_path_found LOW with 0 exposure = 15)
- Unknown severity fallback to UNKNOWN (0.4)
- Unknown verdict raises ValueError
- label_for_verdict output and ValueError on unknown verdict
- NO_PROOF_OF_SAFETY_TEXT constant
- explain_breakdown human readable explanation
"""

from __future__ import annotations

import pytest
from app.scoring import (
    FORMULA_TEXT,
    NO_PROOF_OF_SAFETY_TEXT,
    REACH_VALUES,
    SEVERITY_VALUES,
    WEIGHTS,
    explain_breakdown,
    label_for_verdict,
    score,
)


def test_contract_weights_and_constants() -> None:
    """Weights and formula must match Contract Section 6 exactly."""
    assert WEIGHTS == {"reach": 0.5, "severity": 0.3, "exposure": 0.2}
    assert FORMULA_TEXT == "round(100*(0.5*reach+0.3*severity+0.2*exposure))"
    assert (
        NO_PROOF_OF_SAFETY_TEXT
        == "This is not proof of safety. It only means no path was found in the analyzed graph."
    )


def test_contract_specific_anchor_scores() -> None:
    """Contract Section 6 specific examples:

    - Reachable CRITICAL with full exposure = 100
    - no_path_found LOW with zero exposure = 15 (0.5*0.15 + 0.3*0.25 = 0.15)
    """
    res_max = score("reachable_in_model", "CRITICAL", 5, 5)
    assert res_max["reach"] == 1.0
    assert res_max["severity"] == 1.0
    assert res_max["exposure"] == 1.0
    assert res_max["score"] == 100

    res_min = score("no_path_found", "LOW", 0, 0)
    assert res_min["reach"] == 0.15
    assert res_min["severity"] == 0.25
    assert res_min["exposure"] == 0.0
    # 0.5*0.15 + 0.3*0.25 = 0.075 + 0.075 = 0.15 -> round(100 * 0.15) = 15
    assert res_min["score"] == 15


@pytest.mark.parametrize("verdict,reach_val", list(REACH_VALUES.items()))
@pytest.mark.parametrize("severity,sev_val", list(SEVERITY_VALUES.items()))
def test_all_verdict_and_severity_combinations(
    verdict: str,
    reach_val: float,
    severity: str,
    sev_val: float,
) -> None:
    """Table-driven test over all verdicts and severities."""
    # Test with 50% exposure (1 reaching out of 2 total)
    res = score(verdict, severity, reaching_entrypoints=1, total_public_entrypoints=2)

    assert res["reach"] == reach_val
    assert res["severity"] == sev_val
    assert res["exposure"] == 0.5
    assert res["weights"] == WEIGHTS
    assert res["formula"] == FORMULA_TEXT

    expected_score = round(100 * (0.5 * reach_val + 0.3 * sev_val + 0.2 * 0.5))
    assert res["score"] == expected_score
    assert 0 <= res["score"] <= 100


def test_exposure_edge_cases() -> None:
    """Exposure is 0 when total_public is 0, and is clamped to [0.0, 1.0]."""
    # 1. Total public is 0 -> exposure must be 0.0
    res_zero = score("reachable_in_model", "HIGH", reaching_entrypoints=5, total_public_entrypoints=0)
    assert res_zero["exposure"] == 0.0

    # Negative total -> exposure must be 0.0
    res_neg_tot = score("reachable_in_model", "HIGH", reaching_entrypoints=5, total_public_entrypoints=-2)
    assert res_neg_tot["exposure"] == 0.0

    # 2. Reaching > total -> clamped to 1.0
    res_clamped_high = score("reachable_in_model", "HIGH", reaching_entrypoints=15, total_public_entrypoints=10)
    assert res_clamped_high["exposure"] == 1.0

    # 3. Negative reaching -> clamped to 0.0
    res_clamped_low = score("reachable_in_model", "HIGH", reaching_entrypoints=-5, total_public_entrypoints=10)
    assert res_clamped_low["exposure"] == 0.0


def test_unknown_severity_fallback() -> None:
    """Unknown or None severity maps to UNKNOWN (0.4)."""
    res_unknown_str = score("reachable_in_model", "SOME_CUSTOM_SEVERITY", 2, 4)
    assert res_unknown_str["severity"] == 0.4

    res_none = score("unknown", None, 0, 0)
    assert res_none["severity"] == 0.4

    res_empty = score("no_path_found", "", 0, 0)
    assert res_empty["severity"] == 0.4

    # Case-insensitive
    res_case = score("reachable_in_model", "critical", 1, 1)
    assert res_case["severity"] == 1.0


def test_unknown_verdict_raises_value_error() -> None:
    """Unknown verdict string must raise ValueError."""
    with pytest.raises(ValueError, match="Unknown verdict"):
        score("safe", "CRITICAL", 1, 1)

    with pytest.raises(ValueError, match="Unknown verdict"):
        score("vulnerable", "HIGH", 1, 1)


def test_label_for_verdict() -> None:
    """label_for_verdict maps to exact UI labels and raises ValueError on unknown."""
    assert label_for_verdict("reachable_in_model") == "Reachable in model"
    assert label_for_verdict("unknown") == "Unknown"
    assert label_for_verdict("no_path_found") == "No path found in model"

    with pytest.raises(ValueError, match="Unknown verdict"):
        label_for_verdict("safe")


def test_explain_breakdown() -> None:
    """explain_breakdown returns a non-empty human sentence containing score."""
    breakdown = score("reachable_in_model", "HIGH", 3, 4)
    explanation = explain_breakdown(breakdown)

    assert isinstance(explanation, str)
    assert str(breakdown["score"]) in explanation
    assert "reachability" in explanation
    assert "severity" in explanation
    assert "exposure" in explanation
