"""
GridSense Delhi - Feeder Topology & Estimation Engine
Implements Section 5 of data-sources.md:
Seeds 66kV / 33kV / 11kV substation feeders across Delhi discoms.
Computes allocated feeder demand from live parent discom demand:
  Feeder Demand_est = Discom Demand_actual * alpha_i
All allocated feeds are flagged is_estimated=True.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.models import Feeder, Entity, TelemetryCleaned
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# Benchmark Delhi substations and 11kV/33kV/66kV feeders
BENCHMARK_FEEDERS = [
    # --- BRPL (South & West Delhi) ---
    {"code": "BRPL-FDR-01", "name": "Alaknanda 66kV Bay 1", "discom_code": "BRPL", "substation_name": "Alaknanda 66/11kV Grid", "capacity_mw": 35.0, "lat": 28.5280, "lon": 77.2470, "weight": 0.016},
    {"code": "BRPL-FDR-02", "name": "Vasant Kunj C-Block 33kV", "discom_code": "BRPL", "substation_name": "Vasant Kunj 66/33kV Grid", "capacity_mw": 40.0, "lat": 28.5290, "lon": 77.1510, "weight": 0.018},
    {"code": "BRPL-FDR-03", "name": "Dwarka Sector-6 Main 66kV", "discom_code": "BRPL", "substation_name": "Dwarka Sector-6 66/11kV", "capacity_mw": 50.0, "lat": 28.5920, "lon": 77.0670, "weight": 0.024},
    {"code": "BRPL-FDR-04", "name": "Nehru Place Commercial 33kV", "discom_code": "BRPL", "substation_name": "Nehru Place 66/33kV", "capacity_mw": 45.0, "lat": 28.5490, "lon": 77.2520, "weight": 0.021},
    {"code": "BRPL-FDR-05", "name": "Saket District Centre 11kV", "discom_code": "BRPL", "substation_name": "Saket 66/11kV", "capacity_mw": 30.0, "lat": 28.5240, "lon": 77.2180, "weight": 0.014},
    {"code": "BRPL-FDR-06", "name": "Janakpuri B-Block 33kV", "discom_code": "BRPL", "substation_name": "Janakpuri 66/33kV Grid", "capacity_mw": 42.0, "lat": 28.6210, "lon": 77.0870, "weight": 0.019},

    # --- BYPL (East & Central Delhi) ---
    {"code": "BYPL-FDR-01", "name": "Mayur Vihar Phase-1 66kV", "discom_code": "BYPL", "substation_name": "Mayur Vihar 66/11kV Grid", "capacity_mw": 38.0, "lat": 28.6080, "lon": 77.2970, "weight": 0.040},
    {"code": "BYPL-FDR-02", "name": "Laxmi Nagar Commercial 33kV", "discom_code": "BYPL", "substation_name": "Laxmi Nagar 66/33kV", "capacity_mw": 45.0, "lat": 28.6310, "lon": 77.2770, "weight": 0.048},
    {"code": "BYPL-FDR-03", "name": "Shahdara Industrial Area 66kV", "discom_code": "BYPL", "substation_name": "Shahdara 66/11kV", "capacity_mw": 50.0, "lat": 28.6730, "lon": 77.2910, "weight": 0.052},
    {"code": "BYPL-FDR-04", "name": "Yamuna Vihar C-Block 33kV", "discom_code": "BYPL", "substation_name": "Yamuna Vihar 66/33kV", "capacity_mw": 32.0, "lat": 28.6940, "lon": 77.2720, "weight": 0.035},
    {"code": "BYPL-FDR-05", "name": "Daryaganj Heritage 11kV", "discom_code": "BYPL", "substation_name": "Daryaganj 33/11kV", "capacity_mw": 25.0, "lat": 28.6430, "lon": 77.2410, "weight": 0.028},

    # --- TPDDL (North & North-West Delhi) ---
    {"code": "TPDDL-FDR-01", "name": "Pitampura Commercial 66kV", "discom_code": "TPDDL", "substation_name": "Pitampura 66/11kV Grid", "capacity_mw": 45.0, "lat": 28.6990, "lon": 77.1350, "weight": 0.045},
    {"code": "TPDDL-FDR-02", "name": "Rohini Sector-3 66kV", "discom_code": "TPDDL", "substation_name": "Rohini Sector-3 66/11kV", "capacity_mw": 48.0, "lat": 28.7070, "lon": 77.1180, "weight": 0.050},
    {"code": "TPDDL-FDR-03", "name": "Model Town Residential 33kV", "discom_code": "TPDDL", "substation_name": "Model Town 66/33kV", "capacity_mw": 35.0, "lat": 28.7020, "lon": 77.1920, "weight": 0.038},
    {"code": "TPDDL-FDR-04", "name": "Narela Industrial Phase-1 66kV", "discom_code": "TPDDL", "substation_name": "Narela 66/11kV Grid", "capacity_mw": 60.0, "lat": 28.8470, "lon": 77.0980, "weight": 0.062},
    {"code": "TPDDL-FDR-05", "name": "Badli Industrial 33kV", "discom_code": "TPDDL", "substation_name": "Badli 66/33kV", "capacity_mw": 40.0, "lat": 28.7420, "lon": 77.1420, "weight": 0.042},

    # --- NDMC (Central Vista & Lutyens) ---
    {"code": "NDMC-FDR-01", "name": "Connaught Place Inner Circle 11kV", "discom_code": "NDMC", "substation_name": "CP 33/11kV Substation", "capacity_mw": 25.0, "lat": 28.6328, "lon": 77.2197, "weight": 0.095},
    {"code": "NDMC-FDR-02", "name": "Barakhamba Commercial 33kV", "discom_code": "NDMC", "substation_name": "Barakhamba 66/33kV", "capacity_mw": 35.0, "lat": 28.6290, "lon": 77.2280, "weight": 0.130},
    {"code": "NDMC-FDR-03", "name": "Chanakyapuri Diplomatic 11kV", "discom_code": "NDMC", "substation_name": "Chanakyapuri 33/11kV", "capacity_mw": 20.0, "lat": 28.5980, "lon": 77.1850, "weight": 0.080},
    {"code": "NDMC-FDR-04", "name": "Central Vista High-Security 33kV", "discom_code": "NDMC", "substation_name": "Udyog Bhawan 66/33kV", "capacity_mw": 30.0, "lat": 28.6110, "lon": 77.2120, "weight": 0.115},

    # --- MES (Delhi Cantonment) ---
    {"code": "MES-FDR-01", "name": "Delhi Cantt Base Hospital 11kV", "discom_code": "MES", "substation_name": "Cantt Main 33/11kV", "capacity_mw": 12.0, "lat": 28.5960, "lon": 77.1350, "weight": 0.420},
    {"code": "MES-FDR-02", "name": "Dhaula Kuan Military Station 11kV", "discom_code": "MES", "substation_name": "Dhaula Kuan 33/11kV", "capacity_mw": 10.0, "lat": 28.5930, "lon": 77.1560, "weight": 0.380},
]


def seed_feeders_if_empty():
    """Seed benchmark feeder network topology if table is empty."""
    db: Session = SessionLocal()
    try:
        cnt = db.query(Feeder).count()
        if cnt == 0:
            for bf in BENCHMARK_FEEDERS:
                f = Feeder(
                    code=bf["code"],
                    name=bf["name"],
                    discom_code=bf["discom_code"],
                    substation_name=bf["substation_name"],
                    capacity_mw=bf["capacity_mw"],
                    lat=bf["lat"],
                    lon=bf["lon"],
                    is_scada_connected=False,
                    adapter_type="REST",
                    adapter_config={"allocation_formula": "discom_actual * weight", "parent_discom": bf["discom_code"]},
                    allocation_weight=bf["weight"],
                    is_estimated=True,
                )
                db.add(f)
            db.commit()
            logger.info(f"[Feeders] Seeded {len(BENCHMARK_FEEDERS)} benchmark feeders across Delhi discoms")
    except Exception as e:
        db.rollback()
        logger.error(f"[Feeders] Error seeding feeders: {e}")
    finally:
        db.close()


def update_feeder_loads() -> List[Dict[str, Any]]:
    """
    Calculate live allocated feeder loads from latest parent discom demand.
    Returns list of updated feeder records.
    """
    db: Session = SessionLocal()
    now_ist = datetime.now(IST).replace(tzinfo=None)
    results = []
    try:
        # Get latest demand per discom from TelemetryCleaned
        feeders = db.query(Feeder).all()
        if not feeders:
            seed_feeders_if_empty()
            feeders = db.query(Feeder).all()

        discom_loads = {}
        for d_code in ["BRPL", "BYPL", "TPDDL", "NDMC", "MES"]:
            latest = (
                db.query(TelemetryCleaned)
                .filter(TelemetryCleaned.entity_code == d_code)
                .order_by(TelemetryCleaned.timestamp_ist.desc())
                .first()
            )
            discom_loads[d_code] = latest.demand_mw if latest else 500.0

        for f in feeders:
            p_load = discom_loads.get(f.discom_code, 500.0)
            est_mw = round(p_load * (f.allocation_weight or 0.05), 2)
            f.last_demand_mw = est_mw
            f.last_demand_at = now_ist
            f.is_estimated = True
            util_pct = round((est_mw / f.capacity_mw * 100), 1) if f.capacity_mw else 0.0
            results.append({
                "code": f.code,
                "name": f.name,
                "discom_code": f.discom_code,
                "substation_name": f.substation_name,
                "demand_mw": est_mw,
                "capacity_mw": f.capacity_mw,
                "utilization_pct": util_pct,
                "lat": f.lat,
                "lon": f.lon,
                "is_estimated": True,
                "formula": f"{f.discom_code} ({p_load:.0f} MW) × {f.allocation_weight}",
                "timestamp_ist": now_ist.isoformat(),
            })
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"[Feeders] Error updating feeder loads: {e}")
    finally:
        db.close()
    return results
