# 7.scoring/explainer.py
# Produces human-readable reason codes for a risk decision.
#
# Approach:
#   Without real SHAP (coming in 6.models), we use a weighted
#   contribution approach — each feature has a known risk weight,
#   contribution = feature_value × weight × 100
#   Top N contributors become the reason codes shown to admins.
#
# When 6.models is ready:
#   Replace compute_contributions() with real SHAP values.
#   The rest of this file stays identical.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from hyperparams import SCORING


# ─────────────────────────────────────────────
# FEATURE RISK WEIGHTS
# How much each feature contributes to risk
# when fully anomalous (value = 1.0 or max)
#
# These mirror the signal weights in risk_engine.py
# When SHAP replaces this, these weights are unused
# ─────────────────────────────────────────────
FEATURE_WEIGHTS = {
    "new_device"        : 0.20,
    "new_country"       : 0.20,
    "peer_deviation"    : 0.18,
    "travel_speed_kmh"  : 0.15,
    "hour_deviation"    : 0.10,
    "failed_attempts"   : 0.10,
    "ip_known"          : 0.05,   # inverted — 0 = unknown = risky
    "device_trust_score": 0.02,   # inverted — low trust = risky
}

# ─────────────────────────────────────────────
# HUMAN READABLE TEMPLATES
# One template per feature
# {value} is replaced with the actual value
# ─────────────────────────────────────────────
REASON_TEMPLATES = {
    "new_device"        : "Login from an unrecognized device",
    "new_country"       : "Login from a new country: {value}",
    "peer_deviation"    : "Behavior significantly unlike peer group (deviation: {value})",
    "travel_speed_kmh"  : "Unusually fast travel detected ({value} km/h since last login)",
    "hour_deviation"    : "Login at unusual hour (deviation: {value}h from typical)",
    "failed_attempts"   : "{value} failed attempts before this login",
    "ip_known"          : "Login from an unrecognized IP address",
    "device_trust_score": "Device has low trust score ({value})",
}


def compute_contributions(feature_vector):
    """
    Computes risk contribution of each feature.
    Returns dict of { feature_name: contribution_score }

    Contribution = how much this feature is adding to risk (0.0 to 1.0).
    Higher = this feature is driving risk up more.

    Inverted features (ip_known, device_trust_score):
        Low value = high risk, so contribution = weight × (1 - value)

    Normal features:
        High value = high risk, contribution = weight × normalized_value
    """
    contributions = {}

    # new_device — binary 0/1
    contributions["new_device"] = (
        FEATURE_WEIGHTS["new_device"] * feature_vector.get("new_device", 0)
    )

    # new_country — binary 0/1
    contributions["new_country"] = (
        FEATURE_WEIGHTS["new_country"] * feature_vector.get("new_country", 0)
    )

    # peer_deviation — already 0.0–1.0
    contributions["peer_deviation"] = (
        FEATURE_WEIGHTS["peer_deviation"] * feature_vector.get("peer_deviation", 0)
    )

    # travel_speed_kmh — normalize against 1000 km/h as max meaningful speed
    # Anything above 1000 km/h is already physically impossible
    raw_speed = feature_vector.get("travel_speed_kmh", 0)
    contributions["travel_speed_kmh"] = (
        FEATURE_WEIGHTS["travel_speed_kmh"] * min(raw_speed / 1000.0, 1.0)
    )

    # hour_deviation — normalize against 12h max
    raw_hour_dev = feature_vector.get("hour_deviation", 0)
    contributions["hour_deviation"] = (
        FEATURE_WEIGHTS["hour_deviation"] * min(raw_hour_dev / 12.0, 1.0)
    )

    # failed_attempts — normalize against 5 max
    raw_fails = feature_vector.get("failed_attempts", 0)
    contributions["failed_attempts"] = (
        FEATURE_WEIGHTS["failed_attempts"] * min(raw_fails / 5.0, 1.0)
    )

    # ip_known — inverted: 0 (unknown) = risky
    ip_known = feature_vector.get("ip_known", 0)
    contributions["ip_known"] = (
        FEATURE_WEIGHTS["ip_known"] * (1 - ip_known)
    )

    # device_trust_score — inverted: low trust = risky
    trust = feature_vector.get("device_trust_score", 0.5)
    contributions["device_trust_score"] = (
        FEATURE_WEIGHTS["device_trust_score"] * (1 - trust)
    )

    return contributions


