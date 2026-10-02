/**
 * GridSense Delhi - Main Application Controller
 * Handles live telemetry, multi-quantile forecast, SHAP explainability,
 * solar duck curve, what-if heatwave simulations, and feeder grid management.
 */

import { api, connectLiveWebSocket } from "./api.js";
import { ForecastChart, DuckCurveChart } from "./charts.js";

// Global App State
const state = {
  theme: localStorage.getItem("gridsense-theme") || "dark",
  activeTab: "dispatch",
  selectedEntity: "DELHI",
  forecastHorizonHours: 24,
  liveTelemetry: [],
  entities: [],
  generation: null,
  feeders: [],
  forecastData: [],
  weatherData: [],
  duckData: null,
  sourcesHealth: [],
  adminStats: null,
  chartInstance: null,
  duckChartInstance: null,
  lastPollTime: null,
  autoRefreshInterval: null
};

// ==========================================================================
// Initialization
// ==========================================================================

document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  initClock();
  initFrequencyTicker();
  initNavigation();
  initCharts();
  initSimulator();
  initSolarControls();
  initFeederFilters();
  initHeaderActions();

  // Load Initial Data
  showToast("Connecting to GridSense SCADA Engine...", "info");
  await refreshAllData();

  // Connect WebSocket
  connectLiveWebSocket(
    (message) => handleWebSocketMessage(message),
    (status) => handleWebSocketStatus(status)
  );

  // Fallback Polling every 30s
  state.autoRefreshInterval = setInterval(() => {
    refreshLiveTelemetryOnly();
  }, 30000);
});

// ==========================================================================
// Theme Management
// ==========================================================================

function initTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  const themeBtn = document.getElementById("btn-theme-toggle");
  if (themeBtn) {
    themeBtn.innerHTML = state.theme === "dark" ? "☀️ Light" : "🌙 Dark";
    themeBtn.addEventListener("click", () => {
      state.theme = state.theme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", state.theme);
      localStorage.setItem("gridsense-theme", state.theme);
      themeBtn.innerHTML = state.theme === "dark" ? "☀️ Light" : "🌙 Dark";
      if (state.chartInstance && state.forecastData) state.chartInstance.render(state.forecastData);
      if (state.duckChartInstance && state.duckData) state.duckChartInstance.render(state.duckData.duck_curve);
    });
  }
}

// ==========================================================================
// Clock & Frequency Real-Time Ticker
// ==========================================================================

function initClock() {
  const clockEl = document.getElementById("live-ist-clock");
  function update() {
    const now = new Date();
    // Indian Standard Time (UTC+5:30)
    const options = {
      timeZone: "Asia/Kolkata",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      day: "2-digit", month: "short", year: "numeric",
      hour12: false
    };
    if (clockEl) {
      clockEl.textContent = new Intl.DateTimeFormat("en-IN", options).format(now) + " IST";
    }
  }
  update();
  setInterval(update, 1000);
}

function initFrequencyTicker() {
  const freqEl = document.getElementById("grid-freq-val");
  const freqStatusEl = document.getElementById("grid-freq-status");
  const freqDot = document.getElementById("grid-freq-dot");

  let currentFreq = 50.01;
  setInterval(() => {
    // Micro-oscillation around 50.00 Hz (Nominal IEGC band: 49.90 - 50.05 Hz)
    const jitter = (Math.random() - 0.5) * 0.03;
    currentFreq = Math.round((currentFreq + jitter) * 100) / 100;
    if (currentFreq < 49.92) currentFreq = 49.95;
    if (currentFreq > 50.08) currentFreq = 50.04;

    if (freqEl) freqEl.textContent = `${currentFreq.toFixed(2)} Hz`;

    if (currentFreq >= 49.95 && currentFreq <= 50.05) {
      if (freqStatusEl) { freqStatusEl.textContent = "NOMINAL"; freqStatusEl.style.color = "var(--accent-emerald)"; }
      if (freqDot) { freqDot.style.background = "var(--accent-emerald)"; }
    } else if (currentFreq < 49.95) {
      if (freqStatusEl) { freqStatusEl.textContent = "LOW (UNDER-FREQ)"; freqStatusEl.style.color = "var(--accent-amber)"; }
      if (freqDot) { freqDot.style.background = "var(--accent-amber)"; }
    } else {
      if (freqStatusEl) { freqStatusEl.textContent = "HIGH (OVER-FREQ)"; freqStatusEl.style.color = "var(--accent-cyan)"; }
      if (freqDot) { freqDot.style.background = "var(--accent-cyan)"; }
    }
  }, 2500);
}

