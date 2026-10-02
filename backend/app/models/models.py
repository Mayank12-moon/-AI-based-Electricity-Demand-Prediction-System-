"""
GridSense Delhi - Database Models
SQLAlchemy 2.0 models for all core entities.
All timestamps are IST (Asia/Kolkata).
"""
from datetime import datetime, date
from typing import Optional, Any
from sqlalchemy import (
    Integer, Float, String, Boolean, DateTime, Date,
    Text, ForeignKey, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Entity(Base):
    """Discoms and Delhi State entity registry."""
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)          # 'DELHI', 'BRPL', 'BYPL', 'TPDDL', 'NDMC', 'MES'
    name: Mapped[str] = mapped_column(String(100))
    name_hindi: Mapped[Optional[str]] = mapped_column(String(100))
    zone: Mapped[Optional[str]] = mapped_column(String(50))              # 'state', 'discom', 'feeder'
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)
    contract_peak_mw: Mapped[Optional[float]] = mapped_column(Float)     # Published peak capacity
    capacity_source: Mapped[Optional[str]] = mapped_column(String(200))  # Citation for capacity figure
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())

    telemetry_raw = relationship("TelemetryRaw", back_populates="entity", lazy="dynamic")
    telemetry_cleaned = relationship("TelemetryCleaned", back_populates="entity", lazy="dynamic")
    forecasts = relationship("DemandForecast", back_populates="entity", lazy="dynamic")
    feeders = relationship("Feeder", back_populates="discom", lazy="dynamic")


