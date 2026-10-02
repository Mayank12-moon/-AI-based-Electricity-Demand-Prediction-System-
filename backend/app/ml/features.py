"""
GridSense Delhi - Feature Engineering
Builds the ML feature matrix from cleaned telemetry + weather data.
All features are computed from real measured/forecast data.
"""
import numpy as np
import pandas as pd
import holidays
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.models import TelemetryCleaned, WeatherTelemetry
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

DELHI_HOLIDAYS = holidays.country_holidays("IN", subdiv="DL")

# Festival "season" windows (Navratri -> Diwali + Dussehra area)
FESTIVAL_WINDOWS = [
    {"name": "Navratri-Diwali", "month_start": 10, "day_start": 1, "month_end": 11, "day_end": 15},
    {"name": "Holi", "month_start": 3, "day_start": 1, "month_end": 3, "day_end": 20},
    {"name": "Independence-Republic", "month_start": 1, "day_start": 24, "month_end": 1, "day_end": 28},
]


def _is_festival_season(dt: datetime) -> bool:
    """Check if datetime falls within any major festival window."""
    m, d = dt.month, dt.day
    for fw in FESTIVAL_WINDOWS:
        ms, ds = fw["month_start"], fw["day_start"]
        me, de = fw["month_end"], fw["day_end"]
        start_ok = (m > ms) or (m == ms and d >= ds)
        end_ok = (m < me) or (m == me and d <= de)
        if start_ok and end_ok:
            return True
    return False


def _days_since_heatwave(dt: datetime, weather_df: pd.DataFrame) -> float:
    """Count consecutive days with max_temp >= 40°C ending at dt."""
    if weather_df is None or weather_df.empty:
        return 0.0
    day_max = weather_df.resample("D")["temperature"].max()
    dt_date = dt.date()
    count = 0
    for i in range(30):
        check_date = dt_date - timedelta(days=i)
        if check_date in day_max.index and day_max[check_date] >= 40.0:
            count += 1
        else:
            break
    return float(count)


def build_feature_row(
    dt: datetime,
    demand_history: pd.Series,
    weather_df: Optional[pd.DataFrame] = None
) -> dict:
    """
    Build a single feature dict for a given target datetime.
    demand_history: Series indexed by datetime with demand_mw values.
    weather_df: DataFrame with weather columns indexed by datetime.
    """
    feats = {}

    # --- Temporal features ---
    feats["hour"] = dt.hour
    feats["hour_sin"] = np.sin(2 * np.pi * dt.hour / 24)
    feats["hour_cos"] = np.cos(2 * np.pi * dt.hour / 24)
    feats["dow"] = dt.weekday()   # 0=Monday
    feats["dow_sin"] = np.sin(2 * np.pi * dt.weekday() / 7)
    feats["dow_cos"] = np.cos(2 * np.pi * dt.weekday() / 7)
    feats["month"] = dt.month
    feats["month_sin"] = np.sin(2 * np.pi * dt.month / 12)
    feats["month_cos"] = np.cos(2 * np.pi * dt.month / 12)
    feats["doy"] = dt.timetuple().tm_yday
    feats["doy_sin"] = np.sin(2 * np.pi * feats["doy"] / 365)
    feats["doy_cos"] = np.cos(2 * np.pi * feats["doy"] / 365)
    feats["year"] = dt.year

    # --- Calendar / behavioral ---
    feats["is_holiday"] = float(dt.date() in DELHI_HOLIDAYS)
    feats["is_weekend"] = float(dt.weekday() >= 5)
    feats["is_festival_season"] = float(_is_festival_season(dt))
    feats["is_monday"] = float(dt.weekday() == 0)  # post-weekend rebound

    # --- Demand lags (MW) ---
    lag_minutes = [15, 60, 120, 180, 360, 1440, 2880, 10080]
    lag_labels =  ["15m","1h","2h","3h","6h","24h","48h","168h"]
    for mins, label in zip(lag_minutes, lag_labels):
        lag_ts = dt - timedelta(minutes=mins)
        if lag_ts in demand_history.index:
            feats[f"lag_{label}"] = demand_history[lag_ts]
        else:
            # nearest available
            idx = demand_history.index.searchsorted(lag_ts)
            if 0 < idx < len(demand_history):
                feats[f"lag_{label}"] = float(demand_history.iloc[idx - 1])
            else:
                feats[f"lag_{label}"] = np.nan

    # --- Rolling statistics (last N hours) ---
    for hours in [3, 6, 12, 24, 48, 168]:
        window_start = dt - timedelta(hours=hours)
        window = demand_history[(demand_history.index >= window_start) & (demand_history.index < dt)]
        suffix = f"{hours}h"
        feats[f"roll_mean_{suffix}"] = float(window.mean()) if len(window) > 0 else np.nan
        feats[f"roll_max_{suffix}"]  = float(window.max())  if len(window) > 0 else np.nan
        feats[f"roll_min_{suffix}"]  = float(window.min())  if len(window) > 0 else np.nan
        feats[f"roll_std_{suffix}"]  = float(window.std())  if len(window) > 0 else np.nan

    # --- Weather features ---
    if weather_df is not None and not weather_df.empty:
        # Find nearest weather record <= dt
        past_wx = weather_df[weather_df.index <= dt]
        if not past_wx.empty:
            wx = past_wx.iloc[-1]
            feats["temperature"] = wx.get("temperature", np.nan)
            feats["apparent_temperature"] = wx.get("apparent_temperature", np.nan)
            feats["humidity"] = wx.get("relative_humidity", np.nan)
            feats["dew_point"] = wx.get("dew_point", np.nan)
            feats["wind_speed"] = wx.get("wind_speed", np.nan)
            feats["cloud_cover"] = wx.get("cloud_cover", np.nan)
            feats["precipitation"] = wx.get("precipitation", np.nan)
            feats["shortwave_radiation"] = wx.get("shortwave_radiation", np.nan)
            feats["direct_radiation"] = wx.get("direct_radiation", np.nan)
            feats["diffuse_radiation"] = wx.get("diffuse_radiation", np.nan)
            feats["pm2_5"] = wx.get("pm2_5", np.nan)
            feats["us_aqi"] = wx.get("us_aqi", np.nan)
            feats["cooling_degree_hours"] = wx.get("cooling_degree_hours", np.nan)
            # Heat index approximation
            T = feats.get("temperature", 25)
            RH = feats.get("humidity", 50)
            feats["heat_index"] = (
                -8.78469475556 + 1.61139411 * T + 2.3385476 * RH
                - 0.14611605 * T * RH - 0.012308094 * T**2
                - 0.016424828 * RH**2 + 0.002211732 * T**2 * RH
                + 0.00072546 * T * RH**2 - 0.000003582 * T**2 * RH**2
                if T is not None and RH is not None else np.nan
            )
            feats["days_since_heatwave_start"] = _days_since_heatwave(dt, weather_df)
        else:
            for wk in ["temperature","apparent_temperature","humidity","dew_point","wind_speed",
                       "cloud_cover","precipitation","shortwave_radiation","direct_radiation",
                       "diffuse_radiation","pm2_5","us_aqi","cooling_degree_hours",
                       "heat_index","days_since_heatwave_start"]:
                feats[wk] = np.nan
    else:
        for wk in ["temperature","apparent_temperature","humidity","dew_point","wind_speed",
                   "cloud_cover","precipitation","shortwave_radiation","direct_radiation",
                   "diffuse_radiation","pm2_5","us_aqi","cooling_degree_hours",
                   "heat_index","days_since_heatwave_start"]:
            feats[wk] = np.nan

    return feats


