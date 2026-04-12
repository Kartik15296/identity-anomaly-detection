# models/inference.py
#(The Lazy Loader & Scoring Engine): This is the high-performance module. It lazily loads the artifacts (.pkl files) into memory exactly once and provides the scoring functions used by your real-time risk engine.

import joblib
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any
from .trainer import IF_FEATURES, LR_FEATURES

# Paths match the trainer
_ARTIFACT_DIR = Path(__file__).parent / "artifacts"
_IF_PATH     = _ARTIFACT_DIR / "isolation_forest.pkl"
_SCALER_PATH = _ARTIFACT_DIR / "scaler.pkl"
_LR_PATH     = _ARTIFACT_DIR / "logistic_regression.pkl"

# Model Registry
_if_model: Optional[Any]    = None
_if_scaler: Optional[Any]   = None
_lr_pipeline: Optional[Dict[str, Any]] = None

def _extract_if_vector(fv):
    return np.array([float(fv.get(k, 0.0)) for k in IF_FEATURES], dtype=np.float32)

def _extract_lr_vector(fv):
    return np.array([float(fv.get(k, 0.0)) for k in LR_FEATURES], dtype=np.float32)

def _ensure_models_loaded():
    """Lazy loader. Only reads from disk if models are missing from memory."""
    global _if_model, _if_scaler, _lr_pipeline
    
    if _if_model is None or _if_scaler is None:
        if _IF_PATH.exists() and _SCALER_PATH.exists():
            _if_model  = joblib.load(_IF_PATH)
            _if_scaler = joblib.load(_SCALER_PATH)
        else:
            raise FileNotFoundError("Isolation Forest artifacts missing. Run trainer.py first.")
            
    if _lr_pipeline is None:
        if _LR_PATH.exists():
            _lr_pipeline = joblib.load(_LR_PATH)
        else:
            raise FileNotFoundError("Logistic Regression artifacts missing. Run trainer.py first.")

def force_model_reload():
    """Called by retrainer to flush memory and force disk load on next event."""
    global _if_model, _if_scaler, _lr_pipeline
    _if_model, _if_scaler, _lr_pipeline = None, None, None
    print("[INFERENCE] Model cache cleared. Will reload on next request.")

def get_anomaly_score(feature_vector):
    _ensure_models_loaded()
    assert _if_scaler is not None and _if_model is not None
    x = _extract_if_vector(feature_vector).reshape(1, -1)
    x_scaled = _if_scaler.transform(x)
    raw_score = _if_model.decision_function(x_scaled)[0]
    risk = 0.5 - raw_score
    return round(float(np.clip(risk, 0.0, 1.0)), 4)

def get_attack_probability(feature_vector):
    _ensure_models_loaded()
    assert _lr_pipeline is not None
    x = _extract_lr_vector(feature_vector).reshape(1, -1)
    x_scaled = _lr_pipeline["scaler"].transform(x)
    proba = _lr_pipeline["model"].predict_proba(x_scaled)[0]
    return round(float(proba[1]), 4)

def get_model_scores(feature_vector):
    return {
        "anomaly_score"     : get_anomaly_score(feature_vector),
        "attack_probability": get_attack_probability(feature_vector),
    }

def get_feature_contributions(feature_vector):
    """Returns exact linear attribution for LR model."""
    _ensure_models_loaded()
    assert _lr_pipeline is not None
    x = _extract_lr_vector(feature_vector)
    x_scaled = _lr_pipeline["scaler"].transform(x.reshape(1, -1))[0]
    try:
        coefs = [clf.estimator.coef_[0] for clf in _lr_pipeline["model"].calibrated_classifiers_]
        avg_coef = np.mean(coefs, axis=0)
        return {LR_FEATURES[i]: round(float(avg_coef[i] * x_scaled[i]), 5) for i in range(len(LR_FEATURES))}
    except Exception as e:
        return {f: 0.0 for f in LR_FEATURES}