# 5.Profiling/peer_cluster.py
# Manages peer group behavioral clusters.
# Two clear modes — read mode (fast, called per login) and
# rebuild mode (slow, called weekly by retrain scheduler).
#
# Read mode  : looks up cluster stats, computes peer deviation score
# Rebuild mode : runs k-means on behavioral features, reassigns users

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

import math
from mock_db import (
    PEER_CLUSTERS,
    USER_PROFILES,
    get_dept_encoding,
    get_role_encoding,
    get_office_encoding,
)
from hyperparams import CLUSTERING


# ─────────────────────────────────────────────
# ── READ MODE FUNCTIONS ───────────────────────
# Fast. Called during every login event.
# Never triggers k-means or any heavy computation.
# ─────────────────────────────────────────────

def get_cluster(cluster_id):
    """
    Returns the full cluster dict for a given cluster_id.
    Returns None if cluster not found.
    """
    return PEER_CLUSTERS.get(cluster_id, None)


def get_user_cluster(user_id):
    """
    Returns the cluster a user belongs to.
    Returns None if:
        - user not found
        - user has no cluster assigned
        - user is a DBSCAN outlier (cluster_outlier)
          → caller should treat as no peer group available
    """
    profile = USER_PROFILES.get(user_id)
    if not profile:
        return None

    cluster_id = profile.get("peer_cluster_id")
    if not cluster_id:
        return None

    # Outlier users have no meaningful peer group
    if cluster_id == CLUSTERING["OUTLIER_CLUSTER_ID"]:
        return None

    return PEER_CLUSTERS.get(cluster_id)


def is_common_device_type(cluster, device_type):
    """
    Returns True if device_type is common in this cluster.
    """
    if not cluster:
        return False
    return device_type in cluster.get("common_device_types", [])


def is_common_country(cluster, country):
    """
    Returns True if country is common in this cluster.
    """
    if not cluster:
        return False
    return country in cluster.get("common_countries", [])


def is_common_ip_subnet(cluster, ip_address):
    """
    Returns True if IP matches any common subnet in this cluster.
    """
    if not cluster:
        return False
    subnets = cluster.get("common_ip_subnets", [])
    return any(ip_address.startswith(subnet) for subnet in subnets)


def get_cluster_typical_hours(cluster):
    """
    Returns list of typical login hours for this cluster.
    """
    if not cluster:
        return []
    return cluster.get("common_login_hours", [])


def get_cluster_members(cluster_id):
    """
    Returns list of user_ids in this cluster.
    """
    cluster = PEER_CLUSTERS.get(cluster_id)
    if not cluster:
        return []
    return cluster.get("member_user_ids", [])


def compute_peer_deviation_score(feature_vector, cluster, user_id=None):
    """
    Computes how much a user's current login deviates from
    their peer cluster's behavioral norms.

    Uses a simplified Mahalanobis-style distance — compares
    each signal against cluster norms and aggregates deviation.

    Returns a score between 0.0 and 1.0:
        0.0 → perfectly matches cluster norms
        1.0 → completely unlike the cluster

    Signals compared:
        Behavioral:
            - login_hour vs cluster typical hours
            - device_type match
            - country match
            - ip subnet match
            - failed_attempts vs cluster avg
        Org attributes (NEW):
            - department match vs cluster common departments
            - role match vs cluster common roles
            - office match vs cluster common offices

    Org signals carry lower weight than behavioral signals
    because org attributes change rarely (promotions, transfers)
    and should not dominate the deviation score on their own.
    """
    if not cluster or not feature_vector:
        return 0.5

    behavioral_deviations = []
    org_deviations        = []

    # ── Login hour deviation ──────────────────────────────────────
    cluster_hours = cluster.get("common_login_hours", [])
    if cluster_hours:
        login_hour    = feature_vector.get("login_hour", 12)
        hour_dev      = min(abs(login_hour - h) for h in cluster_hours)
        hour_dev_norm = min(hour_dev / CLUSTERING["HOUR_DEVIATION_MAX"], 1.0)
        behavioral_deviations.append(hour_dev_norm)

    # ── Device type mismatch ──────────────────────────────────────
    peer_device_match = feature_vector.get("peer_device_match", 0)
    behavioral_deviations.append(0.0 if peer_device_match else 1.0)

    # ── Country mismatch ──────────────────────────────────────────
    peer_country_match = feature_vector.get("peer_country_match", 0)
    behavioral_deviations.append(0.0 if peer_country_match else 1.0)

    # ── IP subnet mismatch ────────────────────────────────────────
    peer_ip_match = feature_vector.get("peer_ip_match", 0)
    behavioral_deviations.append(0.0 if peer_ip_match else 1.0)

    # ── Failed attempts vs cluster avg ────────────────────────────
    cluster_avg_fails = cluster.get("avg_failed_attempts", 0.0)
    current_fails     = feature_vector.get("failed_attempts", 0)
    fail_norm         = min(abs(current_fails - cluster_avg_fails) / CLUSTERING["FAILED_ATTEMPTS_MAX"], 1.0)
    behavioral_deviations.append(fail_norm)

    # ── Org attribute deviations (NEW) ────────────────────────────
    # Pull user's org attributes from their profile if user_id provided
    # Otherwise fall back to feature_vector if caller passed them in
    if user_id and user_id in USER_PROFILES:
        profile    = USER_PROFILES[user_id]
        department = profile.get("department", None)
        role       = profile.get("role", None)
        office     = profile.get("office", None)
    else:
        # Caller can pass org fields directly in feature_vector
        department = feature_vector.get("department", None)
        role       = feature_vector.get("role", None)
        office     = feature_vector.get("office", None)

    # Department mismatch
    common_depts = cluster.get("common_departments", [])
    if department and common_depts:
        org_deviations.append(0.0 if department in common_depts else 1.0)

    # Role mismatch
    common_roles = cluster.get("common_roles", [])
    if role and common_roles:
        org_deviations.append(0.0 if role in common_roles else 1.0)

    # Office mismatch
    common_offices = cluster.get("common_offices", [])
    if office and common_offices:
        org_deviations.append(0.0 if office in common_offices else 1.0)

    # ── Weighted aggregate ────────────────────────────────────────
    # Behavioral signals carry 80% weight — org signals carry 20%
    # Org attributes change rarely so they shouldn't dominate
    # But a completely mismatched org profile is still a signal
    behavioral_score = sum(behavioral_deviations) / len(behavioral_deviations) if behavioral_deviations else 0.5
    org_score        = sum(org_deviations)        / len(org_deviations)        if org_deviations        else 0.0

    final_score = round(
        CLUSTERING["PEER_DEV_BEHAVIORAL_WEIGHT"] * behavioral_score +
        CLUSTERING["PEER_DEV_ORG_WEIGHT"]        * org_score,
        3
    )
    return final_score


