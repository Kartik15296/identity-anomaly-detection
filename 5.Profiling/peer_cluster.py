# 5.Profiling/peer_cluster.py
# Manages peer group behavioral clusters.
#
# Key improvements over the original DBSCAN version:
#   1. Gower Distance  — handles mixed categorical + numeric features correctly.
#      Categorical fields (dept, role, office) use 0/1 match distance, not
#      numeric encoding, eliminating false ordinal relationships.
#
#   2. HDBSCAN         — no eps parameter to tune. Discovers cluster count
#      automatically and handles variable-density populations.
#      Uses sklearn.cluster.HDBSCAN (available in sklearn >= 1.3).
#
#   3. Soft membership — HDBSCAN produces per-user membership probabilities.
#      Borderline users (below SOFT_MEMBERSHIP_THRESHOLD) get reduced peer
#      signal weight, exposed via peer_membership_confidence on the profile.
#
#   4. Richer features — clustering now uses:
#      Behavioral: avg_login_hour, login_hour_std, n_devices,
#                  device_type_entropy, country_count, avg_failed_attempts,
#                  total_events
#      Org:        department, role, office (raw strings — Gower handles them)
#
# Read mode  : fast, called per login event
# Rebuild mode: slow, called weekly by retrain_scheduler

import sys
import os
from hyperparams import register_paths
register_paths()

import math
import numpy as np
from collections import Counter
from mock_db import PEER_CLUSTERS, USER_PROFILES
from hyperparams import CLUSTERING


# ─────────────────────────────────────────────
# READ MODE FUNCTIONS
# ─────────────────────────────────────────────

def get_cluster(cluster_id):
    return PEER_CLUSTERS.get(cluster_id, None)


def get_user_cluster(user_id):
    """
    Returns the cluster a user belongs to, or None if outlier/unassigned.
    """
    profile = USER_PROFILES.get(user_id)
    if not profile:
        return None
    cluster_id = profile.get("peer_cluster_id")
    if not cluster_id or cluster_id == CLUSTERING["OUTLIER_CLUSTER_ID"]:
        return None
    return PEER_CLUSTERS.get(cluster_id)


def get_user_membership_confidence(user_id):
    """
    Returns HDBSCAN soft membership probability for a user (0.0-1.0).
    Falls back to 1.0 for manually seeded profiles without this field.
    """
    profile = USER_PROFILES.get(user_id)
    if not profile:
        return 0.0
    cluster_id = profile.get("peer_cluster_id", "")
    if cluster_id == CLUSTERING["OUTLIER_CLUSTER_ID"]:
        return 0.0
    return float(profile.get("peer_membership_confidence", 1.0))


def is_common_device_type(cluster, device_type):
    if not cluster:
        return False
    return device_type in cluster.get("common_device_types", [])


def is_common_country(cluster, country):
    if not cluster:
        return False
    return country in cluster.get("common_countries", [])


def is_common_ip_subnet(cluster, ip_address):
    if not cluster:
        return False
    subnets = cluster.get("common_ip_subnets", [])
    return any(ip_address.startswith(subnet) for subnet in subnets)


def get_cluster_typical_hours(cluster):
    if not cluster:
        return []
    return cluster.get("common_login_hours", [])


def get_cluster_members(cluster_id):
    cluster = PEER_CLUSTERS.get(cluster_id)
    if not cluster:
        return []
    return cluster.get("member_user_ids", [])