class TelemetryRaw(Base):
    """
    Immutable raw readings received verbatim from upstream sources.
    NEVER modified after insert. quality_flag records any anomaly detected.
    """
    __tablename__ = "telemetry_raw"
    __table_args__ = (
        Index("ix_telemetry_raw_entity_ts", "entity_code", "timestamp_ist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_code: Mapped[str] = mapped_column(String(20), ForeignKey("entities.code"))
    timestamp_ist: Mapped[datetime] = mapped_column(DateTime)
    demand_mw: Mapped[Optional[float]] = mapped_column(Float)
    peak_mw: Mapped[Optional[float]] = mapped_column(Float)
    peak_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    min_mw: Mapped[Optional[float]] = mapped_column(Float)
    min_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    avg_mw: Mapped[Optional[float]] = mapped_column(Float)
    frequency_hz: Mapped[Optional[float]] = mapped_column(Float)
    source_name: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    source_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)
    quality_flag: Mapped[Optional[str]] = mapped_column(String(30), default="OK")
    raw_payload: Mapped[Optional[str]] = mapped_column(Text)

    entity = relationship("Entity", back_populates="telemetry_raw")


class TelemetryCleaned(Base):
    """
    Validated, gap-filled continuous series for ML modeling.
    Imputed points are explicitly flagged and labeled.
    """
    __tablename__ = "telemetry_cleaned"
    __table_args__ = (
        UniqueConstraint("entity_code", "timestamp_ist", name="uq_cleaned_entity_ts"),
        Index("ix_telemetry_cleaned_entity_ts", "entity_code", "timestamp_ist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_code: Mapped[str] = mapped_column(String(20), ForeignKey("entities.code"))
    timestamp_ist: Mapped[datetime] = mapped_column(DateTime)
    demand_mw: Mapped[float] = mapped_column(Float)
    imputed: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    imputation_method: Mapped[Optional[str]] = mapped_column(String(50))
    raw_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("telemetry_raw.id"), nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, default=1.0)

    entity = relationship("Entity", back_populates="telemetry_cleaned")


class WeatherTelemetry(Base):
    """Weather + AQI readings per discom zone from Open-Meteo."""
    __tablename__ = "weather_telemetry"
    __table_args__ = (
        UniqueConstraint("zone_code", "timestamp_ist", "is_forecast", name="uq_weather_zone_ts"),
        Index("ix_weather_zone_ts", "zone_code", "timestamp_ist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_code: Mapped[str] = mapped_column(String(20))
    timestamp_ist: Mapped[datetime] = mapped_column(DateTime)
    is_forecast: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    temperature: Mapped[Optional[float]] = mapped_column(Float)
    apparent_temperature: Mapped[Optional[float]] = mapped_column(Float)
    relative_humidity: Mapped[Optional[float]] = mapped_column(Float)
    dew_point: Mapped[Optional[float]] = mapped_column(Float)
    wind_speed: Mapped[Optional[float]] = mapped_column(Float)
    cloud_cover: Mapped[Optional[float]] = mapped_column(Float)
    precipitation: Mapped[Optional[float]] = mapped_column(Float)
    shortwave_radiation: Mapped[Optional[float]] = mapped_column(Float)
    direct_radiation: Mapped[Optional[float]] = mapped_column(Float)
    diffuse_radiation: Mapped[Optional[float]] = mapped_column(Float)
    pm2_5: Mapped[Optional[float]] = mapped_column(Float)
    pm10: Mapped[Optional[float]] = mapped_column(Float)
    us_aqi: Mapped[Optional[float]] = mapped_column(Float)
    cooling_degree_hours: Mapped[Optional[float]] = mapped_column(Float)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    source_url: Mapped[Optional[str]] = mapped_column(String(500))


class DemandForecast(Base):
    """Multi-horizon demand forecasts with uncertainty intervals."""
    __tablename__ = "demand_forecasts"
    __table_args__ = (
        Index("ix_forecast_entity_target", "entity_code", "target_timestamp_ist"),
        Index("ix_forecast_run_at", "forecast_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_code: Mapped[str] = mapped_column(String(20), ForeignKey("entities.code"))
    forecast_run_at: Mapped[datetime] = mapped_column(DateTime)
    target_timestamp_ist: Mapped[datetime] = mapped_column(DateTime)
    horizon_hours: Mapped[Optional[int]] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[Optional[str]] = mapped_column(String(40))
    p05_mw: Mapped[Optional[float]] = mapped_column(Float)
    p10_mw: Mapped[Optional[float]] = mapped_column(Float)
    p50_mw: Mapped[Optional[float]] = mapped_column(Float)
    p90_mw: Mapped[Optional[float]] = mapped_column(Float)
    p95_mw: Mapped[Optional[float]] = mapped_column(Float)
    actual_mw: Mapped[Optional[float]] = mapped_column(Float)
    abs_error_mw: Mapped[Optional[float]] = mapped_column(Float)
    ape_percent: Mapped[Optional[float]] = mapped_column(Float)
    shap_top_features: Mapped[Optional[Any]] = mapped_column(JSON)
    solar_adjustment_mw: Mapped[Optional[float]] = mapped_column(Float)
    net_p50_mw: Mapped[Optional[float]] = mapped_column(Float)

    entity = relationship("Entity", back_populates="forecasts")


class Feeder(Base):
    """Feeder topology and adapter configuration."""
    __tablename__ = "feeders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    discom_code: Mapped[str] = mapped_column(String(20), ForeignKey("entities.code"))
    substation_name: Mapped[Optional[str]] = mapped_column(String(100))
    voltage_kv: Mapped[Optional[float]] = mapped_column(Float, default=11.0)
    capacity_mw: Mapped[Optional[float]] = mapped_column(Float)
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lon: Mapped[Optional[float]] = mapped_column(Float)
    adjacency: Mapped[Optional[Any]] = mapped_column(JSON)
    is_scada_connected: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    adapter_type: Mapped[Optional[str]] = mapped_column(String(20), default="ESTIMATION")
    adapter_config: Mapped[Optional[Any]] = mapped_column(JSON)
    allocation_weight: Mapped[Optional[float]] = mapped_column(Float)
    last_demand_mw: Mapped[Optional[float]] = mapped_column(Float)
    last_demand_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_estimated: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    formula: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())

    discom = relationship("Entity", back_populates="feeders")


class Alert(Base):
    """Capacity threshold alerts and operational warnings."""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_code: Mapped[Optional[str]] = mapped_column(String(20), ForeignKey("entities.code"))
    feeder_code: Mapped[Optional[str]] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    trigger_mw: Mapped[Optional[float]] = mapped_column(Float)
    capacity_mw: Mapped[Optional[float]] = mapped_column(Float)
    utilization_pct: Mapped[Optional[float]] = mapped_column(Float)
    recommended_action: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    assigned_to: Mapped[Optional[str]] = mapped_column(String(100))
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(100))
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    forecast_peak_mw: Mapped[Optional[float]] = mapped_column(Float)
    confidence_pct: Mapped[Optional[float]] = mapped_column(Float)
    notification_dispatched: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)


class SourceHealthLog(Base):
    """Ingestion health tracking per upstream source."""
    __tablename__ = "source_health_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(50))
    fetch_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    success: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    records_ingested: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)


class GridIndiaPSP(Base):
    """Grid-India / POSOCO Daily Power Supply Position records."""
    __tablename__ = "grid_india_psp"
    __table_args__ = (
        UniqueConstraint("report_date", name="uq_grid_india_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date)
    delhi_peak_demand_met_mw: Mapped[Optional[float]] = mapped_column(Float)
    delhi_energy_met_mu: Mapped[Optional[float]] = mapped_column(Float)
    delhi_shortage_mw: Mapped[Optional[float]] = mapped_column(Float)
    grid_frequency_min_hz: Mapped[Optional[float]] = mapped_column(Float)
    grid_frequency_max_hz: Mapped[Optional[float]] = mapped_column(Float)
    grid_frequency_avg_hz: Mapped[Optional[float]] = mapped_column(Float)
    national_demand_met_peak_mw: Mapped[Optional[float]] = mapped_column(Float)
    source_filename: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())


class FeederUploadBatch(Base):
    """Audit log for feeder meter CSV/Excel file uploads."""
    __tablename__ = "feeder_upload_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    discom_code: Mapped[str] = mapped_column(String(20))
    rows_processed: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    status: Mapped[Optional[str]] = mapped_column(String(20), default="SUCCESS")
    error_summary: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(100))
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())


class ModelRegistryRecord(Base):
    """Model tracking and lineage registry."""
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_code: Mapped[str] = mapped_column(String(20))
    model_name: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str] = mapped_column(String(50))
    is_champion: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    horizon_hours: Mapped[Optional[int]] = mapped_column(Integer, default=24)
    metrics: Mapped[Optional[Any]] = mapped_column(JSON)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(300))
    trained_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    notes: Mapped[Optional[str]] = mapped_column(Text)


class AuditLog(Base):
    """User action audit trail for SLDC/Discom operators."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer)
    username: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[Optional[str]] = mapped_column(String(100))
    resource: Mapped[Optional[str]] = mapped_column(String(100))
    details: Mapped[Optional[Any]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())


class User(Base):
    """System users with RBAC."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(100), unique=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(100))
    hashed_password: Mapped[str] = mapped_column(String(200))
    role: Mapped[Optional[str]] = mapped_column(String(30), default="VIEWER")
    discom_scope: Mapped[Optional[str]] = mapped_column(String(20))
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
