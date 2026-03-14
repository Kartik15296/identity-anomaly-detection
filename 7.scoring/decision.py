# 7.scoring/decision.py
# Maps a risk score to a security action.
# Pure logic — no ML, no imports from other project modules.
# Thresholds loaded from hyperparams.
#
# Called by Integration/processor.py after risk_engine produces a score.

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from hyperparams import SCORING


# ─────────────────────────────────────────────
# ACTIONS
# String constants so nothing is hardcoded
# elsewhere in the project
# ─────────────────────────────────────────────
ACTION_ALLOW          = "allow"
ACTION_MFA            = "mfa"
ACTION_LIMITED        = "limited_session"
ACTION_BLOCK          = "block"


def get_action(risk_score):
    """
    Maps a risk score (0–100) to a security action.

    Thresholds from hyperparams.SCORING:
        0  – RISK_ALLOW   → allow login, no friction
        RISK_ALLOW – RISK_MFA     → step-up MFA required
        RISK_MFA   – RISK_LIMITED → scope-limited session
        RISK_LIMITED – 100        → block + admin alert

    Returns dict:
    {
        "action"      : "allow" | "mfa" | "limited_session" | "block",
        "risk_score"  : float,
        "description" : human readable explanation of the action
    }
    """
    allow   = SCORING["RISK_ALLOW"]
    mfa     = SCORING["RISK_MFA"]
    limited = SCORING["RISK_LIMITED"]

    if risk_score <= allow:
        return {
            "action"     : ACTION_ALLOW,
            "risk_score" : risk_score,
            "description": "Login looks normal. Access granted.",
        }
    elif risk_score <= mfa:
        return {
            "action"     : ACTION_MFA,
            "risk_score" : risk_score,
            "description": "Elevated risk detected. Step-up MFA required before access.",
        }
    elif risk_score <= limited:
        return {
            "action"     : ACTION_LIMITED,
            "risk_score" : risk_score,
            "description": "High risk detected. Limited read-only session granted. Full access requires MFA.",
        }
    else:
        return {
            "action"     : ACTION_BLOCK,
            "risk_score" : risk_score,
            "description": "Critical risk detected. Login blocked. Admin alert triggered.",
        }


def is_high_risk(risk_score):
    """Returns True if score requires any friction (MFA or above)."""
    return risk_score > SCORING["RISK_ALLOW"]


def requires_admin_alert(risk_score):
    """Returns True if score should trigger an admin alert."""
    return risk_score > SCORING["RISK_LIMITED"]


# ─────────────────────────────────────────────
# QUICK TEST — python decision.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    test_scores = [
        (15,  "Normal login"),
        (45,  "Slightly suspicious"),
        (72,  "High risk"),
        (88,  "Critical — attack likely"),
    ]

    for score, label in test_scores:
        result = get_action(score)
        print(f"\n  {label} (score={score})")
        print(f"  action      : {result['action']}")
        print(f"  description : {result['description']}")
        print(f"  admin alert : {requires_admin_alert(score)}")