# integration/processor.py
# The single entry point for the full login scoring pipeline.
# Takes one raw login event, runs every layer in order,
# returns a complete result dict.
#
# This is what api.py calls for every alert.
# This is what the terminal simulator will call for live testing.
#
# Pipeline order:
#   1. Feature extraction    (features/extractor.py)
#   2. Profile signals       (profiling/cold_start.py)
#   3. Merge feature vector  (raw + profile combined)
#   4. Risk scoring          (scoring/risk_engine.py)
#   5. Return full result

from database.mock_db import LOGIN_EVENTS
from features.extractor import extract_features
from profiling.cold_start import get_profile_signals
from scoring.risk_engine import compute_full_result


def process_login_event(event):
    """
    Runs a raw login event through the full pipeline.

    Input  : one login event dict (from mock_db or live ingestion)
    Output : complete result dict

    {
        "event_id"     : str,
        "user_id"      : str,
        "risk_score"   : float  0–100,
        "action"       : "allow" | "mfa" | "limited_session" | "block",
        "description"  : str,
        "reason_codes" : [ { feature, contribution, reason }, ... ],
        "signals"      : { normalized signal values },
        "feature_vector": { full merged feature dict },
        "pipeline_meta": { phase, profile_weight, cold_start info }
    }
    """
    user_id = event["user_id"]

    # ── Step 1: Raw feature extraction ───────────────────────────
    # features/extractor.py
    # Login hour, device/country/IP checks, geo distance, travel speed
    raw_features = extract_features(event)

    # ── Step 2: Profile signals ───────────────────────────────────
    # profiling/cold_start.py
    # Peer deviation, cold start phase, blended profile signals
    profile_signals = get_profile_signals(user_id, event)

    # ── Step 3: Merge into final feature vector ───────────────────
    # profile_signals override raw_features for blended signals
    # (new_device, new_country, ip_known are blended in cold_start)
    feature_vector = {**raw_features, **profile_signals}

    # ── Step 4: Score ─────────────────────────────────────────────
    # scoring/risk_engine.py
    # Calls models/models_main.py for anomaly_score + attack_probability
    # Combines all signals into risk_score 0–100
    # Returns action + reason codes
    result = compute_full_result(feature_vector, event=event)

    # ── Step 5: Build full result ─────────────────────────────────
    return {
        "event_id"      : event.get("event_id"),
        "user_id"       : user_id,
        "risk_score"    : result["risk_score"],
        "action"        : result["action"],
        "description"   : result["description"],
        "reason_codes"  : result["reason_codes"],
        "signals"       : result["signals"],
        "feature_vector": feature_vector,
        "pipeline_meta" : {
            "phase"         : profile_signals.get("phase"),
            "profile_weight": profile_signals.get("profile_weight"),
            "peer_deviation": profile_signals.get("peer_deviation"),
        },
    }


# ─────────────────────────────────────────────
# QUICK TEST — python -m integration.processor
# ─────────────────────────────────────────────
if __name__ == "__main__":
    test_cases = [
        ("e003", "Normal login    — Kartik, office"),
        ("e011", "Attack          — Kartik, London 3am"),
        ("e013", "Suspicious      — Arjun, Singapore travel"),
        ("e014", "Cold start      — Sneha, first login"),
        ("e012", "Suspicious      — Priya, New York"),
    ]

    for event_id, label in test_cases:
        event  = next(e for e in LOGIN_EVENTS if e["event_id"] == event_id)
        result = process_login_event(event)

        print(f"\n{'═'*58}")
        print(f"  {label}")
        print(f"{'─'*58}")
        print(f"  risk_score   : {result['risk_score']}")
        print(f"  action       : {result['action']}")
        print(f"  phase        : {result['pipeline_meta']['phase']}")
        print(f"  peer_dev     : {result['pipeline_meta']['peer_deviation']}")
        if result["reason_codes"]:
            print(f"  reasons:")
            for r in result["reason_codes"]:
                print(f"    [{r['contribution']:.3f}]  {r['reason']}")
        else:
            print(f"  reasons      : none — login looks clean")
