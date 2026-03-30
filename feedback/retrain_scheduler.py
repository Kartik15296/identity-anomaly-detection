# feedback/retrain_scheduler.py
# Monitors retraining triggers and fires model retraining when conditions are met.
#
# Three independent triggers — any one fires retraining:
#   1. Drift trigger   — feature distribution shifted (PSI / KS test)
#   2. Time trigger    — N days elapsed since last retrain
#   3. Volume trigger  — N new labeled events accumulated
#
# Also handles weekly DBSCAN cluster rebuild.

from datetime import datetime, timedelta, timezone

from config.hyperparams import CLUSTERING, RETRAINING
from database.mock_db import FEEDBACK_LABELS, LOGIN_EVENTS
from features.drift_monitor import check_drift
from features.extractor import extract_features
from feedback.label_collector import count_labels_since, get_all_labels
from profiling.peer_cluster import rebuild_clusters


# ─────────────────────────────────────────────
# RETRAINING STATE
# Tracks last retrain timestamp and label count.
# When PostgreSQL is added → store in a retraining_log table.
# ─────────────────────────────────────────────
_retrain_state = {
    "last_retrain_at"    : None,   # timestamp of last model retrain
    "last_cluster_rebuild_at": None,   # timestamp of last DBSCAN rebuild
    "labels_at_last_retrain": 0,   # label count at time of last retrain
}


# ─────────────────────────────────────────────
# TRIGGER CHECKS
# ─────────────────────────────────────────────

def check_drift_trigger():
    """
    Checks if feature distributions have drifted enough to trigger retraining.
    Uses PSI and KS-test from drift_monitor.py.

    Baseline = features from first half of known events (training data proxy)
    Current  = features from recent labeled events

    Returns (triggered: bool, reason: str)
    """
    all_events = LOGIN_EVENTS

    if len(all_events) < 10:
        return False, "insufficient_data"

    # Split events into baseline and current
    midpoint       = len(all_events) // 2
    baseline_events = all_events[:midpoint]
    current_events  = all_events[midpoint:]

    baseline_features = []
    for e in baseline_events:
        try:
            baseline_features.append(extract_features(e))
        except Exception:
            continue

    current_features = []
    for e in current_events:
        try:
            current_features.append(extract_features(e))
        except Exception:
            continue

    if not baseline_features or not current_features:
        return False, "insufficient_data"

    report = check_drift(baseline_features, current_features)

    if report["drift_detected"]:
        drifted = [f for f, r in report["features"].items() if r["drifted"]]
        return True, f"drift_in: {', '.join(drifted)}"

    return False, "no_drift"


def check_time_trigger():
    """
    Checks if enough time has passed since last retraining.
    Returns (triggered: bool, reason: str)
    """
    interval_days = RETRAINING["INTERVAL_DAYS"]
    last_retrain  = _retrain_state["last_retrain_at"]

    if last_retrain is None:
        return True, "never_trained"

    last_dt  = datetime.strptime(last_retrain, "%Y-%m-%d %H:%M:%S")
    due_at   = last_dt + timedelta(days=interval_days)
    now      = datetime.now(timezone.utc).replace(tzinfo=None)

    if now >= due_at:
        days_overdue = (now - due_at).days
        return True, f"{interval_days}_days_elapsed (overdue by {days_overdue}d)"

    days_remaining = (due_at - now).days
    return False, f"next_retrain_in_{days_remaining}d"


def check_volume_trigger():
    """
    Checks if enough new labeled events have accumulated since last retrain.
    Returns (triggered: bool, reason: str)
    """
    min_labels   = RETRAINING["MIN_NEW_LABELS"]
    last_retrain = _retrain_state["last_retrain_at"]

    if last_retrain is None:
        current_count = len(get_all_labels())
        if current_count > 0:
            return True, f"never_trained_with_{current_count}_labels"
        return False, "no_labels_yet"

    new_count = count_labels_since(last_retrain)

    if new_count >= min_labels:
        return True, f"{new_count}_new_labels_since_last_retrain"

    return False, f"only_{new_count}_new_labels (need {min_labels})"


def check_cluster_rebuild_trigger():
    """
    Checks if DBSCAN clusters need to be rebuilt.
    Uses CLUSTERING["REBUILD_INTERVAL_DAYS"] from hyperparams.
    Returns (triggered: bool, reason: str)
    """
    interval_days    = CLUSTERING["REBUILD_INTERVAL_DAYS"]
    last_rebuild     = _retrain_state["last_cluster_rebuild_at"]

    if last_rebuild is None:
        return True, "never_rebuilt"

    last_dt        = datetime.strptime(last_rebuild, "%Y-%m-%d %H:%M:%S")
    due_at         = last_dt + timedelta(days=interval_days)
    now            = datetime.now(timezone.utc).replace(tzinfo=None)

    if now >= due_at:
        return True, f"{interval_days}_day_cluster_rebuild_due"

    days_remaining = (due_at - now).days
    return False, f"next_rebuild_in_{days_remaining}d"