def compute_peer_deviation_score(feature_vector, cluster, user_id=None):
    """
    Computes how much a user's current login deviates from their peer cluster.
    Returns 0.0 (matches cluster norms) to 1.0 (completely unlike cluster).

    Behavioral signals (80% weight): hour, device type, country, IP, failed attempts
    Org signals (20% weight): department, role, office

    Soft membership adjustment: borderline members get score blended toward
    neutral (0.5) proportionally to how far below the confidence threshold they are.
    """
    if not cluster or not feature_vector:
        return 0.5

    behavioral_deviations = []
    org_deviations = []

    # Login hour deviation
    cluster_hours = cluster.get("common_login_hours", [])
    if cluster_hours:
        login_hour = feature_vector.get("login_hour", 12)
        hour_dev = min(abs(login_hour - h) for h in cluster_hours)
        behavioral_deviations.append(min(hour_dev / CLUSTERING["HOUR_DEVIATION_MAX"], 1.0))

    # Device type
    peer_device_match = feature_vector.get("peer_device_match", 0)
    behavioral_deviations.append(0.0 if peer_device_match else 1.0)

    # Country
    peer_country_match = feature_vector.get("peer_country_match", 0)
    behavioral_deviations.append(0.0 if peer_country_match else 1.0)

    # IP subnet
    peer_ip_match = feature_vector.get("peer_ip_match", 0)
    behavioral_deviations.append(0.0 if peer_ip_match else 1.0)

    # Failed attempts vs cluster avg
    cluster_avg_fails = cluster.get("avg_failed_attempts", 0.0)
    current_fails = feature_vector.get("failed_attempts", 0)
    behavioral_deviations.append(
        min(abs(current_fails - cluster_avg_fails) / CLUSTERING["FAILED_ATTEMPTS_MAX"], 1.0)
    )

    # Org attributes
    if user_id and user_id in USER_PROFILES:
        p = USER_PROFILES[user_id]
        department = p.get("department")
        role = p.get("role")
        office = p.get("office")
    else:
        department = feature_vector.get("department")
        role = feature_vector.get("role")
        office = feature_vector.get("office")

    if department and cluster.get("common_departments"):
        org_deviations.append(0.0 if department in cluster["common_departments"] else 1.0)
    if role and cluster.get("common_roles"):
        org_deviations.append(0.0 if role in cluster["common_roles"] else 1.0)
    if office and cluster.get("common_offices"):
        org_deviations.append(0.0 if office in cluster["common_offices"] else 1.0)

    # Weighted aggregate
    behavioral_score = sum(behavioral_deviations) / len(behavioral_deviations) if behavioral_deviations else 0.5
    org_score = sum(org_deviations) / len(org_deviations) if org_deviations else 0.0

    raw_score = round(
        CLUSTERING["PEER_DEV_BEHAVIORAL_WEIGHT"] * behavioral_score +
        CLUSTERING["PEER_DEV_ORG_WEIGHT"] * org_score,
        3
    )

    # Soft membership adjustment: blend toward neutral for borderline members
    if user_id:
        confidence = get_user_membership_confidence(user_id)
        threshold = CLUSTERING["SOFT_MEMBERSHIP_THRESHOLD"]
        if confidence < threshold:
            blend_weight = confidence / threshold  # 0.0 at outlier → 1.0 at threshold
            raw_score = round(blend_weight * raw_score + (1 - blend_weight) * 0.5, 3)

    return raw_score


# ─────────────────────────────────────────────
# GOWER DISTANCE
# ─────────────────────────────────────────────

def _gower_distance(vec_a, vec_b):
    """
    Gower distance between two feature dicts.
    Numeric: |a - b| / range  → 0-1
    Categorical: 0 if same string, 1 if different
    Final = mean across all features.
    """
    numeric_keys = CLUSTERING["GOWER_NUMERIC_FEATURES"]
    categorical_keys = CLUSTERING["GOWER_CATEGORICAL_FEATURES"]
    ranges = CLUSTERING["GOWER_NUMERIC_RANGES"]

    distances = []

    for key in numeric_keys:
        a = vec_a.get(key)
        b = vec_b.get(key)
        if a is None or b is None:
            continue
        r = ranges.get(key, 1)
        distances.append(0.0 if r == 0 else min(abs(a - b) / r, 1.0))

    for key in categorical_keys:
        a = vec_a.get(key)
        b = vec_b.get(key)
        if a is None or b is None:
            continue
        distances.append(0.0 if a == b else 1.0)

    return sum(distances) / len(distances) if distances else 1.0


def _build_gower_distance_matrix(feature_vecs, user_ids):
    """
    Builds symmetric Gower Distance matrix for all users.
    Returns (n, n) numpy array — D[i][j] = Gower distance between users i and j.
    """
    n = len(user_ids)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = _gower_distance(feature_vecs[user_ids[i]], feature_vecs[user_ids[j]])
            D[i][j] = d
            D[j][i] = d
    return D


# ─────────────────────────────────────────────
# REBUILD MODE FUNCTIONS
# ─────────────────────────────────────────────

