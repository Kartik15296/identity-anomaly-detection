# 1.config/hyperparams.py
# Central hyperparameter registry for the entire system.
# Every tunable value lives here — nothing hardcoded in module files.
#
# HOW TO USE:
#   from hyperparams import register_paths, COLD_START, TRUST, ...
#   register_paths()   ← call once at top of every file
#
# HOW TO TUNE:
#   Change values here only. All modules pick up the new values automatically.
#   Each section has comments explaining what each param controls and

import sys
import os

def register_paths():
    """
    Adds all project folders to sys.path.
    Call once at the top of every file in the project.
    After this, any file can import from any folder directly.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    folders = [
        root,
        os.path.join(root, "1.config"),
        os.path.join(root, "2.database"),
        os.path.join(root, "3.ingestion"),
        os.path.join(root, "4.features"),
        os.path.join(root, "5.Profiling"),
        os.path.join(root, "6.models"),
        os.path.join(root, "7.scoring"),
        os.path.join(root, "8.feedback"),
        os.path.join(root, "Admin_dashboard"),
        os.path.join(root, "Integration"),
    ]
    for folder in folders:
        if folder not in sys.path:
            sys.path.append(folder)
#   the direction to move it (↑ = increase, ↓ = decrease) for desired effect.


# ═════════════════════════════════════════════════════════════════
# COLD START  —  5.Profiling/cold_start.py
# Controls how quickly a new user transitions from peer-group
# profiling to individual profiling.
# ═════════════════════════════════════════════════════════════════
COLD_START = {

    # Number of login events before individual profile starts contributing.
    # Below this → 100% peer group used.
    # ↑ = be more cautious with new users for longer
    # ↓ = trust individual profile sooner
    "MIN_EVENTS": 30,

    # Number of login events for full individual profile trust.
    # Between MIN_EVENTS and MATURE_EVENTS → linear blend.
    # ↑ = longer transition period
    # ↓ = faster transition to full individual trust
    "MATURE_EVENTS": 100,
}


# ═════════════════════════════════════════════════════════════════
# DEVICE TRUST  —  5.Profiling/user_profile.py
# Controls how device trust scores evolve based on feedback.
# Uses exponential decay model — trust is slow to earn, fast to lose.
# ═════════════════════════════════════════════════════════════════
TRUST = {

    # Base boost rate for MFA pass.
    # Actual boost = PASS_BOOST × (1 - current_trust)  ← diminishing returns
    # ↑ = devices gain trust faster after successful MFA
    # ↓ = trust builds more slowly
    "MFA_PASS_BOOST": 0.05,

    # Base boost rate for admin approval.
    # Slightly stronger than MFA pass — human judgment > automated check.
    # ↑ = admin approval has stronger positive effect
    # ↓ = admin approval has weaker positive effect
    "ADMIN_APPROVE_BOOST": 0.10,

    # Decay multiplier on MFA failure.
    # new_trust = current_trust × MFA_FAIL_DECAY
    # ↓ = harsher penalty (0.3 = cut to 30% of current)
    # ↑ = softer penalty (0.7 = cut to 70% of current)
    "MFA_FAIL_DECAY": 0.50,

    # Decay multiplier on admin block — severe, near zero.
    # new_trust = current_trust × ADMIN_BLOCK_DECAY
    # ↓ = near complete distrust (0.05 = almost zero)
    # ↑ = slightly less severe
    "ADMIN_BLOCK_DECAY": 0.10,

    # Hard bounds — do not change unless you change the scoring scale.
    "MAX": 1.0,
    "MIN": 0.0,

    # Starting trust score for a brand new unseen device.
    # 0.5 = neutral — not trusted, not distrusted.
    # ↓ = start new devices with more suspicion
    # ↑ = start new devices with more trust
    "DEFAULT": 0.5,

    # Rolling window size for login hour history.
    # Keeps this many unique login hours in the user's typical hours list.
    "LOGIN_HOUR_WINDOW": 30,
}


# ═════════════════════════════════════════════════════════════════
# CLUSTERING  —  5.Profiling/peer_cluster.py
# Controls DBSCAN peer group clustering behavior.
# ═════════════════════════════════════════════════════════════════
CLUSTERING = {

    # ── DBSCAN parameters ────────────────────────────────────────
    # eps: neighborhood radius in normalized feature space (0–1 scale).
    # Two users within eps distance of each other are considered neighbors.
    # ↓ = tighter clusters, more users become outliers
    # ↑ = looser clusters, more users get grouped together
    # Typical range: 0.2 – 0.6 for normalized features
    "DBSCAN_EPS": 0.4,

    # min_samples: minimum number of users to form a dense cluster.
    # A group smaller than this becomes outliers, not a cluster.
    # ↑ = require larger groups to form a cluster
    # ↓ = allow smaller groups to form clusters
    # Set to 2 for small orgs, 3–5 for larger orgs
    "DBSCAN_MIN_SAMPLES": 2,

    # Label assigned to users who don't fit any cluster (DBSCAN outliers).
    # These users fall back to 100% individual profiling.
    "OUTLIER_CLUSTER_ID": "cluster_outlier",

    # ── Feature normalization ranges ─────────────────────────────
    # Used to scale raw feature values to 0–1 before clustering.
    # Max values should cover realistic upper bounds for your org.
    # ↑ max = more tolerance for high values before hitting ceiling
    # ↓ max = feature saturates sooner, less differentiation at high end
    "NORM_RANGES": {
        "avg_login_hour" : (0,  23),
        "n_devices"      : (1,  10),
        "total_events"   : (0, 500),
        "dept_encoded"   : (0,   7),
        "role_encoded"   : (0,   8),
        "office_encoded" : (0,   7),
    },

    # ── Peer deviation score weights ─────────────────────────────
    # How much behavioral vs org signals contribute to peer deviation.
    # Must sum to 1.0.
    # ↑ BEHAVIORAL_WEIGHT = org attributes matter less
    # ↓ BEHAVIORAL_WEIGHT = org attributes matter more
    "PEER_DEV_BEHAVIORAL_WEIGHT" : 0.80,
    "PEER_DEV_ORG_WEIGHT"        : 0.20,

    # ── Deviation normalizers ─────────────────────────────────────
    # Max hour gap before deviation is considered fully anomalous.
    # e.g. 12 means logging in 12+ hours from typical = max deviation.
    # ↓ = be stricter about login hour differences
    "HOUR_DEVIATION_MAX": 12,

    # Max failed attempts before failure deviation score is capped at 1.0.
    # ↓ = flag fewer failed attempts as anomalous
    # ↑ = require more failed attempts before fully anomalous
    "FAILED_ATTEMPTS_MAX": 5,

    # How often clusters are rebuilt (in days).
    # ↓ = clusters adapt faster to behavioral changes
    # ↑ = more stable clusters, less compute
    "REBUILD_INTERVAL_DAYS": 7,
}


# ═════════════════════════════════════════════════════════════════
# DRIFT MONITORING  —  4.features/drift_monitor.py
# Controls when feature drift is flagged and retraining is triggered.
# ═════════════════════════════════════════════════════════════════
DRIFT = {

    # PSI thresholds for feature distribution stability.
    # PSI < STABLE     → no action needed
    # PSI STABLE–WARN  → log warning, watch closely
    # PSI > WARN       → trigger retraining
    # ↓ WARN = more sensitive, retrain more often
    # ↑ WARN = more tolerant, retrain less often
    "PSI_STABLE"    : 0.1,
    "PSI_WARN"      : 0.2,

    # KS test p-value threshold.
    # p < threshold → distributions are significantly different → drift
    # ↓ = more sensitive to distribution changes
    # ↑ = less sensitive
    "KS_PVALUE"     : 0.05,

    # Number of buckets for PSI histogram comparison.
    # ↑ = finer-grained comparison, needs more data
    # ↓ = coarser comparison, works with less data
    "PSI_BUCKETS"   : 10,

    # Minimum number of events needed before drift check is meaningful.
    # Below this — skip drift check, not enough data.
    "MIN_EVENTS_FOR_DRIFT": 30,
}


# ═════════════════════════════════════════════════════════════════
# RETRAINING TRIGGERS  —  8.feedback/retrain_scheduler.py
# Controls when the ML model gets retrained.
# Three independent triggers — any one fires retraining.
# ═════════════════════════════════════════════════════════════════
RETRAINING = {

    # Time-based trigger: retrain every N days regardless of drift.
    # ↓ = more frequent retraining, fresher model
    # ↑ = less frequent, more stable but slower to adapt
    "INTERVAL_DAYS"    : 7,

    # Volume trigger: retrain after N new labeled events accumulate.
    # ↓ = retrain more frequently with less data
    # ↑ = wait for more data before retraining
    "MIN_NEW_LABELS"   : 500,

    # Drift trigger: if PSI exceeds PSI_WARN on any feature, retrain.
    # Controlled by DRIFT["PSI_WARN"] above.
}


# ═════════════════════════════════════════════════════════════════
# RISK SCORING  —  7.scoring/risk_engine.py
# Controls how the final risk score maps to security decisions.
# ═════════════════════════════════════════════════════════════════
SCORING = {

    # Risk score boundaries for security decisions.
    # Score 0–ALLOW           → allow login, no friction
    # Score ALLOW–MFA         → step-up MFA required
    # Score MFA–LIMITED       → scope-limited session
    # Score LIMITED–100       → block + admin alert
    # ↑ ALLOW  = allow more logins without friction
    # ↓ ALLOW  = trigger MFA more aggressively
    "RISK_ALLOW"  : 30,
    "RISK_MFA"    : 65,
    "RISK_LIMITED": 80,

    # Number of SHAP reason codes to surface in admin dashboard.
    "TOP_REASON_CODES": 3,
}


# ═════════════════════════════════════════════════════════════════
# GEO / IP  —  4.features/geo_utils.py
# Controls IP resolution and caching behavior.
# ═════════════════════════════════════════════════════════════════
GEO = {

    # How long resolved IP → location results are cached (in seconds).
    # IPs don't change ownership frequently — 24h is safe.
    # ↓ = fresher data, more API calls
    # ↑ = fewer API calls, slightly stale data possible
    "IP_CACHE_TTL_SECONDS": 86400,   # 24 hours

    # Timeout for IP-API.com requests in seconds.
    # Keep low — don't block the login pipeline.
    # ↑ = more tolerant of slow API, but adds latency
    # ↓ = fail fast, fall back to city coordinates sooner
    "IP_API_TIMEOUT": 3,
}