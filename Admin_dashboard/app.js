// Admin_dashboard/app.js
// Handles all API calls and DOM interactions.
// Three responsibilities:
//   1. Load and render alerts from GET /alerts
//   2. Submit admin decisions via POST /feedback
//   3. Load stats from GET /stats

const API_BASE = "http://localhost:8000";

// Currently open detail panel event_id
let activeEventId = null;


// ─────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    loadStats();
    loadAlerts();
});


// ─────────────────────────────────────────────
// STATS
// ─────────────────────────────────────────────

async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/stats`);
        const data = await res.json();

        document.getElementById("stat-pending").textContent = data.pending_review ?? "—";
        document.getElementById("stat-blocked").textContent = data.total_blocked ?? "—";
        document.getElementById("stat-approved").textContent = data.total_approved ?? "—";
        document.getElementById("stat-avg-risk").textContent = data.avg_risk_score ?? "—";
        document.getElementById("stat-users").textContent = data.total_users ?? "—";
    } catch (err) {
        console.error("Failed to load stats:", err);
    }
}


// ─────────────────────────────────────────────
// ALERTS
// ─────────────────────────────────────────────

async function loadAlerts() {
    const container = document.getElementById("alerts-container");
    const emptyState = document.getElementById("empty-state");

    container.innerHTML = `
    <div class="loading-state">
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span class="loading-dot"></span>
      <span>Loading alerts...</span>
    </div>`;
    emptyState.style.display = "none";

    try {
        const res = await fetch(`${API_BASE}/alerts`);
        const data = await res.json();

        document.getElementById("alert-count").textContent = data.total;

        if (data.total === 0) {
            container.innerHTML = "";
            emptyState.style.display = "flex";
            return;
        }

        container.innerHTML = "";
        data.alerts.forEach((alert, idx) => {
            container.appendChild(buildAlertRow(alert, idx + 1));
        });

    } catch (err) {
        container.innerHTML = `
      <div class="loading-state" style="color:#ef4444">
        ✕ Failed to connect to API — is the server running?
      </div>`;
        console.error("Failed to load alerts:", err);
    }
}


function buildAlertRow(alert, num) {
    const row = document.createElement("div");
    row.className = "alert-row";
    row.dataset.eventId = alert.event_id;

    const riskClass = getRiskClass(alert.risk_score);
    const topReason = alert.reason_codes?.[0] ?? "—";
    const ts = formatTimestamp(alert.timestamp);

    row.innerHTML = `
    <div class="col-num">${num}</div>

    <div class="col-user col-user-info">
      <div class="emp-name">${alert.emp_name}</div>
      <div class="emp-meta">${alert.department} · ${alert.role}</div>
    </div>

    <div class="col-time timestamp">${ts}</div>

    <div class="col-location location-tag"
         title="${alert.country}">${alert.location}, ${alert.country}</div>

    <div class="col-device device-tag">${alert.device_type}</div>

    <div class="col-app app-tag">${alert.application}</div>

    <div class="col-risk">
      <span class="risk-badge ${riskClass}">${alert.risk_score}</span>
    </div>

    <div class="col-reason reason-text" title="${topReason}">${topReason}</div>

    <div class="col-action action-group">
      <button class="btn-approve"
        onclick="event.stopPropagation(); submitFeedback('${alert.event_id}', 'admin_approve')">
        Allow
      </button>
      <button class="btn-block"
        onclick="event.stopPropagation(); submitFeedback('${alert.event_id}', 'admin_block')">
        Block
      </button>
    </div>`;

    // Click row to open detail panel
    row.addEventListener("click", () => openDetail(alert));

    return row;
}


// ─────────────────────────────────────────────
// FEEDBACK SUBMISSION
// ─────────────────────────────────────────────

async function submitFeedback(eventId, outcome) {
    try {
        const res = await fetch(`${API_BASE}/feedback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ event_id: eventId, outcome }),
        });

        const data = await res.json();

        if (!res.ok) {
            showToast(`Error: ${data.detail}`, "danger");
            return;
        }

        const label = outcome === "admin_approve" ? "Approved" : "Blocked";
        showToast(`${label} — ${data.message}`, outcome === "admin_approve" ? "success" : "danger");

        // Remove the row from the table
        removeAlertRow(eventId);

        // Close detail panel if open for this event
        if (activeEventId === eventId) closeDetail();

        // Reload stats
        loadStats();

    } catch (err) {
        showToast("Failed to submit feedback — is the server running?", "danger");
        console.error(err);
    }
}