def _build_user_feature_vector(user_id):
    """
    Builds richer behavioral + org feature vector for HDBSCAN clustering.

    Numeric behavioral:
        avg_login_hour, login_hour_std  — computed from time-decayed hour weights
        n_devices, device_type_entropy  — device usage diversity
        country_count                   — geographic spread
        avg_failed_attempts             — failure rate
        total_events                    — activity level

    Categorical org (raw strings — NOT integer-encoded):
        department, role, office
    """
    profile = USER_PROFILES.get(user_id)
    if not profile:
        return None

    # Login hour stats from time-decayed weights
    hour_weights = profile.get("login_hour_weights", {})
    if hour_weights:
        total_w = sum(e["weight"] for e in hour_weights.values())
        avg_hour = (
            sum(int(h) * e["weight"] for h, e in hour_weights.items()) / total_w
            if total_w else 12.0
        )
        variance = (
            sum(e["weight"] * (int(h) - avg_hour) ** 2 for h, e in hour_weights.items()) / total_w
            if total_w else 0.0
        )
        hour_std = math.sqrt(variance)
    else:
        typical = profile.get("typical_login_hours", [])
        avg_hour = sum(typical) / len(typical) if typical else 12.0
        hour_std = (
            math.sqrt(sum((h - avg_hour) ** 2 for h in typical) / len(typical))
            if len(typical) > 1 else 0.0
        )

    # Device features
    known_devices = profile.get("known_devices", [])
    n_devices = max(1, len(known_devices))
    device_type_entropy = profile.get("device_type_entropy", 0.0)
    if device_type_entropy == 0.0 and n_devices > 1:
        p = 1.0 / n_devices
        device_type_entropy = -n_devices * p * math.log(p)

    return {
        "user_id"             : user_id,
        # Numeric
        "avg_login_hour"      : round(avg_hour, 2),
        "login_hour_std"      : round(hour_std, 2),
        "n_devices"           : float(n_devices),
        "device_type_entropy" : round(device_type_entropy, 3),
        "country_count"       : float(profile.get("country_count", len(profile.get("known_countries", ["?"])))),
        "avg_failed_attempts" : float(profile.get("avg_failed_attempts", 0.0)),
        "total_events"        : float(profile.get("total_events", 0)),
        # Categorical (raw strings)
        "department"          : profile.get("department", "Unknown"),
        "role"                : profile.get("role", "Unknown"),
        "office"              : profile.get("office", "Unknown"),
    }


