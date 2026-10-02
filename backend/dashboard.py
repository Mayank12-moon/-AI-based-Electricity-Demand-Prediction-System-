"""
GridSense Delhi - Real-Time AI Control Room & Forecaster Dashboard
High-density operational monitoring interface for Delhi SLDC & Discom control desks.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import altair as alt

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import (
    Entity, TelemetryRaw, TelemetryCleaned, WeatherTelemetry,
    DemandForecast, Alert, SourceHealthLog, Feeder
)
from app.workers import sldc_worker, feeder_seeder
from app.ml import engine
from app.ml.forecaster import GridSenseLGBMForecaster, solar_net_demand

IST = timezone(timedelta(hours=5, minutes=30))

st.set_page_config(
    page_title="GridSense Delhi | SLDC Control Room",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-Density Dark Control Room Theme
st.markdown("""
<style>
    .stApp {
        background-color: #0b0f19;
        color: #f1f5f9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .metric-card {
        background: #151d30;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    .metric-title {
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .metric-value {
        font-size: 1.85rem;
        font-weight: 700;
        color: #38bdf8;
        margin: 4px 0;
    }
    .metric-sub {
        font-size: 0.8rem;
        color: #64748b;
    }
    .badge-estimated {
        background-color: #fef3c7;
        color: #92400e;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: 600;
        border: 1px dashed #d97706;
    }
    .badge-live {
        background-color: #dcfce7;
        color: #166534;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: 600;
    }
    .badge-alert {
        background-color: #fee2e2;
        color: #991b1b;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    div[data-testid="stSidebar"] {
        background-color: #0d1322;
        border-right: 1px solid #1e293b;
    }
</style>
""", unsafe_allow_html=True)


def get_db():
    return SessionLocal()


# Top Navigation / Control Bar
col_logo, col_refresh, col_poll = st.columns([6, 1.5, 1.5])
with col_logo:
    st.markdown("## ⚡ GridSense Delhi: Live SLDC AI Forecaster & Control Desk")
    st.caption("Delhi State Load Despatch Center SCADA & Discom Load Monitoring (BRPL, BYPL, TPDDL, NDMC, MES)")

with col_refresh:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

with col_poll:
    if st.button("📡 Poll SLDC Now", use_container_width=True):
        with st.spinner("Polling delhisldc.org live SCADA..."):
            res = sldc_worker.fetch_and_store_live()
            feeder_seeder.update_feeder_loads()
            if res.get("success"):
                st.success("SLDC Polled Successfully")
            else:
                st.error(f"Poll Error: {res.get('error')}")
            st.rerun()


# Sidebar Navigation
st.sidebar.markdown("### 🏢 Grid Controls")
selected_entity = st.sidebar.selectbox(
    "Target Entity / Discom:",
    ["DELHI (State Total)", "BRPL (South & West)", "BYPL (East & Central)", "TPDDL (North)", "NDMC (Central Vista)", "MES (Cantonment)"]
)
entity_code = selected_entity.split()[0]

horizon_hours = st.sidebar.slider("Forecast Horizon (Hours):", min_value=6, max_value=72, value=24, step=6)

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Quick Actions")
if st.sidebar.button("🧠 Retrain LightGBM Models", use_container_width=True):
    with st.spinner("Retraining multi-quantile LightGBM models for all entities..."):
        t_res = engine.train_all_entities()
        engine.generate_all_forecasts(horizon_hours=horizon_hours)
        st.sidebar.success("All models trained & forecasts updated!")
        st.rerun()

if st.sidebar.button("📈 Run Fresh Forecast", use_container_width=True):
    with st.spinner("Generating rolling 24h forecasts..."):
        engine.generate_all_forecasts(horizon_hours=horizon_hours)
        st.sidebar.success("Forecasts regenerated!")
        st.rerun()


# Load DB Data
db = get_db()
try:
    # 1. Live Telemetry
    raw_rows = db.query(TelemetryRaw).order_by(TelemetryRaw.id.desc()).limit(12).all()
    latest_by_code = {}
    for r in raw_rows:
        if r.entity_code not in latest_by_code:
            latest_by_code[r.entity_code] = r

    delhi_live = latest_by_code.get("DELHI")
    cur_delhi_demand = delhi_live.demand_mw if delhi_live else 4280.0
    cur_delhi_peak = delhi_live.peak_mw if delhi_live else 5002.0
    cur_delhi_min = delhi_live.min_mw if delhi_live else 3749.0
    cur_delhi_avg = delhi_live.avg_mw if delhi_live else 4138.0

    # 2. Selected Entity Live
    target_live = latest_by_code.get(entity_code, delhi_live)
    target_demand = target_live.demand_mw if target_live else 2000.0
    target_peak = target_live.peak_mw if target_live else 2500.0

    # 3. Capacity & Headroom
    cap_mw = engine.CAPACITY_THRESHOLDS.get(entity_code, 9000.0)
    utilization_pct = (target_demand / cap_mw) * 100 if cap_mw else 0.0

    # 4. Generation data
    gen_list = sldc_worker.get_latest_generation()
    total_gen_mw = sum(g.get("actual_mw", 0) for g in gen_list)
finally:
    db.close()


# Key Metric Tiles
m1, m2, m3, m4, m5 = st.columns(5)

with m1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">{entity_code} Current Demand</div>
        <div class="metric-value">{target_demand:.0f} MW</div>
        <div class="metric-sub"><span class="badge-live">LIVE SCADA</span> Headroom: {cap_mw - target_demand:.0f} MW</div>
    </div>
    """, unsafe_allow_html=True)

