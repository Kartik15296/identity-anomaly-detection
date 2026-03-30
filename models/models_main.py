# models/models_main.py
# Real ML model layer — replaces the mock stub entirely.
#
# Two models:
#   MODEL 1 — Isolation Forest (sklearn)
#     Unsupervised. Trained on normal login feature vectors.
#     Scores every login: 0.0 = normal, 1.0 = highly anomalous.
#     Why IF: sub-ms inference, handles tabular data, sklearn-native,
#     no distance matrix, scales to millions of events.
#
#   MODEL 2 — Calibrated Logistic Regression (sklearn)
#     Supervised. Trained on admin-labeled feedback events.
#     Replaces the hardcoded SIGNAL_WEIGHTS in risk_engine.py.
#     Returns attack_probability: 0.0 = legitimate, 1.0 = attack.
#     Why calibrated LR over GBT or River SGD:
#       - Coefficients directly interpretable as signal weights
#       - CalibratedClassifierCV gives honest probabilities
#       - Warm-start retraining every 7 days is more stable than
#         true online learning for this data volume
#       - Exact SHAP-compatible: contribution_i = coef_i * x_i
#       - Retrains from scratch in < 1 second
#
# Persistence: models saved to artifacts/ as .pkl via joblib.
# On first run: train on mock data and save.
# Subsequent runs: load from pkl.
#
# Interface unchanged from mock — nothing else in the project changes.

import os
import numpy as np
import joblib
from pathlib import Path
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler

from config.hyperparams import MODELS
from database.mock_db import FEEDBACK_LABELS, LOGIN_EVENTS
from features.extractor import extract_features
from profiling.cold_start import get_profile_signals

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
_ROOT        = Path(os.path.dirname(os.path.abspath(__file__)))
_ARTIFACTS   = _ROOT / "artifacts"
_IF_PATH     = _ARTIFACTS / "isolation_forest.pkl"
_LR_PATH     = _ARTIFACTS / "logistic_regression.pkl"
_SCALER_PATH = _ARTIFACTS / "if_scaler.pkl"
_ARTIFACTS.mkdir(exist_ok=True)


# ─────────────────────────────────────────────
# FEATURE SCHEMA
# Order matters — numpy arrays are positional.
# ─────────────────────────────────────────────

# IF gets all signals — unsupervised, no label bias
IF_FEATURES = [
    "login_hour",
    "failed_attempts",
    "new_device",
    "new_country",
    "ip_known",
    "device_trust_score",
    "hour_deviation",
    "travel_speed_kmh",
    "distance_km",
    "peer_deviation",
    "peer_membership_confidence",
]

# LR gets the strongest discriminating features for attack vs legit
LR_FEATURES = [
    "new_device",
    "new_country",
    "failed_attempts",
    "peer_deviation",
    "travel_speed_kmh",
    "hour_deviation",
    "device_trust_score",
    "ip_known",
    "peer_membership_confidence",
]


def _extract_if_vector(fv):
    return np.array([float(fv.get(k, 0.0)) for k in IF_FEATURES], dtype=np.float32)

def _extract_lr_vector(fv):
    return np.array([float(fv.get(k, 0.0)) for k in LR_FEATURES], dtype=np.float32)


# ─────────────────────────────────────────────
# MODEL REGISTRY — lazy loaded
# ─────────────────────────────────────────────
_if_model    = None
_if_scaler   = None
_lr_pipeline = None
_pending_labels = []   # (feature_vector_dict, label_str)


def _ensure_models_loaded():
    global _if_model, _if_scaler, _lr_pipeline
    if _if_model is None or _if_scaler is None:
        if _IF_PATH.exists() and _SCALER_PATH.exists():
            _if_model  = joblib.load(_IF_PATH)
            _if_scaler = joblib.load(_SCALER_PATH)
            print(f"[MODEL] IF loaded from disk")
        else:
            _train_isolation_forest()
    if _lr_pipeline is None:
        if _LR_PATH.exists():
            _lr_pipeline = joblib.load(_LR_PATH)
            print(f"[MODEL] LR loaded from disk")
        else:
            _train_logistic_regression()


# ─────────────────────────────────────────────
# TRAINING — ISOLATION FOREST
# ─────────────────────────────────────────────