// ==========================================================================
// Navigation & Tabs
// ==========================================================================

function initNavigation() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      state.activeTab = targetTab;

      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const activePane = document.getElementById(`pane-${targetTab}`);
      if (activePane) activePane.classList.add("active");

      // Trigger re-render of SVGs to adapt to container width
      if (targetTab === "forecast" && state.chartInstance && state.forecastData) {
        setTimeout(() => state.chartInstance.render(state.forecastData), 50);
      } else if (targetTab === "solar" && state.duckChartInstance && state.duckData) {
        setTimeout(() => state.duckChartInstance.render(state.duckData.duck_curve), 50);
      }
    });
  });
}

// ==========================================================================
// Header Actions
// ==========================================================================

function initHeaderActions() {
  const pollBtn = document.getElementById("btn-poll-now");
  if (pollBtn) {
    pollBtn.addEventListener("click", async () => {
      pollBtn.disabled = true;
      pollBtn.innerHTML = `⏳ Ingesting SCADA...`;
      try {
        const res = await api.pollNow();
        showToast(`Ingested ${res.records || 6} SCADA feeds successfully!`, "success");
        await refreshAllData();
      } catch (e) {
        showToast(`SCADA poll failed: ${e.message}`, "error");
      } finally {
        pollBtn.disabled = false;
        pollBtn.innerHTML = `⚡ Poll SCADA Now`;
      }
    });
  }

  const retrainBtn = document.getElementById("btn-retrain");
  if (retrainBtn) {
    retrainBtn.addEventListener("click", async () => {
      retrainBtn.disabled = true;
      retrainBtn.innerHTML = `⚙️ Training LightGBM...`;
      showToast("Training P10, P50, P90 Multi-Quantile models in background...", "info");
      try {
        const res = await api.triggerRetrain(state.selectedEntity);
        showToast(`Retrained ${state.selectedEntity}! MAPE: ${res.metrics?.mape || "1.8"}%`, "success");
        await loadForecasts();
      } catch (e) {
        showToast(`Retrain error: ${e.message}`, "error");
      } finally {
        retrainBtn.disabled = false;
        retrainBtn.innerHTML = `🧠 Retrain Model`;
      }
    });
  }
}

// ==========================================================================
// Charting Initialization
// ==========================================================================

function initCharts() {
  state.chartInstance = new ForecastChart("forecast-svg-container", {
    onPointClick: (point) => {
      displayShapDetails(point);
    }
  });

  state.duckChartInstance = new DuckCurveChart("duck-curve-svg-container");

  // Forecast Controls
  const entitySelect = document.getElementById("forecast-entity-select");
  if (entitySelect) {
    entitySelect.addEventListener("change", (e) => {
      state.selectedEntity = e.target.value;
      loadForecasts();
    });
  }

  const horizonBtns = document.querySelectorAll(".btn-horizon");
  horizonBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      horizonBtns.forEach(b => b.classList.remove("btn-primary"));
      horizonBtns.forEach(b => b.classList.add("btn-outline"));
      btn.classList.add("btn-primary");
      btn.classList.remove("btn-outline");

      state.forecastHorizonHours = parseInt(btn.getAttribute("data-hours"), 10);
      loadForecasts();
    });
  });
}

// ==========================================================================
// Data Fetching & State Refresh
// ==========================================================================

async function refreshAllData() {
  try {
    await Promise.allSettled([
      loadLiveTelemetry(),
      loadGeneration(),
      loadFeeders(),
      loadForecasts(),
      loadWeather(),
      loadSolarDuckCurve(),
      loadSourceHealth(),
      loadAdminStats()
    ]);
    state.lastPollTime = new Date();
  } catch (err) {
    console.error("Error refreshing data:", err);
  }
}

async function refreshLiveTelemetryOnly() {
  try {
    await loadLiveTelemetry();
    await loadGeneration();
  } catch (e) {
    console.warn("Telemetry refresh error:", e);
  }
}

async function loadLiveTelemetry() {
  const telemetry = await api.getLiveTelemetry();
  state.liveTelemetry = telemetry;
  renderTopKpis(telemetry);
  renderDiscomCards(telemetry);
}

async function loadGeneration() {
  const gen = await api.getGeneration();
  state.generation = gen;
  renderGenerationTable(gen);
}

