"""
GridSense Delhi - Open-Meteo Weather Worker
Fetches forecast and historical weather data for all 5 Delhi discom zones.
Also fetches air quality (PM2.5, AQI) from the Open-Meteo AQI API.
No API key required - respects open-meteo.com fair-use policy.
"""
import json
import time
import logging
import urllib.request
import urllib.parse
import ssl
from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, List

from sqlalchemy.orm import Session
from app.models.models import WeatherTelemetry, SourceHealthLog
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Discom zone coordinates (verified against Delhi administrative map)
DISCOM_ZONES = {
    "DELHI":  {"lat": 28.6139, "lon": 77.2090, "name": "Delhi Central (State Ref)"},
    "BRPL":   {"lat": 28.5355, "lon": 77.1600, "name": "BSES Rajdhani (South-West)"},
    "BYPL":   {"lat": 28.6280, "lon": 77.2789, "name": "BSES Yamuna (East)"},
    "TPDDL":  {"lat": 28.7041, "lon": 77.1025, "name": "Tata Power (North)"},
    "NDMC":   {"lat": 28.6353, "lon": 77.2249, "name": "NDMC (Central Vista)"},
    "MES":    {"lat": 28.5961, "lon": 77.1350, "name": "MES (Cantonment)"},
}

WEATHER_VARS = ",".join([
    "temperature_2m", "apparent_temperature", "relative_humidity_2m",
    "dew_point_2m", "wind_speed_10m", "cloud_cover", "precipitation",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation"
])

AQI_VARS = "pm10,pm2_5,us_aqi"

FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_BASE  = "https://archive-api.open-meteo.com/v1/archive"
AQI_BASE      = "https://air-quality-api.open-meteo.com/v1/air-quality"

HEADERS = {"User-Agent": "GridSense-Delhi/1.0 (gridsense@delhi.gov.in)"}


def _fetch_json(url: str) -> Optional[dict]:
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt < 2:
                time.sleep(2 ** attempt * 3)
                continue
            logger.error(f"[Weather] Fetch failed {url}: {exc}")
            return None


