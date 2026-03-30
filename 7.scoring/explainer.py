# 7.scoring/explainer.py
# Produces human-readable reason codes using exact SHAP values from the ML layer.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from hyperparams import SCORING
from models_main import get_feature_contributions

# ─────────────────────────────────────────────
# REASON CODE TEMPLATES
# ─────────────────────────────────────────────
REASON_TEMPLATES = {
    "new_device"        : "Login from an unrecognized device",
    "new_country"       : "Login from a new country ({country})",
    "peer_deviation"    : "Behavior deviates significantly from peer group",
    "travel_speed_kmh"  : "Physically impossible travel speed detected",
    "hour_deviation"    : "Login occurred outside typical working hours",
    "failed_attempts"   : "Multiple failed login attempts prior to success",
    "ip_known"          : "Unrecognized IP address",
    "device_trust_score": "Login from a device with low historical trust",
}

def get_reason_codes(feature_vector, event_context=None):
    """
    Generates dynamic reason codes based on actual ML feature importance.
    """
    # 1. Fetch exact SHAP values from the ML model
    contributions = get_feature_contributions(feature_vector)

    if not contributions:
        return ["No specific anomaly indicators detected."]

    # 2. Sort features by highest positive risk contribution
    # We only care about features that pushed the attack probability UP
    sorted_feats = sorted(contributions.items(), key=lambda x: x[1], reverse=True)

    reason_codes = []
    top_n = SCORING.get("TOP_REASON_CODES", 3)

    # 3. Map the top mathematically significant features to human text
    for feat, shap_value in sorted_feats:
        # Ignore features that actually lowered the risk score (negative SHAP)
        if shap_value <= 0:
            continue 
        
        if feat in REASON_TEMPLATES:
            msg = REASON_TEMPLATES[feat]
            
            # Inject context if available
            if feat == "new_country" and event_context and "country" in event_context:
                msg = msg.format(country=event_context["country"])
            else:
                msg = msg.replace(" ({country})", "")
            
            reason_codes.append(msg)
        
        if len(reason_codes) >= top_n:
            break
            
    # Fallback if the attack was caused by complex latent patterns
    if not reason_codes:
        reason_codes.append("Anomaly detected via complex multivariate patterns.")

    return reason_codes