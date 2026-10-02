import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_FILE = os.path.join(BASE_BACKEND_DIR, "gridsense.db").replace("\\", "/")
DEFAULT_DB_URL = f"sqlite:///{DEFAULT_DB_FILE}"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    PROJECT_NAME: str = "GridSense Delhi"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", DEFAULT_DB_URL)
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "gridsense-delhi-secret-super-secure-key-2026-sldc-discoms")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 hours
    ALGORITHM: str = "HS256"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "*"
    ]
    
    # Polling & Cadence
    SLDC_POLL_INTERVAL_SECONDS: int = 180 # 3 minutes
    WEATHER_POLL_INTERVAL_SECONDS: int = 1800 # 30 minutes
    FORECAST_INTERVAL_SECONDS: int = 3600 # 1 hour
    
    # Discom Configs
    DELHI_PEAK_CAPACITY_MW: float = 9000.0 # Record peak in Delhi was 8656 MW in June 2024
    BRPL_PEAK_CAPACITY_MW: float = 3800.0
    BYPL_PEAK_CAPACITY_MW: float = 2000.0
    TPDDL_PEAK_CAPACITY_MW: float = 2500.0
    NDMC_PEAK_CAPACITY_MW: float = 450.0
    MES_PEAK_CAPACITY_MW: float = 75.0
    
    # Solar defaults (Delhi Solar Policy 2024)
    DEFAULT_SOLAR_INSTALLED_CAPACITY_MW: float = 1500.0

settings = Settings()
