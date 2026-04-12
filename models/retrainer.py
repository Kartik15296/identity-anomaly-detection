# models/retrainer.py (The Caller / Maintenance Engine): This file contains the logic for warm-starting or full retraining based on accumulated feedback loops. This is what your weekly cron job or threshold-trigger will call.

# models/retrainer.py
import numpy as np
from config.hyperparams import MODELS
from models.trainer import train_isolation_forest, train_logistic_regression, _extract_lr_vector

# In-memory buffer for labels. In a true production system, this would be a DB query.
_pending_labels = []

def update_online_learner(feature_vector, label):
    """
    Accumulates a labeled event. Triggers full retrain when threshold reached.
    label: "attack" or "legitimate"
    """
    global _pending_labels
    _pending_labels.append((dict(feature_vector), label))
    n = len(_pending_labels)
    threshold = MODELS["LR_RETRAIN_AFTER_N_LABELS"]
    
    print(f"[RETRAINER] Label buffered: {label} ({n}/{threshold} pending)")
    
    if n >= threshold:
        print(f"[RETRAINER] Threshold reached ({threshold}) — Triggering Retrain")
        execute_retrain()

def execute_retrain(labeled_events=None):
    """
    Full retrain of both models. Called by threshold or scheduled job.
    """
    global _pending_labels
    print(f"\n[RETRAINER] === Full retrain initiated ===")
    
    # Always retrain unsupervised IF
    train_isolation_forest()
    
    # Handle supervised LR retraining
    if labeled_events:
        X = np.array([_extract_lr_vector(fv) for fv, _ in labeled_events], dtype=np.float32)
        y = np.array([1 if lb == "attack" else 0 for _, lb in labeled_events], dtype=int)
        train_logistic_regression(X, y)
    else:
        # Use pending labels to build data
        train_logistic_regression(pending_labels=_pending_labels)
        
    # Flush the buffer after successful retrain
    _pending_labels = []
    print(f"[RETRAINER] === Retrain complete ===\n")
    
    # IMPORTANT: You must signal the inference layer to reload the models from disk
    from models.inference import force_model_reload
    force_model_reload()

def get_pending_label_count():
    return len(_pending_labels)