# mock_db.py
# Place this in your project root.
# This mimics exactly what PostgreSQL tables would return.
# When you wire up the real DB later, only this file changes.
# Everything else imports from here and stays untouched.

# ─────────────────────────────────────────────
# LOGIN EVENTS
# Represents the login_events table
# Each dict = one row
# ─────────────────────────────────────────────

LOGIN_EVENTS = [

    # ── NORMAL USERS ──────────────────────────────────────────────

    # Kartik — regular engineer, Bangalore, office hours
    {"event_id": "e001", "user_id": "u01", "timestamp": "2026-03-10 09:15:00", "ip_address": "10.0.1.45",  "location": "Bangalore",  "country": "India",  "device_id": "d_mac_01",  "device_type": "MacBook",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e002", "user_id": "u01", "timestamp": "2026-03-11 09:42:00", "ip_address": "10.0.1.45",  "location": "Bangalore",  "country": "India",  "device_id": "d_mac_01",  "device_type": "MacBook",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e003", "user_id": "u01", "timestamp": "2026-03-12 10:05:00", "ip_address": "10.0.1.45",  "location": "Bangalore",  "country": "India",  "device_id": "d_mac_01",  "device_type": "MacBook",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e004", "user_id": "u01", "timestamp": "2026-03-13 09:30:00", "ip_address": "10.0.1.45",  "location": "Bangalore",  "country": "India",  "device_id": "d_mac_01",  "device_type": "MacBook",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},

    # Priya — product manager, Mumbai, mix of mobile and desktop
    {"event_id": "e005", "user_id": "u02", "timestamp": "2026-03-10 10:20:00", "ip_address": "10.0.2.88",  "location": "Mumbai",     "country": "India",  "device_id": "d_iph_02",  "device_type": "iPhone",   "browser": "Safari",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e006", "user_id": "u02", "timestamp": "2026-03-11 11:00:00", "ip_address": "10.0.2.88",  "location": "Mumbai",     "country": "India",  "device_id": "d_lap_02",  "device_type": "Laptop",   "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e007", "user_id": "u02", "timestamp": "2026-03-12 09:55:00", "ip_address": "10.0.2.88",  "location": "Mumbai",     "country": "India",  "device_id": "d_iph_02",  "device_type": "iPhone",   "browser": "Safari",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},

    # Arjun — DevOps, Hyderabad, always uses company VPN
    {"event_id": "e008", "user_id": "u03", "timestamp": "2026-03-10 08:50:00", "ip_address": "10.0.3.12",  "location": "Hyderabad",  "country": "India",  "device_id": "d_lin_03",  "device_type": "Linux",    "browser": "Firefox", "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e009", "user_id": "u03", "timestamp": "2026-03-11 08:30:00", "ip_address": "10.0.3.12",  "location": "Hyderabad",  "country": "India",  "device_id": "d_lin_03",  "device_type": "Linux",    "browser": "Firefox", "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e010", "user_id": "u03", "timestamp": "2026-03-12 08:45:00", "ip_address": "10.0.3.12",  "location": "Hyderabad",  "country": "India",  "device_id": "d_lin_03",  "device_type": "Linux",    "browser": "Firefox", "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},

    # ── SUSPICIOUS / ATTACK EVENTS ────────────────────────────────

    # Kartik — sudden login from London, unknown device, 3am
    {"event_id": "e011", "user_id": "u01", "timestamp": "2026-03-14 03:22:00", "ip_address": "82.45.12.99", "location": "London",     "country": "UK",     "device_id": "d_unk_99",  "device_type": "Windows",  "browser": "Edge",    "login_success": True,  "failed_attempts": 3, "mfa_triggered": True,  "mfa_result": "fail"},

    # Priya — login from US, new device, multiple failures
    {"event_id": "e012", "user_id": "u02", "timestamp": "2026-03-14 14:10:00", "ip_address": "192.168.99.1","location": "New York",   "country": "USA",    "device_id": "d_unk_88",  "device_type": "Windows",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 5, "mfa_triggered": True,  "mfa_result": "fail"},

    # Arjun — impossible travel (Hyderabad at 8am, Singapore at 9am same day)
    {"event_id": "e013", "user_id": "u03", "timestamp": "2026-03-13 09:10:00", "ip_address": "203.0.113.5", "location": "Singapore",  "country": "Singapore", "device_id": "d_lin_03", "device_type": "Linux",   "browser": "Firefox", "login_success": True,  "failed_attempts": 0, "mfa_triggered": True,  "mfa_result": "pass"},

    # ── NEW USER — COLD START ──────────────────────────────────────

    # Sneha — joined yesterday, no history, first logins
    {"event_id": "e014", "user_id": "u04", "timestamp": "2026-03-13 10:00:00", "ip_address": "10.0.1.50",  "location": "Bangalore",  "country": "India",  "device_id": "d_mac_04",  "device_type": "MacBook",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
    {"event_id": "e015", "user_id": "u04", "timestamp": "2026-03-14 09:45:00", "ip_address": "10.0.1.50",  "location": "Bangalore",  "country": "India",  "device_id": "d_mac_04",  "device_type": "MacBook",  "browser": "Chrome",  "login_success": True,  "failed_attempts": 0, "mfa_triggered": False, "mfa_result": None},
]


# ─────────────────────────────────────────────
# USER PROFILES
# Represents the user_profiles table
# Baseline behavior per user built from history
# ─────────────────────────────────────────────

USER_PROFILES = {
    "u01": {
        "user_id": "u01",
        "name": "Kartik",
        "department": "Engineering",
        "role": "Software Engineer",
        "office": "Bangalore",
        "total_events": 104,             # enough for mature phase
        "typical_login_hours": [8, 9, 10, 11],
        "known_devices": ["d_mac_01"],
        "known_countries": ["India"],
        "known_ips": ["10.0.1.45"],
        "avg_failed_attempts": 0.1,
        "device_trust": {"d_mac_01": 0.95},
        "peer_cluster_id": "cluster_eng_blr",
    },
    "u02": {
        "user_id": "u02",
        "name": "Priya",
        "department": "Product",
        "role": "Product Manager",
        "office": "Mumbai",
        "total_events": 87,
        "typical_login_hours": [9, 10, 11, 12],
        "known_devices": ["d_iph_02", "d_lap_02"],
        "known_countries": ["India"],
        "known_ips": ["10.0.2.88"],
        "avg_failed_attempts": 0.2,
        "device_trust": {"d_iph_02": 0.9, "d_lap_02": 0.85},
        "peer_cluster_id": "cluster_prod_mum",
    },
    "u03": {
        "user_id": "u03",
        "name": "Arjun",
        "department": "DevOps",
        "role": "DevOps Engineer",
        "office": "Hyderabad",
        "total_events": 201,
        "typical_login_hours": [8, 9],
        "known_devices": ["d_lin_03"],
        "known_countries": ["India"],
        "known_ips": ["10.0.3.12"],
        "avg_failed_attempts": 0.0,
        "device_trust": {"d_lin_03": 0.99},
        "peer_cluster_id": "cluster_devops_hyd",
    },
    "u04": {
        "user_id": "u04",
        "name": "Sneha",
        "department": "Engineering",
        "role": "Software Engineer",
        "office": "Bangalore",
        "total_events": 2,               # cold start — only 2 events so far
        "typical_login_hours": [],       # not enough data yet
        "known_devices": ["d_mac_04"],
        "known_countries": ["India"],
        "known_ips": ["10.0.1.50"],
        "avg_failed_attempts": 0.0,
        "device_trust": {"d_mac_04": 0.5},
        "peer_cluster_id": "cluster_eng_blr",  # assigned to peer cluster immediately
    },
}


# ─────────────────────────────────────────────
# PEER CLUSTERS
# Represents the peer_clusters table
# Behavioral norms per cluster
# ─────────────────────────────────────────────

PEER_CLUSTERS = {
    "cluster_eng_blr": {
        "cluster_id": "cluster_eng_blr",
        "label": "Engineering — Bangalore",
        "member_user_ids": ["u01", "u04"],
        "common_login_hours": [8, 9, 10, 11],
        "common_countries": ["India"],
        "common_ip_subnets": ["10.0.1."],
        "common_device_types": ["MacBook", "Linux"],
        "avg_failed_attempts": 0.1,
    },
    "cluster_prod_mum": {
        "cluster_id": "cluster_prod_mum",
        "label": "Product — Mumbai",
        "member_user_ids": ["u02"],
        "common_login_hours": [9, 10, 11, 12],
        "common_countries": ["India"],
        "common_ip_subnets": ["10.0.2."],
        "common_device_types": ["iPhone", "Laptop"],
        "avg_failed_attempts": 0.2,
    },
    "cluster_devops_hyd": {
        "cluster_id": "cluster_devops_hyd",
        "label": "DevOps — Hyderabad",
        "member_user_ids": ["u03"],
        "common_login_hours": [8, 9],
        "common_countries": ["India"],
        "common_ip_subnets": ["10.0.3."],
        "common_device_types": ["Linux"],
        "avg_failed_attempts": 0.0,
    },
}


# ─────────────────────────────────────────────
# CATEGORY ENCODING REGISTRIES
# Represents org lookup tables — in production
# these are populated from Okta / HR system
# before any user ever logs in.
#
# Key   = string value from user profile
# Value = numeric index used in k-means clustering
#
# If an unknown value arrives (should not happen
# with clean Okta data) the encoding helpers below
# dynamically assign the next available index and
# log a warning.
# ─────────────────────────────────────────────

DEPARTMENT_REGISTRY = {
    "Engineering" : 0,
    "Product"     : 1,
    "DevOps"      : 2,
    "Design"      : 3,
    "Sales"       : 4,
    "Finance"     : 5,
    "HR"          : 6,
    "Security"    : 7,
}

ROLE_REGISTRY = {
    "Software Engineer"  : 0,
    "Senior Engineer"    : 1,
    "DevOps Engineer"    : 2,
    "Product Manager"    : 3,
    "Designer"           : 4,
    "Sales Executive"    : 5,
    "Finance Analyst"    : 6,
    "HR Manager"         : 7,
    "Security Analyst"   : 8,
}

OFFICE_REGISTRY = {
    "Bangalore"  : 0,
    "Mumbai"     : 1,
    "Hyderabad"  : 2,
    "Delhi"      : 3,
    "London"     : 4,
    "New York"   : 5,
    "Singapore"  : 6,
    "Dubai"      : 7,
}


# ─────────────────────────────────────────────
# FEEDBACK LABELS
# Represents the feedback_labels table
# Admin decisions and MFA outcomes on past events
# ─────────────────────────────────────────────

FEEDBACK_LABELS = [
    {"event_id": "e011", "label": "attack",    "source": "mfa_fail",      "notes": "MFA failed, likely account takeover"},
    {"event_id": "e012", "label": "attack",    "source": "mfa_fail",      "notes": "MFA failed, new country + device"},
    {"event_id": "e013", "label": "legitimate","source": "admin_approve",  "notes": "Confirmed business travel to Singapore"},
]


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# Mimic what DB query functions would return
# When you add PostgreSQL, replace these functions only
# ─────────────────────────────────────────────

def get_user_profile(user_id):
    return USER_PROFILES.get(user_id, None)

def get_peer_cluster(cluster_id):
    return PEER_CLUSTERS.get(cluster_id, None)

def get_user_events(user_id):
    return [e for e in LOGIN_EVENTS if e["user_id"] == user_id]

def get_event_by_id(event_id):
    return next((e for e in LOGIN_EVENTS if e["event_id"] == event_id), None)

def get_feedback_for_event(event_id):
    return next((f for f in FEEDBACK_LABELS if f["event_id"] == event_id), None)


def get_dept_encoding(department):
    """
    Returns numeric encoding for a department.
    Primary path   — lookup in DEPARTMENT_REGISTRY (Okta data, always present)
    Fallback path  — dynamic assignment if somehow missing, logs a warning
    When PostgreSQL arrives, replace with: SELECT id FROM departments WHERE name = %s
    """
    if department in DEPARTMENT_REGISTRY:
        return DEPARTMENT_REGISTRY[department]
    new_index = max(DEPARTMENT_REGISTRY.values()) + 1
    DEPARTMENT_REGISTRY[department] = new_index
    print(f"[WARN] Unknown department '{department}' — dynamically assigned index {new_index}")
    return new_index


def get_role_encoding(role):
    """
    Returns numeric encoding for a role.
    Primary path   — lookup in ROLE_REGISTRY
    Fallback path  — dynamic assignment with warning
    """
    if role in ROLE_REGISTRY:
        return ROLE_REGISTRY[role]
    new_index = max(ROLE_REGISTRY.values()) + 1
    ROLE_REGISTRY[role] = new_index
    print(f"[WARN] Unknown role '{role}' — dynamically assigned index {new_index}")
    return new_index


def get_office_encoding(office):
    """
    Returns numeric encoding for an office location.
    Primary path   — lookup in OFFICE_REGISTRY
    Fallback path  — dynamic assignment with warning
    """
    if office in OFFICE_REGISTRY:
        return OFFICE_REGISTRY[office]
    new_index = max(OFFICE_REGISTRY.values()) + 1
    OFFICE_REGISTRY[office] = new_index
    print(f"[WARN] Unknown office '{office}' — dynamically assigned index {new_index}")
    return new_index