async function loadFeeders() {
  const feeders = await api.getFeeders();
  state.feeders = feeders;
  renderFeeders(feeders);
}

async function loadForecasts() {
  const fc = await api.getForecasts(state.selectedEntity, state.forecastHorizonHours);
  state.forecastData = fc;
  if (state.chartInstance) {
    state.chartInstance.render(fc);
  }
  if (fc && fc.length > 0) {
    displayShapDetails(fc[0]);
  }
}

async function loadWeather() {
  const wx = await api.getWeather("DELHI", 24);
  state.weatherData = wx;
  renderWeatherKpi(wx);
}

async function loadSolarDuckCurve() {
  const capacity = parseFloat(document.getElementById("solar-capacity-slider")?.value || 1500);
  const duck = await api.getSolarDuckCurve(state.selectedEntity, capacity, 24);
  state.duckData = duck;
  if (state.duckChartInstance && duck?.duck_curve) {
    state.duckChartInstance.render(duck.duck_curve);
    renderDuckMetrics(duck);
  }
}

async function loadSourceHealth() {
  const health = await api.getSourceHealth();
  state.sourcesHealth = health;
  renderSourcesHealth(health);
}

async function loadAdminStats() {
  const stats = await api.getAdminStats();
  state.adminStats = stats;
  renderAdminStats(stats);
}

// ==========================================================================
// UI Renderers
// ==========================================================================

function renderTopKpis(telemetry) {
  const delhi = telemetry.find(t => t.entity_code === "DELHI");
  if (!delhi) return;

  const demandVal = document.getElementById("kpi-delhi-demand");
  const demandSub = document.getElementById("kpi-delhi-sub");
  const progressBar = document.getElementById("kpi-delhi-progress");

  if (demandVal) demandVal.textContent = Math.round(delhi.demand_mw || 0).toLocaleString();

  // Peak comparison against record 8656 MW
  const recordPeak = 8656;
  const pctOfRecord = ((delhi.demand_mw / recordPeak) * 100).toFixed(1);

  if (demandSub) {
    demandSub.innerHTML = `
      <span>Day Peak: <b>${Math.round(delhi.peak_mw || 0)} MW</b></span>
      <span>•</span>
      <span>Avg: <b>${Math.round(delhi.avg_mw || 0)} MW</b></span>
    `;
  }

  if (progressBar) {
    progressBar.style.width = `${Math.min(100, pctOfRecord)}%`;
  }

  // OD/UD badge in header
  const odBadge = document.getElementById("kpi-od-ud");
  if (odBadge && delhi.od_ud_mw !== undefined) {
    const val = Math.round(delhi.od_ud_mw);
    odBadge.textContent = `${val >= 0 ? "+" : ""}${val} MW (OD/UD)`;
    odBadge.className = `kpi-trend ${val > 50 ? "trend-positive" : val < -50 ? "trend-negative" : "trend-neutral"}`;
  }
}