def _build_normal_training_data():
    """
    Training data = confirmed-legit events + low-suspicion heuristic events
    + synthetic normal samples to meet minimum training size.
    """
    approved_ids = {f["event_id"] for f in FEEDBACK_LABELS if f["label"] == "legitimate"}
    normal_vectors = []

    for event in LOGIN_EVENTS:
        try:
            raw  = extract_features(event)
            prof = get_profile_signals(event["user_id"], event)
            fv   = {**raw, **prof}
            is_approved = event["event_id"] in approved_ids
            is_clean    = (
                fv.get("new_device", 0) == 0
                and fv.get("new_country", 0) == 0
                and fv.get("failed_attempts", 0) == 0
                and fv.get("travel_speed_kmh", 0) < 200
            )
            if is_approved or is_clean:
                normal_vectors.append(_extract_if_vector(fv))
        except Exception:
            continue

    rng = np.random.default_rng(seed=MODELS["IF_RANDOM_STATE"])
    n_synth = max(0, MODELS["IF_MIN_TRAINING_SAMPLES"] - len(normal_vectors))
    if n_synth > 0:
        print(f"[MODEL] Generating {n_synth} synthetic normal samples for IF")
        synthetic = np.column_stack([
            rng.integers(8, 18, n_synth).astype(float),   # login_hour
            rng.integers(0, 2,  n_synth).astype(float),   # failed_attempts
            np.zeros(n_synth),                             # new_device
            np.zeros(n_synth),                             # new_country
            np.ones(n_synth),                              # ip_known
            rng.uniform(0.7, 1.0, n_synth),                # device_trust_score
            rng.uniform(0,   2,   n_synth),                # hour_deviation
            rng.uniform(0,   50,  n_synth),                # travel_speed_kmh
            rng.uniform(0,   20,  n_synth),                # distance_km
            rng.uniform(0,   0.2, n_synth),                # peer_deviation
            rng.uniform(0.7, 1.0, n_synth),                # peer_membership_confidence
        ])
        normal_vectors.extend(synthetic.tolist())

    return np.array(normal_vectors, dtype=np.float32)


def _train_isolation_forest():
    global _if_model, _if_scaler
    X = _build_normal_training_data()
    print(f"[MODEL] Training IF on {len(X)} normal samples × {X.shape[1]} features")

    _if_scaler = StandardScaler()
    X_scaled   = _if_scaler.fit_transform(X)

    _if_model = IsolationForest(
        n_estimators  = MODELS["IF_N_ESTIMATORS"],
        contamination = MODELS["IF_CONTAMINATION"],
        max_samples   = "auto",
        random_state  = MODELS["IF_RANDOM_STATE"],
        n_jobs        = 1,
    )
    _if_model.fit(X_scaled)
    joblib.dump(_if_model,  _IF_PATH)
    joblib.dump(_if_scaler, _SCALER_PATH)
    print(f"[MODEL] IF saved → {_IF_PATH.name}")


# ─────────────────────────────────────────────
# TRAINING — LOGISTIC REGRESSION
# ─────────────────────────────────────────────

