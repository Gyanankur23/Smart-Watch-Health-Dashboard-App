import os
import time
import json
import random
import requests
from datetime import datetime, timedelta

import streamlit as st
import plotly.graph_objects as go

# -----------------------------
# App config
# -----------------------------
st.set_page_config(
    page_title="Health Book",
    page_icon="❤️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------
# Helper: state init
# -----------------------------
def init_state():
    if "hr_series" not in st.session_state:
        st.session_state.hr_series = []  # list of (timestamp, bpm)
    if "alerts" not in st.session_state:
        st.session_state.alerts = []  # list of dicts with time, type, value, message
    if "sleep_summary" not in st.session_state:
        st.session_state.sleep_summary = {"duration_min": 0, "quality": "—"}
    if "fitness" not in st.session_state:
        st.session_state.fitness = {"steps": 0, "calories": 0}
    if "nutrition" not in st.session_state:
        st.session_state.nutrition = {"hydration_ml": 0, "meals": 0}
    if "last_fetch" not in st.session_state:
        st.session_state.last_fetch = None

init_state()

# -----------------------------
# Sidebar: data source & thresholds
# -----------------------------
st.sidebar.title("Synchronization")
st.sidebar.caption("Configure data source and alert thresholds")

data_source = st.sidebar.selectbox(
    "Data source",
    ["Simulated (built-in)", "HTTP JSON (phone/watch companion)"],
    index=0
)

data_url = st.sidebar.text_input(
    "HTTP JSON URL",
    value=os.getenv("DATA_URL", ""),
    help="Public HTTPS endpoint returning live JSON data. Leave empty for simulated."
)

st.sidebar.markdown("---")
safe_low = st.sidebar.number_input("Heart rate safe low (bpm)", value=55, step=1)
safe_high = st.sidebar.number_input("Heart rate safe high (bpm)", value=100, step=1)
alert_high = st.sidebar.number_input("Alert high threshold (bpm)", value=120, step=1)
alert_low = st.sidebar.number_input("Alert low threshold (bpm)", value=45, step=1)

refresh_sec = st.sidebar.slider("Auto-refresh interval (seconds)", 1, 10, 2)

# -----------------------------
# Data schema helpers
# -----------------------------
def parse_payload(payload: dict):
    """
    Expected schema:
    {
      "timestamp": "2025-11-18T12:34:56Z",
      "heart_rate_bpm": 72,
      "sleep": {"duration_min": 420, "quality": "good"},
      "fitness": {"steps": 3456, "calories": 280},
      "nutrition": {"hydration_ml": 900, "meals": 2},
      "emergency": {"active": false, "reason": ""}
    }
    """
    ts_str = payload.get("timestamp")
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.utcnow()
    except Exception:
        ts = datetime.utcnow()

    hr = payload.get("heart_rate_bpm", None)
    sleep = payload.get("sleep", {})
    fitness = payload.get("fitness", {})
    nutrition = payload.get("nutrition", {})
    emergency = payload.get("emergency", {"active": False, "reason": ""})

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

def simulate_payload():
    now = datetime.utcnow()
    # Simulate circadian HR with small randomness
    base_hr = 72 + int(5 * (random.random() - 0.5))
    # Occasionally spike high/low to test alerts
    spike = random.choices([0, 1], weights=[96, 4])[0]
    if spike == 1:
        base_hr = random.choice([random.randint(alert_high, alert_high + 20),
                                 random.randint(max(30, alert_low - 10), alert_low)])

    payload = {
        "timestamp": now.isoformat() + "Z",
        "heart_rate_bpm": base_hr,
        "sleep": {
            "duration_min": random.choice([0, 360, 420, 480]),
            "quality": random.choice(["fair", "good", "excellent", "—"])
        },
        "fitness": {
            "steps": random.randint(1000, 8000),
            "calories": random.randint(150, 600)
        },
        "nutrition": {
            "hydration_ml": random.randint(500, 2000),
            "meals": random.randint(1, 3)
        },
        "emergency": {
            "active": base_hr >= alert_high or base_hr <= alert_low,
            "reason": "Heart rate out of bounds" if (base_hr >= alert_high or base_hr <= alert_low) else ""
        }
    }
    return payload

# -----------------------------
# Update state from source
# -----------------------------
def update_state_from_source():
    if data_source.startswith("HTTP"):
        payload = fetch_http_json(data_url)
        if payload is None:
            payload = simulate_payload()  # resilient fallback
    else:
        payload = simulate_payload()

    ts, hr, sleep, fitness, nutrition, emergency = parse_payload(payload)

    # Update series
    if hr is not None:
        st.session_state.hr_series.append((ts, int(hr)))
        # Keep last 10 minutes of data
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        st.session_state.hr_series = [p for p in st.session_state.hr_series if p[0] >= cutoff]

        # Alert logging
        if hr >= alert_high or hr <= alert_low:
            st.session_state.alerts.append({
                "time": ts.isoformat(),
                "type": "EMERGENCY",
                "value": int(hr),
                "message": f"Heart rate {hr} bpm out of bounds"
            })
            # Keep last 50 alerts
            st.session_state.alerts = st.session_state.alerts[-50:]

    # Update panels
    st.session_state.sleep_summary = {
        "duration_min": sleep.get("duration_min", st.session_state.sleep_summary["duration_min"]),
        "quality": sleep.get("quality", st.session_state.sleep_summary["quality"])
    }
    st.session_state.fitness = {
        "steps": fitness.get("steps", st.session_state.fitness["steps"]),
        "calories": fitness.get("calories", st.session_state.fitness["calories"])
    }
    st.session_state.nutrition = {
        "hydration_ml": nutrition.get("hydration_ml", st.session_state.nutrition["hydration_ml"]),
        "meals": nutrition.get("meals", st.session_state.nutrition["meals"])
    }

    st.session_state.last_fetch = datetime.utcnow()

# Perform update
update_state_from_source()

# -----------------------------
# Top bar: title and key stat
# -----------------------------
col_l, col_r = st.columns([2, 1])
with col_l:
    st.title("Health Book")
    st.caption("Heart Rate • Sleep • Emergency • Fitness • Nutrition")
with col_r:
    # Show latest BPM big number
    latest_bpm = st.session_state.hr_series[-1][1] if st.session_state.hr_series else "—"
    st.metric("Current Heart Rate", f"{latest_bpm if latest_bpm != '—' else latest_bpm} bpm" if latest_bpm != "—" else "—", help="Live from wearable / data feed")

# -----------------------------
# Main charts
# -----------------------------
hr_container = st.container()
with hr_container:
    st.subheader("Heart rate (live)")
    # Build line chart with safe band
    times = [t for (t, _) in st.session_state.hr_series]
    values = [v for (_, v) in st.session_state.hr_series]

    fig = go.Figure()

    # Safe band
    if times:
        fig.add_trace(go.Scatter(
            x=[times[0], times[-1], times[-1], times[0]],
            y=[safe_low, safe_low, safe_high, safe_high],
            fill="toself",
            fillcolor="rgba(0, 200, 0, 0.1)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            name="Safe range"
        ))

    # Live HR line
    fig.add_trace(go.Scatter(
        x=times,
        y=values,
        mode="lines+markers",
        line=dict(color="#e91e63", width=3),
        marker=dict(size=6),
        name="BPM"
    ))

    # Alert thresholds
    fig.add_hline(y=alert_high, line=dict(color="red", dash="dot"), annotation_text=f"Alert high {alert_high} bpm")
    fig.add_hline(y=alert_low, line=dict(color="red", dash="dot"), annotation_text=f"Alert low {alert_low} bpm")

    fig.update_layout(
        height=320,
        margin=dict(l=30, r=20, t=30, b=30),
        xaxis_title="Time (last 10 min)",
        yaxis_title="BPM",
        template="plotly_white"
    )
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Panels: Emergency, Sleep, Fitness, Nutrition
# -----------------------------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.subheader("Emergency")
    # Status
    current_bpm = st.session_state.hr_series[-1][1] if st.session_state.hr_series else None
    emergency_active = current_bpm is not None and (current_bpm >= alert_high or current_bpm <= alert_low)
    status = "Active" if emergency_active else "Normal"
    st.write(f"Status: **{status}**")
    if st.session_state.alerts:
        last = st.session_state.alerts[-1]
        st.write(f"Last alert: {last['message']} at {last['time']}")
    else:
        st.write("No alerts in the current session.")
    st.caption("Alerts trigger when BPM exceeds thresholds")

with c2:
    st.subheader("Sleep")
    st.write(f"Duration: **{st.session_state.sleep_summary['duration_min']} min**")
    st.write(f"Quality: **{st.session_state.sleep_summary['quality']}**")
    st.caption("Summary provided by companion app/watch")

with c3:
    st.subheader("Fitness")
    st.write(f"Steps: **{st.session_state.fitness['steps']}**")
    st.write(f"Calories: **{st.session_state.fitness['calories']}**")
    st.caption("Daily activity totals")

with c4:
    st.subheader("Nutrition")
    st.write(f"Hydration: **{st.session_state.nutrition['hydration_ml']} ml**")
    st.write(f"Meals: **{st.session_state.nutrition['meals']}**")
    st.caption("Quick intake indicators")

# -----------------------------
# Footer: sync info & auto refresh
# -----------------------------
sync_col1, sync_col2, sync_col3 = st.columns(3)
with sync_col1:
    last = st.session_state.last_fetch
    st.caption(f"Last sync: {last.strftime('%H:%M:%S')} UTC" if last else "Last sync: —")
with sync_col2:
    st.caption(f"Data source: {data_source}")
with sync_col3:
    st.caption(f"Refresh every {refresh_sec}s")

# Auto-refresh
time.sleep(refresh_sec)
st.experimental_rerun()
