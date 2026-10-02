# GridSense Delhi: Live Data Sources & Discovery Analysis

This document details the real-world discovery findings, endpoint architectures, payload schemas, update cadences, and integration adapters for the **GridSense Delhi** system. Every metric in GridSense Delhi originates from verified, live public and operational sources.

---

## 1. Delhi State Load Despatch Center (SLDC)

### 1.1 Real-Time Discom & State Demand Feed
- **Primary Live URL**: `https://www.delhisldc.org/Redirect.aspx?Loc=0805`
- **Internal ASP.NET Handler**: `https://www.delhisldc.org/Loadcurve.aspx?Loc=0805`
- **Update Frequency**: Every 1–5 minutes (live SCADA updates).
- **Data Format**: Server-rendered HTML table (`#ContentPlaceHolder2_dgdetails`) and dynamic WebChart session PNG (`/WebCharts/<uuid>.Png`).
- **Discoms Covered**:
  1. `Delhi` (Total State Demand)
  2. `BRPL` (BSES Rajdhani Power Limited - South & West Delhi)
  3. `BYPL` (BSES Yamuna Power Limited - East & Central Delhi)
  4. `NDPL` / `TPDDL` (Tata Power Delhi Distribution Limited - North & North-West Delhi)
  5. `NDMC` (New Delhi Municipal Council - Central Vista, Connaught Place, Chanakyapuri)
  6. `MES` (Military Engineer Services - Delhi Cantonment)
- **Extracted Fields per Entity**:
  - `Peak Load` (MW)
  - `Peak Load Time` (HH:MM:SS IST)
  - `Min. Load` (MW)
  - `Min. Load Time` (HH:MM:SS IST)
  - `Avg. Load` (MW)
  - `Current Timestamp` (DD/MM/YYYY HH:MM:SS IST)
- **Historical Query Mechanism**:
  - ASP.NET Postback using `__VIEWSTATE`, `__EVENTVALIDATION`, and `ctl00$ContentPlaceHolder2$SelectedDate` (`DD/MM/YYYY`) with `ctl00$ContentPlaceHolder2$cmbdiscom`.
  - Tested and confirmed working for arbitrary historical dates (e.g. 30/09/2026 returned peak 5473 MW at 18:55:46).

### 1.2 Discom Drawal & Generation Schedules (15-Minute Block SCADA)
- **URL**: `https://www.delhisldc.org/dc_schedule.aspx`
- **Update Frequency**: Continuous throughout the day (revision numbers up to Rev 115+ daily).
- **Files Published**:
  - `api_response_<DD-MM-YYYY>.json`: Full system interchange & schedule revision JSON (1.9+ MB per day).
  - `BRPLDS_<DD-MM-YYYY>.csv`: 96 time-block schedule (15-min intervals) for BRPL including plant-level drawals (Dadri, Pragati, Rithala, Rihand, Singrauli, Solar/Wind).
  - `BYPLDS_<DD-MM-YYYY>.csv`: 96 time-block schedule for BYPL.
  - `TPDDLDS_<DD-MM-YYYY>.csv` / `NDPLDS`: 96 time-block schedule for TPDDL.
  - `NDMCDS_<DD-MM-YYYY>.csv`: 96 time-block schedule for NDMC.
  - `MESDS_<DD-MM-YYYY>.csv`: 96 time-block schedule for MES.
- **Data Granularity**: 96 blocks per 24-hour cycle (00:00, 00:15, 00:30, ..., 23:45).

---

## 2. Grid Controller of India (Grid-India / POSOCO)

### 2.1 Daily Power Supply Position (PSP) Reports
- **Portal**: `https://grid-india.in/reports/daily-reports/psp-report/`
- **Underlying REST API**: `https://webapi.grid-india.in/api/v1/file`
- **Payload**: `{"_source": "grdw", "_type": "DAILY_PSP_REPORT"}`
- **Repository Size**: **6,343 live daily reports** cataloged from 2010 to October 2026.
- **File Storage CDN**: `https://webcdn.grid-india.in/files/grdw/<YYYY>/<MM>/<filename>.xls`
- **Format**: Standard Microsoft Excel BIFF8 (`.xls`) parsed via `pandas` + `xlrd`.
- **Key Sheets**:
  - `MOP_E`: State-wise Peak Demand Met (MW), Energy Met (MU), Shortage / Unconstrained Demand. Specifically extracts Delhi row:
    - *Row 22 (Delhi)*: Peak Demand Met (MW), Energy Met (MU), Hydro/Thermal/Gas allocation.
  - `TimeSeries`: 15-Minute instantaneous frequency, regional demand, and national hydro/thermal generation.
- **Cross-Validation**: Used to cross-verify SLDC daily totals and historical multi-year baselines.

---

## 3. Open-Meteo High-Resolution Weather & Air Quality APIs