function removeAlertRow(eventId) {
    const row = document.querySelector(`[data-event-id="${eventId}"]`);
    if (!row) return;

    row.classList.add("removing");

    row.addEventListener("animationend", () => {
        row.remove();

        // Renumber remaining rows
        const rows = document.querySelectorAll(".alert-row");
        rows.forEach((r, i) => {
            const numEl = r.querySelector(".col-num");
            if (numEl) numEl.textContent = i + 1;
        });

        // Update count badge
        document.getElementById("alert-count").textContent = rows.length;

        // Show empty state if no rows left
        if (rows.length === 0) {
            document.getElementById("empty-state").style.display = "flex";
        }
    });
}


// ─────────────────────────────────────────────
// DETAIL PANEL
// ─────────────────────────────────────────────

function openDetail(alert) {
    activeEventId = alert.event_id;

    const content = document.getElementById("detail-content");
    const riskClass = getRiskClass(alert.risk_score);

    const reasonsHtml = (alert.reason_codes || []).map(r => `
    <div class="reason-item">
      <span class="reason-dot">▸</span>
      <span>${r}</span>
    </div>`).join("") || "<div class='reason-item'><span>No reasons flagged</span></div>";

    content.innerHTML = `
    <div class="detail-row">
      <span class="detail-label">Employee</span>
      <span class="detail-value">${alert.emp_name}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">User ID</span>
      <span class="detail-value">${alert.user_id}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Department</span>
      <span class="detail-value">${alert.department}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Role</span>
      <span class="detail-value">${alert.role}</span>
    </div>

    <div class="detail-section-title">Login Event</div>

    <div class="detail-row">
      <span class="detail-label">Timestamp</span>
      <span class="detail-value">${alert.timestamp}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Location</span>
      <span class="detail-value">${alert.location}, ${alert.country}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Device</span>
      <span class="detail-value">${alert.device_type}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Application</span>
      <span class="detail-value">${alert.application}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Failed attempts</span>
      <span class="detail-value">${alert.failed_attempts}</span>
    </div>

    <div class="detail-section-title">Risk Assessment</div>

    <div class="detail-row">
      <span class="detail-label">Risk Score</span>
      <span class="detail-value">
        <span class="risk-badge ${riskClass}">${alert.risk_score}</span>
      </span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Decision</span>
      <span class="detail-value" style="text-transform:uppercase;font-size:0.72rem;letter-spacing:0.05em;">
        ${alert.action}
      </span>
    </div>

    <div class="detail-section-title">Reason Codes</div>
    ${reasonsHtml}`;

    // Wire up detail panel action buttons
    document.getElementById("detail-approve-btn").onclick = () =>
        submitFeedback(alert.event_id, "admin_approve");
    document.getElementById("detail-block-btn").onclick = () =>
        submitFeedback(alert.event_id, "admin_block");

    document.getElementById("detail-overlay").classList.add("open");
    document.getElementById("detail-panel").classList.add("open");
}


function closeDetail() {
    activeEventId = null;
    document.getElementById("detail-overlay").classList.remove("open");
    document.getElementById("detail-panel").classList.remove("open");
}


// ─────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────

function getRiskClass(score) {
    if (score >= 80) return "critical";
    if (score >= 65) return "high";
    return "medium";
}

function formatTimestamp(ts) {
    // "2026-03-14 03:22:00" → "Mar 14, 03:22"
    const [date, time] = ts.split(" ");
    const [year, month, day] = date.split("-");
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const hhmm = time.slice(0, 5);
    return `${months[parseInt(month) - 1]} ${parseInt(day)}, ${hhmm}`;
}

function showToast(message, type = "success") {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.className = "toast";
    }, 3000);
}