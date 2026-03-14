# 8.feedback/profile_updater.py
# Updates user behavioral baseline after a confirmed feedback outcome.
# Called by label_collector.py after every labeled event.
#
# What gets updated per outcome:
#   legitimate → add device/country/ip to known lists, update trust, update hours
#   attack     → penalize device trust, do NOT add anything to known lists

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from mock_db import get_user_profile
from user_profile import (
    update_device_trust,
    add_known_device,
    add_known_country,
    add_known_ip,
    update_login_hours,
    increment_event_count,
)


def update_profile_from_feedback(event, outcome, label):
    """
    Updates user profile based on feedback outcome.

    event   : raw login event dict
    outcome : "mfa_pass" | "mfa_fail" | "admin_approve" | "admin_block"
    label   : "legitimate" | "attack"
    """
    user_id = event["user_id"]
    profile = get_user_profile(user_id)

    if not profile:
        print(f"[WARN] No profile found for user {user_id} — skipping update")
        return

    device_id  = event.get("device_id")
    country    = event.get("country")
    ip_address = event.get("ip_address")
    login_hour = int(event.get("timestamp", "2026-01-01 09:00:00").split(" ")[1].split(":")[0])

    if label == "legitimate":
        _handle_legitimate(profile, device_id, country, ip_address, login_hour, outcome)
    elif label == "attack":
        _handle_attack(profile, device_id, outcome)

    print(f"[PROFILE] Updated profile for user={user_id} outcome={outcome}")


def _handle_legitimate(profile, device_id, country, ip_address, login_hour, outcome):
    """
    Confirmed legitimate login — expand user's known baseline.

    Updates:
        device trust  — boost (diminishing returns via exponential model)
        known devices — add if new
        known country — add if new
        known IP      — add if new
        login hours   — rolling update
        event count   — increment (moves user toward mature phase)
    """
    # Boost device trust
    update_device_trust(profile, device_id, outcome)

    # Expand known lists — this device/country/IP is now confirmed safe
    add_known_device(profile, device_id)
    add_known_country(profile, country)
    add_known_ip(profile, ip_address)

    # Update typical login hours
    update_login_hours(profile, login_hour)

    # Increment event count — moves cold start users toward mature phase
    increment_event_count(profile)


def _handle_attack(profile, device_id, outcome):
    """
    Confirmed attack — penalize device trust only.
    Do NOT add device/country/IP to known lists.
    Do NOT update login hours or event count.
    Attacker's patterns should not pollute the user's baseline.
    """
    update_device_trust(profile, device_id, outcome)


def bulk_update_from_labels(feedback_labels):
    """
    Processes a list of feedback labels in bulk.
    Used by retrain_scheduler when replaying historical labels.

    feedback_labels : list of feedback dicts from label_collector
    """
    from mock_db import get_event_by_id

    updated = 0
    skipped = 0

    for fb in feedback_labels:
        event = get_event_by_id(fb.get("event_id"))
        if not event:
            skipped += 1
            continue

        update_profile_from_feedback(event, fb["source"], fb["label"])
        updated += 1

    print(f"[PROFILE] Bulk update complete — updated={updated} skipped={skipped}")
    return updated, skipped


# ─────────────────────────────────────────────
# QUICK TEST — python profile_updater.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from mock_db import USER_PROFILES, get_event_by_id

    print("── Before updates ────────────────────────────────────")
    profile = get_user_profile("u01")
    print(f"  Kartik known devices  : {profile['known_devices']}")
    print(f"  Kartik known countries: {profile['known_countries']}")
    print(f"  Kartik total events   : {profile['total_events']}")
    print(f"  Kartik device trust   : {profile['device_trust']}")

    # Simulate: Arjun Singapore travel confirmed legitimate by admin
    event = get_event_by_id("e013")
    print("\n── Admin approve — Arjun Singapore travel ────────────")
    update_profile_from_feedback(event, "admin_approve", "legitimate")
    arjun = get_user_profile("u03")
    print(f"  Arjun known countries : {arjun['known_countries']}")
    print(f"  Arjun device trust    : {arjun['device_trust']}")
    print(f"  Arjun total events    : {arjun['total_events']}")

    # Simulate: Kartik London attack confirmed by admin block
    event = get_event_by_id("e011")
    print("\n── Admin block — Kartik London attack ────────────────")
    trust_before = profile["device_trust"].get("d_unk_99", 0.5)
    update_profile_from_feedback(event, "admin_block", "attack")
    trust_after = profile["device_trust"].get("d_unk_99", 0.5)
    print(f"  Attack device trust before : {trust_before}")
    print(f"  Attack device trust after  : {trust_after}")
    print(f"  Kartik known devices (attack device NOT added): {profile['known_devices']}")