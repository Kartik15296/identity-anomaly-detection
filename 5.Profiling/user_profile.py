# 5.Profiling/user_profile.py
# Manages individual user behavioral baselines.
# All reads come from mock_db (later PostgreSQL).
# All writes update the in-memory mock_db dict (later DB UPDATE queries).
#
# This file has no ML — pure profile read/write logic.
# Called by cold_start.py and extractor.py

import sys
import os
from hyperparams import register_paths
register_paths()

from mock_db import USER_PROFILES
from hyperparams import TRUST, CLUSTERING

# ─────────────────────────────────────────────
# DEVICE TRUST SETTINGS — loaded from 1.config/hyperparams.py
# Tweak values there, not here.
# ─────────────────────────────────────────────
TRUST_MFA_PASS_BOOST      = TRUST["MFA_PASS_BOOST"]
TRUST_ADMIN_APPROVE_BOOST = TRUST["ADMIN_APPROVE_BOOST"]
TRUST_MFA_FAIL_DECAY      = TRUST["MFA_FAIL_DECAY"]
TRUST_ADMIN_BLOCK_DECAY   = TRUST["ADMIN_BLOCK_DECAY"]
TRUST_MAX                 = TRUST["MAX"]
TRUST_MIN                 = TRUST["MIN"]
TRUST_DEFAULT             = TRUST["DEFAULT"]
LOGIN_HOUR_WINDOW         = TRUST["LOGIN_HOUR_WINDOW"]


# ─────────────────────────────────────────────
# READ FUNCTIONS
# ─────────────────────────────────────────────

def get_profile(user_id):
    """
    Returns the full profile dict for a user.
    Returns None if user not found.
    """
    return USER_PROFILES.get(user_id, None)


def is_known_device(profile, device_id):
    """
    Returns True if device_id is in user's known devices list.
    """
    if not profile:
        return False
    return device_id in profile.get("known_devices", [])


def is_known_country(profile, country):
    """
    Returns True if country is in user's known countries list.
    """
    if not profile:
        return False
    return country in profile.get("known_countries", [])


def is_known_ip(profile, ip_address):
    """
    Returns True if IP is in user's known IPs list.
    """
    if not profile:
        return False
    return ip_address in profile.get("known_ips", [])


def get_hour_deviation(profile, login_hour):
    """
    Returns how far the current login hour is from the user's typical hours.
    Takes the minimum distance to any typical hour.

    Example:
        typical_hours = [8, 9, 10]
        login_hour    = 14
        deviation     = min(|14-8|, |14-9|, |14-10|) = 4

    Returns 0.0 if no typical hours recorded yet (cold start).
    """
    if not profile:
        return 0.0

    typical_hours = profile.get("typical_login_hours", [])
    if not typical_hours:
        return 0.0

    return float(min(abs(login_hour - h) for h in typical_hours))


def get_device_trust(profile, device_id):
    """
    Returns trust score for a specific device (0.0 to 1.0).
    Returns TRUST_DEFAULT (0.5) for unknown/new devices.
    """
    if not profile:
        return TRUST_DEFAULT

    trust_map = profile.get("device_trust", {})
    return trust_map.get(device_id, TRUST_DEFAULT)


# ─────────────────────────────────────────────
# WRITE FUNCTIONS
# These update the in-memory profile.
# When PostgreSQL is added, these become UPDATE queries.
# ─────────────────────────────────────────────