# ─────────────────────────────────────────────
# RETRAINING EXECUTION
# ─────────────────────────────────────────────

def run_retrain(reason):
    """
    Executes model retraining.
    Calls models_main.py retraining interface.

    For now with mock setup:
        Logs what would happen and updates retrain state.
    When 6.models is ready:
        Calls real trainer.py to retrain Isolation Forest.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[RETRAIN] Triggered at {now}")
    print(f"[RETRAIN] Reason: {reason}")
    print(f"[RETRAIN] Total labeled events: {len(get_all_labels())}")

    # ── Collect training data ─────────────────────────────────────
    all_labels  = get_all_labels()
    attack_count = sum(1 for l in all_labels if l["label"] == "attack")
    legit_count  = sum(1 for l in all_labels if l["label"] == "legitimate")

    print(f"[RETRAIN] Label breakdown — attack={attack_count} legitimate={legit_count}")

    # ── Call model trainer ────────────────────────────────────────
    # When 6.models/trainer.py is ready:
    #   from trainer import retrain_isolation_forest
    #   retrain_isolation_forest(training_data)
    print(f"[RETRAIN] Model retraining would run here (6.models/trainer.py)")

    # ── Update retrain state ──────────────────────────────────────
    _retrain_state["last_retrain_at"]       = now
    _retrain_state["labels_at_last_retrain"] = len(all_labels)

    print(f"[RETRAIN] Complete — state updated")
    return True


def run_cluster_rebuild():
    """
    Executes DBSCAN cluster rebuild.
    Calls peer_cluster.rebuild_clusters().
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n[CLUSTERS] Rebuild triggered at {now}")
    assignments = rebuild_clusters()
    print(f"[CLUSTERS] New assignments: {assignments}")

    _retrain_state["last_cluster_rebuild_at"] = now
    return assignments


# ─────────────────────────────────────────────
# MAIN SCHEDULER FUNCTION
# Call this on a schedule (e.g. daily cron job)
# ─────────────────────────────────────────────

def run_scheduler():
    """
    Checks all triggers and fires retraining/rebuild if needed.
    Returns a report of what was checked and what fired.

    Call this:
        - Daily via a scheduled job
        - After every admin feedback action
        - After MFA batch processing
    """
    report = {
        "checked_at"      : datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "retrain_fired"   : False,
        "retrain_reason"  : None,
        "rebuild_fired"   : False,
        "rebuild_reason"  : None,
        "trigger_results" : {},
    }

    # ── Check model retraining triggers ──────────────────────────
    triggers = {
        "drift"  : check_drift_trigger,
        "time"   : check_time_trigger,
        "volume" : check_volume_trigger,
    }

    for name, check_fn in triggers.items():
        fired, reason = check_fn()
        report["trigger_results"][name] = {
            "fired": fired, "reason": reason
        }
        print(f"[SCHEDULER] {name:8} trigger: {'FIRED' if fired else 'ok'} — {reason}")

        if fired and not report["retrain_fired"]:
            report["retrain_fired"]  = True
            report["retrain_reason"] = f"{name}: {reason}"
            run_retrain(reason=f"{name}: {reason}")

    # ── Check cluster rebuild trigger ─────────────────────────────
    rebuild_fired, rebuild_reason = check_cluster_rebuild_trigger()
    report["trigger_results"]["cluster_rebuild"] = {
        "fired": rebuild_fired, "reason": rebuild_reason
    }
    print(f"[SCHEDULER] {'rebuild':8} trigger: {'FIRED' if rebuild_fired else 'ok'} — {rebuild_reason}")

    if rebuild_fired:
        report["rebuild_fired"]  = True
        report["rebuild_reason"] = rebuild_reason
        run_cluster_rebuild()

    return report


# ─────────────────────────────────────────────
# QUICK TEST — python -m feedback.retrain_scheduler
# ─────────────────────────────────────────────
if __name__ == "__main__":

    print("── Checking individual triggers ──────────────────────")
    drift_fired,  drift_reason  = check_drift_trigger()
    time_fired,   time_reason   = check_time_trigger()
    vol_fired,    vol_reason    = check_volume_trigger()
    rebuild_fired, rebuild_reason = check_cluster_rebuild_trigger()

    print(f"  Drift   : {'FIRED' if drift_fired  else 'ok'} — {drift_reason}")
    print(f"  Time    : {'FIRED' if time_fired   else 'ok'} — {time_reason}")
    print(f"  Volume  : {'FIRED' if vol_fired    else 'ok'} — {vol_reason}")
    print(f"  Rebuild : {'FIRED' if rebuild_fired else 'ok'} — {rebuild_reason}")

    print("\n── Running full scheduler ────────────────────────────")
    report = run_scheduler()

    print(f"\n── Scheduler report ──────────────────────────────────")
    print(f"  retrain_fired  : {report['retrain_fired']}")
    print(f"  retrain_reason : {report['retrain_reason']}")
    print(f"  rebuild_fired  : {report['rebuild_fired']}")
