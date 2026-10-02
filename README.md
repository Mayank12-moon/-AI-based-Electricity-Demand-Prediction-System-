# GridSense Delhi: Real-Time AI Electricity Demand Prediction & Control Room

GridSense Delhi is an industrial-grade electricity demand forecasting and SCADA monitoring platform for the **Delhi State Load Despatch Center (SLDC)** and its five distribution companies:
- **BRPL** (BSES Rajdhani Power Limited — South & West Delhi)
- **BYPL** (BSES Yamuna Power Limited — East & Central Delhi)
- **TPDDL** (Tata Power Delhi Distribution Limited — North & North-West Delhi)
- **NDMC** (New Delhi Municipal Council — Central Vista & Lutyens)
- **MES** (Military Engineer Services — Delhi Cantonment)

---

## Architecture Overview

```
                                  [ Live Upstream Feeds ]
                                             │
               ┌─────────────────────────────┼─────────────────────────────┐
               ▼                             ▼                             ▼
       Delhi SLDC Scraper            Open-Meteo Weather            Grid-India (POSOCO)
   • Loc=0804: Instantaneous drawals  • 16-day hourly forecast      • Daily PSP Reports (.xls)
   • Loc=0805: Day peaks & averages   • 5 Discom zone coordinates   • 15-min TimeSeries blocks
   • dc_schedule: 15-min blocks CSV   • Solar radiation (GHI/DHI)   • Multi-year national baselines
   • Power plants generation by unit  • Air Quality (PM2.5, AQI)
               │                             │                             │
               └─────────────────────────────┼─────────────────────────────┘
                                             ▼
                                  [ Telemetry Storage ]
                                • SQLite / PostgreSQL
                                • TelemetryRaw (Immutable audit)
                                • TelemetryCleaned (Gap-filled)
                                • WeatherTelemetry (Forecast/Archive)
                                             │
                                             ▼
                             [ Feature Engineering Matrix ]
                             • 64 Real-time features
                             • Lags (15m, 1h, 2h, 3h, 6h, 24h, 168h)
                             • Rolling stats (Mean, Std, Max, Min)
                             • Heat Index & Cooling Degree Hours
                             • Delhi Gazetted Holidays & Festivals
                                             │
                                             ▼
                             [ Multi-Quantile LightGBM ]
                             • P10 (10th percentile - Low risk)
                             • P50 (Median point forecast)
                             • P90 (90th percentile - Peak risk)
                             • SHAP Explainability Engine
                             • Rooftop Solar Duck Curve Net Demand
                                             │
               ┌─────────────────────────────┴─────────────────────────────┐
               ▼                                                           ▼
     [ FastAPI Backend REST & WS ]                               [ Streamlit Control Room ]
     • Port 8000                                                 • Port 8501
     • Real-time SCADA endpoints                                 • Live Discom drawals & gauges
     • 24h / 168h forecast APIs                                  • P10/P50/P90 forecast envelopes
     • Feeder allocated loads (22 feeders)                       • 22 Delhi feeders with badges
     • Plant generation breakdowns                               • Interactive What-If heatwave test
     • What-If heatwave simulator                                • Active capacity headroom alerts
```

---

## Key Features

1. **Dual-Endpoint SLDC Real-Time SCADA**:
   - `Loc=0804`: Extracts instantaneous demand in MW for Delhi state total (e.g. 4,280 MW) and Discom drawals, scheduled allocations, overdraw/underdraw (OD/UD), and 7 in-state power generation plants (Bawana CCGT, GT, Waste-to-Energy).
   - `Loc=0805`: Ingests day peak, peak time, day minimum, and day average loads.
2. **Multi-Quantile LightGBM Forecaster (P10, P50, P90)**:
   - Evaluates multi-horizon forecasts with prediction intervals for probabilistic grid management.
3. **Explainable AI (SHAP)**:
   - Computes exact feature attributions for every hour and translates them into plain-English operator sentences (e.g., *"Yesterday same hour demand (4,120 MW) increased today's by ~185 MW"*, *"Temperature 34.5°C increased demand by ~81 MW"*).
4. **Rooftop Solar Duck Curve & Net Demand**:
   - Derives solar generation relief from Open-Meteo Global Horizontal Irradiance ($GHI$) and temperature derating coefficients, outputting Gross vs Net demand curves.
5. **22-Feeder Substation Network**:
   - Covers 66kV, 33kV, and 11kV substations across Delhi discoms with load allocation weights ($\alpha_i$) and explicit `ESTIMATED` badges per regulatory policy.
6. **Operational What-If Heatwave Simulator**:
   - Real-time simulation of temperature surges (+1°C to +8°C), humidity shifts, and solar buildouts using thermal cooling load elasticity and LightGBM inference.
7. **Automated Capacity Alerts**:
   - Evaluates forecasted peaks against licensed Discom capacities (>85% `WATCH`, >90% `WARNING`, >95% `CRITICAL`) with recommended dispatcher interventions.

---

## Quickstart

### 1. Run FastAPI Backend
```powershell
cd d:\electricity\backend
$env:PYTHONPATH='.'
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation will be live at: `http://localhost:8000/api/docs`

### 2. Run Streamlit Control Room Dashboard
```powershell
cd d:\electricity\backend
$env:PYTHONPATH='.'
streamlit run dashboard.py --server.port 8501
```
Dashboard will open at: `http://localhost:8501`

### 3. Run System Diagnostic Test
```powershell
cd d:\electricity
$env:PYTHONPATH='d:\electricity\backend'
python scripts\test_api_endpoints.py
```
