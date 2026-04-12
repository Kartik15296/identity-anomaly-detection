# models/trainer.py
"""
Trainer: Incremental Retraining Pipeline
This script retrains models using existing DB data.
- Does NOT clear the database
- Keeps all existing events and user data
- Retrains models with new feedback
- Updates selectively: model artifacts and user/group/cluster parameters
"""

import joblib
import numpy as np
from pathlib import Path
from datetime import datetime
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler

from config.hyperparams import MODELS
from database.database_crud import (
    get_all_login_events, 
    get_all_feedback_labels,
    get_all_user_profiles,
    db
)
from features.extractor import extract_features
from profiling.cold_start import get_profile_signals

_ARTIFACT_DIR = Path(__file__).parent / "artifacts"
_ARTIFACT_DIR.mkdir(exist_ok=True)

_IF_PATH     = _ARTIFACT_DIR / "isolation_forest.pkl"
_SCALER_PATH = _ARTIFACT_DIR / "scaler.pkl"
_LR_PATH     = _ARTIFACT_DIR / "logistic_regression.pkl"

IF_FEATURES = [
    "login_hour", "failed_attempts", "new_device", "new_country",
    "ip_known", "device_trust_score", "hour_deviation",
    "travel_speed_kmh", "distance_km", "peer_deviation",
    "peer_membership_confidence",
]

LR_FEATURES = [
    "new_device", "new_country", "failed_attempts", "peer_deviation",
    "travel_speed_kmh", "hour_deviation", "device_trust_score",
    "ip_known", "peer_membership_confidence",
]

def _extract_if_vector(fv):
    return np.array([float(fv.get(k, 0.0)) for k in IF_FEATURES], dtype=np.float32)

def _extract_lr_vector(fv):
    return np.array([float(fv.get(k, 0.0)) for k in LR_FEATURES], dtype=np.float32)

def build_normal_training_data():
    """
    Builds IF training data from existing DB (incremental).
    Uses all approved/clean events for normal class definition.
    """
    print("[TRAINER] Building normal training data from existing DB...")
    
    approved_ids = {f["event_id"] for f in get_all_feedback_labels() if f.get("label") == "legitimate"}
    normal_vectors = []

    for event in get_all_login_events():
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
        print(f"[TRAINER] Generating {n_synth} synthetic normal samples for IF")
        # ... (Include your synthetic generation logic here) ...
        pass # Replaced with pass for brevity in this example

    return np.array(normal_vectors, dtype=np.float32)

def build_labeled_training_data(pending_labels=None):
     """
     Builds LR training data from existing DB (incremental).
     Uses feedback labels accumulated in the system.
     """
     if pending_labels is None:
         pending_labels = []

     print("[TRAINER] Building labeled training data from existing DB...")
     
     event_map = {e["event_id"]: e for e in get_all_login_events()}
     X, y = [], []

     all_feedback = list(get_all_feedback_labels()) + [
         {"event_id": "synthetic", "label": lb, "_fv": fv}
         for fv, lb in pending_labels
     ]

     for fb in all_feedback:
         label = 1 if fb.get("label") == "attack" else 0
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

     # ... (Include your LR synthetic generation logic here) ...
     return np.array(X, dtype=np.float32), np.array(y, dtype=int)


def train_isolation_forest():
    """
    Trains and saves the Isolation Forest model.
    Retrains from scratch using all events in DB.
    """
    print("[TRAINER] Training Isolation Forest...")
    
    X = build_normal_training_data()
    
    if len(X) == 0:
        print("[TRAINER] ✗ No training data available for IF")
        return False
    
    print(f"[TRAINER] Training IF on {len(X)} normal samples")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators  = MODELS["IF_N_ESTIMATORS"],
        contamination = MODELS["IF_CONTAMINATION"],
        max_samples   = "auto",
        random_state  = MODELS["IF_RANDOM_STATE"],
        n_jobs        = -1,
    )
    model.fit(X_scaled)
    joblib.dump(model,  _IF_PATH)
    joblib.dump(scaler, _SCALER_PATH)
    print(f"[TRAINER] ✓ IF model saved to artifacts")
    return True


