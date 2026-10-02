/**
 * GridSense Delhi - Interactive SVG Charting Engine
 * Pure Vanilla SVG & Canvas, high performance, zero external bloated dependencies
 */

export class ForecastChart {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    this.options = Object.assign({
      onPointClick: null,
      height: 380,
      margin: { top: 20, right: 30, bottom: 40, left: 60 }
    }, options);

    this.data = [];
    this.tooltip = null;
    this.init();
  }

  init() {
    if (!this.container) return;
    this.container.innerHTML = `
      <svg class="chart-svg" preserveAspectRatio="none" id="${this.container.id}-svg"></svg>
      <div class="chart-tooltip" id="${this.container.id}-tooltip"></div>
    `;
    this.svg = document.getElementById(`${this.container.id}-svg`);
    this.tooltip = document.getElementById(`${this.container.id}-tooltip`);

    window.addEventListener("resize", () => {
      if (this.data && this.data.length > 0) {
        this.render(this.data);
      }
    });
  }

  render(data) {
    if (!this.svg || !data || data.length === 0) return;
    this.data = data;

    const width = this.container.clientWidth || 800;
    const height = this.options.height;
    const { top, right, bottom, left } = this.options.margin;
    const innerWidth = width - left - right;
    const innerHeight = height - top - bottom;

    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    // Compute Y Domain (min P10 to max P90 with padding)
    let minVal = Infinity;
    let maxVal = -Infinity;

    data.forEach(d => {
      const p10 = d.p10_mw ?? d.p50_mw ?? 0;
      const p90 = d.p90_mw ?? d.p50_mw ?? 0;
      const net = d.net_p50_mw ?? p10;
      if (p10 < minVal) minVal = p10;
      if (net < minVal) minVal = net;
      if (p90 > maxVal) maxVal = p90;
    });

    if (minVal === Infinity) { minVal = 0; maxVal = 5000; }
    minVal = Math.floor(minVal * 0.9 / 500) * 500;
    maxVal = Math.ceil(maxVal * 1.08 / 500) * 500;
    if (minVal < 0) minVal = 0;

    const scaleX = (idx) => left + (idx / (data.length - 1 || 1)) * innerWidth;
    const scaleY = (val) => top + innerHeight - ((val - minVal) / (maxVal - minVal || 1)) * innerHeight;

    // Build Grid & Axis
    let svgContent = `<g class="chart-grid">`;
    const yTicksCount = 5;
    for (let i = 0; i <= yTicksCount; i++) {
      const val = minVal + (i / yTicksCount) * (maxVal - minVal);
      const y = scaleY(val);
      svgContent += `
        <line class="chart-grid-line" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" />
        <text class="chart-axis-text" x="${left - 8}" y="${y + 4}" text-anchor="end">${Math.round(val)} MW</text>
      `;
    }

    // X Axis Ticks (show ~6-8 evenly spaced ticks)
    const xStep = Math.max(1, Math.floor(data.length / 6));
    data.forEach((d, i) => {
      if (i % xStep === 0 || i === data.length - 1) {
        const x = scaleX(i);
        const dt = new Date(d.timestamp_ist);
        const timeLabel = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        svgContent += `
          <line class="chart-grid-line" x1="${x}" y1="${top}" x2="${x}" y2="${top + innerHeight}" />
          <text class="chart-axis-text" x="${x}" y="${height - 12}" text-anchor="middle">${timeLabel}</text>
        `;
      }
    });
    svgContent += `</g>`;

    // P10-P90 Area Polygon
    let areaPath = "";
    data.forEach((d, i) => {
      const x = scaleX(i);
      const y90 = scaleY(d.p90_mw || d.p50_mw);
      areaPath += `${i === 0 ? "M" : "L"} ${x} ${y90} `;
    });
    for (let i = data.length - 1; i >= 0; i--) {
      const d = data[i];
      const x = scaleX(i);
      const y10 = scaleY(d.p10_mw || d.p50_mw);
      areaPath += `L ${x} ${y10} `;
    }
    areaPath += "Z";
    svgContent += `<path class="chart-area-p90p10" d="${areaPath}" />`;

    // Net Demand Line (Dashed)
    let netPath = "";
    data.forEach((d, i) => {
      const x = scaleX(i);
      const y = scaleY(d.net_p50_mw || d.p50_mw);
      netPath += `${i === 0 ? "M" : "L"} ${x} ${y} `;
    });
    svgContent += `<path class="chart-line-net" d="${netPath}" />`;

    // P50 Line (Solid Cyan)
    let p50Path = "";
    data.forEach((d, i) => {
      const x = scaleX(i);
      const y = scaleY(d.p50_mw);
      p50Path += `${i === 0 ? "M" : "L"} ${x} ${y} `;
    });
    svgContent += `<path class="chart-line-p50" d="${p50Path}" />`;

    // Interactive Dots
    svgContent += `<g class="chart-interactive-dots">`;
    data.forEach((d, i) => {
      const x = scaleX(i);
      const y = scaleY(d.p50_mw);
      svgContent += `
        <circle class="chart-dot" cx="${x}" cy="${y}" data-index="${i}"></circle>
      `;
    });
    svgContent += `</g>`;

    this.svg.innerHTML = svgContent;

    // Attach Event Listeners to Dots
    this.svg.querySelectorAll(".chart-dot").forEach(circle => {
      circle.addEventListener("mouseenter", (e) => {
        const idx = parseInt(e.target.getAttribute("data-index"), 10);
        this.showTooltip(e, data[idx]);
      });
      circle.addEventListener("mouseleave", () => {
        this.hideTooltip();
      });
      circle.addEventListener("click", (e) => {
        const idx = parseInt(e.target.getAttribute("data-index"), 10);
        if (typeof this.options.onPointClick === "function") {
          this.options.onPointClick(data[idx], idx);
        }
      });
    });
  }

  showTooltip(event, point) {
    if (!this.tooltip || !point) return;
    const dt = new Date(point.timestamp_ist);
    const dateStr = dt.toLocaleDateString([], { month: "short", day: "numeric" });
    const timeStr = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    this.tooltip.innerHTML = `
      <div style="font-weight:700; color:var(--accent-cyan); margin-bottom:4px;">${dateStr} ${timeStr} IST</div>
      <div style="display:flex; justify-content:space-between; gap:12px;"><span>P50 Median:</span> <b>${Math.round(point.p50_mw)} MW</b></div>
      <div style="display:flex; justify-content:space-between; gap:12px; color:var(--text-secondary);"><span>P10 - P90:</span> <span>${Math.round(point.p10_mw)} - ${Math.round(point.p90_mw)} MW</span></div>
      ${point.solar_mw ? `<div style="display:flex; justify-content:space-between; gap:12px; color:var(--accent-amber);"><span>Solar Relief:</span> <b>-${Math.round(point.solar_mw)} MW</b></div>` : ''}
      ${point.net_p50_mw ? `<div style="display:flex; justify-content:space-between; gap:12px; color:var(--accent-emerald);"><span>Net Grid:</span> <b>${Math.round(point.net_p50_mw)} MW</b></div>` : ''}
      <div style="font-size:0.68rem; color:var(--text-muted); margin-top:4px;">Click to view SHAP Explainability</div>
    `;

    const rect = this.container.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    this.tooltip.style.left = `${x}px`;
    this.tooltip.style.top = `${y}px`;
    this.tooltip.style.display = "block";
  }

  hideTooltip() {
    if (this.tooltip) {
      this.tooltip.style.display = "none";
    }
  }
}


