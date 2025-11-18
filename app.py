import streamlit as st
import plotly.graph_objects as go
import random
import time
from datetime import datetime, timedelta

# Page setup
st.set_page_config(page_title="Health Book", page_icon="❤️", layout="wide")

# Initialize session state
if "hr_series" not in st.session_state:
    st.session_state.hr_series = []

# Sidebar settings
st.sidebar.title("Settings")
safe_low = st.sidebar.slider("Safe BPM Low", 40, 70, 55)
safe_high = st.sidebar.slider("Safe BPM High", 90, 130, 100)
refresh_sec = st.sidebar.slider("Refresh Interval (sec)", 1, 10, 2)

# Simulate live heart rate
def simulate_heart_rate():
    base = 72
    variation = random.randint(-5, 5)
    spike = random.choices([0, 1], weights=[95, 5])[0]
    if spike:
        return random.choice([random.randint(130, 150), random.randint(30, 45)])
    return base + variation

# Update heart rate series
def update_hr_series():
    now = datetime.utcnow()
    bpm = simulate_heart_rate()
    st.session_state.hr_series.append((now, bpm))
    cutoff = now - timedelta(minutes=10)
    st.session_state.hr_series = [
        p for p in st.session_state.hr_series
        if isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], datetime) and p[0] >= cutoff
    ]
    return bpm

# Update and get latest BPM
latest_bpm = update_hr_series()

# Title and current BPM
st.title("Health Book")
st.metric("Current Heart Rate", f"{latest_bpm} bpm")

# Heart rate chart
times = [t for (t, _) in st.session_state.hr_series]
values = [v for (_, v) in st.session_state.hr_series]

fig = go.Figure()
if times:
    fig.add_trace(go.Scatter(
        x=[times[0], times[-1], times[-1], times[0]],
        y=[safe_low, safe_low, safe_high, safe_high],
        fill="toself",
        fillcolor="rgba(0,200,0,0.1)",
        line=dict(color="rgba(0,0,0,0)"),
        hoverinfo="skip",
        name="Safe Range"
    ))

fig.add_trace(go.Scatter(
    x=times,
    y=values,
    mode="lines+markers",
    line=dict(color="#e91e63", width=3),
    marker=dict(size=6),
    name="BPM"
))

fig.update_layout(
    height=300,
    margin=dict(l=30, r=20, t=30, b=30),
    xaxis_title="Time (last 10 min)",
    yaxis_title="BPM",
    template="plotly_white"
)

st.plotly_chart(fig, use_container_width=True)

# Emergency status
st.subheader("Emergency Status")
if latest_bpm >= safe_high or latest_bpm <= safe_low:
    st.error(f" Alert: Heart rate {latest_bpm} bpm out of safe range!")
else:
    st.success(" Heart rate within safe range.")

# Panels
col1, col2, col3 = st.columns(3)
with col1:
    st.subheader("Sleep")
    st.write("Duration: 420 min")
    st.write("Quality: Good")

with col2:
    st.subheader("Fitness")
    st.write("Steps: 3456")
    st.write("Calories: 280")

with col3:
    st.subheader("Nutrition")
    st.write("Hydration: 900 ml")
    st.write("Meals: 2")

# Auto-refresh
time.sleep(refresh_sec)
st.experimental_rerun()
