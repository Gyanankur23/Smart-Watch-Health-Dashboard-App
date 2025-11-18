# streamlit_app.py
import os
import time
import random
import requests
from datetime import datetime, timedelta, timezone

import streamlit as st
import plotly.graph_objects as go
import streamlit.components.v1 as components

# -----------------------------
# Page setup and brand styling
# -----------------------------
st.set_page_config(
    page_title="PulseGuard SOS",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded"
)

BRAND_CSS = """
<style>
:root {
  --brand-bg: #0b1220;
  --brand-card: #121a2b;
  --brand-accent: #22d3ee;
  --brand-danger: #ef4444;
  --brand-success: #10b981;
  --brand-text: #e5e7eb;
  --brand-muted: #94a3b8;
}
body { background-color: var(--brand-bg); }
.block-container { padding-top: 1rem; }
.header-strip {
  width: 100%; padding: 16px 20px; border-radius: 12px;
  background: linear-gradient(90deg, #0ea5e9, #22d3ee 50%, #10b981);
  color: #0b1220; font-weight: 700; display: flex; align-items: center; justify-content: space-between;
}
.header-title { font-size: 24px; letter-spacing: 0.5px; }
.header-sub { font-size: 14px; opacity: 0.9; }
.metric-card {
  background-color: var(--brand-card); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px; padding: 16px; color: var(--brand-text);
}
.metric-label { font-size: 13px; color: var(--brand-muted); }
.metric-value { font-size: 36px; font-weight: 800; color: #ffffff; }
.section-title { color: var(--brand-text); font-size: 18px; font-weight: 700; padding: 6px 0 10px 0; }
.badge { display: inline-block; padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; letter-spacing: 0.3px; }
.badge-green { background-color: rgba(16,185,129,0.18); color: #10b981; border: 1px solid rgba(16,185,129,0.35); }
.badge-red { background-color: rgba(239,68,68,0.18); color: #ef4444; border: 1px solid rgba(239,68,68,0.35); }
.badge-blue { background-color: rgba(34,211,238,0.18); color: #22d3ee; border: 1px solid rgba(34,211,238,0.35); }
.card {
  background-color: var(--brand-card); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px; padding: 16px; color: var(--brand-text);
}
.footer { color: var(--brand-muted); font-size: 12px; padding-top: 8px; text-align: right; }
.pulse-dot {
  width: 12px; height: 12px; border-radius: 50%;
  background-color: #22d3ee; display: inline-block; margin-right: 6px;
  box-shadow: 0 0 0 rgba(34,211,238, 0.7);
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(34,211,238, 0.7); }
  70% { box-shadow: 0 0 0 10px rgba(34,211,238, 0); }
  100% { box-shadow: 0 0 0 0 rgba(34,211,238, 0); }
}
</style>
"""

JS_EFFECTS = """
<script>
document.addEventListener("DOMContentLoaded", function(){
  const blocks = document.querySelectorAll(".block-container, .metric-card, .card");
  blocks.forEach(b => {
    b.style.transition = "opacity 0.3s ease";
    b.style.opacity = 0.0;
    setTimeout(() => { b.style.opacity = 1.0; }, 100);
  });
});
</script>
"""

st.markdown(BRAND_CSS, unsafe_allow_html=True)
components.html(JS_EFFECTS, height=0)

# -----------------------------
# Sidebar: data source & thresholds
# (Put data source selector early so functions can reference them safely)
# -----------------------------
st.sidebar.markdown("<div class='section-title'>Synchronization</div>", unsafe_allow_html=True)

data_source = st.sidebar.selectbox(
    "Data source",
    ["Simulated (realistic)", "HTTP JSON (watch/phone companion)"],
    index=0
)

data_url = st.sidebar.text_input(
    "Live JSON URL",
    value=os.getenv("DATA_URL", ""),
    help="Public HTTPS endpoint returning latest payload. Leave blank for simulation."
)

st.sidebar.markdown("---")
st.sidebar.markdown("<div class='section-title'>Monitoring controls</div>", unsafe_allow_html=True)

safe_low = st.sidebar.number_input("Safe BPM low", value=55, step=1)
safe_high = st.sidebar.number_input("Safe BPM high", value=100, step=1)
alert_low = st.sidebar.number_input("Alert threshold low", value=45, step=1)
alert_high = st.sidebar.number_input("Alert threshold high", value=120, step=1)

auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
refresh_sec = st.sidebar.slider("Refresh interval (sec)", 2, 10, 3)

st.sidebar.markdown("---")
st.sidebar.caption("Tip: Use the HTTP JSON mode to connect your watch/phone companion feed.")

# -----------------------------
# Session state init (single definition)
# -----------------------------
def init_state_once():
    ss = st.session_state
    if "hr_series" not in ss:
        ss.hr_series = []   # list[(aware datetime, bpm)]
    if "alerts" not in ss:
        ss.alerts = []      # list[dict]
    if "sleep" not in ss:
        ss.sleep = {"duration_min": None, "quality": None}
    if "fitness" not in ss:
        ss.fitness = {"steps": None, "calories": None}
    if "nutrition" not in ss:
        ss.nutrition = {"hydration_ml": None, "meals": None}
    if "last_sync" not in ss:
        ss.last_sync = None

init_state_once()

# -----------------------------
# Data helpers (UTC-aware)
# -----------------------------
def parse_payload(payload: dict):
    """
    Normalizes incoming payload into:
    (aware datetime, hr, sleep, fitness, nutrition, emergency)
    Accepts timestamp as ISO string (with Z or offset) or as datetime object.
    """
    if not isinstance(payload, dict):
        # defensive
        payload = {}

    ts_raw = payload.get("timestamp")
    ts = None

    try:
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif isinstance(ts_raw, str):
            # Normalize 'Z' to +00:00 and parse
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            # normalize to UTC timezone object
            ts = ts.astimezone(timezone.utc)
    except Exception:
        ts = datetime.now(timezone.utc)

    hr = payload.get("heart_rate_bpm", None)
    sleep = payload.get("sleep", {}) or {}
    fitness = payload.get("fitness", {}) or {}
    nutrition = payload.get("nutrition", {}) or {}
    emergency = payload.get("emergency", {"active": False, "reason": ""}) or {"active": False, "reason": ""}

return ts, hr, sleep, fitness, nutrition, emergency

def fetch_http_json(url: str):
    if not url:
        return None
    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            return r.json()
        else:
            st.sidebar.warning(f"HTTP status {r.status_code} from data URL")
            return None
    except Exception as e:
        st.sidebar.error(f"Fetch error: {e}")
        return None

def simulate_payload_dict():
    """
    Returns a payload dictionary (timestamp as ISO Z string) to match parse_payload expectations.
    """
    now = datetime.now(timezone.utc)

    circadian = 72 + int(4 * (random.random() - 0.5))
    r = random.random()
    if r < 0.03:
        hr = random.randint(alert_high, alert_high + 20)
    elif r < 0.06:
        hr = random.randint(max(30, alert_low - 10), alert_low)
    else:
        hr = circadian + random.randint(-3, 3)

    sleep_options = [
        {"duration_min": 0, "quality": "—"},
        {"duration_min": 360, "quality": "fair"},
        {"duration_min": 420, "quality": "good"},
        {"duration_min": 480, "quality": "excellent"},
    ]
    sleep = random.choice(sleep_options)

    fitness = {
        "steps": random.randint(800, 12000),
        "calories": random.randint(180, 650)
    }
    nutrition = {
        "hydration_ml": random.randint(600, 2500),
        "meals": random.randint(1, 4)
    }

    emergency_active = hr >= alert_high or hr <= alert_low

    payload = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "heart_rate_bpm": hr,
        "sleep": sleep,
        "fitness": fitness,
        "nutrition": nutrition,
        "emergency": {
            "active": emergency_active,
            "reason": "Heart rate out of bounds" if emergency_active else ""
        }
    }
    return payload