Open-Meteo provides millisecond-latency, keyless weather APIs with specific latitude/longitude resolution tailored to Delhi's five discom zones:

| Zone / Discom | Primary Area | Latitude (°N) | Longitude (°E) | Elevation (m) |
|---|---|---|---|---|
| **Delhi Central** | Capital Hub / Benchmark | 28.6139 | 77.2090 | 216 |
| **BRPL** | South & West Delhi | 28.5355 | 77.1600 | 228 |
| **BYPL** | East & Central Delhi (Yamuna) | 28.6280 | 77.2789 | 208 |
| **TPDDL** | North & North-West Delhi | 28.7041 | 77.1025 | 220 |
| **MES** | Delhi Cantonment | 28.5961 | 77.1350 | 230 |

### 3.1 Forecast API
- **Endpoint**: `https://api.open-meteo.com/v1/forecast`
- **Horizon**: 16 days hourly (384 steps).
- **Variables**:
  - `temperature_2m` (°C)
  - `apparent_temperature` (°C) (Heat Index / Wind Chill proxy)
  - `relative_humidity_2m` (%)
  - `dew_point_2m` (°C)
  - `wind_speed_10m` (km/h)
  - `cloud_cover` (%)
  - `precipitation` (mm)
  - `shortwave_radiation` (W/m²)
  - `direct_radiation` (W/m²)
  - `diffuse_radiation` (W/m²)
- **Timezone**: `Asia/Kolkata` (IST).

### 3.2 Historical Archive API
- **Endpoint**: `https://archive-api.open-meteo.com/v1/archive`
- **Coverage**: Multi-year historical backfill from 1940 to present date.
- **Use Case**: ML model feature engineering, training dataset backfill, historical heatwave correlation.

### 3.3 Air Quality API
- **Endpoint**: `https://air-quality-api.open-meteo.com/v1/air-quality`
- **Variables**: `pm2_5`, `pm10`, `carbon_monoxide`, `nitrogen_dioxide`, `sulphur_dioxide`, `ozone`, `us_aqi`, `european_aqi`.
- **Correlation**: Severe smog / AQI peaks in November–January reduce solar generation and alter cooling/heating device usage in NCR.

---

## 4. Indian Calendar & Festival Engine

- **Library & Source**: Official Delhi NCT Gazetted holidays engine (`holidays.country_holidays('IN', subdiv='DL')`).
- **Dynamic Year Generation**: Re-evaluates on any target date/year.
- **Variables Generated**:
  - `is_holiday`: Boolean flag.
  - `holiday_name`: Exact gazetted festival/holiday title (Diwali, Eid, Holi, Independence Day, Republic Day, Gandhi Jayanti, etc.).
  - `is_weekend`: Saturday/Sunday flag.
  - `is_festival_season`: Festive lighting load modifier (Navratri through Diwali).

---

## 5. Feeder Telemetry Architecture & Estimation Policy

Public regulatory sources provide Discom-level resolution, but feeder-level SCADA is restricted behind discom intranet firewalls.

- **Pluggable Adapter Interfaces**:
  1. `CSV/Excel Adapter`: Bulk upload of 15-minute feeder meter recordings with schema auto-detection.
  2. `REST Poller Adapter`: Scheduled polling of Discom internal API endpoints.
  3. `MQTT / Kafka Adapter`: Streaming topic consumer for SCADA edge nodes.
  4. `OPC-UA / IEC 60870-5-104 Stub`: Documented industrial protocol bridge.
- **Strict Data Integrity Policy**:
  - Unconnected feeders utilize allocation from parent discom load:
    $$\text{Feeder Demand}_{\text{est}} = \text{Discom Demand}_{\text{actual}} \times \alpha_i$$
  - Every allocated number in the UI is rendered with distinct dotted styling, amber warning icon, and explicit badge:
    `ESTIMATED (allocated from discom load using historical shares)`.
  - Tooltips specify the exact formula, discom parent, and allocation weight.

---

## 6. Polling, Resilience & Data Quality Assurance

- **Ingestion Workers**:
  - Real-time SLDC Poller: Every 3 minutes.
  - Weather Poller: Every 30 minutes.
  - Daily Report Ingestion: Every 6 hours.
- **Dropout & Anomaly Handling**:
  - **Zero / Negative Detection**: Flagged `QUALITY_INVALID_ZERO`.
  - **Spike Detection**: Step changes $>30\%$ in 3 minutes flagged `QUALITY_SPIKE`.
  - **Staleness Detection**: Unchanged value over 6 consecutive cycles flagged `QUALITY_STALE`.
  - **Cleaned Series Separation**: Raw series remains completely untouched in `telemetry_raw`; cleaned series in `telemetry_cleaned` with interpolation method explicitly recorded (`linear_30m`, `previous_valid`).