def update_device_trust(profile, device_id, outcome):
    """
    Adjusts device trust using exponential decay model.

    Trust gain  — diminishing returns:
        boost = BASE_BOOST × (1 - current_trust)
        Already trusted devices gain almost nothing from another pass.
        Low trust devices grow faster but never jump suddenly.

    Trust loss  — proportional decay:
        new_trust = current_trust × DECAY_FACTOR
        A highly trusted device loses more in absolute terms.
        A low trust device is pushed closer to zero.
        Admin block is severe — near zero regardless of history.

    outcome options:
        "mfa_pass"      → small diminishing gain
        "mfa_fail"      → 50% decay — significant hit
        "admin_approve" → moderate diminishing gain
        "admin_block"   → 90% decay — near zero, severe

    Examples at trust = 0.90:
        mfa_pass    → 0.90 + 0.05 × 0.10 = 0.905
        mfa_fail    → 0.90 × 0.50        = 0.450
        admin_block → 0.90 × 0.10        = 0.090

    Examples at trust = 0.30:
        mfa_pass    → 0.30 + 0.05 × 0.70 = 0.335
        mfa_fail    → 0.30 × 0.50        = 0.150
        admin_block → 0.30 × 0.10        = 0.030
    """
    if not profile:
        return

    if "device_trust" not in profile:
        profile["device_trust"] = {}

    current_trust = profile["device_trust"].get(device_id, TRUST_DEFAULT)

    if outcome == "mfa_pass":
        # Diminishing returns — room to grow shrinks as trust increases
        new_trust = current_trust + TRUST_MFA_PASS_BOOST * (1 - current_trust)

    elif outcome == "admin_approve":
        # Slightly stronger boost than MFA pass, same diminishing logic
        new_trust = current_trust + TRUST_ADMIN_APPROVE_BOOST * (1 - current_trust)

    elif outcome == "mfa_fail":
        # Proportional decay — cuts trust in half regardless of starting point
        new_trust = current_trust * TRUST_MFA_FAIL_DECAY

    elif outcome == "admin_block":
        # Severe decay — near zero, device is considered compromised
        new_trust = current_trust * TRUST_ADMIN_BLOCK_DECAY

    else:
        return  # unknown outcome, do nothing

    profile["device_trust"][device_id] = round(
        max(TRUST_MIN, min(TRUST_MAX, new_trust)), 4
    )


def add_known_device(profile, device_id):
    """
    Adds a device to the user's known devices list.
    Called after admin approves a login from a new device.
    Initializes trust at TRUST_DEFAULT if not already tracked.
    """
    if not profile:
        return

    if "known_devices" not in profile:
        profile["known_devices"] = []

    if device_id not in profile["known_devices"]:
        profile["known_devices"].append(device_id)

    if "device_trust" not in profile:
        profile["device_trust"] = {}

    if device_id not in profile["device_trust"]:
        profile["device_trust"][device_id] = TRUST_DEFAULT


def add_known_country(profile, country):
    """
    Adds a country to the user's known countries list.
    Called after admin confirms legitimate travel.
    """
    if not profile:
        return

    if "known_countries" not in profile:
        profile["known_countries"] = []

    if country not in profile["known_countries"]:
        profile["known_countries"].append(country)


def add_known_ip(profile, ip_address):
    """
    Adds an IP to the user's known IPs list.
    Called after confirmed legitimate login from a new IP.
    """
    if not profile:
        return

    if "known_ips" not in profile:
        profile["known_ips"] = []

    if ip_address not in profile["known_ips"]:
        profile["known_ips"].append(ip_address)


