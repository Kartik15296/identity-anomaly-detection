# 7.scoring/risk_engine.py
# Combines all signals into a final risk score 0–100.
#
# Current approach — weighted combination with hardcoded weights.
# This mimics what the trained logistic regression meta-learner will do.
#
# When 6.models is ready:
#   Replace SIGNAL_WEIGHTS with weights learned from labeled feedback data.
#   The compute_risk_score() function signature stays identical.
#   processor.py and everything downstream needs no changes.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from hyperparams import SCORING, CLUSTERING
from models_main import get_model_scores
from decision import get_action
from explainer import get_reason_codes


# ─────────────────────────────────────────────
# SIGNAL WEIGHTS
# How much each signal contributes to final score.
# Must sum to 1.0.
#
# Placeholder weights — will be replaced by
# logistic regression trained weights from 6.models.
#
# Design rationale:
#   new_device + new_country carry most weight —
#   these are the strongest account takeover signals.
#   peer_deviation adds context — a new device that
#   matches peer group patterns is less suspicious.
#   travel_speed is strong when high but often 0.
#   failed_attempts is a clear attack signal.
# ─────────────────────────────────────────────
SIGNAL_WEIGHTS = {
    "new_device"         : 0.20,
    "new_country"        : 0.18,
    "peer_deviation"     : 0.16,
    "anomaly_score"      : 0.15,   # Isolation Forest — from 6.models/main.py
    "attack_probability" : 0.12,   # Online Learner   — from 6.models/main.py
    "failed_attempts"    : 0.09,
    "travel_speed_kmh"   : 0.07,
    "hour_deviation"     : 0.02,
    "device_trust_score" : 0.01,   # inverted — lower trust = higher risk
}

# Sanity check — weights must sum to 1.0
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-6, \
    f"SIGNAL_WEIGHTS must sum to 1.0, got {sum(SIGNAL_WEIGHTS.values())}"


def _normalize_signals(feature_vector):
    """
    Converts raw feature values to 0.0–1.0 risk contribution per signal.
    Each signal is normalized so 1.0 = maximally risky.

    Inverted signals (ip_known, device_trust_score):
        High value = safe → contribution = 1 - value

    Continuous signals:
        Normalized against a max reference value from hyperparams.
    """
    hour_dev_max  = CLUSTERING["HOUR_DEVIATION_MAX"]
    fail_max      = CLUSTERING["FAILED_ATTEMPTS_MAX"]
    speed_max     = 1000.0   # km/h — above this is physically impossible anyway

    normalized = {}

    # Binary signals — already 0 or 1
    normalized["new_device"]  = float(feature_vector.get("new_device", 0))
    normalized["new_country"] = float(feature_vector.get("new_country", 0))

    # Peer deviation — already 0.0–1.0
    normalized["peer_deviation"] = float(feature_vector.get("peer_deviation", 0.0))

    # Anomaly score + attack probability from 6.models/main.py
    # When real model is ready, main.py swaps in the real predictions.
    # Nothing here changes.
    model_scores = get_model_scores(feature_vector)

    normalized["anomaly_score"] = float(model_scores.get("anomaly_score", 0.0))

    # Attack probability from online learner — already 0.0–1.0
    normalized["attack_probability"] = float(model_scores.get("attack_probability", 0.0))

    # Failed attempts — normalize against max
    raw_fails = feature_vector.get("failed_attempts", 0)
    normalized["failed_attempts"] = min(raw_fails / fail_max, 1.0)

    # Travel speed — normalize against max meaningful speed
    raw_speed = feature_vector.get("travel_speed_kmh", 0)
    normalized["travel_speed_kmh"] = min(raw_speed / speed_max, 1.0)

    # Hour deviation — normalize against max
    raw_hour_dev = feature_vector.get("hour_deviation", 0)
    normalized["hour_deviation"] = min(raw_hour_dev / hour_dev_max, 1.0)

    # Device trust — inverted: low trust = high risk
    trust = feature_vector.get("device_trust_score", 0.5)
    normalized["device_trust_score"] = 1.0 - trust

    return normalized


def compute_risk_score(feature_vector):
    """
    Computes final risk score from merged feature vector.

    Input  : merged feature dict from Integration/processor.py
             (raw features from 4.features + profile signals from 5.Profiling)
    Output : risk score float 0.0–100.0

    Score interpretation:
        0  – RISK_ALLOW   : normal, allow login
        RISK_ALLOW – RISK_MFA     : step-up MFA
        RISK_MFA   – RISK_LIMITED : limited session
        RISK_LIMITED – 100        : block + alert
    """
    normalized = _normalize_signals(feature_vector)

    # Weighted sum of all normalized signals
    raw_score = sum(
        normalized.get(signal, 0.0) * weight
        for signal, weight in SIGNAL_WEIGHTS.items()
    )

    # Scale to 0–100
    risk_score = round(raw_score * 100, 2)

    return risk_score


def compute_full_result(feature_vector, event=None):
    """
    Convenience function — runs risk scoring + decision + explanation
    in one call. Returns the complete result dict.

    Used by Integration/processor.py as the single scoring entry point.

    Returns:
    {
        "risk_score"  : float,
        "action"      : "allow" | "mfa" | "limited_session" | "block",
        "description" : str,
        "reason_codes": [ {feature, contribution, reason}, ... ],
        "signals"     : normalized signal values for debugging
    }
    """
    risk_score   = compute_risk_score(feature_vector)
    decision     = get_action(risk_score)
    reason_codes = get_reason_codes(feature_vector, event=event)
    normalized   = _normalize_signals(feature_vector)

    return {
        "risk_score"  : risk_score,
        "action"      : decision["action"],
        "description" : decision["description"],
        "reason_codes": reason_codes,
        "signals"     : {k: round(v, 4) for k, v in normalized.items()},
    }


# ─────────────────────────────────────────────
# QUICK TEST — python risk_engine.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from mock_db import LOGIN_EVENTS
    from extractor import extract_features
    from cold_start import get_profile_signals

    test_cases = [
        ("u01", "e003", "Normal login    — Kartik, office"),
        ("u01", "e011", "Attack          — Kartik, London 3am"),
        ("u03", "e013", "Suspicious      — Arjun, Singapore travel"),
        ("u04", "e014", "Cold start      — Sneha, first login"),
    ]

    for user_id, event_id, label in test_cases:
        event = next(e for e in LOGIN_EVENTS if e["event_id"] == event_id)

        # Merge features from both layers
        raw_features     = extract_features(event)
        profile_signals  = get_profile_signals(user_id, event)
        feature_vector   = {**raw_features, **profile_signals}

        result = compute_full_result(feature_vector, event=event)

        print(f"\n{'─'*58}")
        print(f"  {label}")
        print(f"{'─'*58}")
        print(f"  risk_score  : {result['risk_score']}")
        print(f"  action      : {result['action']}")
        print(f"  reason codes:")
        for r in result["reason_codes"]:
            print(f"    → {r['reason']}")