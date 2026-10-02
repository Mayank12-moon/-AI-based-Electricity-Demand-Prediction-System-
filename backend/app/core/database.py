"""Database session setup and initialization."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.models import Base, Entity

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and seed initial entity data."""
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Seed entities if not present
        existing = db.query(Entity).count()
        if existing == 0:
            entities = [
                Entity(
                    code="DELHI",
                    name="Delhi (State Total)",
                    name_hindi="दिल्ली (राज्य)",
                    zone="state",
                    lat=28.6139, lon=77.2090,
                    contract_peak_mw=9000.0,
                    capacity_source="Delhi SLDC Record Peak 8656 MW (June 2024), operational headroom 9000 MW"
                ),
                Entity(
                    code="BRPL",
                    name="BSES Rajdhani Power Limited",
                    name_hindi="बीएसईएस राजधानी पावर लिमिटेड",
                    zone="discom",
                    lat=28.5355, lon=77.1600,
                    contract_peak_mw=3800.0,
                    capacity_source="BRPL Annual Report 2023-24 peak demand"
                ),
                Entity(
                    code="BYPL",
                    name="BSES Yamuna Power Limited",
                    name_hindi="बीएसईएस यमुना पावर लिमिटेड",
                    zone="discom",
                    lat=28.6280, lon=77.2789,
                    contract_peak_mw=2000.0,
                    capacity_source="BYPL Annual Report 2023-24 peak demand"
                ),
                Entity(
                    code="TPDDL",
                    name="Tata Power Delhi Distribution Ltd (NDPL)",
                    name_hindi="टाटा पावर दिल्ली डिस्ट्रीब्यूशन लि.",
                    zone="discom",
                    lat=28.7041, lon=77.1025,
                    contract_peak_mw=2500.0,
                    capacity_source="TPDDL Annual Report 2023-24 peak demand"
                ),
                Entity(
                    code="NDMC",
                    name="New Delhi Municipal Council",
                    name_hindi="नई दिल्ली नगर पालिका परिषद",
                    zone="discom",
                    lat=28.6353, lon=77.2249,
                    contract_peak_mw=450.0,
                    capacity_source="NDMC Annual Report 2023-24"
                ),
                Entity(
                    code="MES",
                    name="Military Engineer Services (Cantonment)",
                    name_hindi="सैन्य अभियंता सेवा",
                    zone="discom",
                    lat=28.5961, lon=77.1350,
                    contract_peak_mw=75.0,
                    capacity_source="Delhi SLDC historical peak for MES zone"
                ),
            ]
            db.add_all(entities)
            db.commit()
            print("[DB] Seeded 6 entities (Delhi + 5 discoms)")
    finally:
        db.close()
