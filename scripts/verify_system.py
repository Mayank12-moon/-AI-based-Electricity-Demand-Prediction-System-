import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

def test_imports():
    print("--- 1. Testing Imports ---")
    modules = [
        "app.core.config",
        "app.core.database",
        "app.models.models",
        "app.workers.sldc_worker",
        "app.workers.weather_worker",
        "app.ml.features",
        "app.ml.forecaster",
        "app.main"
    ]
    for m in modules:
        try:
            __import__(m)
            print(f"  [OK] {m}")
        except Exception as e:
            print(f"  [FAIL] {m}: {e}")
            traceback.print_exc()

def test_database():
    print("\n--- 2. Testing Database ---")
    try:
        from app.core.database import SessionLocal, init_db
        from app.models.models import Entity, TelemetryRaw, TelemetryCleaned, WeatherTelemetry
        init_db()
        db = SessionLocal()
        entities = db.query(Entity).all()
        print(f"  [OK] DB initialized. Entities count: {len(entities)}")
        for e in entities:
            print(f"       - {e.code}: {e.name} (Peak Cap: {e.contract_peak_mw} MW)")
        raw_cnt = db.query(TelemetryRaw).count()
        clean_cnt = db.query(TelemetryCleaned).count()
        wx_cnt = db.query(WeatherTelemetry).count()
        print(f"  [OK] TelemetryRaw: {raw_cnt}, TelemetryCleaned: {clean_cnt}, WeatherTelemetry: {wx_cnt}")
        db.close()
    except Exception as e:
        print(f"  [FAIL] DB test: {e}")
        traceback.print_exc()

def test_sldc_worker():
    print("\n--- 3. Testing SLDC Worker ---")
    try:
        from app.workers.sldc_worker import fetch_and_store_live
        res = fetch_and_store_live()
        print(f"  Result: {res}")
    except Exception as e:
        print(f"  [FAIL] SLDC worker: {e}")
        traceback.print_exc()

def test_weather_worker():
    print("\n--- 4. Testing Weather Worker ---")
    try:
        # test just 1 zone forecast query
        from app.workers.weather_worker import DISCOM_ZONES, FORECAST_BASE, WEATHER_VARS, _fetch_json, _weather_data_to_records
        import urllib.parse
        lat, lon = DISCOM_ZONES["DELHI"]["lat"], DISCOM_ZONES["DELHI"]["lon"]
        params = urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "hourly": WEATHER_VARS,
            "timezone": "Asia/Kolkata",
            "forecast_days": 1,
        })
        url = f"{FORECAST_BASE}?{params}"
        data = _fetch_json(url)
        if data and "hourly" in data:
            recs = _weather_data_to_records("DELHI", data, is_forecast=True, aqi_by_time={}, source_url=url)
            print(f"  [OK] Open-Meteo test returned {len(recs)} hourly records for DELHI")
        else:
            print(f"  [FAIL] Open-Meteo returned: {data}")
    except Exception as e:
        print(f"  [FAIL] Weather worker: {e}")
        traceback.print_exc()

def test_feature_engineering():
    print("\n--- 5. Testing Feature Engineering ---")
    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime, timedelta
        from app.ml.features import build_feature_row
        
        now = datetime.now()
        dates = pd.date_range(now - timedelta(days=7), now, freq="15min")
        dummy_demand = pd.Series(np.random.normal(4500, 300, len(dates)), index=dates)
        
        row = build_feature_row(now, dummy_demand, None)
        print(f"  [OK] Built feature row with {len(row)} features:")
        for k in list(row.keys())[:10]:
            print(f"       - {k}: {row[k]}")
    except Exception as e:
        print(f"  [FAIL] Features: {e}")
        traceback.print_exc()

def test_forecaster():
    print("\n--- 6. Testing LGBM Forecaster ---")
    try:
        import pandas as pd
        import numpy as np
        from app.ml.forecaster import GridSenseLGBMForecaster, solar_net_demand
        
        # Test solar net demand formula
        sol = solar_net_demand(
            gross_demand_mw=5000.0,
            installed_capacity_mw=1500.0,
            ghi_wm2=750.0,
            cloud_cover_pct=20.0,
            temperature_c=35.0
        )
        print(f"  [OK] Solar net demand: {sol}")
        
        # Test synthetic train
        X = pd.DataFrame({
            "hour": np.random.randint(0, 24, 200),
            "dow": np.random.randint(0, 7, 200),
            "temp": np.random.uniform(20, 45, 200),
            "lag_1h": np.random.uniform(3000, 6000, 200)
        })
        y = pd.Series(X["lag_1h"] + X["temp"] * 30 + np.random.normal(0, 50, 200))
        
        fc = GridSenseLGBMForecaster("TEST_ENTITY")
        fc.train(X, y)
        preds = fc.predict(X.iloc[:5])
        print(f"  [OK] LGBM train & predict succeeded. Sample predictions:\n{preds}")
        
        # Test feature importance / shap
        shap_res = fc.shap_top_features(X.iloc[:1])
        print(f"  [OK] SHAP/Importance result: {shap_res}")
        
        # Clean up test model
        import os
        from app.ml.forecaster import MODEL_DIR
        test_path = os.path.join(MODEL_DIR, "TEST_ENTITY.pkl")
        if os.path.exists(test_path):
            os.remove(test_path)
    except Exception as e:
        print(f"  [FAIL] Forecaster: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    test_imports()
    test_database()
    test_sldc_worker()
    test_weather_worker()
    test_feature_engineering()
    test_forecaster()