def train_logistic_regression(X=None, y=None, pending_labels=None):
    """
    Trains and saves the Calibrated Logistic Regression model.
    Retrains from scratch using all feedback in DB.
    """
    if X is None or y is None:
        X, y = build_labeled_training_data(pending_labels)

    n_attacks = int(y.sum())
    n_legit   = int(len(y) - n_attacks)
    print(f"[TRAINER] Training LR: {len(X)} samples (attack={n_attacks}, legit={n_legit})")

    if len(X) == 0:
        print("[TRAINER] ✗ No training data available for LR")
        return False

    base_lr = LogisticRegression(
        C            = MODELS["LR_C"],
        solver       = "lbfgs",
        class_weight = "balanced",
        max_iter     = 1000,
        random_state = MODELS["LR_RANDOM_STATE"],
    )

    cv = min(3, max(2, min(n_attacks, n_legit)))
    if cv < 2:
        print("[TRAINER] ⚠ Insufficient samples for cross-validation")
        calibrated = base_lr
    else:
        calibrated = CalibratedClassifierCV(estimator=base_lr, method="sigmoid", cv=cv)

    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    calibrated.fit(X_scaled, y)

    pipeline = {
        "scaler"   : scaler,
        "model"    : calibrated,
        "features" : LR_FEATURES,
        "n_train"  : len(X),
        "n_attacks": n_attacks,
        "n_legit"  : n_legit,
        "timestamp": datetime.now().isoformat(),
    }
    joblib.dump(pipeline, _LR_PATH)
    print(f"[TRAINER] ✓ LR model saved to artifacts")
    return True


def update_user_parameters(batch_size=50):
    """
    Updates user-level parameters based on recent feedback.
    Called after model retraining to update selective user/cluster attributes.
    """
    print("[TRAINER] Updating user-level parameters...")
    
    try:
        profiles = get_all_user_profiles()
        
        for idx, profile in enumerate(profiles):
            user_id = profile.get("user_id")
            
            # Get user's recent feedback
            user_events = [e for e in get_all_login_events() if e["user_id"] == user_id]
            user_feedback = [f for f in get_all_feedback_labels() if f["event_id"] in {e["event_id"] for e in user_events}]
            
            if user_feedback:
                # Update attack/legitimate ratio
                attacks = sum(1 for f in user_feedback if f.get("label") == "attack")
                legit = sum(1 for f in user_feedback if f.get("label") == "legitimate")
                
                update_doc = {
                    "last_updated": datetime.now().isoformat(),
                    "recent_attacks": attacks,
                    "recent_legit": legit,
                }
                
                db.user_profiles.update_one(
                    {"user_id": user_id},
                    {"$set": update_doc}
                )
            
            if (idx + 1) % batch_size == 0:
                print(f"[TRAINER] ✓ Updated {idx + 1} user profiles")
        
        print(f"[TRAINER] ✓ User parameters updated for {len(profiles)} profiles")
        return True
    
    except Exception as e:
        print(f"[TRAINER] ✗ Error updating user parameters: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("TRAINER: INCREMENTAL RETRAINING PIPELINE")
    print("=" * 70 + "\n")
    
    try:
        # Check if DB has data
        events_count = len(get_all_login_events())
        feedback_count = len(get_all_feedback_labels())
        
        if events_count == 0:
            print("[TRAINER] ✗ No events in database. Use bootstrap_models.py first!")
            exit(1)
        
        print(f"[TRAINER] Found {events_count} events and {feedback_count} feedback labels")
        
        # Train models
        if_success = train_isolation_forest()
        lr_success = train_logistic_regression()
        
        # Update user parameters
        if if_success and lr_success:
            update_user_parameters()
        
        # Final summary
        print("\n" + "=" * 70)
        if if_success and lr_success:
            print("✓ RETRAINING COMPLETE: Models retrained and parameters updated")
        else:
            print("⚠ RETRAINING PARTIAL: Some models failed to train")
        print("=" * 70 + "\n")
    
    except Exception as e:
        print(f"\n✗ RETRAINING FAILED: {e}\n")
        raise