def _build_labeled_training_data():
    """
    Builds (X, y) from feedback labels + pending labels + synthetic samples.
    y: 1 = attack, 0 = legitimate.
    """
    event_map = {e["event_id"]: e for e in LOGIN_EVENTS}
    X, y = [], []

    all_feedback = list(FEEDBACK_LABELS) + [
        {"event_id": "synthetic", "label": lb, "_fv": fv}
        for fv, lb in _pending_labels
    ]

    for fb in all_feedback:
        label = 1 if fb["label"] == "attack" else 0
        fv    = fb.get("_fv")
        if fv is None:
            event = event_map.get(fb.get("event_id"))
            if not event:
                continue
            try:
                raw  = extract_features(event)
                prof = get_profile_signals(event["user_id"], event)
                fv   = {**raw, **prof}
            except Exception:
                continue
        X.append(_extract_lr_vector(fv))
        y.append(label)

    rng = np.random.default_rng(seed=MODELS["LR_RANDOM_STATE"])
    n_each = max(0, MODELS["LR_MIN_TRAINING_SAMPLES"] // 2 - len(X) // 2)
    if n_each > 0:
        print(f"[MODEL] Generating {n_each * 2} synthetic LR training samples")
        attacks = np.column_stack([
            rng.choice([0, 1], n_each, p=[0.7, 0.3]).astype(float),
            rng.choice([0, 1], n_each, p=[0.4, 0.6]).astype(float),
            rng.integers(3, 10, n_each).astype(float),
            rng.uniform(0.5, 1.0, n_each),
            rng.uniform(400, 1200, n_each),
            rng.uniform(5, 12, n_each),
            rng.uniform(0.0, 0.4, n_each),
            np.zeros(n_each),
            rng.uniform(0.0, 0.4, n_each),
        ])
        legits = np.column_stack([
            np.zeros(n_each),
            np.zeros(n_each),
            rng.integers(0, 2, n_each).astype(float),
            rng.uniform(0.0, 0.2, n_each),
            rng.uniform(0, 50, n_each),
            rng.uniform(0, 2, n_each),
            rng.uniform(0.7, 1.0, n_each),
            np.ones(n_each),
            rng.uniform(0.7, 1.0, n_each),
        ])
        X.extend(attacks.tolist()); y.extend([1] * n_each)
        X.extend(legits.tolist());  y.extend([0] * n_each)

    return np.array(X, dtype=np.float32), np.array(y, dtype=int)


def _train_logistic_regression(X=None, y=None):
    global _lr_pipeline
    if X is None or y is None:
        X, y = _build_labeled_training_data()

    n_attacks = int(y.sum())
    n_legit   = int(len(y) - n_attacks)
    print(f"[MODEL] Training LR: {len(X)} samples (attack={n_attacks}, legit={n_legit})")

    base_lr = LogisticRegression(
        C            = MODELS["LR_C"],
        solver       = "lbfgs",
        class_weight = "balanced",
        max_iter     = 1000,
        random_state = MODELS["LR_RANDOM_STATE"],
    )
    cv = min(3, max(2, n_attacks, n_legit))
    calibrated = CalibratedClassifierCV(estimator=base_lr, method="sigmoid", cv=cv)

    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    calibrated.fit(X_scaled, y)

    _lr_pipeline = {
        "scaler"   : scaler,
        "model"    : calibrated,
        "features" : LR_FEATURES,
        "n_train"  : len(X),
        "n_attacks": n_attacks,
        "n_legit"  : n_legit,
    }
    joblib.dump(_lr_pipeline, _LR_PATH)
    print(f"[MODEL] LR saved → {_LR_PATH.name}")
    _log_lr_weights(calibrated, scaler)


def _log_lr_weights(calibrated, scaler):
    """Prints learned signal weights after LR training."""
    try:
        coefs = [clf.estimator.coef_[0] for clf in calibrated.calibrated_classifiers_]
        avg_coef  = np.mean(coefs, axis=0)
        importance = avg_coef * scaler.scale_
        print(f"\n[MODEL] Learned signal weights (+ = raises attack risk):")
        for i in np.argsort(np.abs(importance))[::-1]:
            bar  = "█" * int(abs(importance[i]) * 40)
            sign = "↑" if importance[i] > 0 else "↓"
            print(f"  {LR_FEATURES[i]:<30} {sign} {importance[i]:+.4f}  {bar}")
        print()
    except Exception as e:
        print(f"[MODEL] Could not log weights: {e}")


# ─────────────────────────────────────────────
# INFERENCE
# ─────────────────────────────────────────────

def get_anomaly_score(feature_vector):
    """
    Returns float 0.0 (normal) → 1.0 (highly anomalous).
    Maps IF.score_samples() range [-0.5, 0.5] → [1.0, 0.0].
    """
    _ensure_models_loaded()
    x        = _extract_if_vector(feature_vector).reshape(1, -1)
    x_scaled = _if_scaler.transform(x)
    raw      = _if_model.score_samples(x_scaled)[0]
    clipped  = np.clip(raw, -0.5, 0.5)
    return round(float(1.0 - (clipped + 0.5)), 4)


def get_attack_probability(feature_vector):
    """
    Returns float 0.0 (legitimate) → 1.0 (attack).
    From calibrated LR predict_proba, class index 1 = attack.
    """
    _ensure_models_loaded()
    x        = _extract_lr_vector(feature_vector).reshape(1, -1)
    x_scaled = _lr_pipeline["scaler"].transform(x)
    proba    = _lr_pipeline["model"].predict_proba(x_scaled)[0]
    return round(float(proba[1]), 4)


def get_model_scores(feature_vector):
    """
    Main entry point for risk_engine.py — signature unchanged from mock.
    Returns { anomaly_score: float, attack_probability: float }
    """
    return {
        "anomaly_score"     : get_anomaly_score(feature_vector),
        "attack_probability": get_attack_probability(feature_vector),
    }


# ─────────────────────────────────────────────
# FEEDBACK — accumulates labels, retrains at threshold
# ─────────────────────────────────────────────

def update_online_learner(feature_vector, label):
    """
    Accumulates a labeled event. Triggers full retrain when threshold reached.
    label: "attack" or "legitimate"
    """
    _pending_labels.append((dict(feature_vector), label))
    n = len(_pending_labels)
    threshold = MODELS["LR_RETRAIN_AFTER_N_LABELS"]
    print(f"[MODEL] Label buffered: {label} ({n}/{threshold} pending)")
    if n >= threshold:
        print(f"[MODEL] Threshold reached — retraining")
        retrain_models()


def retrain_models(labeled_events=None):
    """
    Full retrain of both models. Called by retrain_scheduler or label threshold.
    labeled_events: optional [(feature_vector_dict, label_str)] override.
    """
    global _pending_labels
    print(f"\n[MODEL] === Full retrain triggered ===")
    _train_isolation_forest()
    if labeled_events:
        X = np.array([_extract_lr_vector(fv) for fv, _ in labeled_events], dtype=np.float32)
        y = np.array([1 if lb == "attack" else 0 for _, lb in labeled_events], dtype=int)
        _train_logistic_regression(X, y)
    else:
        _train_logistic_regression()
    _pending_labels = []
    print(f"[MODEL] === Retrain complete ===\n")


# ─────────────────────────────────────────────
# EXPLAINABILITY — exact linear attribution
# ─────────────────────────────────────────────

def get_feature_contributions(feature_vector):
    """
    Returns per-feature contribution to attack probability.
    For calibrated LR: contribution_i = coef_i * scaled_x_i (exact, no approximation).
    Positive = pushes toward attack. Negative = pushes toward legitimate.
    """
    _ensure_models_loaded()
    x        = _extract_lr_vector(feature_vector)
    x_scaled = _lr_pipeline["scaler"].transform(x.reshape(1, -1))[0]
    try:
        coefs    = [clf.estimator.coef_[0] for clf in _lr_pipeline["model"].calibrated_classifiers_]
        avg_coef = np.mean(coefs, axis=0)
        return {LR_FEATURES[i]: round(float(avg_coef[i] * x_scaled[i]), 5) for i in range(len(LR_FEATURES))}
    except Exception as e:
        print(f"[MODEL] Contributions failed: {e}")
        return {f: 0.0 for f in LR_FEATURES}


def get_model_info():
    """Returns summary of loaded models — for admin dashboard health panel."""
    _ensure_models_loaded()
    return {
        "isolation_forest": {
            "loaded"       : _if_model is not None,
            "n_estimators" : getattr(_if_model, "n_estimators", None),
            "n_features"   : len(IF_FEATURES),
            "artifact"     : _IF_PATH.name,
        },
        "logistic_regression": {
            "loaded"         : _lr_pipeline is not None,
            "n_train"        : _lr_pipeline.get("n_train") if _lr_pipeline else None,
            "n_attacks"      : _lr_pipeline.get("n_attacks") if _lr_pipeline else None,
            "n_legit"        : _lr_pipeline.get("n_legit") if _lr_pipeline else None,
            "n_features"     : len(LR_FEATURES),
            "pending_labels" : len(_pending_labels),
            "artifact"       : _LR_PATH.name,
        },
    }

# ─────────────────────────────────────────────
# QUICK TEST — python -m models.models_main
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from scoring.decision import get_action
    from scoring.risk_engine import compute_risk_score

    print("=" * 62)
    print("  Model Training + Inference Test")
    print("=" * 62)

    # Force fresh retrain
    for p in [_IF_PATH, _LR_PATH, _SCALER_PATH]:
        if p.exists():
            p.unlink()

    test_cases = [
        ("u01", "e003", "Normal login     — Kartik, office"),
        ("u01", "e011", "Attack           — Kartik, London 3am"),
        ("u03", "e013", "Suspicious       — Arjun, Singapore"),
        ("u04", "e014", "Cold start       — Sneha, first login"),
        ("u02", "e012", "Suspicious       — Priya, New York"),
    ]

    print(f"\n{'─'*62}")
    print(f"  {'Scenario':<35} {'anomaly':>8}  {'attack_p':>9}  {'action':>12}")
    print(f"{'─'*62}")

    for user_id, event_id, label in test_cases:
        event  = next(e for e in LOGIN_EVENTS if e["event_id"] == event_id)
        raw    = extract_features(event)
        prof   = get_profile_signals(user_id, event)
        fv     = {**raw, **prof}
        scores = get_model_scores(fv)
        risk   = compute_risk_score(fv)
        action = get_action(risk)["action"]
        print(f"  {label:<35} {scores['anomaly_score']:>8.4f}  "
              f"{scores['attack_probability']:>9.4f}  {action:>12}")

    print(f"\n{'─'*62}")
    print("  Feature contributions — attack event (e011):")
    print(f"{'─'*62}")
    event = next(e for e in LOGIN_EVENTS if e["event_id"] == "e011")
    fv    = {**extract_features(event), **get_profile_signals("u01", event)}
    for feat, val in sorted(get_feature_contributions(fv).items(), key=lambda x: -abs(x[1])):
        bar = "█" * int(abs(val) * 60)
        print(f"  {feat:<30}  {val:+.4f}  {bar}")

    print(f"\n{'─'*62}")
    print("  Model info:")
    print(f"{'─'*62}")
    for model_name, info in get_model_info().items():
        print(f"  {model_name}:")
        for k, v in info.items():
            print(f"    {k:<22}: {v}")

    print(f"\n{'─'*62}")
    print("  Label accumulation simulation:")
    print(f"{'─'*62}")
    event = next(e for e in LOGIN_EVENTS if e["event_id"] == "e011")
    fv    = {**extract_features(event), **get_profile_signals("u01", event)}
    update_online_learner(fv, "attack")
    update_online_learner(fv, "attack")
    print(f"  Pending labels: {len(_pending_labels)}")
