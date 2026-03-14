# 4.features/extractor.py
# Extracts raw features from a login event + individual user profile.
#
# Responsibility boundary:
#   DOES    — raw event signals, individual profile signals, geo/travel signals
#   DOES NOT — peer cluster signals, cold start blending, phase logic
#
# Peer signals and blending live in 5.Profiling/cold_start.py
# Integration/processor.py merges both outputs into the final feature vector.
#
# Dependency direction:
#   4.features → mock_db (data)
#   4.features → geo_utils (utility)
#   4.features → hyperparams (config)
#   NO imports from 5.Profiling

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from mock_db import get_user_profile, get_user_events
from geo_utils import resolve_ip, get_distance_km, get_travel_speed_kmh
from datetime import datetime


def extract_features(event):
    """
    Takes one raw login event dict.
    Returns raw feature dict — no blending, no peer signals.

    Output keys:
        login_hour          — hour of day (0–23)
        failed_attempts     — failed attempts before this login
        new_device          — 1 if device_id not in user's known devices
        new_country         — 1 if country not in user's known countries
        ip_known            — 1 if IP in user's known IPs
        device_trust_score  — trust score for this device (0.0–1.0)
        hour_deviation      — distance from user's typical login hours
        distance_km         — km from last login location
        travel_speed_kmh    — km/h from last login (continuous, not binary)

    These raw signals are passed to Integration/processor.py
    which merges them with peer signals from 5.Profiling/cold_start.py
    """

    user_id  = event["user_id"]
    profile  = get_user_profile(user_id)

    # ── Basic event features ──────────────────────────────────────
    login_dt        = datetime.strptime(event["timestamp"], "%Y-%m-%d %H:%M:%S")
    login_hour      = login_dt.hour
    failed_attempts = event.get("failed_attempts", 0)

    # ── Individual profile signals ────────────────────────────────
    if profile:
        known_devices    = profile.get("known_devices", [])
        known_countries  = profile.get("known_countries", [])
        known_ips        = profile.get("known_ips", [])
        typical_hours    = profile.get("typical_login_hours", [])
        device_trust_map = profile.get("device_trust", {})

        new_device         = 0 if event["device_id"]  in known_devices   else 1
        new_country        = 0 if event["country"]    in known_countries  else 1
        ip_known           = 1 if event["ip_address"] in known_ips        else 0
        device_trust_score = device_trust_map.get(event["device_id"], 0.5)
        hour_deviation     = min(abs(login_hour - h) for h in typical_hours) if typical_hours else 0.0

    else:
        # No profile at all — treat everything as unknown
        new_device         = 1
        new_country        = 1
        ip_known           = 0
        device_trust_score = 0.5
        hour_deviation     = 0.0

    # ── Geo / travel signals ──────────────────────────────────────
    current_location = resolve_ip(
        event["ip_address"],
        fallback_city=event.get("location")
    )

    prior_events = [
        e for e in get_user_events(user_id)
        if e["timestamp"] < event["timestamp"] and e["event_id"] != event["event_id"]
    ]

    if prior_events:
        last_event    = max(prior_events, key=lambda e: e["timestamp"])
        last_location = resolve_ip(
            last_event["ip_address"],
            fallback_city=last_event.get("location")
        )
        last_time        = datetime.strptime(last_event["timestamp"], "%Y-%m-%d %H:%M:%S")
        hours_apart      = abs((login_dt - last_time).total_seconds() / 3600)
        distance_km      = get_distance_km(
            last_location.get("lat"), last_location.get("lon"),
            current_location.get("lat"), current_location.get("lon"),
        )
        travel_speed_kmh = get_travel_speed_kmh(distance_km, hours_apart)
    else:
        distance_km      = 0.0
        travel_speed_kmh = 0.0

    # ── Return raw feature dict ───────────────────────────────────
    return {
        "login_hour"        : login_hour,
        "failed_attempts"   : failed_attempts,
        "new_device"        : new_device,
        "new_country"       : new_country,
        "ip_known"          : ip_known,
        "device_trust_score": device_trust_score,
        "hour_deviation"    : hour_deviation,
        "distance_km"       : distance_km      if distance_km      is not None else 0.0,
        "travel_speed_kmh"  : travel_speed_kmh if travel_speed_kmh is not None else 0.0,
    }


# ─────────────────────────────────────────────
# QUICK TEST — python extractor.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from mock_db import LOGIN_EVENTS

    test_cases = [
        ("e003", "Normal login  — Kartik, office, known device"),
        ("e011", "Attack        — Kartik, London 3am, unknown device"),
        ("e013", "Travel        — Arjun, Singapore"),
        ("e014", "Cold start    — Sneha, first login"),
    ]

    for event_id, label in test_cases:
        event    = next(e for e in LOGIN_EVENTS if e["event_id"] == event_id)
        features = extract_features(event)
        print(f"\n{'─'*55}")
        print(f"  {label}")
        print(f"{'─'*55}")
        for k, v in features.items():
            print(f"  {k:<22} : {v}")