# 5.Profiling/cold_start.py
# Handles the three-phase onboarding logic.
# Coordinator between user_profile.py and peer_cluster.py.
# Decides which signals to trust based on how much history a user has.
#
# Phase 1 — cold start  (0–30 events)   : full peer group
# Phase 2 — transition  (30–100 events) : linear blend
# Phase 3 — mature      (100+ events)   : full individual profile

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from user_profile import (
    get_profile,
    is_known_device,
    is_known_country,
    is_known_ip,
    get_hour_deviation,
    get_device_trust,
    increment_event_count,
)
from peer_cluster import (
    get_user_cluster,
    is_common_device_type,
    is_common_country,
    is_common_ip_subnet,
    get_cluster_typical_hours,
    compute_peer_deviation_score,
)
from hyperparams import COLD_START, CLUSTERING

# ─────────────────────────────────────────────
# PHASE THRESHOLDS — loaded from 1.config/hyperparams.py
# ─────────────────────────────────────────────
COLD_START_MIN    = COLD_START["MIN_EVENTS"]
COLD_START_MATURE = COLD_START["MATURE_EVENTS"]


# ─────────────────────────────────────────────
# PHASE LOGIC
# ─────────────────────────────────────────────

def get_phase(user_id):
    """
    Returns (phase_name, individual_weight) for a user.

    phase_name       : "cold_start" | "transition" | "mature" | "outlier"
    individual_weight: 0.0 → trust peer fully
                       0.5 → equal blend
                       1.0 → trust individual fully

    Phases:
        cold_start  — fewer than MIN_EVENTS logins, use peer group
        transition  — between MIN and MATURE, linear blend
        mature      — more than MATURE events, full individual
        outlier     — DBSCAN found no cluster for this user,
                      fall back to full individual regardless of event count
                      (no peer group available to blend with)
    """
    profile = get_profile(user_id)
    if not profile:
        return "cold_start", 0.0

    # ── Outlier check — DBSCAN assigned no cluster ────────────────
    cluster_id = profile.get("peer_cluster_id", "")
    if cluster_id == CLUSTERING["OUTLIER_CLUSTER_ID"]:
        # No peer group exists — must rely on individual profile entirely
        # Even if the user has few events, peer signals aren't available
        return "outlier", 1.0

    total_events = profile.get("total_events", 0)

    if total_events < COLD_START_MIN:
        return "cold_start", 0.0
    elif total_events < COLD_START_MATURE:
        weight = (total_events - COLD_START_MIN) / (COLD_START_MATURE - COLD_START_MIN)
        return "transition", round(weight, 2)
    else:
        return "mature", 1.0


def blend(individual_value, peer_value, individual_weight):
    """
    Blends individual and peer signal values based on weight.
    Used for numeric signals like hour_deviation.

    individual_weight = 1.0 → returns individual_value
    individual_weight = 0.0 → returns peer_value
    individual_weight = 0.5 → returns average of both
    """
    return round(
        individual_weight * individual_value + (1 - individual_weight) * peer_value,
        3
    )


def blend_binary(individual_flag, peer_flag, individual_weight):
    """
    Blends two binary signals (0 or 1) based on weight.
    Returns 0 or 1 — rounds the blended float.

    Example:
        individual says new_device=1 (unknown device)
        peer says new_device=0 (device type is common in cluster)
        weight=0.3 (early transition phase)
        result = round(0.3*1 + 0.7*0) = round(0.3) = 0
        → peer cluster context overrides individual suspicion
    """
    return round(
        individual_weight * individual_flag + (1 - individual_weight) * peer_flag
    )


# ─────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────