# ─────────────────────────────────────────────
# ── REBUILD MODE FUNCTIONS ────────────────────
# Slow. Called weekly by 8.feedback/retrain_scheduler.py
# NEVER called during a live login scoring request.
# ─────────────────────────────────────────────

def _build_user_feature_vector(user_id):
    """
    Builds behavioral + org feature vector for a user
    for the purpose of k-means clustering.

    Behavioral features (what the user does):
        avg_login_hour  — average hour of day they log in
        n_devices       — how many devices they use
        total_events    — how active they are

    Org features (who the user is — from Okta):
        dept_encoded    — department as numeric index
        role_encoded    — role as numeric index
        office_encoded  — office location as numeric index

    All features are normalized to 0–1 before clustering
    so no single feature dominates the distance calculation.
    Normalization ranges defined in _NORM_RANGES below.
    """
    profile = USER_PROFILES.get(user_id)
    if not profile:
        return None

    typical_hours = profile.get("typical_login_hours", [])
    avg_hour      = sum(typical_hours) / len(typical_hours) if typical_hours else 12.0
    n_devices     = len(profile.get("known_devices", []))
    total_events  = profile.get("total_events", 0)

    # Org attributes — encoded via registry
    dept_encoded   = get_dept_encoding(profile.get("department", "Unknown"))
    role_encoded   = get_role_encoding(profile.get("role", "Unknown"))
    office_encoded = get_office_encoding(profile.get("office", "Unknown"))

    return {
        "user_id"       : user_id,
        # Raw values — normalized inside rebuild_clusters before k-means
        "avg_login_hour": avg_hour,
        "n_devices"     : n_devices,
        "total_events"  : total_events,
        "dept_encoded"  : dept_encoded,
        "role_encoded"  : role_encoded,
        "office_encoded": office_encoded,
    }


# Normalization ranges — loaded from 1.config/hyperparams.py
# Tweak values there, not here.
_NORM_RANGES = CLUSTERING["NORM_RANGES"]


def _normalize_vector(vec, keys):
    """
    Normalizes feature values to 0–1 range using _NORM_RANGES.
    Returns a new dict with normalized values.
    Clips values outside the defined range to 0 or 1.
    """
    normalized = {}
    for key in keys:
        if key not in vec:
            normalized[key] = 0.0
            continue
        min_val, max_val = _NORM_RANGES.get(key, (0, 1))
        if max_val == min_val:
            normalized[key] = 0.0
        else:
            normalized[key] = max(0.0, min(1.0, (vec[key] - min_val) / (max_val - min_val)))
    return normalized


def _euclidean_distance(vec1, vec2, keys):
    """Simple euclidean distance between two dicts on given keys."""
    return math.sqrt(sum((vec1[k] - vec2[k]) ** 2 for k in keys if k in vec1 and k in vec2))