def load_entity_demand_series(entity_code: str, start: datetime, end: datetime) -> pd.Series:
    """Load cleaned demand series from DB for feature engineering."""
    db = SessionLocal()
    try:
        rows = (
            db.query(TelemetryCleaned)
            .filter(
                TelemetryCleaned.entity_code == entity_code,
                TelemetryCleaned.timestamp_ist >= start,
                TelemetryCleaned.timestamp_ist <= end,
            )
            .order_by(TelemetryCleaned.timestamp_ist)
            .all()
        )
        if not rows:
            return pd.Series(dtype=float)
        idx = [r.timestamp_ist for r in rows]
        vals = [r.demand_mw for r in rows]
        return pd.Series(vals, index=pd.DatetimeIndex(idx))
    finally:
        db.close()


def load_weather_dataframe(zone_code: str, start: datetime, end: datetime, include_forecast: bool = False) -> pd.DataFrame:
    """Load weather records from DB into a DataFrame indexed by timestamp."""
    db = SessionLocal()
    try:
        q = (
            db.query(WeatherTelemetry)
            .filter(
                WeatherTelemetry.zone_code == zone_code,
                WeatherTelemetry.timestamp_ist >= start,
                WeatherTelemetry.timestamp_ist <= end,
            )
        )
        if not include_forecast:
            q = q.filter(WeatherTelemetry.is_forecast == False)
        rows = q.order_by(WeatherTelemetry.timestamp_ist).all()
        if not rows:
            return pd.DataFrame()
        data = []
        for r in rows:
            data.append({
                "temperature": r.temperature,
                "apparent_temperature": r.apparent_temperature,
                "relative_humidity": r.relative_humidity,
                "dew_point": r.dew_point,
                "wind_speed": r.wind_speed,
                "cloud_cover": r.cloud_cover,
                "precipitation": r.precipitation,
                "shortwave_radiation": r.shortwave_radiation,
                "direct_radiation": r.direct_radiation,
                "diffuse_radiation": r.diffuse_radiation,
                "pm2_5": r.pm2_5,
                "us_aqi": r.us_aqi,
                "cooling_degree_hours": r.cooling_degree_hours,
            })
        return pd.DataFrame(data, index=pd.DatetimeIndex([r.timestamp_ist for r in rows]))
    finally:
        db.close()