def update_login_hours(profile, login_hour, current_timestamp=None):
    """
    Updates the user's typical login hours using exponential time-decay.

    Instead of a simple deduped set, we maintain a weighted frequency
    map: { hour -> weight } where weight decays over time.

    On each legitimate login:
        1. Apply decay to all existing hour weights based on time elapsed.
        2. Add 1.0 to the weight of the current login hour.
        3. Drop any hours whose weight has fallen below HOUR_DECAY_MIN_WEIGHT.
        4. Update the flat list in typical_login_hours for backward compat.

    This means:
        - A user who used to log in at 3am but switched to 9am will
          gradually lose the 3am signal instead of keeping it forever.
        - The transition happens over weeks, not overnight.
        - Sudden schedule changes (after travel, after changing roles)
          adapt naturally without manual intervention.

    Called after every confirmed legitimate login.
    """
    if not profile:
        return

    decay_factor  = CLUSTERING["HOUR_DECAY_FACTOR"]
    min_weight    = CLUSTERING["HOUR_DECAY_MIN_WEIGHT"]

    from datetime import datetime, timezone

    # Parse current timestamp or use now
    if current_timestamp:
        try:
            now = datetime.strptime(current_timestamp, "%Y-%m-%d %H:%M:%S")
        except Exception:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Load existing weighted hour map
    # Format: { "9": {"weight": 0.85, "last_seen": "2026-03-12 09:00:00"} }
    hour_weights = profile.get("login_hour_weights", {})

    # Apply time-decay to all existing entries
    surviving = {}
    for h_str, entry in hour_weights.items():
        last_seen_str = entry.get("last_seen", "2026-01-01 00:00:00")
        try:
            last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            last_seen = now
        hours_elapsed = max(0, (now - last_seen).total_seconds() / 3600)
        decayed = entry["weight"] * (decay_factor ** hours_elapsed)
        if decayed >= min_weight:
            surviving[h_str] = {"weight": round(decayed, 4), "last_seen": last_seen_str}

    # Add current login hour
    h_key = str(login_hour)
    current_weight = surviving.get(h_key, {}).get("weight", 0.0)
    surviving[h_key] = {
        "weight"   : round(min(current_weight + 1.0, 10.0), 4),  # cap at 10
        "last_seen": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    profile["login_hour_weights"] = surviving

    # Keep flat list in sync for all downstream code that reads typical_login_hours
    profile["typical_login_hours"] = sorted(int(h) for h in surviving.keys())


def increment_event_count(profile):
    """
    Increments total_events counter after each confirmed login.
    This moves the user toward mature phase over time.
    """
    if not profile:
        return

    profile["total_events"] = profile.get("total_events", 0) + 1


# ─────────────────────────────────────────────
# QUICK TEST — python user_profile.py
# ─────────────────────────────────────────────
if __name__ == "__main__":

    print("── Read operations ───────────────────────────────────")
    profile = get_profile("u01")
    print(f"User            : {profile['name']}")
    print(f"Known device    : {is_known_device(profile, 'd_mac_01')}")
    print(f"Unknown device  : {is_known_device(profile, 'd_unk_99')}")
    print(f"Known country   : {is_known_country(profile, 'India')}")
    print(f"Unknown country : {is_known_country(profile, 'UK')}")
    print(f"Hour deviation (login at 10am) : {get_hour_deviation(profile, 10)}")
    print(f"Hour deviation (login at 3am)  : {get_hour_deviation(profile, 3)}")
    print(f"Device trust (known)   : {get_device_trust(profile, 'd_mac_01')}")
    print(f"Device trust (unknown) : {get_device_trust(profile, 'd_unk_99')}")

    print("\n── Trust updates — exponential decay model ───────────")
    profile = get_profile("u01")  # reset to fresh profile

    print(f"\n  Starting trust (well trusted device): {get_device_trust(profile, 'd_mac_01')}")

    print("\n  -- 5 consecutive MFA passes (diminishing returns) --")
    for i in range(5):
        update_device_trust(profile, "d_mac_01", "mfa_pass")
        print(f"  After pass {i+1}: {get_device_trust(profile, 'd_mac_01')}")

    print("\n  -- Single MFA fail (proportional decay) --")
    update_device_trust(profile, "d_mac_01", "mfa_fail")
    print(f"  After fail  : {get_device_trust(profile, 'd_mac_01')}")

    print("\n  -- Admin block (severe decay) --")
    update_device_trust(profile, "d_mac_01", "admin_block")
    print(f"  After block : {get_device_trust(profile, 'd_mac_01')}")

    print("\n  -- New unknown device (starts at 0.5) --")
    print(f"  New device trust    : {get_device_trust(profile, 'd_unk_99')}")
    update_device_trust(profile, "d_unk_99", "mfa_fail")
    print(f"  After single fail   : {get_device_trust(profile, 'd_unk_99')}")
    update_device_trust(profile, "d_unk_99", "admin_block")
    print(f"  After admin block   : {get_device_trust(profile, 'd_unk_99')}")

    print("\n── Adding new device after admin approve ─────────────")
    print(f"Known devices before : {profile['known_devices']}")
    add_known_device(profile, "d_new_05")
    print(f"Known devices after  : {profile['known_devices']}")
    print(f"Trust for new device : {get_device_trust(profile, 'd_new_05')}")

    print("\n── Adding new country after travel confirmed ─────────")
    print(f"Known countries before : {profile['known_countries']}")
    add_known_country(profile, "UK")
    print(f"Known countries after  : {profile['known_countries']}")

    print("\n── Event count and login hours ───────────────────────")
    print(f"Total events before : {profile['total_events']}")
    increment_event_count(profile)
    print(f"Total events after  : {profile['total_events']}")
    print(f"Typical hours before : {profile['typical_login_hours']}")
    update_login_hours(profile, 14)
    print(f"Typical hours after  : {profile['typical_login_hours']}")