def _ist_to_naive(ts_str: str) -> Optional[datetime]:
    """Convert Open-Meteo timestamp string (naive UTC assumed) to naive IST."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            # Open-Meteo returns local time when timezone param is set
            return dt
        return dt.astimezone(IST).replace(tzinfo=None)
    except ValueError:
        return None


def fetch_forecast_all_zones() -> Dict[str, int]:
    """Fetch 16-day hourly forecast for all discom zones and store in DB."""
    fetch_start = time.time()
    totals = {"zones": 0, "records": 0}

    for zone_code, zone_info in DISCOM_ZONES.items():
        lat, lon = zone_info["lat"], zone_info["lon"]
        params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "hourly": WEATHER_VARS,
            "timezone": "Asia/Kolkata",
            "forecast_days": 16,
        })
        url = f"{FORECAST_BASE}?{params}"
        data = _fetch_json(url)
        if not data:
            continue

        # AQI (separate API)
        aqi_params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "hourly": AQI_VARS,
            "timezone": "Asia/Kolkata",
            "forecast_days": 5,
        })
        aqi_data = _fetch_json(f"{AQI_BASE}?{aqi_params}")
        aqi_by_time = {}
        if aqi_data and "hourly" in aqi_data:
            aqi_h = aqi_data["hourly"]
            for i, t in enumerate(aqi_h.get("time", [])):
                aqi_by_time[t] = {
                    "pm2_5": aqi_h.get("pm2_5", [None])[i] if i < len(aqi_h.get("pm2_5", [])) else None,
                    "pm10": aqi_h.get("pm10", [None])[i] if i < len(aqi_h.get("pm10", [])) else None,
                    "us_aqi": aqi_h.get("us_aqi", [None])[i] if i < len(aqi_h.get("us_aqi", [])) else None,
                }

        records = _weather_data_to_records(zone_code, data, is_forecast=True, aqi_by_time=aqi_by_time, source_url=url)
        _upsert_weather_records(records)
        totals["zones"] += 1
        totals["records"] += len(records)
        time.sleep(0.5)  # polite rate limiting

    _log_health("OPEN_METEO_FORECAST", True, int((time.time()-fetch_start)*1000), totals["records"], None)
    logger.info(f"[Weather] Forecast ingested {totals['records']} records across {totals['zones']} zones")
    return totals


def fetch_historical_weather(start_date: str, end_date: str, zone_code: str = "DELHI") -> int:
    """
    Backfill historical weather archive for a zone.
    start_date/end_date: 'YYYY-MM-DD'
    """
    zone_info = DISCOM_ZONES.get(zone_code, DISCOM_ZONES["DELHI"])
    lat, lon = zone_info["lat"], zone_info["lon"]
    params = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": WEATHER_VARS,
        "timezone": "Asia/Kolkata",
    })
    url = f"{ARCHIVE_BASE}?{params}"
    data = _fetch_json(url)
    if not data:
        return 0
    records = _weather_data_to_records(zone_code, data, is_forecast=False, aqi_by_time={}, source_url=url)
    _upsert_weather_records(records)
    logger.info(f"[Weather] Archive {zone_code} {start_date}→{end_date}: {len(records)} records")
    return len(records)


def backfill_all_zones(years: int = 5):
    """Backfill historical weather for all zones up to N years."""
    today = date.today()
    start = date(today.year - years, 1, 1)
    # End yesterday (archive API not up-to-date for today)
    end = date(today.year, today.month, today.day) - timedelta(days=1)

    # Chunk by year to avoid timeout
    for year in range(start.year, end.year + 1):
        chunk_start = date(year, 1, 1)
        chunk_end = min(date(year, 12, 31), end)
        for zone_code in DISCOM_ZONES:
            count = fetch_historical_weather(
                chunk_start.strftime("%Y-%m-%d"),
                chunk_end.strftime("%Y-%m-%d"),
                zone_code
            )
            logger.info(f"[Backfill] {zone_code} {year}: {count} records")
            time.sleep(1)  # polite delay between zones


def _weather_data_to_records(
    zone_code: str, data: dict, is_forecast: bool,
    aqi_by_time: dict, source_url: str
) -> List[WeatherTelemetry]:
    """Convert Open-Meteo JSON hourly data to WeatherTelemetry ORM records."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    records = []

    def g(key, i):
        vals = hourly.get(key, [])
        return vals[i] if i < len(vals) else None

    for i, t_str in enumerate(times):
        ts = _ist_to_naive(t_str)
        if ts is None:
            continue
        temp = g("temperature_2m", i)
        cdh = max(0.0, (temp or 0) - 24.0)  # cooling degree hours base 24°C
        aqi_info = aqi_by_time.get(t_str, {})

        rec = WeatherTelemetry(
            zone_code=zone_code,
            timestamp_ist=ts,
            is_forecast=is_forecast,
            temperature=temp,
            apparent_temperature=g("apparent_temperature", i),
            relative_humidity=g("relative_humidity_2m", i),
            dew_point=g("dew_point_2m", i),
            wind_speed=g("wind_speed_10m", i),
            cloud_cover=g("cloud_cover", i),
            precipitation=g("precipitation", i),
            shortwave_radiation=g("shortwave_radiation", i),
            direct_radiation=g("direct_radiation", i),
            diffuse_radiation=g("diffuse_radiation", i),
            pm2_5=aqi_info.get("pm2_5"),
            pm10=aqi_info.get("pm10"),
            us_aqi=aqi_info.get("us_aqi"),
            cooling_degree_hours=cdh,
            source_url=source_url,
        )
        records.append(rec)
    return records


def _upsert_weather_records(records: List[WeatherTelemetry]):
    """Bulk upsert weather records, ignoring duplicates."""
    if not records:
        return
    db: Session = SessionLocal()
    try:
        for rec in records:
            existing = (
                db.query(WeatherTelemetry)
                .filter_by(
                    zone_code=rec.zone_code,
                    timestamp_ist=rec.timestamp_ist,
                    is_forecast=rec.is_forecast,
                )
                .first()
            )
            if existing:
                # Update forecast data (it changes as models improve)
                existing.temperature = rec.temperature
                existing.apparent_temperature = rec.apparent_temperature
                existing.cloud_cover = rec.cloud_cover
                existing.shortwave_radiation = rec.shortwave_radiation
                existing.cooling_degree_hours = rec.cooling_degree_hours
                if rec.pm2_5 is not None:
                    existing.pm2_5 = rec.pm2_5
                    existing.us_aqi = rec.us_aqi
            else:
                db.add(rec)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(f"[Weather] DB upsert error: {exc}")
    finally:
        db.close()


def _log_health(source: str, success: bool, latency_ms: int, records: int, error: Optional[str]):
    db = SessionLocal()
    try:
        db.add(SourceHealthLog(
            source_name=source, success=success,
            latency_ms=latency_ms, records_ingested=records, error_message=error
        ))
        db.commit()
    except Exception:
        pass
    finally:
        db.close()