def rebuild_clusters():
    """
    Runs HDBSCAN with Gower Distance on all user feature vectors.
    No need to specify number of clusters — HDBSCAN discovers them.

    Steps:
        1. Build richer feature vectors (behavioral + categorical org)
        2. Compute pairwise Gower Distance matrix
        3. Run HDBSCAN on precomputed distance matrix (metric='precomputed')
        4. Extract soft membership probabilities, store on user profiles
        5. Update PEER_CLUSTERS and USER_PROFILES in memory

    Returns: { user_id: cluster_id } assignments dict
    """
    from sklearn.cluster import HDBSCAN

    min_cluster_size = CLUSTERING["HDBSCAN_MIN_CLUSTER_SIZE"]
    outlier_id = CLUSTERING["OUTLIER_CLUSTER_ID"]

    # Step 1: Build feature vectors
    raw_vecs = {}
    for user_id in USER_PROFILES:
        vec = _build_user_feature_vector(user_id)
        if vec:
            raw_vecs[user_id] = vec

    if len(raw_vecs) < min_cluster_size:
        print(f"[WARN] Not enough users ({len(raw_vecs)}) for HDBSCAN. Skipping rebuild.")
        return {}

    user_ids = list(raw_vecs.keys())
    print(f"[INFO] Building Gower Distance matrix for {len(user_ids)} users...")

    # Step 2: Gower Distance matrix
    D = _build_gower_distance_matrix(raw_vecs, user_ids)
    print(f"[INFO] Distance matrix: shape={D.shape}, mean={D.mean():.3f}, max={D.max():.3f}")

    # Step 3: HDBSCAN on precomputed distances
    hdb_kwargs = {
        "min_cluster_size"    : min_cluster_size,
        "min_samples"         : CLUSTERING["HDBSCAN_MIN_SAMPLES"],
        "metric"              : "precomputed",
        "allow_single_cluster": CLUSTERING["HDBSCAN_ALLOW_SINGLE_CLUSTER"],
    }

    clusterer = HDBSCAN(**hdb_kwargs)
    clusterer.fit(D)

    labels = clusterer.labels_
    probabilities = clusterer.probabilities_

    unique_labels = set(labels)
    n_clusters = len(unique_labels - {-1})
    n_outliers = list(labels).count(-1)
    print(f"[INFO] HDBSCAN: {n_clusters} clusters, {n_outliers} outliers (min_cluster_size={min_cluster_size})")

    # Step 4: Build assignments and update user profiles
    cluster_id_map = {label: f"cluster_dynamic_{label}" for label in unique_labels if label != -1}
    cluster_id_map[-1] = outlier_id

    assignments = {user_ids[i]: cluster_id_map[labels[i]] for i in range(len(user_ids))}

    for i, uid in enumerate(user_ids):
        if uid in USER_PROFILES:
            USER_PROFILES[uid]["peer_cluster_id"] = assignments[uid]
            USER_PROFILES[uid]["peer_membership_confidence"] = round(float(probabilities[i]), 4)

    # Step 5: Rebuild PEER_CLUSTERS
    for label in unique_labels:
        cluster_id = cluster_id_map[label]
        members = [uid for uid, cid in assignments.items() if cid == cluster_id]

        if label == -1:
            PEER_CLUSTERS[cluster_id] = {
                "cluster_id"         : cluster_id,
                "label"              : "Outliers — individual profiling",
                "member_user_ids"    : members,
                "is_outlier_cluster" : True,
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

        all_hours, all_countries, all_devices, all_depts, all_roles, all_offices = [], [], [], [], [], []
        total_fails = 0.0

        for uid in members:
            p = USER_PROFILES.get(uid, {})
            all_hours     += p.get("typical_login_hours", [])
            all_countries += p.get("known_countries", [])
            all_devices   += list(p.get("device_trust", {}).keys())
            all_depts.append(p.get("department", "Unknown"))
            all_roles.append(p.get("role", "Unknown"))
            all_offices.append(p.get("office", "Unknown"))
            total_fails += p.get("avg_failed_attempts", 0.0)

        top_depts   = [d for d, _ in Counter(all_depts).most_common(3)]
        top_roles   = [r for r, _ in Counter(all_roles).most_common(3)]
        top_offices = [o for o, _ in Counter(all_offices).most_common(3)]

        PEER_CLUSTERS[cluster_id] = {
            "cluster_id"         : cluster_id,
            "label"              : f"Dynamic Cluster {label}",
            "member_user_ids"    : members,
            "is_outlier_cluster" : False,
            "common_login_hours" : sorted(set(all_hours)),
            "common_countries"   : list(set(all_countries)),
            "common_ip_subnets"  : [],
            "common_device_types": list(set(all_devices)),
            "common_departments" : top_depts,
            "common_roles"       : top_roles,
            "common_offices"     : top_offices,
            "avg_failed_attempts": round(total_fails / len(members), 3) if members else 0,
        }

    return assignments


# ─────────────────────────────────────────────
# QUICK TEST — python peer_cluster.py
# ─────────────────────────────────────────────
if __name__ == "__main__":

    print("── Read mode ─────────────────────────────────────────")
    cluster = get_user_cluster("u01")
    if cluster:
        print(f"Kartik cluster     : {cluster['label']}")
        print(f"Common hours       : {get_cluster_typical_hours(cluster)}")
        print(f"Common depts       : {cluster.get('common_departments', [])}")
    else:
        print("Kartik: no cluster (will be assigned on rebuild)")

    print(f"\nKartik membership confidence : {get_user_membership_confidence('u01')}")
    print(f"Sneha  membership confidence : {get_user_membership_confidence('u04')}")

    print("\n── Feature vectors (richer format) ───────────────────")
    for uid in ["u01", "u02", "u03", "u04"]:
        vec = _build_user_feature_vector(uid)
        if vec:
            p = USER_PROFILES[uid]
            print(f"\n  {p['name']} ({p['department']} / {p['role']} / {p['office']})")
            print(f"    avg_hour={vec['avg_login_hour']}  hour_std={vec['login_hour_std']}"
                  f"  n_devices={vec['n_devices']}  entropy={vec['device_type_entropy']}")
            print(f"    countries={vec['country_count']}  avg_fails={vec['avg_failed_attempts']}"
                  f"  events={vec['total_events']}")

    print("\n── Gower Distance matrix ─────────────────────────────")
    uids = ["u01", "u02", "u03", "u04"]
    vecs = {uid: _build_user_feature_vector(uid) for uid in uids}
    D = _build_gower_distance_matrix(vecs, uids)
    print("         " + "  ".join(f"{uid:>6}" for uid in uids))
    for i, uid_i in enumerate(uids):
        name = USER_PROFILES[uid_i]["name"][:6]
        row = "  ".join(f"{D[i][j]:.3f}" for j in range(len(uids)))
        print(f"  {name:<7} {row}")

    print("\n── Rebuild clusters (HDBSCAN + Gower) ────────────────")
    assignments = rebuild_clusters()
    print("Assignments:")
    for uid, cluster_id in assignments.items():
        name = USER_PROFILES[uid]["name"]
        dept = USER_PROFILES[uid]["department"]
        conf = USER_PROFILES[uid].get("peer_membership_confidence", "n/a")
        print(f"  {name:<10} ({dept:<15}) → {cluster_id}  confidence={conf}")

    print("\n── Peer deviation scores ─────────────────────────────")
    cluster = get_user_cluster("u01")
    if cluster:
        normal = {"login_hour": 9, "failed_attempts": 0,
                  "peer_device_match": 1, "peer_country_match": 1, "peer_ip_match": 1}
        attack = {"login_hour": 3, "failed_attempts": 3,
                  "peer_device_match": 0, "peer_country_match": 0, "peer_ip_match": 0}
        print(f"  Normal login deviation : {compute_peer_deviation_score(normal, cluster, user_id='u01')}")
        print(f"  Attack login deviation : {compute_peer_deviation_score(attack, cluster, user_id='u01')}")
    else:
        print("  (Run rebuild_clusters first to populate clusters)")