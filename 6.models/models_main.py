# 6.models/main.py
# Mock model interface — mimics exactly what the real ML models will return.
# All other folders (7.scoring, 8.feedback, Admin_dashboard) import from here.
#
# When 6.models is fully built:
#   Replace each function body with real model calls.
#   Function signatures stay IDENTICAL — nothing else in the project changes.
#
# Two models mocked here:
#   1. Isolation Forest  — unsupervised anomaly score
#   2. Online Learner    — supervised attack probability (River)

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

# ─────────────────────────────────────────────
# MODEL 1 — ISOLATION FOREST
# Unsupervised. Trained on normal login events.
# Returns anomaly_score: 0.0 = normal, 1.0 = highly anomalous
#
# Real version will:
#   Load artifacts/isolation_forest.pkl
#   Call model.predict() on the feature vector
#   Map output to 0.0–1.0 range
# ─────────────────────────────────────────────

def get_anomaly_score(feature_vector):
    """
    Takes merged feature vector dict.
    Returns anomaly_score float (0.0 to 1.0).

    0.0 = completely normal
    1.0 = highly anomalous

    Mock logic:
        Counts how many red-flag signals are present.
        Each red flag adds to the score.
        Mimics what Isolation Forest will produce.
    """
    score = 0.0

    if feature_vector.get("new_device", 0) == 1:
        score += 0.25

    if feature_vector.get("new_country", 0) == 1:
        score += 0.25

    if feature_vector.get("failed_attempts", 0) >= 3:
        score += 0.20

    if feature_vector.get("hour_deviation", 0) >= 4:
        score += 0.15

    if feature_vector.get("travel_speed_kmh", 0) >= 500:
        score += 0.15

    if feature_vector.get("peer_deviation", 0.0) >= 0.6:
        score += 0.10

    if feature_vector.get("ip_known", 1) == 0:
        score += 0.05

    if feature_vector.get("device_trust_score", 0.5) <= 0.3:
        score += 0.05

    return round(min(score, 1.0), 4)


# ─────────────────────────────────────────────
# MODEL 2 — ONLINE LEARNER
# Supervised. Updates incrementally from feedback labels.
# Returns attack_probability: 0.0 = legitimate, 1.0 = attack
#
# Real version will:
#   Load artifacts/online_learner.pkl (River model)
#   Call model.predict_proba_one() on the feature vector
#   Return probability of attack class
# ─────────────────────────────────────────────

def get_attack_probability(feature_vector):
    """
    Takes merged feature vector dict.
    Returns attack_probability float (0.0 to 1.0).

    0.0 = very likely legitimate
    1.0 = very likely attack

    Mock logic:
        Weighted combination of strongest attack signals.
        Mimics what a trained River classifier will produce.
    """
    prob = 0.0

    # Strong signals
    if feature_vector.get("new_device", 0) == 1:
        prob += 0.20

    if feature_vector.get("new_country", 0) == 1:
        prob += 0.20

    # Failed attempts — strong attack signal
    fails = feature_vector.get("failed_attempts", 0)
    if fails >= 5:
        prob += 0.25
    elif fails >= 3:
        prob += 0.15
    elif fails >= 1:
        prob += 0.05

    # Peer deviation
    peer_dev = feature_vector.get("peer_deviation", 0.0)
    if peer_dev >= 0.7:
        prob += 0.15
    elif peer_dev >= 0.4:
        prob += 0.08

    # Travel speed
    speed = feature_vector.get("travel_speed_kmh", 0)
    if speed >= 900:
        prob += 0.15
    elif speed >= 400:
        prob += 0.08

    # Trust
    trust = feature_vector.get("device_trust_score", 0.5)
    if trust <= 0.2:
        prob += 0.10

    return round(min(prob, 1.0), 4)


# ─────────────────────────────────────────────
# COMBINED MODEL OUTPUT
# Single entry point used by 7.scoring/risk_engine.py
# Returns both scores together
# ─────────────────────────────────────────────

def get_model_scores(feature_vector):
    """
    Main function called by risk_engine.py.
    Returns both model outputs in one call.

    Returns:
    {
        "anomaly_score"      : float 0.0–1.0  (Isolation Forest)
        "attack_probability" : float 0.0–1.0  (Online Learner)
    }

    When real models are ready:
        Replace get_anomaly_score() with real IF prediction
        Replace get_attack_probability() with real River prediction
        This dict structure stays identical
    """
    return {
        "anomaly_score"     : get_anomaly_score(feature_vector),
        "attack_probability": get_attack_probability(feature_vector),
    }


# ─────────────────────────────────────────────
# FEEDBACK INTERFACE
# Called by 8.feedback/label_collector.py
# Passes a labeled event to the online learner for incremental update
#
# Real version will:
#   Load online_learner.pkl
#   Call model.learn_one(features, label)
#   Save updated model back to artifacts/
# ─────────────────────────────────────────────

def update_online_learner(feature_vector, label):
    """
    Incrementally updates the online learner with one labeled event.

    feature_vector : merged feature dict
    label          : "attack" or "legitimate"

    Mock: just prints what the real model would do.
    Real version: calls River model.learn_one()
    """
    print(f"[MODEL] Online learner update — label={label}, "
          f"new_device={feature_vector.get('new_device')}, "
          f"new_country={feature_vector.get('new_country')}, "
          f"anomaly_score={get_anomaly_score(feature_vector)}")


# ─────────────────────────────────────────────
# QUICK TEST — python main.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from mock_db import LOGIN_EVENTS
    from extractor import extract_features
    from cold_start import get_profile_signals

    test_cases = [
        ("u01", "e003", "Normal login  — Kartik, office"),
        ("u01", "e011", "Attack        — Kartik, London 3am"),
        ("u03", "e013", "Suspicious    — Arjun, Singapore"),
        ("u04", "e014", "Cold start    — Sneha, first login"),
    ]

    print(f"{'─'*60}")
    print(f"  {'Scenario':<35} {'anomaly':>8}  {'attack_prob':>12}")
    print(f"{'─'*60}")

    for user_id, event_id, label in test_cases:
        event          = next(e for e in LOGIN_EVENTS if e["event_id"] == event_id)
        raw_features   = extract_features(event)
        profile_signals = get_profile_signals(user_id, event)
        feature_vector  = {**raw_features, **profile_signals}

        scores = get_model_scores(feature_vector)
        print(f"  {label:<35} {scores['anomaly_score']:>8}  {scores['attack_probability']:>12}")

    print(f"\n── Online learner feedback test ──────────────────────")
    event          = next(e for e in LOGIN_EVENTS if e["event_id"] == "e011")
    raw_features   = extract_features(event)
    profile_signals = get_profile_signals("u01", event)
    feature_vector  = {**raw_features, **profile_signals}
    update_online_learner(feature_vector, label="attack")