"""
ReachGuard — Deterministic Finding Scoring Engine.

Pure functions implementing Contract Section 6:
Formula:
  reach     = 1.0 (reachable_in_model) | 0.5 (unknown) | 0.15 (no_path_found)
  severity  = 1.0 CRITICAL | 0.75 HIGH | 0.5 MODERATE | 0.25 LOW | 0.4 UNKNOWN
  exposure  = reaching_public_entrypoints / total_public_entrypoints (0 if no public entrypoints)
  score     = round(100 * (0.5 * reach + 0.3 * severity + 0.2 * exposure))

No imports from other app modules.
"""

from __future__ import annotations

from typing import Any

# ── Weights & Constants ──────────────────────────────────────────

WEIGHTS: dict[str, float] = {
    "reach": 0.5,
    "severity": 0.3,
    "exposure": 0.2,
}

FORMULA_TEXT: str = "round(100*(0.5*reach+0.3*severity+0.2*exposure))"

REACH_VALUES: dict[str, float] = {
    "reachable_in_model": 1.0,
    "unknown": 0.5,
    "no_path_found": 0.15,
}

SEVERITY_VALUES: dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH": 0.75,
    "MODERATE": 0.5,
    "LOW": 0.25,
    "UNKNOWN": 0.4,
}

VERDICT_LABELS: dict[str, str] = {
    "reachable_in_model": "Reachable in model",
    "unknown": "Unknown",
    "no_path_found": "No path found in model",
}

NO_PROOF_OF_SAFETY_TEXT: str = (
    "This is not proof of safety. It only means no path was found in the analyzed graph."
)


def label_for_verdict(verdict: str) -> str:
    """Return human-readable UI label for a given verdict string.

    Raises ValueError if verdict is not recognized.
    """
    if verdict not in VERDICT_LABELS:
        raise ValueError(
            f"Unknown verdict: '{verdict}'. Expected one of {list(VERDICT_LABELS.keys())}"
        )
    return VERDICT_LABELS[verdict]


def score(
    verdict: str,
    severity: str | None,
    reaching_entrypoints: int = 0,
    total_public_entrypoints: int = 0,
    *,
    reaching_public: int | None = None,
    total_public: int | None = None,
) -> dict[str, Any]:
    """Calculate deterministic risk score and breakdown according to Contract Section 6.

    Args:
        verdict: 'reachable_in_model', 'unknown', or 'no_path_found'.
                 Raises ValueError for unknown verdict strings.
        severity: 'CRITICAL', 'HIGH', 'MODERATE', 'LOW', 'UNKNOWN' (case-insensitive).
                  Unknown or None severity strings map to 'UNKNOWN' (0.4).
        reaching_entrypoints: Number of public entrypoints that reach the package.
        total_public_entrypoints: Total number of public entrypoints in repo.
                                  Exposure is 0 if total_public_entrypoints is 0,
                                  and is clamped between 0.0 and 1.0.
        reaching_public: Alias for reaching_entrypoints.
        total_public: Alias for total_public_entrypoints.

    Returns:
        dict with reach, severity, exposure, weights, score, formula.
    """
    if reaching_public is not None:
        reaching_entrypoints = reaching_public
    if total_public is not None:
        total_public_entrypoints = total_public
    if verdict not in REACH_VALUES:
        raise ValueError(
            f"Unknown verdict: '{verdict}'. Expected one of {list(REACH_VALUES.keys())}"
        )
    reach_val = REACH_VALUES[verdict]

    sev_key = (severity or "").strip().upper()
    sev_val = SEVERITY_VALUES.get(sev_key, SEVERITY_VALUES["UNKNOWN"])

    if total_public_entrypoints <= 0:
        exposure_val = 0.0
    else:
        raw_exposure = reaching_entrypoints / total_public_entrypoints
        exposure_val = max(0.0, min(1.0, float(raw_exposure)))

    raw_score = (
        WEIGHTS["reach"] * reach_val
        + WEIGHTS["severity"] * sev_val
        + WEIGHTS["exposure"] * exposure_val
    )
    score_val = round(100.0 * raw_score)

    return {
        "reach": reach_val,
        "severity": sev_val,
        "exposure": exposure_val,
        "weights": dict(WEIGHTS),
        "score": score_val,
        "formula": FORMULA_TEXT,
    }


def explain_breakdown(breakdown: dict[str, Any]) -> str:
    """Return one human sentence explaining the score breakdown."""
    score_val = breakdown.get("score", 0)
    reach_val = breakdown.get("reach", 0.0)
    sev_val = breakdown.get("severity", 0.0)
    exp_val = breakdown.get("exposure", 0.0)

    verdict_name = next((k for k, v in REACH_VALUES.items() if v == reach_val), "verdict")
    verdict_label = VERDICT_LABELS.get(verdict_name, verdict_name)
    sev_name = next((k for k, v in SEVERITY_VALUES.items() if v == sev_val), "severity")

    return (
        f"Score {score_val}/100 computed from {verdict_label} reachability ({reach_val}), "
        f"{sev_name} severity ({sev_val}), and {exp_val:.1%} public exposure ({exp_val})."
    )
