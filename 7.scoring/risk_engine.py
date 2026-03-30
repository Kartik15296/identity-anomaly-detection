# 7.scoring/risk_engine.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from models_main import get_model_scores
from decision import get_action
from explainer import get_reason_codes

def compute_full_result(feature_vector, event=None):
    """
    Computes final risk score driven purely by the Dual-Model ML architecture.
    """
    # 1. Fetch pure ML predictions
    scores = get_model_scores(feature_vector)
    anomaly_score = scores.get("anomaly_score", 0.0)       # Unsupervised IF
    attack_prob   = scores.get("attack_probability", 0.0)  # Supervised LR
    
    # 2. Blend ML models into a 0-100 Risk Score
    # We heavily weight the supervised model (80%), using the 
    # unsupervised model (20%) to catch zero-day anomalies.
    risk_score = (attack_prob * 0.8 + anomaly_score * 0.2) * 100
    risk_score = round(min(max(risk_score, 0), 100), 2)
    
    # 3. Evaluate Policy
    decision = get_action(risk_score)
    
    # 4. Extract Dynamic SHAP Explanations
    reason_codes = get_reason_codes(feature_vector, event_context=event)
    
    return {
        "event_id"    : event["event_id"] if event else "unknown",
        "user_id"     : event["user_id"] if event else "unknown",
        "risk_score"  : risk_score,
        "action"      : decision["action"],
        "description" : decision["description"],
        "reason_codes": reason_codes,
        "ml_scores"   : scores
    }