def get_profile_signals(user_id, event):
    """
    Main function of this module.
    Returns a complete set of profile-based signals for a login event,
    blended appropriately based on the user's cold start phase.

    Input  : user_id, raw login event dict
    Output : dict of blended profile signals ready for feature vector

    {
        "phase"              : "cold_start" | "transition" | "mature" | "outlier",
        "profile_weight"     : 0.0 to 1.0,
        "new_device"         : 0 or 1,
        "new_country"        : 0 or 1,
        "ip_known"           : 0 or 1,
        "device_trust_score" : 0.0 to 1.0,
        "hour_deviation"     : float,
        "peer_deviation"     : float (0.0 to 1.0),
    }

    Outlier users:
        DBSCAN found no cluster for this user.
        All signals come from individual profile.
        peer_deviation = 0.0 (no cluster to deviate from).
    """
    phase, weight = get_phase(user_id)
    profile       = get_profile(user_id)
    cluster       = get_user_cluster(user_id)

    # Outlier users have no cluster — treat as None
    is_outlier = (phase == "outlier")
    if is_outlier:
        cluster = None

    device_id   = event.get("device_id")
    device_type = event.get("device_type")
    country     = event.get("country")
    ip_address  = event.get("ip_address")
    login_hour  = int(event.get("timestamp", "2026-01-01 09:00:00").split(" ")[1].split(":")[0])

    # ── Individual signals ────────────────────────────────────────
    ind_new_device  = 0 if is_known_device(profile, device_id)  else 1
    ind_new_country = 0 if is_known_country(profile, country)   else 1
    ind_ip_known    = 1 if is_known_ip(profile, ip_address)      else 0
    ind_hour_dev    = get_hour_deviation(profile, login_hour)
    ind_trust       = get_device_trust(profile, device_id)

    # ── Peer signals ──────────────────────────────────────────────
    # Skip entirely for outlier users — no cluster exists
    if cluster and not is_outlier:
        peer_new_device  = 0 if is_common_device_type(cluster, device_type) else 1
        peer_new_country = 0 if is_common_country(cluster, country)         else 1
        peer_ip_known    = 1 if is_common_ip_subnet(cluster, ip_address)    else 0
        cluster_hours    = get_cluster_typical_hours(cluster)
        peer_hour_dev    = float(min(abs(login_hour - h) for h in cluster_hours)) if cluster_hours else 0.0
    else:
        # No cluster — peer signals default to neutral
        peer_new_device  = ind_new_device
        peer_new_country = ind_new_country
        peer_ip_known    = ind_ip_known
        peer_hour_dev    = ind_hour_dev

    # ── Blend based on phase ──────────────────────────────────────
    blended_new_device  = blend_binary(ind_new_device,  peer_new_device,  weight)
    blended_new_country = blend_binary(ind_new_country, peer_new_country, weight)
    blended_ip_known    = blend_binary(ind_ip_known,    peer_ip_known,    weight)
    blended_hour_dev    = blend(ind_hour_dev, peer_hour_dev, weight)

    # Trust score — always from individual profile
    device_trust = ind_trust

    # ── Peer deviation score ──────────────────────────────────────
    if cluster and not is_outlier:
        mini_features = {
            "login_hour"        : login_hour,
            "failed_attempts"   : event.get("failed_attempts", 0),
            "peer_device_match" : 1 - peer_new_device,
            "peer_country_match": 1 - peer_new_country,
            "peer_ip_match"     : peer_ip_known,
        }
        peer_deviation = compute_peer_deviation_score(mini_features, cluster, user_id=user_id)
    else:
        # Outlier — no peer group to deviate from
        peer_deviation = 0.0

    return {
        "phase"             : phase,
        "profile_weight"    : weight,
        "new_device"        : blended_new_device,
        "new_country"       : blended_new_country,
        "ip_known"          : blended_ip_known,
        "device_trust_score": device_trust,
        "hour_deviation"    : blended_hour_dev,
        "peer_deviation"    : peer_deviation,
    }


# ─────────────────────────────────────────────
# QUICK TEST — python cold_start.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from mock_db import LOGIN_EVENTS, USER_PROFILES
    from hyperparams import CLUSTERING

    test_cases = [
        ("u01", "e003", "Mature user   — Kartik, normal office login"),
        ("u01", "e011", "Mature user   — Kartik, London attack"),
        ("u04", "e014", "Cold start    — Sneha, first login"),
    ]

    for user_id, event_id, label in test_cases:
        event   = next(e for e in LOGIN_EVENTS if e["event_id"] == event_id)
        signals = get_profile_signals(user_id, event)
        print(f"\n{'─'*55}")
        print(f"  {label}")
        print(f"{'─'*55}")
        for k, v in signals.items():
            print(f"  {k:<22} : {v}")

    # ── Outlier scenario ──────────────────────────────────────────
    print(f"\n{'─'*55}")
    print(f"  Outlier user  — DBSCAN found no cluster for Arjun")
    print(f"{'─'*55}")
    # Temporarily set Arjun as outlier to test the path
    original_cluster = USER_PROFILES["u03"]["peer_cluster_id"]
    USER_PROFILES["u03"]["peer_cluster_id"] = CLUSTERING["OUTLIER_CLUSTER_ID"]

    event   = next(e for e in LOGIN_EVENTS if e["event_id"] == "e008")
    signals = get_profile_signals("u03", event)
    for k, v in signals.items():
        print(f"  {k:<22} : {v}")

    # Restore original cluster
    USER_PROFILES["u03"]["peer_cluster_id"] = original_cluster