export class DuckCurveChart {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.init();
  }

  init() {
    if (!this.container) return;
    this.container.innerHTML = `<svg class="chart-svg" preserveAspectRatio="none" id="${this.container.id}-svg"></svg>`;
    this.svg = document.getElementById(`${this.container.id}-svg`);
  }

  render(duckPoints) {
    if (!this.svg || !duckPoints || duckPoints.length === 0) return;

    const width = this.container.clientWidth || 800;
    const height = 340;
    const margin = { top: 20, right: 30, bottom: 40, left: 60 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    let maxVal = Math.max(...duckPoints.map(p => p.gross_demand_mw || 0)) * 1.1;
    let minVal = Math.min(...duckPoints.map(p => p.net_demand_mw || 0)) * 0.9;
    if (minVal < 0) minVal = 0;

    const scaleX = (i) => margin.left + (i / (duckPoints.length - 1 || 1)) * innerWidth;
    const scaleY = (v) => margin.top + innerHeight - ((v - minVal) / (maxVal - minVal || 1)) * innerHeight;

    let svg = `<g class="chart-grid">`;
    // Y Ticks
    for (let i = 0; i <= 4; i++) {
      const val = minVal + (i / 4) * (maxVal - minVal);
      const y = scaleY(val);
      svg += `
        <line class="chart-grid-line" x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" />
        <text class="chart-axis-text" x="${margin.left - 8}" y="${y + 4}" text-anchor="end">${Math.round(val)} MW</text>
      `;
    }

    // X Ticks
    duckPoints.forEach((d, i) => {
      if (i % 3 === 0 || i === duckPoints.length - 1) {
        const x = scaleX(i);
        const dt = new Date(d.timestamp_ist);
        const timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        svg += `
          <line class="chart-grid-line" x1="${x}" y1="${margin.top}" x2="${x}" y2="${margin.top + innerHeight}" />
          <text class="chart-axis-text" x="${x}" y="${height - 12}" text-anchor="middle">${timeStr}</text>
        `;
      }
    });
    svg += `</g>`;

    // Gross Demand (Cyan line)
    let grossPath = "";
    duckPoints.forEach((p, i) => {
      const x = scaleX(i);
      const y = scaleY(p.gross_demand_mw);
      grossPath += `${i === 0 ? "M" : "L"} ${x} ${y} `;
    });
    svg += `<path d="${grossPath}" fill="none" stroke="#00e5ff" stroke-width="2.5" />`;

    // Net Demand (Amber line showing duck curve belly)
    let netPath = "";
    duckPoints.forEach((p, i) => {
      const x = scaleX(i);
      const y = scaleY(p.net_demand_mw);
      netPath += `${i === 0 ? "M" : "L"} ${x} ${y} `;
    });
    svg += `<path d="${netPath}" fill="none" stroke="#f59e0b" stroke-width="3" filter="drop-shadow(0 0 6px rgba(245, 158, 11, 0.4))" />`;

    // Solar Relief Area Fill between Gross & Net
    let reliefArea = "";
    duckPoints.forEach((p, i) => {
      const x = scaleX(i);
      const yGross = scaleY(p.gross_demand_mw);
      reliefArea += `${i === 0 ? "M" : "L"} ${x} ${yGross} `;
    });
    for (let i = duckPoints.length - 1; i >= 0; i--) {
      const p = duckPoints[i];
      const x = scaleX(i);
      const yNet = scaleY(p.net_demand_mw);
      reliefArea += `L ${x} ${yNet} `;
    }
    reliefArea += "Z";
    svg += `<path d="${reliefArea}" fill="rgba(245, 158, 11, 0.18)" />`;

    this.svg.innerHTML = svg;
  }
}