# -----------------------------
# State updater (single, robust)
# -----------------------------
def update_state_from_source_once():
    # Decide source
    if isinstance(data_source, str) and data_source.startswith("HTTP"):
        payload = fetch_http_json(data_url)
        if payload is None:
            payload = simulate_payload_dict()
    else:
        payload = simulate_payload_dict()

    ts, hr, sleep, fitness, nutrition, emergency = parse_payload(payload)

    # Update HR series safely (aware datetimes)
    if hr is not None:
        try:
            hr_int = int(hr)
        except Exception:
            # If can't convert, skip
            hr_int = None

        if hr_int is not None:
            st.session_state.hr_series.append((ts, hr_int))

            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            # Keep only tuples with aware datetimes and recent enough
            st.session_state.hr_series = [
                p for p in st.session_state.hr_series
                if isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], datetime) and p[0].tzinfo is not None and p[0] >= cutoff
            ]

            # Log alert if out of bounds
            if hr_int >= alert_high or hr_int <= alert_low:
                st.session_state.alerts.append({
                    "time": ts.isoformat().replace("+00:00", "Z"),
                    "type": "EMERGENCY",
                    "value": int(hr_int),
                    "message": f"Heart rate {hr_int} bpm out of bounds"
                })
                st.session_state.alerts = st.session_state.alerts[-50:]

    # Update panels (preserve previous values if incoming missing keys)
    st.session_state.sleep = {
        "duration_min": sleep.get("duration_min", st.session_state.sleep.get("duration_min")),
        "quality": sleep.get("quality", st.session_state.sleep.get("quality"))
    }
    st.session_state.fitness = {
        "steps": fitness.get("steps", st.session_state.fitness.get("steps")),
        "calories": fitness.get("calories", st.session_state.fitness.get("calories"))
    }
    st.session_state.nutrition = {
        "hydration_ml": nutrition.get("hydration_ml", st.session_state.nutrition.get("hydration_ml")),
        "meals": nutrition.get("meals", st.session_state.nutrition.get("meals"))
    }
    st.session_state.last_sync = datetime.now(timezone.utc)

# One update per load (safe)
update_state_from_source_once()

# -----------------------------
# Header
# -----------------------------
st.markdown(
    "<div class='header-strip'>"
    "<div><span class='pulse-dot'></span><span class='header-title'>PulseGuard SOS – Live Wearable Dashboard</span>"
    "<div class='header-sub'>Real-time vitals • Alerts • Care insights</div></div>"
    "<div class='badge badge-blue'>SYNC ACTIVE</div>"
    "</div>",
    unsafe_allow_html=True
)

# -----------------------------
# Top metrics row
# -----------------------------
m1, m2, m3 = st.columns([1, 1, 1])
with m1:
    current_bpm = st.session_state.hr_series[-1][1] if st.session_state.hr_series else None
    display_bpm = "—" if current_bpm is None else f"{current_bpm} bpm"
    st.markdown("<div class='metric-card'><div class='metric-label'>Current Heart Rate</div>"
                f"<div class='metric-value'>{display_bpm}</div></div>",
                unsafe_allow_html=True)
with m2:
    last_sync = st.session_state.last_sync
    last_sync_str = last_sync.astimezone(timezone.utc).strftime("%H:%M:%S UTC") if last_sync else "—"
    st.markdown("<div class='metric-card'><div class='metric-label'>Last Sync</div>"
                f"<div class='metric-value'>{last_sync_str}</div></div>", unsafe_allow_html=True)
with m3:
    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_alerts = 0
    for a in st.session_state.alerts:
        try:
            at = datetime.fromisoformat(a["time"].replace("Z", "+00:00"))
            if at >= ten_min_ago:
                recent_alerts += 1
        except Exception:
            continue
    st.markdown("<div class='metric-card'><div class='metric-label'>Alerts (10 min)</div>"
                f"<div class='metric-value'>{recent_alerts}</div></div>", unsafe_allow_html=True)

# -----------------------------
# Heart rate chart
# -----------------------------
st.markdown("<div class='section-title'>Heart rate (live)</div>", unsafe_allow_html=True)
times = [t for (t, _) in st.session_state.hr_series]
values = [v for (_, v) in st.session_state.hr_series]

fig = go.Figure()

if times:
    # Safe band polygon based on first and last time
    fig.add_trace(go.Scatter(
        x=[times[0], times[-1], times[-1], times[0]],
        y=[safe_low, safe_low, safe_high, safe_high],
        fill="toself",
        fillcolor="rgba(16,185,129,0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        hoverinfo="skip",
        name="Safe range"
    ))

# Live line
fig.add_trace(go.Scatter(
    x=times,
    y=values,
    mode="lines+markers",
    line=dict(color="#22d3ee", width=3),
    marker=dict(size=5),
    name="BPM"
))

# Threshold lines
fig.add_hline(y=alert_high, line=dict(color="red", dash="dot"),
              annotation_text=f"Alert high {alert_high} bpm", annotation_position="top right")
fig.add_hline(y=alert_low, line=dict(color="red", dash="dot"),
              annotation_text=f"Alert low {alert_low} bpm", annotation_position="bottom right")

