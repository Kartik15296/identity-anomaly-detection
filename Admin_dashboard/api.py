# admin_dashboard/api.py
# FastAPI server — 3 endpoints only.
# Sits between the HTML frontend and all backend Python modules.
#
# Run from project root:
#   uvicorn admin_dashboard.api:app --reload --port 8000
#
# Endpoints:
#   GET  /alerts      → high risk login events for admin review
#   POST /feedback    → admin allow / block decision
#   GET  /stats       → summary counts for dashboard header

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database.mock_db import FEEDBACK_LABELS, LOGIN_EVENTS, USER_PROFILES
from features.extractor import extract_features
from feedback.label_collector import record_feedback
from profiling.cold_start import get_profile_signals
from scoring.decision import requires_admin_alert
from scoring.risk_engine import compute_full_result

app = FastAPI(title="Identity Anomaly Detection — Admin API")

# ── CORS — allow frontend to call the API ────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve static frontend files ──────────────────────────────────
dashboard_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=dashboard_dir), name="static")


# ─────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    event_id : str
    outcome  : str   # "admin_approve" or "admin_block"
    notes    : str = ""


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _build_alert(event):
    """
    Builds a single alert dict for the frontend from a raw login event.
    Runs the full scoring pipeline to get risk score and reason codes.
    """
    user_id  = event["user_id"]
    profile  = USER_PROFILES.get(user_id, {})

    # Run scoring pipeline
    try:
        raw_features    = extract_features(event)
        profile_signals = get_profile_signals(user_id, event)
        feature_vector  = {**raw_features, **profile_signals}
        result          = compute_full_result(feature_vector, event=event)
    except Exception as e:
        return None

    # Only surface events that need admin attention
    if not requires_admin_alert(result["risk_score"]):
        return None

    # Check if already actioned (exists in FEEDBACK_LABELS)
    already_actioned = any(
        f["event_id"] == event["event_id"]
        and f["source"] in ("admin_approve", "admin_block")
        for f in FEEDBACK_LABELS
    )
    if already_actioned:
        return None

    return {
        "event_id"    : event["event_id"],
        "user_id"     : user_id,
        "emp_name"    : profile.get("name", user_id),
        "department"  : profile.get("department", "—"),
        "role"        : profile.get("role", "—"),
        "timestamp"   : event["timestamp"],
        "location"    : event.get("location", "Unknown"),
        "country"     : event.get("country", "Unknown"),
        "device_type" : event.get("device_type", "Unknown"),
        "application" : "Okta",
        "risk_score"  : result["risk_score"],
        "action"      : result["action"],
        "reason_codes": [r["reason"] for r in result["reason_codes"]],
        "failed_attempts": event.get("failed_attempts", 0),
    }


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/")
def serve_dashboard():
    """Serve the admin dashboard HTML."""
    return FileResponse(os.path.join(dashboard_dir, "index.html"))


@app.get("/alerts")
def get_alerts():
    """
    Returns list of high risk login events pending admin review.
    Sorted by risk score descending — highest risk on top.
    Excludes events already actioned by admin.
    """
    alerts = []
    for event in LOGIN_EVENTS:
        alert = _build_alert(event)
        if alert:
            alerts.append(alert)

    alerts.sort(key=lambda x: x["risk_score"], reverse=True)
    return {"alerts": alerts, "total": len(alerts)}


@app.post("/feedback")
def submit_feedback(body: FeedbackRequest):
    """
    Records admin decision for a login event.
    Triggers profile update and online learner update.

    outcome: "admin_approve" → legitimate
             "admin_block"   → attack
    """
    valid_outcomes = ("admin_approve", "admin_block")
    if body.outcome not in valid_outcomes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome. Must be one of: {valid_outcomes}"
        )

    result = record_feedback(body.event_id, body.outcome, notes=body.notes)

    if not result:
        raise HTTPException(status_code=404, detail=f"Event {body.event_id} not found")

    return {
        "success"  : True,
        "event_id" : body.event_id,
        "outcome"  : body.outcome,
        "label"    : result["label"],
        "message"  : f"Event {body.event_id} marked as {result['label']}"
    }


@app.get("/stats")
def get_stats():
    """
    Returns summary statistics for the dashboard header.
    """
    all_alerts = [_build_alert(e) for e in LOGIN_EVENTS]
    all_alerts = [a for a in all_alerts if a is not None]

    # Include already-actioned events for historical counts
    total_flagged = len(all_alerts)
    pending       = sum(1 for a in all_alerts)

    admin_actions = [
        f for f in FEEDBACK_LABELS
        if f["source"] in ("admin_approve", "admin_block")
    ]
    total_blocked  = sum(1 for f in admin_actions if f["label"] == "attack")
    total_approved = sum(1 for f in admin_actions if f["label"] == "legitimate")

    avg_risk = (
        round(sum(a["risk_score"] for a in all_alerts) / len(all_alerts), 1)
        if all_alerts else 0
    )

    return {
        "pending_review" : pending,
        "total_blocked"  : total_blocked,
        "total_approved" : total_approved,
        "avg_risk_score" : avg_risk,
        "total_users"    : len(USER_PROFILES),
    }
    