def get_reason_codes(feature_vector, event=None, top_n=None):
    """
    Returns top N reason codes explaining why a login was flagged.

    feature_vector : merged feature dict from processor.py
    event          : raw login event (used for value interpolation in templates)
    top_n          : number of reasons to return (defaults to SCORING config)

    Returns list of dicts:
    [
        {
            "feature"     : "new_country",
            "contribution": 0.18,
            "reason"      : "Login from a new country: UK"
        },
        ...
    ]
    """
    if top_n is None:
        top_n = SCORING["TOP_REASON_CODES"]

    contributions = compute_contributions(feature_vector)

    # Sort by contribution descending
    sorted_features = sorted(
        contributions.items(),
        key=lambda x: x[1],
        reverse=True
    )

    # Only include features that meaningfully contributed
    # Threshold of 0.01 filters out near-zero noise
    active = [(f, c) for f, c in sorted_features if c > 0.01]

    reason_codes = []
    for feature, contribution in active[:top_n]:
        template = REASON_TEMPLATES.get(feature, feature)

        # Interpolate {value} in template
        value = _get_display_value(feature, feature_vector, event)
        reason = template.replace("{value}", str(value))

        reason_codes.append({
            "feature"     : feature,
            "contribution": round(contribution, 4),
            "reason"      : reason,
        })

    return reason_codes


def _get_display_value(feature, feature_vector, event=None):
    """
    Returns a human-friendly display value for a feature.
    Used to fill {value} in reason templates.
    """
    if feature == "new_country" and event:
        return event.get("country", feature_vector.get("new_country", "unknown"))

    if feature == "travel_speed_kmh":
        return round(feature_vector.get("travel_speed_kmh", 0), 1)

    if feature == "hour_deviation":
        return round(feature_vector.get("hour_deviation", 0), 1)

    if feature == "failed_attempts":
        return feature_vector.get("failed_attempts", 0)

    if feature == "peer_deviation":
        return round(feature_vector.get("peer_deviation", 0), 2)

    if feature == "device_trust_score":
        return round(feature_vector.get("device_trust_score", 0.5), 2)

    return feature_vector.get(feature, "N/A")


# ─────────────────────────────────────────────
# QUICK TEST — python explainer.py
# ─────────────────────────────────────────────
if __name__ == "__main__":

    test_cases = [
        (
            "Normal login — Kartik",
            {
                "new_device": 0, "new_country": 0, "peer_deviation": 0.003,
                "travel_speed_kmh": 0, "hour_deviation": 0,
                "failed_attempts": 0, "ip_known": 1, "device_trust_score": 0.95,
            },
            {"country": "India"}
        ),
        (
            "Attack — London 3am",
            {
                "new_device": 1, "new_country": 1, "peer_deviation": 0.639,
                "travel_speed_kmh": 449.73, "hour_deviation": 5,
                "failed_attempts": 3, "ip_known": 0, "device_trust_score": 0.5,
            },
            {"country": "UK"}
        ),
        (
            "Suspicious — Singapore travel",
            {
                "new_device": 0, "new_country": 1, "peer_deviation": 0.4,
                "travel_speed_kmh": 134.87, "hour_deviation": 0,
                "failed_attempts": 0, "ip_known": 0, "device_trust_score": 0.99,
            },
            {"country": "Singapore"}
        ),
    ]

    for label, features, event in test_cases:
        reasons = get_reason_codes(features, event=event)
        print(f"\n{'─'*55}")
        print(f"  {label}")
        print(f"{'─'*55}")
        for i, r in enumerate(reasons, 1):
            print(f"  {i}. [{r['contribution']:.4f}]  {r['reason']}")