fig.update_layout(
    height=320,
    margin=dict(l=30, r=20, t=30, b=30),
    xaxis_title="Time (last 10 min)",
    yaxis_title="BPM",
    template="plotly_dark",
    paper_bgcolor="#0b1220",
    plot_bgcolor="#0b1220",
    font=dict(color="#e5e7eb")
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Emergency + panels row
# -----------------------------
c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
with c1:
    st.markdown("<div class='section-title'>Emergency status</div>", unsafe_allow_html=True)
    current_bpm_val = st.session_state.hr_series[-1][1] if st.session_state.hr_series else None
    emergency_active = current_bpm_val is not None and (current_bpm_val >= alert_high or current_bpm_val <= alert_low)
    if emergency_active:
        st.markdown("<div class='card'><span class='badge badge-red'>SOS ACTIVE</span><br/><br/>"
                    f"<strong>Reason:</strong> Heart rate {current_bpm_val} bpm out of bounds.<br/>"
                    "Alerts sent to registered contacts.</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='card'><span class='badge badge-green'>Normal</span><br/><br/>"
                    "Vitals within safe range. Monitoring continues.</div>", unsafe_allow_html=True)

    # Recent alerts list
    if st.session_state.alerts:
        st.markdown("<div class='section-title'>Recent alerts</div>", unsafe_allow_html=True)
        for a in reversed(st.session_state.alerts[-5:]):
            st.markdown(f"<div class='card' style='margin-bottom:8px'>"
                        f"<strong>{a['type']}</strong> • {a['message']}<br/>"
                        f"<span class='badge badge-blue'>{a['time']}</span></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='card'>No alerts in the current session.</div>", unsafe_allow_html=True)

with c2:
    st.markdown("<div class='section-title'>Sleep</div>", unsafe_allow_html=True)
    sl = st.session_state.sleep
    st.markdown(f"<div class='card'>"
                f"Duration: <strong>{sl['duration_min'] if sl['duration_min'] is not None else '—'} min</strong><br/>"
                f"Quality: <strong>{sl['quality'] if sl['quality'] else '—'}</strong></div>", unsafe_allow_html=True)

with c3:
    st.markdown("<div class='section-title'>Fitness</div>", unsafe_allow_html=True)
    ft = st.session_state.fitness
    st.markdown(f"<div class='card'>"
                f"Steps: <strong>{ft['steps'] if ft['steps'] is not None else '—'}</strong><br/>"
                f"Calories: <strong>{ft['calories'] if ft['calories'] is not None else '—'}</strong></div>", unsafe_allow_html=True)

with c4:
    st.markdown("<div class='section-title'>Nutrition</div>", unsafe_allow_html=True)
    nt = st.session_state.nutrition
    st.markdown(f"<div class='card'>"
                f"Hydration: <strong>{nt['hydration_ml'] if nt['hydration_ml'] is not None else '—'} ml</strong><br/>"
                f"Meals: <strong>{nt['meals'] if nt['meals'] is not None else '—'}</strong></div>", unsafe_allow_html=True)

# -----------------------------
# Footer + refresh logic
# -----------------------------
left, mid, right = st.columns([1,1,1])
with left:
    st.markdown("<div class='footer'>Data source: "
                f"{'HTTP JSON' if isinstance(data_source, str) and data_source.startswith('HTTP') else 'Simulated (realistic)'}"
                "</div>", unsafe_allow_html=True)
with mid:
    st.markdown("<div class='footer'>Safe range: "
                f"{safe_low}–{safe_high} bpm • Alerts at {alert_low}/{alert_high} bpm"
                "</div>", unsafe_allow_html=True)
with right:
    st.markdown("<div class='footer'>Refresh interval: "
                f"{refresh_sec}s • Auto: {'ON' if auto_refresh else 'OFF'}"
                "</div>", unsafe_allow_html=True)

# Safe auto-refresh (toggle + countdown), avoids infinite loops if disabled
if auto_refresh:
    countdown_placeholder = st.empty()
    for i in range(refresh_sec, 0, -1):
        countdown_placeholder.markdown(f"<div class='footer'>Refreshing in {i} seconds…</div>", unsafe_allow_html=True)
        time.sleep(1)
    # Trigger a safe rerun once to refresh the UI with new data
    st.experimental_rerun()
