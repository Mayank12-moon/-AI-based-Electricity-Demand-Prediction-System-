"""
GridSense Delhi - FastAPI Application
Provides all REST + WebSocket endpoints for the Delhi SLDC control room UI.
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import pandas as pd

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text, func as sqlfunc

from app.core.config import settings
from app.core.database import get_db, init_db
from app.models.models import (
    Entity, TelemetryRaw, TelemetryCleaned, WeatherTelemetry,
    DemandForecast, Alert, SourceHealthLog, User, Feeder
)
from app.workers import sldc_worker, weather_worker, feeder_seeder
from app.ml.features import load_entity_demand_series, load_weather_dataframe, build_feature_row
from app.ml.forecaster import GridSenseLGBMForecaster, solar_net_demand
from app.ml import engine

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Current time in Delhi IST (naive for SQLite/database storage)."""
    return datetime.now(IST).replace(tzinfo=None)


# --- Background scheduler ---
_scheduler = None
_ws_clients: List[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, seed entities and feeders, start ingestion & forecasting scheduler."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    feeder_seeder.seed_feeders_if_empty()
    
    # Start APScheduler for live polling & forecasting
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    
    # 1. SLDC poll every 3 minutes
    _scheduler.add_job(
        _run_sldc_poll, "interval",
        seconds=settings.SLDC_POLL_INTERVAL_SECONDS,
        id="sldc_poll", replace_existing=True
    )
    # 2. Weather fetch every 30 minutes
    _scheduler.add_job(
        _run_weather_poll, "interval",
        seconds=settings.WEATHER_POLL_INTERVAL_SECONDS,
        id="weather_poll", replace_existing=True
    )
    # 3. Forecast generation every 1 hour
    _scheduler.add_job(
        _run_forecast_job, "interval",
        seconds=settings.FORECAST_INTERVAL_SECONDS,
        id="forecast_job", replace_existing=True
    )
    # 4. Feeder allocated load update every 3 minutes
    _scheduler.add_job(
        _run_feeder_update, "interval",
        seconds=settings.SLDC_POLL_INTERVAL_SECONDS,
        id="feeder_update", replace_existing=True
    )
    
    _scheduler.start()
    
    # Initial immediate ingestion and updates on startup via asyncio.to_thread
    asyncio.create_task(_initial_startup_tasks())
    
    logger.info("[App] GridSense Delhi started — ingestion and forecasting workers running")
    yield
    
    if _scheduler:
        _scheduler.shutdown()
    logger.info("[App] GridSense Delhi stopped")


async def _initial_startup_tasks():
    """Run initial ingestion and forecast generation in thread pool."""
    try:
        await asyncio.to_thread(sldc_worker.fetch_and_store_live)
        await asyncio.to_thread(feeder_seeder.update_feeder_loads)
        # Ensure at least 1 forecast run exists
        await asyncio.to_thread(engine.generate_all_forecasts, 24)
    except Exception as e:
        logger.error(f"[Startup] Initial tasks error: {e}")


async def _run_sldc_poll():
    """Async wrapper for SLDC polling + WebSocket broadcast."""
    try:
        result = await asyncio.to_thread(sldc_worker.fetch_and_store_live)
        await asyncio.to_thread(feeder_seeder.update_feeder_loads)
        if result.get("success"):
            await _broadcast_ws({
                "type": "sldc_update",
                "records": result["records"],
                "timestamp": datetime.now(IST).isoformat()
            })
    except Exception as e:
        logger.error(f"[Worker] SLDC poll failed: {e}")


async def _run_weather_poll():
    try:
        await asyncio.to_thread(weather_worker.fetch_forecast_all_zones)
    except Exception as e:
        logger.error(f"[Worker] Weather poll failed: {e}")


async def _run_forecast_job():
    try:
        await asyncio.to_thread(engine.generate_all_forecasts, 24)
        await _broadcast_ws({
            "type": "forecast_update",
            "timestamp": datetime.now(IST).isoformat()
        })
    except Exception as e:
        logger.error(f"[Worker] Forecast job failed: {e}")


async def _run_feeder_update():
    try:
        await asyncio.to_thread(feeder_seeder.update_feeder_loads)
    except Exception as e:
        logger.error(f"[Worker] Feeder update failed: {e}")


async def _broadcast_ws(message: dict):
    """Broadcast JSON message to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# --- App init ---
app = FastAPI(
    title="GridSense Delhi API",
    description="Real-Time AI Electricity Demand Prediction for Delhi SLDC & Discoms",
    version=settings.VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/api/v1/health")
def health_check():
    """Health check endpoint for deployment monitoring."""
    return {"status": "ok", "service": "GridSense Delhi API", "version": settings.VERSION}


# ============ PYDANTIC SCHEMAS ============

class EntityOut(BaseModel):
    code: str
    name: str
    name_hindi: Optional[str]
    zone: str
    lat: Optional[float]
    lon: Optional[float]
    contract_peak_mw: Optional[float]

    class Config:
        from_attributes = True


class TelemetryPoint(BaseModel):
    entity_code: str
    timestamp_ist: datetime
    demand_mw: Optional[float]
    peak_mw: Optional[float]
    peak_time: Optional[datetime]
    min_mw: Optional[float]
    avg_mw: Optional[float]
    quality_flag: str
    source_name: str
    source_url: Optional[str]
    fetched_at: datetime

    class Config:
        from_attributes = True


class AlertOut(BaseModel):
    id: int
    entity_code: Optional[str]
    severity: str
    title: str
    description: Optional[str]
    trigger_mw: Optional[float]
    capacity_mw: Optional[float]
    utilization_pct: Optional[float]
    recommended_action: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class FeederOut(BaseModel):
    code: str
    name: str
    discom_code: str
    substation_name: Optional[str]
    capacity_mw: Optional[float]
    demand_mw: Optional[float]
    utilization_pct: Optional[float]
    lat: Optional[float]
    lon: Optional[float]
    is_estimated: bool
    formula: Optional[str]

    class Config:
        from_attributes = True


class SolarRequest(BaseModel):
    entity_code: str = "DELHI"
    installed_capacity_mw: float = 1500.0
    hours: int = 24


class WhatIfRequest(BaseModel):
    entity_code: str = "DELHI"
    temp_offset_c: float = 0.0
    humidity_offset_pct: float = 0.0
    is_holiday: Optional[bool] = None
    solar_capacity_mw: float = 1500.0
    hours: int = 24


# ============ HEALTH & DIAGNOSTICS ============

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "GridSense Delhi",
        "timestamp_ist": datetime.now(IST).isoformat()
    }


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ============ ENTITIES ============

@app.get("/api/v1/entities", response_model=List[EntityOut])
def get_entities(db: Session = Depends(get_db)):
    return db.query(Entity).all()


@app.get("/api/v1/entities/{code}", response_model=EntityOut)
def get_entity(code: str, db: Session = Depends(get_db)):
    e = db.query(Entity).filter_by(code=code.upper()).first()
    if not e:
        raise HTTPException(404, f"Entity {code} not found")
    return e


# ============ LIVE TELEMETRY ============

@app.get("/api/v1/telemetry/live", response_model=List[TelemetryPoint])
def get_live_telemetry(db: Session = Depends(get_db)):
    """Latest reading per entity from raw telemetry."""
    subq = (
        db.query(
            TelemetryRaw.entity_code,
            sqlfunc.max(TelemetryRaw.fetched_at).label("max_fetched")
        ).group_by(TelemetryRaw.entity_code).subquery()
    )
    rows = (
        db.query(TelemetryRaw)
        .join(subq, (TelemetryRaw.entity_code == subq.c.entity_code) &
              (TelemetryRaw.fetched_at == subq.c.max_fetched))
        .all()
    )
    return rows


@app.get("/api/v1/telemetry/historical")
def get_historical_telemetry(
    entity_code: str = "DELHI",
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """Cleaned demand series for the requested past hours (IST based)."""
    since = now_ist() - timedelta(hours=hours)
    rows = (
        db.query(TelemetryCleaned)
        .filter(
            TelemetryCleaned.entity_code == entity_code.upper(),
            TelemetryCleaned.timestamp_ist >= since,
        )
        .order_by(TelemetryCleaned.timestamp_ist)
        .all()
    )
    return [
        {
            "timestamp_ist": r.timestamp_ist.isoformat(),
            "demand_mw": r.demand_mw,
            "imputed": r.imputed,
            "quality_score": r.quality_score,
        }
        for r in rows
    ]


@app.post("/api/v1/telemetry/poll-now")
def poll_now(background_tasks: BackgroundTasks):
    """Trigger an immediate SLDC poll and feeder update."""
    def _do_poll():
        sldc_worker.fetch_and_store_live()
        feeder_seeder.update_feeder_loads()

    background_tasks.add_task(_do_poll)
    return {"message": "SLDC poll triggered", "timestamp": datetime.now(IST).isoformat()}


# ============ POWER GENERATION ============

@app.get("/api/v1/generation")
def get_generation():
    """Real-time Delhi power plant generation by unit from SLDC Loc=0804."""
    gen = sldc_worker.get_latest_generation()
    total_mw = sum(g.get("actual_mw", 0) for g in gen)
    return {
        "timestamp_ist": datetime.now(IST).isoformat(),
        "total_actual_mw": round(total_mw, 1),
        "plants": gen
    }


# ============ FEEDERS ============

@app.get("/api/v1/feeders")
def get_feeders(discom_code: Optional[str] = None, db: Session = Depends(get_db)):
    """List 22 Delhi substation feeders with allocated demand and badges."""
    feeder_list = feeder_seeder.update_feeder_loads()
    if discom_code:
        feeder_list = [f for f in feeder_list if f["discom_code"] == discom_code.upper()]
    return feeder_list


# ============ FORECASTS ============

@app.get("/api/v1/forecasts")
def get_forecasts(
    entity_code: str = "DELHI",
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """Get latest LightGBM multi-quantile forecasts with explainability and net demand."""
    now = now_ist()
    until = now + timedelta(hours=hours)

    rows = (
        db.query(DemandForecast)
        .filter(
            DemandForecast.entity_code == entity_code.upper(),
            DemandForecast.target_timestamp_ist >= now,
            DemandForecast.target_timestamp_ist <= until,
        )
        .order_by(DemandForecast.target_timestamp_ist)
        .all()
    )

    # If empty, generate now
    if not rows:
        engine.generate_forecasts_for_entity(entity_code.upper(), horizon_hours=hours)
        rows = (
            db.query(DemandForecast)
            .filter(
                DemandForecast.entity_code == entity_code.upper(),
                DemandForecast.target_timestamp_ist >= now,
                DemandForecast.target_timestamp_ist <= until,
            )
            .order_by(DemandForecast.target_timestamp_ist)
            .all()
        )

    return [
        {
            "timestamp_ist": r.target_timestamp_ist.isoformat(),
            "horizon_hours": r.horizon_hours,
            "p10_mw": r.p10_mw,
            "p50_mw": r.p50_mw,
            "p90_mw": r.p90_mw,
            "net_p50_mw": r.net_p50_mw,
            "solar_mw": r.solar_adjustment_mw,
            "model_name": r.model_name,
            "shap_features": r.shap_top_features or [],
        }
        for r in rows
    ]


@app.post("/api/v1/ml/train")
def trigger_training(entity_code: Optional[str] = None, background_tasks: BackgroundTasks = BackgroundTasks()):
    """Trigger LightGBM quantile regression training for one or all entities."""
    if entity_code:
        background_tasks.add_task(engine.train_model_for_entity, entity_code.upper())
        return {"message": f"Training scheduled for {entity_code.upper()}"}
    else:
        background_tasks.add_task(engine.train_all_entities)
        return {"message": "Full system training scheduled for all entities"}


@app.post("/api/v1/ml/forecast")
def trigger_forecast_generation(horizon_hours: int = 24, background_tasks: BackgroundTasks = BackgroundTasks()):
    """Trigger immediate forecast generation for all entities."""
    background_tasks.add_task(engine.generate_all_forecasts, horizon_hours)
    return {"message": f"Forecast generation triggered for {horizon_hours}h horizon"}


# ============ WEATHER ============

@app.get("/api/v1/weather")
def get_weather(
    zone_code: str = "DELHI",
    hours: int = 48,
    include_forecast: bool = True,
    db: Session = Depends(get_db)
):
    now = now_ist()
    since = now - timedelta(hours=6)
    until = now + timedelta(hours=hours)

    q = db.query(WeatherTelemetry).filter(
        WeatherTelemetry.zone_code == zone_code.upper(),
        WeatherTelemetry.timestamp_ist >= since,
        WeatherTelemetry.timestamp_ist <= until,
    )
    if not include_forecast:
        q = q.filter(WeatherTelemetry.is_forecast == False)
    rows = q.order_by(WeatherTelemetry.timestamp_ist).all()
    return [
        {
            "timestamp_ist": r.timestamp_ist.isoformat(),
            "is_forecast": r.is_forecast,
            "temperature": r.temperature,
            "apparent_temperature": r.apparent_temperature,
            "cloud_cover": r.cloud_cover,
            "shortwave_radiation": r.shortwave_radiation,
            "us_aqi": r.us_aqi,
            "cooling_degree_hours": r.cooling_degree_hours,
            "humidity": r.relative_humidity,
        }
        for r in rows
    ]


# ============ SOLAR ============

@app.post("/api/v1/solar")
def calculate_solar(req: SolarRequest, db: Session = Depends(get_db)):
    """Calculate rooftop solar generation and duck curve using real Open-Meteo GHI."""
    since = now_ist()
    until = since + timedelta(hours=req.hours)
    wx_rows = (
        db.query(WeatherTelemetry)
        .filter(
            WeatherTelemetry.zone_code == req.entity_code,
            WeatherTelemetry.timestamp_ist >= since,
            WeatherTelemetry.timestamp_ist <= until,
            WeatherTelemetry.is_forecast == True,
        )
        .order_by(WeatherTelemetry.timestamp_ist)
        .all()
    )
    demand_rows = (
        db.query(TelemetryCleaned)
        .filter(
            TelemetryCleaned.entity_code == req.entity_code,
            TelemetryCleaned.timestamp_ist >= since - timedelta(hours=2),
        )
        .order_by(TelemetryCleaned.timestamp_ist.desc())
        .limit(1)
        .all()
    )
    current_demand = demand_rows[0].demand_mw if demand_rows else 4300.0

    curve = []
    for wx in wx_rows:
        sol = solar_net_demand(
            gross_demand_mw=float(current_demand),
            installed_capacity_mw=req.installed_capacity_mw,
            ghi_wm2=float(wx.shortwave_radiation or 0),
            cloud_cover_pct=float(wx.cloud_cover or 0),
            temperature_c=float(wx.temperature or 30),
        )
        curve.append({
            "timestamp_ist": wx.timestamp_ist.isoformat(),
            "gross_demand_mw": current_demand,
            "solar_mw": sol["solar_mw"],
            "net_demand_mw": sol["net_demand_mw"],
            "solar_contribution_pct": sol["solar_contribution_pct"],
            "ghi_wm2": wx.shortwave_radiation,
            "cloud_cover_pct": wx.cloud_cover,
            "temperature_c": wx.temperature,
        })

    return {"duck_curve": curve, "installed_capacity_mw": req.installed_capacity_mw}


# ============ WHAT-IF SIMULATOR ============

@app.post("/api/v1/what-if")
def what_if_scenario(req: WhatIfRequest, db: Session = Depends(get_db)):
    """
    Real-time What-If scenario simulator.
    Modifies temperature, humidity, calendar, and solar buildout.
    Runs inference through the trained LightGBM model and returns baseline vs scenario.
    """
    fc = GridSenseLGBMForecaster(req.entity_code)
    if not fc.load():
        engine.train_model_for_entity(req.entity_code)
        if not fc.load():
            raise HTTPException(500, f"Model training required for {req.entity_code}")

    now = now_ist()
    history_start = now - timedelta(days=10)
    demand_history = load_entity_demand_series(req.entity_code, history_start, now)
    if demand_history.empty:
        demand_history = engine.ensure_training_data(req.entity_code, days=7)

    wx_df = load_weather_dataframe(req.entity_code, history_start, now + timedelta(hours=req.hours + 2), include_forecast=True)

    baseline_curve = []
    scenario_curve = []
    capacity_mw = engine.CAPACITY_THRESHOLDS.get(req.entity_code, 3000.0)

    for h in range(1, req.hours + 1):
        target_dt = (now + timedelta(hours=h)).replace(minute=0, second=0, microsecond=0)
        
        # 1. Baseline feature row
        base_feats = build_feature_row(target_dt, demand_history, wx_df)
        df_base = pd.DataFrame([base_feats])
        pred_base = fc.predict(df_base)
        p50_base = float(pred_base["p50"].iloc[0])

        sol_base = solar_net_demand(
            gross_demand_mw=p50_base,
            installed_capacity_mw=req.solar_capacity_mw,
            ghi_wm2=base_feats.get("shortwave_radiation", 0),
            cloud_cover_pct=base_feats.get("cloud_cover", 0),
            temperature_c=base_feats.get("temperature", 30)
        )

        baseline_curve.append({
            "timestamp_ist": target_dt.isoformat(),
            "gross_mw": round(p50_base, 1),
            "solar_mw": round(sol_base["solar_mw"], 1),
            "net_mw": round(sol_base["net_demand_mw"], 1),
        })

        # 2. Scenario feature row with parameter perturbations
        scen_feats = dict(base_feats)
        if req.temp_offset_c != 0.0:
            cur_t = scen_feats.get("temperature", 30.0) or 30.0
            scen_feats["temperature"] = cur_t + req.temp_offset_c
            scen_feats["apparent_temperature"] = (scen_feats.get("apparent_temperature", cur_t) or cur_t) + req.temp_offset_c * 1.2
            scen_feats["cooling_degree_hours"] = max(0.0, scen_feats["temperature"] - 24.0)

        if req.humidity_offset_pct != 0.0:
            cur_rh = scen_feats.get("humidity", 50.0) or 50.0
            scen_feats["humidity"] = min(100.0, max(0.0, cur_rh + req.humidity_offset_pct))

        # Recompute heat index
        T_scen = scen_feats.get("temperature", 30.0)
        RH_scen = scen_feats.get("humidity", 50.0)
        scen_feats["heat_index"] = (
            -8.78469475556 + 1.61139411 * T_scen + 2.3385476 * RH_scen
            - 0.14611605 * T_scen * RH_scen - 0.012308094 * T_scen**2
            - 0.016424828 * RH_scen**2 + 0.002211732 * T_scen**2 * RH_scen
            + 0.00072546 * T_scen * RH_scen**2 - 0.000003582 * T_scen**2 * RH_scen**2
        )

        if req.is_holiday is not None:
            scen_feats["is_holiday"] = 1.0 if req.is_holiday else 0.0

        df_scen = pd.DataFrame([scen_feats])
        pred_scen = fc.predict(df_scen)
        # Apply physical Delhi cooling elasticity (~2.0% per deg C heatwave offset)
        elasticity_factor = 1.0 + (req.temp_offset_c * 0.020) + (req.humidity_offset_pct * 0.003)
        p50_scen = float(pred_scen["p50"].iloc[0]) * elasticity_factor

        sol_scen = solar_net_demand(
            gross_demand_mw=p50_scen,
            installed_capacity_mw=req.solar_capacity_mw,
            ghi_wm2=scen_feats.get("shortwave_radiation", 0),
            cloud_cover_pct=scen_feats.get("cloud_cover", 0),
            temperature_c=scen_feats.get("temperature", 30)
        )

        scenario_curve.append({
            "timestamp_ist": target_dt.isoformat(),
            "gross_mw": round(p50_scen, 1),
            "solar_mw": round(sol_scen["solar_mw"], 1),
            "net_mw": round(sol_scen["net_demand_mw"], 1),
        })

    # Summary metrics
    base_peak = max(b["gross_mw"] for b in baseline_curve) if baseline_curve else 0.0
    scen_peak = max(s["gross_mw"] for s in scenario_curve) if scenario_curve else 0.0
    delta_peak = round(scen_peak - base_peak, 1)
    peak_util_pct = round((scen_peak / capacity_mw) * 100, 1)

    return {
        "entity_code": req.entity_code,
        "capacity_mw": capacity_mw,
        "temp_offset_c": req.temp_offset_c,
        "humidity_offset_pct": req.humidity_offset_pct,
        "solar_capacity_mw": req.solar_capacity_mw,
        "baseline_peak_mw": base_peak,
        "scenario_peak_mw": scen_peak,
        "delta_peak_mw": delta_peak,
        "scenario_utilization_pct": peak_util_pct,
        "baseline": baseline_curve,
        "scenario": scenario_curve,
    }


# ============ ALERTS ============

@app.get("/api/v1/alerts", response_model=List[AlertOut])
def get_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    q = db.query(Alert)
    if status:
        q = q.filter(Alert.status == status.upper())
    if severity:
        q = q.filter(Alert.severity == severity.upper())
    return q.order_by(Alert.created_at.desc()).limit(limit).all()


@app.patch("/api/v1/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, assigned_to: Optional[str] = None, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "ACKNOWLEDGED"
    alert.acknowledged_at = now_ist()
    if assigned_to:
        alert.assigned_to = assigned_to
    db.commit()
    return {"message": "Alert acknowledged", "status": "ACKNOWLEDGED"}


@app.patch("/api/v1/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = "RESOLVED"
    alert.resolved_at = now_ist()
    db.commit()
    return {"message": "Alert resolved", "status": "RESOLVED"}


# ============ SOURCE HEALTH ============

@app.get("/api/v1/sources/health")
def get_source_health(db: Session = Depends(get_db)):
    """Health status per upstream source with 1-hour error rate calculation."""
    sources = ["SLDC", "OPEN_METEO_FORECAST", "GRID_INDIA"]
    result = []
    one_hour_ago = now_ist() - timedelta(hours=1)
    for source in sources:
        latest = (
            db.query(SourceHealthLog)
            .filter(SourceHealthLog.source_name == source)
            .order_by(SourceHealthLog.fetch_at.desc())
            .first()
        )
        recent = (
            db.query(SourceHealthLog)
            .filter(
                SourceHealthLog.source_name == source,
                SourceHealthLog.fetch_at >= one_hour_ago,
            )
            .all()
        )
        total = len(recent)
        errors = sum(1 for r in recent if not r.success)
        result.append({
            "source": source,
            "last_fetch": latest.fetch_at.isoformat() if latest else None,
            "last_success": latest.success if latest else None,
            "last_latency_ms": latest.latency_ms if latest else None,
            "last_records": latest.records_ingested if latest else 0,
            "error_message": latest.error_message if latest and not latest.success else None,
            "error_rate_1h": f"{errors}/{total}" if total else "0/0",
            "status": "UP" if (latest and latest.success) else "DOWN",
        })
    return result


# ============ WEBSOCKET ============

@app.websocket("/ws/live")
async def live_ws(websocket: WebSocket):
    """WebSocket endpoint for real-time telemetry push to control rooms."""
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "GridSense Delhi Live Telemetry Feed Connected",
            "timestamp": datetime.now(IST).isoformat(),
        }))
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({
                "type": "ping",
                "timestamp": datetime.now(IST).isoformat()
            }))
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)
    except Exception:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


# ============ ADMIN STATS ============

@app.get("/api/v1/admin/stats")
def get_admin_stats(db: Session = Depends(get_db)):
    """System-wide operational telemetry counts."""
    raw_count = db.query(TelemetryRaw).count()
    cleaned_count = db.query(TelemetryCleaned).count()
    weather_count = db.query(WeatherTelemetry).count()
    forecast_count = db.query(DemandForecast).count()
    alert_count = db.query(Alert).filter(Alert.status == "ACTIVE").count()
    feeder_count = db.query(Feeder).count()
    return {
        "raw_telemetry_records": raw_count,
        "cleaned_telemetry_records": cleaned_count,
        "weather_records": weather_count,
        "forecast_records": forecast_count,
        "feeders_monitored": feeder_count,
        "active_alerts": alert_count,
        "timestamp_ist": datetime.now(IST).isoformat(),
    }


# ============ STATIC FRONTEND MOUNT ============
_frontend_candidates = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend")),
    os.path.abspath("frontend"),
]
_frontend_dir = next((p for p in _frontend_candidates if os.path.exists(p)), None)
if _frontend_dir:
    logger.info(f"[Static] Mounting frontend from: {_frontend_dir}")
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
else:
    logger.warning("[Static] Frontend directory not found in candidates.")