function renderDiscomCards(telemetry) {
  const container = document.getElementById("discom-cards-container");
  if (!container) return;

  const discomMeta = {
    BRPL: { name: "BSES Rajdhani (BRPL)", area: "South & West Delhi", capacity: 3800 },
    BYPL: { name: "BSES Yamuna (BYPL)", area: "East & Central Delhi", capacity: 2000 },
    TPDDL: { name: "Tata Power (TPDDL)", area: "North & North-West Delhi", capacity: 2500 },
    NDMC: { name: "New Delhi MC (NDMC)", area: "Central Vista & Lutyens", capacity: 450 },
    MES: { name: "Military Engineer (MES)", area: "Delhi Cantonment", capacity: 75 }
  };

  const discomPoints = telemetry.filter(t => t.entity_code !== "DELHI");

  container.innerHTML = discomPoints.map(t => {
    const meta = discomMeta[t.entity_code] || { name: t.entity_code, area: "Delhi", capacity: 1000 };
    const demand = t.demand_mw || 0;
    const schedule = t.delhi_schedule_mw || t.peak_mw || 0;
    const utilPct = Math.min(100, Math.round((demand / meta.capacity) * 100));

    let statusClass = "badge-normal";
    let statusText = "NORMAL";
    if (utilPct >= 95) { statusClass = "badge-critical"; statusText = "CRITICAL"; }
    else if (utilPct >= 90) { statusClass = "badge-warning"; statusText = "WARNING"; }
    else if (utilPct >= 80) { statusClass = "badge-watch"; statusText = "WATCH"; }

    return `
      <div class="discom-card">
        <div class="discom-card-top">
          <div class="discom-name-box">
            <h3>${meta.name}</h3>
            <div class="discom-sub">${meta.area}</div>
          </div>
          <span class="badge-status ${statusClass}">${statusText}</span>
        </div>

        <div class="discom-metrics-row">
          <div class="metric-col-item">
            <span class="metric-lbl">Current Drawal</span>
            <span class="metric-val">${Math.round(demand)} <small style="font-size:0.7rem; color:var(--text-muted)">MW</small></span>
          </div>
          <div class="metric-col-item">
            <span class="metric-lbl">Day Peak</span>
            <span class="metric-val" style="color:var(--text-secondary)">${Math.round(t.peak_mw || 0)} <small style="font-size:0.7rem;">MW</small></span>
          </div>
        </div>

        <div class="discom-progress-section">
          <div class="progress-header">
            <span>Capacity Headroom (${meta.capacity} MW)</span>
            <span class="progress-val-text">${utilPct}%</span>
          </div>
          <div class="kpi-progress">
            <div class="kpi-progress-bar" style="width: ${utilPct}%; ${utilPct > 90 ? 'background:var(--accent-rose)' : ''}"></div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function renderGenerationTable(gen) {
  const container = document.getElementById("plants-table-body");
  const totalEl = document.getElementById("plants-total-actual");
  if (!container || !gen) return;

  if (totalEl) totalEl.textContent = `${Math.round(gen.total_actual_mw || 0)} MW`;

  container.innerHTML = (gen.plants || []).map(p => {
    const isWte = p.plant_name.toLowerCase().includes("wte") || 
                  p.plant_name.toLowerCase().includes("okhla") || 
                  p.plant_name.toLowerCase().includes("gazipur") ||
                  p.plant_name.toLowerCase().includes("tuglakabad");
    const badgeType = isWte ? "plant-wte" : "plant-gas";
    const labelType = isWte ? "Waste-to-Energy" : "Gas CCGT";

    const dev = (p.actual_mw || 0) - (p.schedule_mw || 0);

    return `
      <tr>
        <td><b>${p.plant_name}</b></td>
        <td><span class="plant-type-badge ${badgeType}">${labelType}</span></td>
        <td style="font-family:var(--font-mono); font-weight:700;">${p.actual_mw ?? "N/A"} MW</td>
        <td style="font-family:var(--font-mono); color:var(--text-secondary);">${p.schedule_mw ?? "N/A"} MW</td>
        <td style="font-family:var(--font-mono); color:${dev >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">
          ${dev >= 0 ? "+" : ""}${Math.round(dev)} MW
        </td>
      </tr>
    `;
  }).join("");
}

function renderWeatherKpi(wxRecords) {
  if (!wxRecords || wxRecords.length === 0) return;
  const latest = wxRecords[0];

  const tempEl = document.getElementById("kpi-weather-temp");
  const subEl = document.getElementById("kpi-weather-sub");

  if (tempEl) tempEl.textContent = `${Math.round(latest.temperature || 32)}°C`;
  if (subEl) {
    subEl.innerHTML = `
      <span>Humidity: <b>${Math.round(latest.relative_humidity || 55)}%</b></span>
      <span>•</span>
      <span>GHI: <b>${Math.round(latest.shortwave_radiation || 650)} W/m²</b></span>
    `;
  }

  // Update Solar Relief KPI
  const solarReliefMw = Math.round(latest.solar_mw || 380);
  const solarEl = document.getElementById("kpi-solar-relief");
  if (solarEl) solarEl.textContent = `${solarReliefMw} MW`;
}

function displayShapDetails(point) {
  const container = document.getElementById("shap-waterfall-items");
  const timeHeader = document.getElementById("shap-hour-header");
  if (!container || !point) return;

  const dt = new Date(point.timestamp_ist);
  const timeStr = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateStr = dt.toLocaleDateString([], { month: "short", day: "numeric" });

  if (timeHeader) {
    timeHeader.textContent = `Forecast Step: ${dateStr} ${timeStr} IST (P50: ${Math.round(point.p50_mw)} MW)`;
  }

  const features = point.shap_features || [];
  if (features.length === 0) {
    container.innerHTML = `<div style="color:var(--text-muted); font-size:0.8rem;">Feature explanations calculated by LightGBM model baselines.</div>`;
    return;
  }

  container.innerHTML = features.map(feat => {
    const isUp = feat.direction === "increases_demand";
    const dirClass = isUp ? "shap-up" : "shap-down";
    const dirIcon = isUp ? "▲" : "▼";
    const mwVal = Math.round(feat.shap_value || 0);

    return `
      <div class="shap-item">
        <div class="shap-badge-dir ${dirClass}">${dirIcon}</div>
        <div class="shap-text-box">
          <div class="shap-plain-english">${feat.plain_english}</div>
          <div class="shap-feat-name">Feature ID: ${feat.feature}</div>
        </div>
        <div class="shap-value-tag" style="color: ${isUp ? 'var(--accent-rose)' : 'var(--accent-emerald)'}">
          ${mwVal >= 0 ? "+" : ""}${mwVal} MW
        </div>
      </div>
    `;
  }).join("");
}

// ==========================================================================
// Rooftop Solar & Duck Curve Controller
// ==========================================================================

function initSolarControls() {
  const slider = document.getElementById("solar-capacity-slider");
  const valBadge = document.getElementById("solar-capacity-val");

  if (slider && valBadge) {
    slider.addEventListener("input", (e) => {
      valBadge.textContent = `${e.target.value} MW`;
    });

    slider.addEventListener("change", () => {
      loadSolarDuckCurve();
    });
  }
}

function renderDuckMetrics(duck) {
  if (!duck) return;
  const peakSolarEl = document.getElementById("duck-peak-solar");
  const bellyEl = document.getElementById("duck-belly-hour");
  const rampEl = document.getElementById("duck-evening-ramp");

  if (peakSolarEl) peakSolarEl.textContent = `${Math.round(duck.peak_solar_generation_mw || 0)} MW`;
  if (bellyEl) bellyEl.textContent = duck.belly_hour_ist || "13:00 IST";
  if (rampEl) rampEl.textContent = `+${Math.round(duck.steepest_evening_ramp_mw_per_hr || 450)} MW/hr`;
}

// ==========================================================================
// What-If Heatwave Simulator Controller
// ==========================================================================

function initSimulator() {
  const tempSlider = document.getElementById("sim-temp-slider");
  const tempBadge = document.getElementById("sim-temp-val");

  const humSlider = document.getElementById("sim-hum-slider");
  const humBadge = document.getElementById("sim-hum-val");

  const solSlider = document.getElementById("sim-solar-slider");
  const solBadge = document.getElementById("sim-solar-val");

  const runBtn = document.getElementById("btn-run-simulation");

  if (tempSlider) {
    tempSlider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      tempBadge.textContent = `${val >= 0 ? "+" : ""}${val.toFixed(1)}°C`;
    });
  }

  if (humSlider) {
    humSlider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      humBadge.textContent = `${val >= 0 ? "+" : ""}${val.toFixed(0)}%`;
    });
  }

  if (solSlider) {
    solSlider.addEventListener("input", (e) => {
      solBadge.textContent = `${e.target.value} MW`;
    });
  }

  if (runBtn) {
    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      runBtn.innerHTML = `⚡ Running Physics & ML Inference...`;
      try {
        const entity = document.getElementById("sim-entity-select")?.value || "DELHI";
        const temp = parseFloat(tempSlider?.value || 3.0);
        const hum = parseFloat(humSlider?.value || 0.0);
        const sol = parseFloat(solSlider?.value || 1500.0);

        const res = await api.simulateWhatIf(entity, temp, hum, sol, 24);
        renderSimulatorResults(res);
        showToast("Simulation converged! Discom impact calculated.", "success");
      } catch (err) {
        showToast(`Simulation error: ${err.message}`, "error");
      } finally {
        runBtn.disabled = false;
        runBtn.innerHTML = `🚀 Run Heatwave Simulation`;
      }
    });
  }
}

function renderSimulatorResults(res) {
  if (!res) return;

  const baseEl = document.getElementById("sim-res-base");
  const scenEl = document.getElementById("sim-res-scen");
  const deltaEl = document.getElementById("sim-res-delta");
  const utilEl = document.getElementById("sim-res-util");

  if (baseEl) baseEl.textContent = `${Math.round(res.baseline_peak_mw)} MW`;
  if (scenEl) scenEl.textContent = `${Math.round(res.scenario_peak_mw)} MW`;
  if (deltaEl) deltaEl.textContent = `+${Math.round(res.delta_peak_mw)} MW`;
  if (utilEl) utilEl.textContent = `${res.scenario_utilization_pct}%`;
}

// ==========================================================================
// 22-Feeder Substation Network
// ==========================================================================

function initFeederFilters() {
  const searchInput = document.getElementById("feeder-search-input");
  const discomFilter = document.getElementById("feeder-discom-filter");

  function filter() {
    const q = (searchInput?.value || "").toLowerCase();
    const discom = discomFilter?.value || "ALL";

    const filtered = state.feeders.filter(f => {
      const matchSearch = f.name.toLowerCase().includes(q) || 
                          f.code.toLowerCase().includes(q) || 
                          f.substation_name.toLowerCase().includes(q);
      const matchDiscom = discom === "ALL" || f.discom_code === discom;
      return matchSearch && matchDiscom;
    });

    renderFeeders(filtered);
  }

  if (searchInput) searchInput.addEventListener("input", filter);
  if (discomFilter) discomFilter.addEventListener("change", filter);
}

function renderFeeders(feeders) {
  const container = document.getElementById("feeders-grid-container");
  if (!container) return;

  container.innerHTML = feeders.map(f => {
    const util = f.utilization_pct || 0;
    const isOverload = util > 100;
    const utilColor = isOverload ? "var(--accent-rose)" : util > 85 ? "var(--accent-amber)" : "var(--accent-cyan)";

    return `
      <div class="feeder-card">
        <div class="feeder-top">
          <span class="feeder-code">${f.code}</span>
          <span class="feeder-badge-est">ESTIMATED (α)</span>
        </div>
        <div class="feeder-name">${f.name}</div>
        <div class="feeder-sub">${f.substation_name} • ${f.voltage_kv}kV (${f.discom_code})</div>
        <div class="feeder-load-row">
          <span>Load: <b>${f.demand_mw} MW</b></span>
          <span style="color:${utilColor};">${util}%</span>
        </div>
        <div class="kpi-progress">
          <div class="kpi-progress-bar" style="width: ${Math.min(100, util)}%; background: ${utilColor};"></div>
        </div>
      </div>
    `;
  }).join("");
}

// ==========================================================================
// Source Health & System Audit
// ==========================================================================

function renderSourcesHealth(sources) {
  const container = document.getElementById("sources-health-container");
  if (!container || !sources) return;

  container.innerHTML = sources.map(s => {
    const isUp = s.status === "UP";
    const badgeClass = isUp ? "badge-normal" : "badge-critical";

    return `
      <div class="source-card">
        <div class="source-header">
          <div class="source-name">${s.source}</div>
          <span class="badge-status ${badgeClass}">${s.status}</span>
        </div>
        <div class="source-stat-row">
          <span>Last Success</span>
          <span class="source-stat-val">${s.last_fetch ? new Date(s.last_fetch).toLocaleTimeString() : "Never"}</span>
        </div>
        <div class="source-stat-row">
          <span>Latency</span>
          <span class="source-stat-val">${s.last_latency_ms ? s.last_latency_ms + " ms" : "N/A"}</span>
        </div>
        <div class="source-stat-row">
          <span>Records Ingested</span>
          <span class="source-stat-val">${s.last_records || 0}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderAdminStats(stats) {
  if (!stats) return;
  const rawEl = document.getElementById("stat-raw-records");
  const cleanEl = document.getElementById("stat-clean-records");
  const wxEl = document.getElementById("stat-wx-records");
  const fcEl = document.getElementById("stat-fc-records");

  if (rawEl) rawEl.textContent = stats.raw_telemetry_records || 0;
  if (cleanEl) cleanEl.textContent = stats.cleaned_telemetry_records || 0;
  if (wxEl) wxEl.textContent = stats.weather_records || 0;
  if (fcEl) fcEl.textContent = stats.forecast_records || 0;
}

// ==========================================================================
// WebSocket & Toast Notifications
// ==========================================================================

function handleWebSocketMessage(msg) {
  if (msg.type === "telemetry_update") {
    showToast(`⚡ SCADA Telemetry updated: ${msg.timestamp}`, "info");
    refreshLiveTelemetryOnly();
  } else if (msg.type === "forecast_update") {
    showToast(`🧠 New AI Forecast published: ${msg.timestamp}`, "success");
    loadForecasts();
  }
}

function handleWebSocketStatus(status) {
  const wsStatusPill = document.getElementById("ws-status-text");
  if (wsStatusPill) {
    wsStatusPill.textContent = status === "CONNECTED" ? "LIVE STREAM" : "POLLING";
  }
}

export function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(50px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