def rebuild_clusters():
    """
    Runs DBSCAN clustering on all user behavioral + org feature vectors.
    Replaces k-means — no need to specify n_clusters upfront.

    Called weekly by 8.feedback/retrain_scheduler — never during live scoring.

    Why DBSCAN over k-means:
        - Discovers number of clusters automatically
        - Users who don't fit any cluster become outliers (cluster_outlier)
        - Handles clusters of unequal size and arbitrary shape
        - Outlier label is meaningful — those users get full individual profiling

    Steps:
        1. Build feature vectors for all users (behavioral + org)
        2. Normalize all features to 0–1 range
        3. Run DBSCAN using eps and min_samples from hyperparams
        4. Users labeled -1 by DBSCAN → assigned to OUTLIER_CLUSTER_ID
        5. Update PEER_CLUSTERS and USER_PROFILES in memory

    Hyperparams used (from 1.config/hyperparams.py):
        CLUSTERING["DBSCAN_EPS"]         — neighborhood radius
        CLUSTERING["DBSCAN_MIN_SAMPLES"] — min users to form a cluster
        CLUSTERING["OUTLIER_CLUSTER_ID"] — label for unclassified users
    """
    from sklearn.cluster import DBSCAN
    import numpy as np

    CLUSTER_KEYS = [
        "avg_login_hour",
        "n_devices",
        "total_events",
        "dept_encoded",
        "role_encoded",
        "office_encoded",
    ]

    eps         = CLUSTERING["DBSCAN_EPS"]
    min_samples = CLUSTERING["DBSCAN_MIN_SAMPLES"]
    outlier_id  = CLUSTERING["OUTLIER_CLUSTER_ID"]

    # ── Step 1: Build raw vectors ─────────────────────────────────
    raw_vectors = {}
    for user_id in USER_PROFILES:
        vec = _build_user_feature_vector(user_id)
        if vec:
            raw_vectors[user_id] = vec

    if len(raw_vectors) < min_samples:
        print(f"[WARN] Not enough users ({len(raw_vectors)}) for DBSCAN (min_samples={min_samples}). Skipping rebuild.")
        return {}

    user_ids = list(raw_vectors.keys())

    # ── Step 2: Normalize to 0–1 ─────────────────────────────────
    norm_vectors = {
        uid: _normalize_vector(raw_vectors[uid], CLUSTER_KEYS)
        for uid in user_ids
    }

    # Build matrix for sklearn — rows = users, cols = features
    X = np.array([
        [norm_vectors[uid][k] for k in CLUSTER_KEYS]
        for uid in user_ids
    ])

    # ── Step 3: Run DBSCAN ────────────────────────────────────────
    db          = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean")
    labels      = db.fit_predict(X)
    # labels[i] = cluster index for user_ids[i]
    # labels[i] = -1 → outlier, doesn't fit any cluster

    unique_labels  = set(labels)
    n_clusters     = len(unique_labels - {-1})
    n_outliers     = list(labels).count(-1)

    print(f"[INFO] DBSCAN found {n_clusters} clusters, {n_outliers} outliers "
          f"(eps={eps}, min_samples={min_samples})")

    # ── Step 4: Build assignment dict ────────────────────────────
    # Map cluster index → cluster_id string
    cluster_id_map = {
        label: f"cluster_dynamic_{label}"
        for label in unique_labels if label != -1
    }
    cluster_id_map[-1] = outlier_id  # outliers get special ID

    assignments = {
        user_ids[i]: cluster_id_map[labels[i]]
        for i in range(len(user_ids))
    }

    # ── Step 5: Update USER_PROFILES ─────────────────────────────
    for uid, cluster_id in assignments.items():
        if uid in USER_PROFILES:
            USER_PROFILES[uid]["peer_cluster_id"] = cluster_id

    # ── Step 6: Rebuild PEER_CLUSTERS entries ────────────────────
    for label in unique_labels:
        cluster_id = cluster_id_map[label]
        members    = [uid for uid, cid in assignments.items() if cid == cluster_id]

        if label == -1:
            # Outlier cluster — minimal entry, these users use individual profiling
            PEER_CLUSTERS[cluster_id] = {
                "cluster_id"         : cluster_id,
                "label"              : "Outliers — individual profiling",
                "member_user_ids"    : members,
                "is_outlier_cluster" : True,
                # Empty norms — outlier users rely on their individual profile
                "common_login_hours" : [],
                "common_countries"   : [],
                "common_ip_subnets"  : [],
                "common_device_types": [],
                "common_departments" : [],
                "common_roles"       : [],
                "common_offices"     : [],
                "avg_failed_attempts": 0,
            }
            continue

        # Regular cluster — aggregate norms from members
        all_hours     = []
        all_devices   = []
        all_countries = []
        all_depts     = []
        all_roles     = []
        all_offices   = []
        total_fails   = 0

        for uid in members:
            p = USER_PROFILES.get(uid, {})
            all_hours     += p.get("typical_login_hours", [])
            all_devices   += p.get("known_devices", [])
            all_countries += p.get("known_countries", [])
            all_depts.append(p.get("department", "Unknown"))
            all_roles.append(p.get("role", "Unknown"))
            all_offices.append(p.get("office", "Unknown"))
            total_fails   += p.get("avg_failed_attempts", 0)

        PEER_CLUSTERS[cluster_id] = {
            "cluster_id"          : cluster_id,
            "label"               : f"Dynamic Cluster {label}",
            "member_user_ids"     : members,
            "is_outlier_cluster"  : False,
            "common_login_hours"  : sorted(set(all_hours)),
            "common_countries"    : list(set(all_countries)),
            "common_ip_subnets"   : [],
            "common_device_types" : list(set(all_devices)),
            "common_departments"  : list(set(all_depts)),
            "common_roles"        : list(set(all_roles)),
            "common_offices"      : list(set(all_offices)),
            "avg_failed_attempts" : round(total_fails / len(members), 3) if members else 0,
        }

    return assignments


