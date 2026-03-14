# 8.feedback/label_collector.py
# Converts MFA outcomes and admin decisions into structured feedback labels.
# These labels feed into:
#   - profile_updater.py  (update user baseline)
#   - retrain_scheduler.py (accumulate training data)
#   - models_main.py       (online learner incremental update)
#
# Label sources:
#   mfa_pass      → login confirmed legitimate
#   mfa_fail      → login likely malicious
#   admin_approve → admin confirmed legitimate
#   admin_block   → admin confirmed attack

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hyperparams import register_paths
register_paths()

from datetime import datetime, timezone
from mock_db import (
    FEEDBACK_LABELS,
    get_event_by_id,
    get_user_profile,
)
from models_main import update_online_learner


# ─────────────────────────────────────────────
# LABEL CONSTANTS
# ─────────────────────────────────────────────
LABEL_LEGITIMATE = "legitimate"
LABEL_ATTACK     = "attack"

# Which outcomes map to which label
OUTCOME_TO_LABEL = {
    "mfa_pass"      : LABEL_LEGITIMATE,
    "admin_approve" : LABEL_LEGITIMATE,
    "mfa_fail"      : LABEL_ATTACK,
    "admin_block"   : LABEL_ATTACK,
}


def record_feedback(event_id, outcome, notes=""):
    """
    Main entry point for all feedback.
    Records a labeled event and triggers downstream updates.

    event_id : ID of the login event being labeled
    outcome  : "mfa_pass" | "mfa_fail" | "admin_approve" | "admin_block"
    notes    : optional admin note

    Returns the created feedback label dict.
    """
    if outcome not in OUTCOME_TO_LABEL:
        print(f"[WARN] Unknown outcome '{outcome}' — skipping feedback")
        return None

    event = get_event_by_id(event_id)
    if not event:
        print(f"[WARN] Event '{event_id}' not found — skipping feedback")
        return None

    label = OUTCOME_TO_LABEL[outcome]

    feedback = {
        "event_id"   : event_id,
        "user_id"    : event["user_id"],
        "label"      : label,
        "source"     : outcome,
        "notes"      : notes,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Store in mock_db feedback labels
    # When PostgreSQL is added → INSERT INTO feedback_labels
    FEEDBACK_LABELS.append(feedback)

    print(f"[FEEDBACK] event={event_id} user={event['user_id']} "
          f"outcome={outcome} label={label}")

    # ── Trigger downstream updates ────────────────────────────────
    _trigger_profile_update(event, outcome, label)
    _trigger_model_update(event, label)

    return feedback


def _trigger_profile_update(event, outcome, label):
    """
    Triggers profile_updater to update user baseline
    based on the feedback outcome.
    """
    from profile_updater import update_profile_from_feedback
    update_profile_from_feedback(event, outcome, label)


def _trigger_model_update(event, label):
    """
    Passes the labeled event to the online learner for incremental update.
    Builds a minimal feature vector from the raw event for the model.
    """
    from extractor import extract_features
    from cold_start import get_profile_signals

    user_id         = event["user_id"]
    raw_features    = extract_features(event)
    profile_signals = get_profile_signals(user_id, event)
    feature_vector  = {**raw_features, **profile_signals}

    update_online_learner(feature_vector, label)


def get_all_labels():
    """Returns all recorded feedback labels."""
    return FEEDBACK_LABELS


def get_labels_for_user(user_id):
    """Returns all feedback labels for a specific user."""
    return [f for f in FEEDBACK_LABELS if f.get("user_id") == user_id]


def get_recent_labels(since_timestamp):
    """
    Returns feedback labels recorded after a given timestamp string.
    Used by retrain_scheduler to count new labels since last retrain.
    """
    return [
        f for f in FEEDBACK_LABELS
        if f.get("recorded_at", "") >= since_timestamp
    ]


def count_labels_since(since_timestamp):
    """Returns count of new labeled events since a given timestamp."""
    return len(get_recent_labels(since_timestamp))


# ─────────────────────────────────────────────
# QUICK TEST — python label_collector.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    from mock_db import FEEDBACK_LABELS

    print(f"Existing labels in mock_db : {len(FEEDBACK_LABELS)}")

    print("\n── MFA pass — Arjun Singapore travel confirmed legit ──")
    fb = record_feedback("e013", "mfa_pass", notes="User confirmed business travel")
    print(f"Recorded : {fb}")

    print("\n── Admin block — Kartik London attack confirmed ────────")
    fb = record_feedback("e011", "admin_block", notes="Confirmed account takeover")
    print(f"Recorded : {fb}")

    print("\n── Admin approve — Priya New York confirmed legit ──────")
    fb = record_feedback("e012", "admin_approve", notes="Confirmed business trip")
    print(f"Recorded : {fb}")

    print(f"\nTotal labels now : {len(FEEDBACK_LABELS)}")
    print(f"Labels for u01   : {len(get_labels_for_user('u01'))}")