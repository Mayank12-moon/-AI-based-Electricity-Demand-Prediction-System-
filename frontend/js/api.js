/**
 * GridSense Delhi - API Client & WebSocket Gateway
 */

// If running in dev on different port, default to backend port 8000
const API_BASE = window.location.port === "8000" || window.location.pathname.startsWith("/api") 
  ? "" 
  : "http://localhost:8000";

const WS_BASE = (window.location.protocol === "https:" ? "wss://" : "ws://") + 
  (window.location.port === "8000" ? window.location.host : "localhost:8000");

export async function fetchJson(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`API Error ${res.status}: ${errText}`);
    }
    return await res.json();
  } catch (err) {
    console.warn(`[GridSense API] Failed to fetch ${endpoint}:`, err);
    throw err;
  }
}

export const api = {
  // 1. Entities
  getEntities: () => fetchJson("/api/v1/entities"),
  
  // 2. Telemetry
  getLiveTelemetry: () => fetchJson("/api/v1/telemetry/live"),
  getHistoricalTelemetry: (entityCode = "DELHI", hours = 24) => 
    fetchJson(`/api/v1/telemetry/historical?entity_code=${entityCode}&hours=${hours}`),
  pollNow: () => fetchJson("/api/v1/telemetry/poll-now", { method: "POST" }),

  // 3. Generation
  getGeneration: () => fetchJson("/api/v1/generation"),

  // 4. Feeders
  getFeeders: () => fetchJson("/api/v1/feeders"),

  // 5. Forecasts
  getForecasts: (entityCode = "DELHI", hours = 24) => 
    fetchJson(`/api/v1/forecasts?entity_code=${entityCode}&hours=${hours}`),
  triggerRetrain: (entityCode = "DELHI") =>
    fetchJson("/api/v1/ml/train", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_code: entityCode })
    }),

  // 6. Weather
  getWeather: (zoneCode = "DELHI", hours = 24) => 
    fetchJson(`/api/v1/weather?zone_code=${zoneCode}&hours=${hours}`),

  // 7. Rooftop Solar
  getSolarDuckCurve: (entityCode = "DELHI", installedCapacityMw = 1500.0, hours = 24) =>
    fetchJson("/api/v1/solar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_code: entityCode,
        installed_capacity_mw: installedCapacityMw,
        hours: hours
      })
    }),

  // 8. What-If Simulator
  simulateWhatIf: (entityCode, tempOffset, humidityOffset, solarCapacity, hours = 24) =>
    fetchJson("/api/v1/what-if", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_code: entityCode,
        temp_offset_c: tempOffset,
        humidity_offset_pct: humidityOffset,
        solar_capacity_mw: solarCapacity,
        hours: hours
      })
    }),

  // 9. Source Health & Alerts
  getSourceHealth: () => fetchJson("/api/v1/sources/health"),
  getAlerts: () => fetchJson("/api/v1/alerts"),
  acknowledgeAlert: (alertId, user = "Dispatcher") =>
    fetchJson(`/api/v1/alerts/${alertId}/acknowledge`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledged_by: user })
    }),
  getAdminStats: () => fetchJson("/api/v1/admin/stats")
};

/**
 * Live WebSocket Connection with auto-reconnect
 */
export function connectLiveWebSocket(onMessageCallback, onStatusCallback) {
  let ws = null;
  let reconnectTimer = null;

  function connect() {
    try {
      ws = new WebSocket(`${WS_BASE}/ws/live`);

      ws.onopen = () => {
        if (typeof onStatusCallback === "function") onStatusCallback("CONNECTED");
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (typeof onMessageCallback === "function") onMessageCallback(payload);
        } catch (e) {
          console.warn("[WS] Error parsing message:", e);
        }
      };

      ws.onerror = () => {
        if (typeof onStatusCallback === "function") onStatusCallback("ERROR");
      };

      ws.onclose = () => {
        if (typeof onStatusCallback === "function") onStatusCallback("DISCONNECTED");
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 4000);
      };
    } catch (e) {
      if (typeof onStatusCallback === "function") onStatusCallback("FAILED");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 5000);
    }
  }

  connect();

  return {
    disconnect: () => {
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    }
  };
}