# ─────────────────────────────────────────────
# QUICK TEST — python peer_cluster.py
# ─────────────────────────────────────────────
if __name__ == "__main__":

    print("── Read mode ─────────────────────────────────────────")
    cluster = get_user_cluster("u01")
    print(f"Kartik cluster     : {cluster['label']}")
    print(f"Common hours       : {get_cluster_typical_hours(cluster)}")
    print(f"MacBook common?    : {is_common_device_type(cluster, 'MacBook')}")
    print(f"Windows common?    : {is_common_device_type(cluster, 'Windows')}")
    print(f"India common?      : {is_common_country(cluster, 'India')}")
    print(f"UK common?         : {is_common_country(cluster, 'UK')}")
    print(f"10.0.1.x common?   : {is_common_ip_subnet(cluster, '10.0.1.45')}")
    print(f"82.45.x common?    : {is_common_ip_subnet(cluster, '82.45.12.99')}")

    print("\n── Peer deviation score ──────────────────────────────")
    normal_features = {
        "login_hour": 9, "failed_attempts": 0,
        "peer_device_match": 1, "peer_country_match": 1, "peer_ip_match": 1
    }
    attack_features = {
        "login_hour": 3, "failed_attempts": 3,
        "peer_device_match": 0, "peer_country_match": 0, "peer_ip_match": 0
    }
    # Org mismatch only — behavioral looks fine but wrong dept/role/office
    org_mismatch_features = {
        "login_hour": 9, "failed_attempts": 0,
        "peer_device_match": 1, "peer_country_match": 1, "peer_ip_match": 1,
        "department": "Finance", "role": "Finance Analyst", "office": "New York"
    }

    print(f"Normal login (with org)      : {compute_peer_deviation_score(normal_features, cluster, user_id='u01')}")
    print(f"Attack login (with org)      : {compute_peer_deviation_score(attack_features, cluster, user_id='u01')}")
    print(f"Org mismatch only (no user)  : {compute_peer_deviation_score(org_mismatch_features, cluster)}")
    print(f"Normal login (no user_id)    : {compute_peer_deviation_score(normal_features, cluster)}")

    print("\n── Feature vectors with org attributes ───────────────")
    for uid in ["u01", "u02", "u03", "u04"]:
        vec = _build_user_feature_vector(uid)
        p   = USER_PROFILES[uid]
        print(f"\n  {p['name']} ({p['department']} / {p['role']} / {p['office']})")
        print(f"  Raw    : hour={vec['avg_login_hour']}, devices={vec['n_devices']}, events={vec['total_events']}")
        print(f"  Org    : dept={vec['dept_encoded']}, role={vec['role_encoded']}, office={vec['office_encoded']}")
        norm = _normalize_vector(vec, ["avg_login_hour","n_devices","total_events","dept_encoded","role_encoded","office_encoded"])
        print(f"  Normed : { {k: round(v,3) for k,v in norm.items()} }")

    print("\n── Rebuild clusters (DBSCAN — behavioral + org) ──────")
    assignments = rebuild_clusters()
    print(f"Assignments:")
    for uid, cluster_id in assignments.items():
        name = USER_PROFILES[uid]['name']
        dept = USER_PROFILES[uid]['department']
        print(f"  {name:<10} ({dept:<15}) → {cluster_id}")

    print("\n── Fallback test (unknown dept) ──────────────────────")
    from mock_db import get_dept_encoding
    print(f"Known dept    : {get_dept_encoding('Engineering')}")
    print(f"Unknown dept  : {get_dept_encoding('Marketing')}")  # triggers warning + dynamic assign