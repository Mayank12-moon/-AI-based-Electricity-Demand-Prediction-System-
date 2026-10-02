import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient
from app.main import app

def test_all():
    client = TestClient(app)
    
    print("Testing Endpoints:")
    
    # 1. Health
    res = client.get("/health")
    assert res.status_code == 200, res.text
    print("  [OK] /health ->", res.json())
    
    # 2. Ready
    res = client.get("/ready")
    assert res.status_code == 200, res.text
    print("  [OK] /ready ->", res.json())
    
    # 3. Entities
    res = client.get("/api/v1/entities")
    assert res.status_code == 200, res.text
    data = res.json()
    print(f"  [OK] /api/v1/entities -> {len(data)} entities found")
    
    # 4. Live Telemetry
    res = client.get("/api/v1/telemetry/live")
    assert res.status_code == 200, res.text
    live = res.json()
    print(f"  [OK] /api/v1/telemetry/live -> {len(live)} live entity readings:")
    for r in live:
        print(f"       {r['entity_code']}: Demand {r['demand_mw']} MW (Day Peak: {r['peak_mw']} MW, Avg: {r['avg_mw']} MW)")
        
    # 5. Historical Telemetry
    res = client.get("/api/v1/telemetry/historical?entity_code=DELHI&hours=24")
    assert res.status_code == 200, res.text
    hist = res.json()
    print(f"  [OK] /api/v1/telemetry/historical -> {len(hist)} points for DELHI in past 24h")
    
    # 6. Real-time Generation by Plant
    res = client.get("/api/v1/generation")
    assert res.status_code == 200, res.text
    gen = res.json()
    print(f"  [OK] /api/v1/generation -> Total {gen['total_actual_mw']} MW across {len(gen['plants'])} plants:")
    for p in gen['plants']:
        print(f"       - {p['plant_name']}: {p['actual_mw']} MW (Schedule: {p['schedule_mw']} MW)")
        
    # 7. Feeders
    res = client.get("/api/v1/feeders")
    assert res.status_code == 200, res.text
    feeders = res.json()
    print(f"  [OK] /api/v1/feeders -> {len(feeders)} feeders monitored across Delhi discoms")
    for f in feeders[:3]:
        print(f"       - {f['code']} ({f['name']}): {f['demand_mw']} MW / {f['capacity_mw']} MW ({f['utilization_pct']}%) [{f['formula']}]")
        
    # 8. Forecasts
    res = client.get("/api/v1/forecasts?entity_code=DELHI&hours=24")
    assert res.status_code == 200, res.text
    fc = res.json()
    print(f"  [OK] /api/v1/forecasts -> {len(fc)} forecast steps for DELHI:")
    if fc:
        first = fc[0]
        print(f"       Step 1 ({first['timestamp_ist']}): P10={first['p10_mw']} MW, P50={first['p50_mw']} MW, P90={first['p90_mw']} MW, Solar={first['solar_mw']} MW, Net P50={first['net_p50_mw']} MW")
        print(f"       Top SHAP Driver: {first['shap_features'][0]['plain_english'] if first['shap_features'] else 'None'}")
        
    # 9. Weather
    res = client.get("/api/v1/weather?zone_code=DELHI&hours=24")
    assert res.status_code == 200, res.text
    wx = res.json()
    print(f"  [OK] /api/v1/weather -> {len(wx)} weather records for DELHI")
    
    # 10. Solar Duck Curve
    res = client.post("/api/v1/solar", json={"entity_code": "DELHI", "installed_capacity_mw": 1500.0, "hours": 24})
    assert res.status_code == 200, res.text
    sol = res.json()
    print(f"  [OK] /api/v1/solar -> Duck curve generated with {len(sol['duck_curve'])} hourly points")
    
    # 11. What-If Simulator (+3°C heatwave)
    res = client.post("/api/v1/what-if", json={
        "entity_code": "DELHI",
        "temp_offset_c": 3.0,
        "humidity_offset_pct": 5.0,
        "solar_capacity_mw": 2000.0,
        "hours": 24
    })
    assert res.status_code == 200, res.text
    wi = res.json()
    print(f"  [OK] /api/v1/what-if (+3°C Heatwave Simulation):")
    print(f"       Baseline Peak: {wi['baseline_peak_mw']} MW")
    print(f"       Scenario Peak: {wi['scenario_peak_mw']} MW")
    print(f"       Delta Peak: +{wi['delta_peak_mw']} MW")
    print(f"       Scenario Utilization: {wi['scenario_utilization_pct']}% of licensed {wi['capacity_mw']} MW capacity")
    
    # 12. Source Health
    res = client.get("/api/v1/sources/health")
    assert res.status_code == 200, res.text
    sh = res.json()
    print(f"  [OK] /api/v1/sources/health -> {sh}")
    
    # 13. Admin stats
    res = client.get("/api/v1/admin/stats")
    assert res.status_code == 200, res.text
    stats = res.json()
    print(f"  [OK] /api/v1/admin/stats -> {stats}")

if __name__ == "__main__":
    test_all()
