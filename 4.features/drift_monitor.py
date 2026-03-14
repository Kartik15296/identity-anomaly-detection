# 4.features/drift_monitor.py
# Monitors feature distributions for concept drift.
# Called by 8.feedback/retrain_scheduler.py to decide if retraining is needed.
#
# Two methods:
#   PSI  (Population Stability Index) — catches gradual distribution shifts
#   KS   (Kolmogorov-Smirnov test)    — catches sudden distribution changes
#
# How it works:
#   1. You have a baseline — feature distributions from training data
#   2. New events come in over time — current feature distributions
#   3. This module compares them and flags when drift is detected
#   4. If drift is detected → retrain_scheduler triggers model retraining

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

import math
from scipy import stats
from extractor import extract_features
from mock_db import LOGIN_EVENTS
from hyperparams import DRIFT

# ─────────────────────────────────────────────
# THRESHOLDS — loaded from 1.config/hyperparams.py
# ─────────────────────────────────────────────
PSI_NO_DRIFT        = DRIFT["PSI_STABLE"]
PSI_MODERATE_DRIFT  = DRIFT["PSI_WARN"]
KS_PVALUE_THRESHOLD = DRIFT["KS_PVALUE"]

# Features we monitor for drift
# These are the numeric ones — PSI and KS don't apply to categorical
MONITORED_FEATURES = [
    "login_hour",
    "failed_attempts",
    "device_trust_score",
    "hour_deviation",
    "distance_km",
    "travel_speed_kmh",
]


def compute_psi(baseline_values, current_values, buckets=None):
    """
    Computes Population Stability Index between two distributions.

    PSI = sum((current% - baseline%) * ln(current% / baseline%))

    baseline_values : list of feature values from training period
    current_values  : list of feature values from recent events
    buckets         : number of bins (defaults to DRIFT PSI_BUCKETS from hyperparams)

    Returns PSI score (float)
    """
    if buckets is None:
        buckets = DRIFT["PSI_BUCKETS"]
    if not baseline_values or not current_values:
        return 0.0

    # Build bin edges from baseline distribution
    min_val = min(min(baseline_values), min(current_values))
    max_val = max(max(baseline_values), max(current_values))

    if min_val == max_val:
        return 0.0

    bucket_size = (max_val - min_val) / buckets
    edges = [min_val + i * bucket_size for i in range(buckets + 1)]

    def get_bucket_counts(values):
        counts = [0] * buckets
        for v in values:
            idx = int((v - min_val) / bucket_size)
            idx = min(idx, buckets - 1)  # clamp last value into final bucket
            counts[idx] += 1
        return counts

    baseline_counts = get_bucket_counts(baseline_values)
    current_counts  = get_bucket_counts(current_values)

    n_baseline = len(baseline_values)
    n_current  = len(current_values)

    psi = 0.0
    for b_count, c_count in zip(baseline_counts, current_counts):
        # Avoid division by zero — use small epsilon
        b_pct = max(b_count / n_baseline, 1e-6)
        c_pct = max(c_count / n_current,  1e-6)
        psi  += (c_pct - b_pct) * math.log(c_pct / b_pct)

    return round(psi, 4)


def compute_ks(baseline_values, current_values):
    """
    Runs Kolmogorov-Smirnov two-sample test.
    Returns (statistic, p_value).
    Low p-value (<0.05) means distributions are significantly different.
    """
    if not baseline_values or not current_values:
        return 0.0, 1.0

    statistic, p_value = stats.ks_2samp(baseline_values, current_values)
    return round(statistic, 4), round(p_value, 4)


def interpret_psi(psi_score):
    """Human readable PSI interpretation."""
    if psi_score < PSI_NO_DRIFT:
        return "stable"
    elif psi_score < PSI_MODERATE_DRIFT:
        return "moderate_drift"
    else:
        return "significant_drift"


def check_drift(baseline_features_list, current_features_list):
    """
    Main function. Compares two sets of feature vectors for drift.

    baseline_features_list : list of feature dicts from training period
    current_features_list  : list of feature dicts from recent events

    Returns drift report dict:
    {
        "drift_detected"  : True/False   — should we retrain?
        "features"        : {
            "login_hour" : {
                "psi"        : 0.05,
                "psi_status" : "stable",
                "ks_stat"    : 0.12,
                "ks_pvalue"  : 0.34,
                "ks_drift"   : False
            },
            ...
        }
    }
    """
    if not baseline_features_list or not current_features_list:
        return {"drift_detected": False, "features": {}, "reason": "insufficient_data"}

    report = {"features": {}}
    any_drift = False

    for feature in MONITORED_FEATURES:
        baseline_vals = [f[feature] for f in baseline_features_list if feature in f]
        current_vals  = [f[feature] for f in current_features_list  if feature in f]

        psi               = compute_psi(baseline_vals, current_vals)
        psi_status        = interpret_psi(psi)
        ks_stat, ks_pval  = compute_ks(baseline_vals, current_vals)
        ks_drift          = ks_pval < KS_PVALUE_THRESHOLD

        feature_drifted = psi_status == "significant_drift" or ks_drift
        if feature_drifted:
            any_drift = True

        report["features"][feature] = {
            "psi"        : psi,
            "psi_status" : psi_status,
            "ks_stat"    : ks_stat,
            "ks_pvalue"  : ks_pval,
            "ks_drift"   : ks_drift,
            "drifted"    : feature_drifted,
        }

    report["drift_detected"] = any_drift
    report["reason"]         = "drift_in_features" if any_drift else "all_stable"

    return report


# ─────────────────────────────────────────────
# QUICK TEST — python drift_monitor.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from scipy import stats

    # Build baseline features from normal events (e001–e010)
    normal_event_ids = ["e001","e002","e003","e004","e005","e006","e007","e008","e009","e010"]
    baseline = []
    for eid in normal_event_ids:
        event = next((e for e in LOGIN_EVENTS if e["event_id"] == eid), None)
        if event:
            baseline.append(extract_features(event))

    # Build current features — mix of normal + attack events
    current_event_ids = ["e011", "e012", "e013"]
    current = []
    for eid in current_event_ids:
        event = next((e for e in LOGIN_EVENTS if e["event_id"] == eid), None)
        if event:
            current.append(extract_features(event))

    print(f"Baseline events : {len(baseline)}")
    print(f"Current events  : {len(current)}")

    report = check_drift(baseline, current)

    print(f"\nDrift detected  : {report['drift_detected']}")
    print(f"Reason          : {report['reason']}")
    print(f"\n{'─'*60}")
    print(f"  {'Feature':<22} {'PSI':>6}  {'PSI Status':<20} {'KS Drift'}")
    print(f"{'─'*60}")
    for feat, result in report["features"].items():
        print(f"  {feat:<22} {result['psi']:>6}  {result['psi_status']:<20} {result['ks_drift']}")