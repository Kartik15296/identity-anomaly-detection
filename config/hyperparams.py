# config/hyperparams.py
# Central hyperparameter registry for the entire system.
# Every tunable value lives here — nothing hardcoded in module files.
#
# HOW TO USE:
#   from config.hyperparams import COLD_START, TRUST, ...
#
# HOW TO TUNE:
#   Change values here only. All modules pick up the new values automatically.
#   Each section has comments explaining what each param controls and

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
# Controls HDBSCAN peer group clustering behavior.
# Uses Gower Distance for mixed-type feature handling.
# ═════════════════════════════════════════════════════════════════
CLUSTERING = {

    # ── HDBSCAN parameters ───────────────────────────────────────
    # min_cluster_size: minimum users to form a persistent cluster.
    # HDBSCAN discovers number of clusters automatically — no eps needed.
    # ↑ = require larger groups, more users become outliers
    # ↓ = allow smaller groups to form clusters
    # Set to 2 for small orgs (<50 users), 3–5 for larger orgs
    "HDBSCAN_MIN_CLUSTER_SIZE": 2,

    # min_samples: controls how conservative outlier labeling is.
    # None = defaults to min_cluster_size (recommended starting point).
    "HDBSCAN_MIN_SAMPLES": 1,

    # allow_single_cluster: if True, allows HDBSCAN to find a single cluster
    # covering all (non-outlier) points. Important for small orgs where all
    # users may genuinely form one behavioral group.
    # Set False for large orgs with clearly distinct behavioral groups.
    "HDBSCAN_ALLOW_SINGLE_CLUSTER": True,

    # Soft membership threshold: users with cluster membership probability
    # below this value are treated as "borderline" and get extra individual
    # profiling weight even if technically assigned to a cluster.
    # Range 0.0–1.0. 0.4 = must be 40% confident to trust cluster signals.
    # ↑ = stricter, more users fall back to individual profiling
    # ↓ = more permissive, cluster signals used even for weak members
    "SOFT_MEMBERSHIP_THRESHOLD": 0.4,

    # Label assigned to users who don't fit any cluster (HDBSCAN outliers).
    # These users fall back to 100% individual profiling.
    "OUTLIER_CLUSTER_ID": "cluster_outlier",

    # ── Gower Distance feature types ─────────────────────────────
    # Declares which features are categorical vs numeric.
    # Categorical features use 0/1 match distance (no false ordering).
    # Numeric features use normalized absolute difference.
    # Add new features here when extending _build_user_feature_vector.
    "GOWER_CATEGORICAL_FEATURES": [
        "department",   # string — same dept = 0, different = 1
        "role",         # string — same role = 0, different = 1
        "office",       # string — same office = 0, different = 1
    ],
    "GOWER_NUMERIC_FEATURES": [
        "avg_login_hour",       # 0–23
        "login_hour_std",       # 0–12 (std dev of login hours)
        "n_devices",            # 1–10
        "device_type_entropy",  # 0–2.3 (diversity of device types)
        "country_count",        # 1–10 (unique countries logged in from)
        "avg_failed_attempts",  # 0–5
        "total_events",         # 0–500
    ],

    # Normalization ranges for numeric features in Gower distance.
    # Used to scale |a - b| to 0–1 range per feature.
    # Range = max - min. Update when org scale changes.
    "GOWER_NUMERIC_RANGES": {
        "avg_login_hour"      : 23,
        "login_hour_std"      : 12,
        "n_devices"           : 9,
        "device_type_entropy" : 2.3,
        "country_count"       : 9,
        "avg_failed_attempts" : 5,
        "total_events"        : 500,
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
    "HOUR_DEVIATION_MAX": 12,

    # Max failed attempts before failure deviation score is capped at 1.0.
    "FAILED_ATTEMPTS_MAX": 5,

    # How often clusters are rebuilt (in days).
    "REBUILD_INTERVAL_DAYS": 7,

    # ── Login hour time-decay (user_profile.py) ──────────────────
    # Controls how quickly old login hours fade from the user's profile.
    # Applied as: weight = decay_factor ^ hours_since_login
    # 0.99 = very slow decay (hours from 1 week ago still ~85% weight)
    # 0.95 = moderate decay  (hours from 1 week ago ~70% weight)
    # ↓ = profile adapts faster to schedule changes
    # ↑ = profile is more stable, slower to forget old patterns
    "HOUR_DECAY_FACTOR": 0.98,

    # Minimum weight before a login hour is dropped from the profile.
    # Below this threshold, the hour is considered "forgotten".
    "HOUR_DECAY_MIN_WEIGHT": 0.20,
}


# ═════════════════════════════════════════════════════════════════
# ML MODELS  —  6.models/models_main.py
# Controls Isolation Forest and Logistic Regression training.
# ═════════════════════════════════════════════════════════════════
MODELS = {

    # ── Isolation Forest ─────────────────────────────────────────
    # n_estimators: number of trees. More = more stable scores, slower fit.
    # 200 is the sweet spot for login-volume data — training < 2 seconds.
    # ↑ = more stable anomaly scores, slower to train
    # ↓ = noisier scores, faster to train
    "IF_N_ESTIMATORS": 200,

    # contamination: expected fraction of anomalies in training data.
    # "auto" lets IF use its own internal threshold based on score distribution.
    # Can also set a float e.g. 0.05 = expect 5% of logins to be attacks.
    # "auto" is recommended unless you have a good estimate of your attack rate.
    "IF_CONTAMINATION": "auto",

    # Random state for reproducibility.
    "IF_RANDOM_STATE": 42,

    # Minimum normal training samples. Below this, synthetic samples are generated.
    # ↑ = model sees more varied normal behavior before scoring live events
    # ↓ = faster to train, but IF may be less well-calibrated
    "IF_MIN_TRAINING_SAMPLES": 300,

    # ── Logistic Regression ──────────────────────────────────────
    # C: inverse regularization strength. Smaller = stronger regularization.
    # 1.0 is the sklearn default — good for small labeled datasets.
    # ↓ = more regularized, less overfitting, may underfit on noisy data
    # ↑ = less regularized, fits training data more closely
    "LR_C": 1.0,

    # Random state for reproducibility.
    "LR_RANDOM_STATE": 42,

    # Minimum labeled training samples. Below this, synthetic samples are added.
    "LR_MIN_TRAINING_SAMPLES": 200,

    # How many new pending labels to accumulate before triggering a retrain.
    # Lower = model adapts faster, more frequent retraining overhead.
    # ↓ = retrain more eagerly (useful when attack patterns are shifting fast)
    # ↑ = batch more labels before retraining (more stable, less compute)
    "LR_RETRAIN_AFTER_N_LABELS": 50,
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