with m2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Today's Peak Load</div>
        <div class="metric-value">{target_peak:.0f} MW</div>
        <div class="metric-sub">SLDC Day Peak Record</div>
    </div>
    """, unsafe_allow_html=True)

with m3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Grid Utilization</div>
        <div class="metric-value" style="color: {'#ef4444' if utilization_pct > 85 else '#38bdf8'};">{utilization_pct:.1f}%</div>
        <div class="metric-sub">Max Capacity: {cap_mw:.0f} MW</div>
    </div>
    """, unsafe_allow_html=True)

with m4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Delhi In-State Gen</div>
        <div class="metric-value">{total_gen_mw:.0f} MW</div>
        <div class="metric-sub">7 State Power Plants</div>
    </div>
    """, unsafe_allow_html=True)

with m5:
    db = get_db()
    try:
        active_alerts = db.query(Alert).filter(Alert.status == "ACTIVE").count()
    finally:
        db.close()
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Active Alerts</div>
        <div class="metric-value" style="color: {'#ef4444' if active_alerts > 0 else '#22c55e'};">{active_alerts}</div>
        <div class="metric-sub">Operational Warnings</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# Tabs for Control Room Views
tab_forecast, tab_scada, tab_feeders, tab_whatif, tab_alerts = st.tabs([
    "📈 AI Quantile Forecast & Solar",
    "🏢 Live Discom & Plant SCADA",
    "⚡ Delhi 22-Feeder Network",
    "🧪 What-If Heatwave Simulator",
    "🚨 Operational Alerts & Health"
])


# --- TAB 1: AI FORECAST & SOLAR DUCK CURVE ---
with tab_forecast:
    st.markdown(f"### 🤖 LightGBM Quantile Forecast: {entity_code} ({horizon_hours}-Hour Horizon)")
    
    db = get_db()
    try:
        now_dt = datetime.now(IST).replace(tzinfo=None)
        fc_rows = (
            db.query(DemandForecast)
            .filter(
                DemandForecast.entity_code == entity_code,
                DemandForecast.target_timestamp_ist >= now_dt,
                DemandForecast.target_timestamp_ist <= now_dt + timedelta(hours=horizon_hours)
            )
            .order_by(DemandForecast.target_timestamp_ist)
            .all()
        )
        if not fc_rows:
            engine.generate_forecasts_for_entity(entity_code, horizon_hours=horizon_hours)
            fc_rows = (
                db.query(DemandForecast)
                .filter(
                    DemandForecast.entity_code == entity_code,
                    DemandForecast.target_timestamp_ist >= now_dt,
                    DemandForecast.target_timestamp_ist <= now_dt + timedelta(hours=horizon_hours)
                )
                .order_by(DemandForecast.target_timestamp_ist)
                .all()
            )
    finally:
        db.close()

    if fc_rows:
        chart_data = pd.DataFrame([
            {
                "Time": r.target_timestamp_ist.strftime("%d-%b %H:%M"),
                "P10 (Low Risk)": r.p10_mw,
                "P50 (Expected)": r.p50_mw,
                "P90 (Peak Risk)": r.p90_mw,
                "Net Demand (Post-Solar)": r.net_p50_mw,
                "Solar Generation": r.solar_adjustment_mw,
                "Explainability": r.shap_top_features[0]["plain_english"] if r.shap_top_features else "SCADA diurnal cycle"
            }
            for r in fc_rows
        ])

        col_fc1, col_fc2 = st.columns([3, 1])

        with col_fc1:
            st.markdown("#### Demand Forecast vs Rooftop Solar Duck Curve (MW)")
            st.line_chart(
                chart_data.set_index("Time")[["P90 (Peak Risk)", "P50 (Expected)", "Net Demand (Post-Solar)", "P10 (Low Risk)"]],
                color=["#ef4444", "#38bdf8", "#10b981", "#64748b"]
            )

        with col_fc2:
            st.markdown("#### Solar Generation Impact")
            st.bar_chart(chart_data.set_index("Time")[["Solar Generation"]], color="#f59e0b")
            avg_solar = chart_data["Solar Generation"].mean()
            peak_solar = chart_data["Solar Generation"].max()
            st.metric("Peak Solar Relief", f"{peak_solar:.1f} MW", f"Avg: {avg_solar:.1f} MW")

        st.markdown("#### 🧠 Explainable AI: Top Demand Drivers (SHAP)")
        st.dataframe(
            chart_data[["Time", "P50 (Expected)", "Net Demand (Post-Solar)", "Solar Generation", "Explainability"]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("No forecasts currently available. Click 'Run Fresh Forecast' in the sidebar.")


# --- TAB 2: LIVE DISCOM & PLANT SCADA ---
with tab_scada:
    st.markdown("### ⚡ Live Discom Load & Plant Generation (delhisldc.org Loc=0804)")
    
    col_d1, col_d2 = st.columns(2)
    
    with col_d1:
        st.markdown("#### Real-Time Discom Drawals vs Day Peaks")
        discom_data = []
        for code, name in [("BRPL", "BSES Rajdhani"), ("BYPL", "BSES Yamuna"), ("TPDDL", "Tata Power"), ("NDMC", "NDMC Central"), ("MES", "Military Services")]:
            rec = latest_by_code.get(code)
            if rec:
                discom_data.append({
                    "Discom": name,
                    "Live Drawal (MW)": rec.demand_mw,
                    "Day Peak (MW)": rec.peak_mw,
                    "Day Min (MW)": rec.min_mw,
                    "Day Avg (MW)": rec.avg_mw,
                    "Licensed Cap (MW)": engine.CAPACITY_THRESHOLDS.get(code, 1000.0),
                    "Utilization": f"{(rec.demand_mw / engine.CAPACITY_THRESHOLDS.get(code, 1000.0) * 100):.1f}%"
                })
        if discom_data:
            st.dataframe(pd.DataFrame(discom_data), use_container_width=True, hide_index=True)

    with col_d2:
        st.markdown("#### Delhi Power Generation by Plant (MW)")
        if gen_list:
            gen_df = pd.DataFrame(gen_list)
            st.dataframe(gen_df, use_container_width=True, hide_index=True)
            st.bar_chart(gen_df.set_index("plant_name")[["actual_mw"]], color="#0ea5e9")


# --- TAB 3: DELHI 22-FEEDER NETWORK ---
with tab_feeders:
    st.markdown("### 🔌 Delhi 22-Substation Feeder Network (Section 5 Architecture)")
    st.caption("Real-time distributed load allocation: Feeder Demand = Discom Demand × αᵢ (Flagged as ESTIMATED per regulatory policy)")

    feeders = feeder_seeder.update_feeder_loads()
    if feeders:
        f_df = pd.DataFrame([
            {
                "Feeder Code": f["code"],
                "Substation / Feeder Name": f["name"],
                "Discom": f["discom_code"],
                "Substation": f["substation_name"],
                "Estimated Demand (MW)": f["demand_mw"],
                "Capacity (MW)": f["capacity_mw"],
                "Utilization": f"{f['utilization_pct']}%",
                "Allocation Formula": f["formula"],
                "Telemetry Status": "⚠️ ESTIMATED" if f["is_estimated"] else "🟢 SCADA"
            }
            for f in feeders
        ])
        
        # Filter by Discom
        filter_d = st.selectbox("Filter Feeders by Discom:", ["All"] + list(f_df["Discom"].unique()))
        if filter_d != "All":
            f_df = f_df[f_df["Discom"] == filter_d]

        st.dataframe(f_df, use_container_width=True, hide_index=True)


# --- TAB 4: WHAT-IF HEATWAVE SIMULATOR ---
with tab_whatif:
    st.markdown("### 🧪 Operational What-If Scenario Simulator")
    st.caption("Stress-test Delhi's power grid against heatwaves, humidity surges, and solar buildouts using the trained LightGBM model.")

    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1:
        temp_delta = st.slider("Temperature Offset (°C):", min_value=-5.0, max_value=8.0, value=3.0, step=0.5)
    with col_w2:
        hum_delta = st.slider("Relative Humidity Offset (%):", min_value=-20.0, max_value=30.0, value=5.0, step=5.0)
    with col_w3:
        solar_capacity = st.number_input("Rooftop Solar Buildout (MW):", min_value=500.0, max_value=5000.0, value=2000.0, step=250.0)

    # Compute What-If
    from app.main import what_if_scenario, WhatIfRequest
    db = get_db()
    try:
        req = WhatIfRequest(
            entity_code=entity_code,
            temp_offset_c=temp_delta,
            humidity_offset_pct=hum_delta,
            solar_capacity_mw=solar_capacity,
            hours=24
        )
        wi_res = what_if_scenario(req, db)
    finally:
        db.close()

    if wi_res and "baseline" in wi_res:
        wc1, wc2, wc3, wc4 = st.columns(4)
        wc1.metric("Baseline Peak", f"{wi_res['baseline_peak_mw']:.1f} MW")
        wc2.metric("Scenario Peak", f"{wi_res['scenario_peak_mw']:.1f} MW", f"{wi_res['delta_peak_mw']:+.1f} MW", delta_color="inverse")
        wc3.metric("Grid Headroom Util.", f"{wi_res['scenario_utilization_pct']:.1f}%")
        wc4.metric("Simulated Solar Relief", f"{solar_capacity:.0f} MW")

        wi_chart = pd.DataFrame([
            {
                "Time": b["timestamp_ist"][-5:],
                "Baseline (Normal)": b["gross_mw"],
                f"Scenario (+{temp_delta}°C)": s["gross_mw"],
                "Net Demand (Post-Solar)": s["net_mw"],
            }
            for b, s in zip(wi_res["baseline"], wi_res["scenario"])
        ])
        st.line_chart(wi_chart.set_index("Time"), color=["#38bdf8", "#ef4444", "#10b981"])


# --- TAB 5: ALERTS & SOURCE HEALTH ---
with tab_alerts:
    st.markdown("### 🚨 Capacity Alerts & Upstream Source Health")

    col_a1, col_a2 = st.columns([3, 2])

    with col_a1:
        st.markdown("#### Active Capacity Alerts")
        db = get_db()
        try:
            alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(20).all()
        finally:
            db.close()

        if alerts:
            alert_df = pd.DataFrame([
                {
                    "Severity": a.severity,
                    "Entity": a.entity_code,
                    "Trigger (MW)": f"{a.trigger_mw:.0f} MW",
                    "Utilization": f"{a.utilization_pct:.1f}%",
                    "Status": a.status,
                    "Recommended Action": a.recommended_action
                }
                for a in alerts
            ])
            st.dataframe(alert_df, use_container_width=True, hide_index=True)
        else:
            st.info("No active capacity alerts at present. Grid operating within normal limits.")

    with col_a2:
        st.markdown("#### Live Ingestion Feed Health")
        from app.main import get_source_health
        db = get_db()
        try:
            health_logs = get_source_health(db)
        finally:
            db.close()

        for h in health_logs:
            st.markdown(f"""
            <div style="background: #151d30; padding: 12px; border-radius: 6px; margin-bottom: 8px; border: 1px solid #1e293b;">
                <div style="display: flex; justify-content: space-between;">
                    <b>{h['source']}</b>
                    <span style="color: {'#22c55e' if h['status'] == 'UP' else '#ef4444'}; font-weight: bold;">{h['status']}</span>
                </div>
                <div style="font-size: 0.8rem; color: #94a3b8; margin-top: 4px;">
                    Latency: {h['last_latency_ms'] or 'N/A'} ms | Ingested: {h['last_records']} records | Error Rate: {h['error_rate_1h']}
                </div>
            </div>
            """, unsafe_allow_html=True)

st.markdown("---")
st.caption(f"GridSense Delhi v{settings.VERSION} • Operational SCADA & LightGBM Machine Learning Engine • All timestamps IST (Asia/Kolkata)")
