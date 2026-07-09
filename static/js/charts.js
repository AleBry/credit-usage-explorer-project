/**
 * BNLChart — Chart.js wrapper with Export PNG and Fullscreen modal.
 * Requires: Chart.js 4.x, Bootstrap 5, chartjs-plugin-zoom (for zoom/pan charts).
 */
'use strict';

// Crosshair Plugin - registered globally so all charts benefit
if (typeof Chart !== 'undefined') {
  Chart.register({
    id: 'bnl-crosshair',
    afterDraw(chart) {
      if (chart._crosshairX == null) return;
      const { ctx, chartArea: { top, bottom } } = chart;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(chart._crosshairX, top);
      ctx.lineTo(chart._crosshairX, bottom);
      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(0,0,0,.18)';
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.restore();
    },
    afterEvent(chart, args) {
      const t = args.event.type;
      if (t === 'mousemove') { chart._crosshairX = args.event.x; args.changed = true; }
      else if (t === 'mouseleave' || t === 'mouseout') { chart._crosshairX = null; args.changed = true; }
    },
  });
}

// Vertical marker line at a given category label (e.g. the weekly->monthly cap
// switch week). Set chart.$marker = { week: 'YYYY-MM-DD', label: '...' }.
if (typeof Chart !== 'undefined') {
  Chart.register({
    id: 'bnl-week-marker',
    afterDraw(chart) {
      const m = chart.$marker;
      if (!m || !m.week) return;
      const labels = chart.data.labels || [];
      let idx = labels.indexOf(m.week);
      if (idx < 0) idx = labels.findIndex(w => String(w) >= m.week);
      if (idx < 0) return;
      const x = chart.scales.x.getPixelForValue(idx);
      const { ctx, chartArea: { top, bottom } } = chart;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = 'rgba(214,51,132,.9)';
      ctx.setLineDash([5, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(214,51,132,.95)';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(m.label || 'monthly caps', x + 4, top + 10);
      ctx.restore();
    },
  });
}

// Shared categorical palette for multi-series charts.
const BNL_PALETTE = [
  '#0d6efd', '#20c997', '#fd7e14', '#6f42c1', '#d63384',
  '#0dcaf0', '#198754', '#ffc107', '#dc3545', '#6c757d',
];

/**
 * Render the "credits by usage type per week" stacked bar chart.
 * @param {string} canvasId
 * @param {{weeks:string[], series:{name:string,data:number[]}[]}} data
 * @param {object} [opts]  { exportName, stacked }
 * @returns {BNLChart|null}
 */
function renderUsageTypeChart(canvasId, data, opts = {}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  if (!data || !data.weeks || !data.weeks.length || !data.series.length) {
    const host = canvas.parentElement;
    if (host) host.innerHTML = '<div class="text-muted small p-3 text-center">No usage-type data available.</div>';
    return null;
  }
  const stacked = opts.stacked !== false;
  const datasets = data.series.map((s, i) => ({
    label: s.name,
    data: s.data,
    backgroundColor: BNL_PALETTE[i % BNL_PALETTE.length],
    borderWidth: 0,
    borderRadius: 2,
  }));
  const chart = new BNLChart(canvasId, {
    type: 'bar',
    data: { labels: data.weeks, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'bottom', labels: { font: { size: 10 }, boxWidth: 12, padding: 8, usePointStyle: true } },
        tooltip: {
          callbacks: {
            title: items => 'Week of ' + items[0].label,
            label: ctx => `  ${ctx.dataset.label}: ${Math.round(ctx.raw || 0).toLocaleString()} credits`,
            footer: items => 'Total: ' + Math.round(items.reduce((s, i) => s + (i.raw || 0), 0)).toLocaleString(),
          },
        },
      },
      scales: {
        x: { stacked, grid: { display: false }, ticks: { font: { size: 9 }, maxRotation: 45, maxTicksLimit: 24 } },
        y: {
          stacked, beginAtZero: true, grid: { color: 'rgba(0,0,0,.05)' },
          ticks: { font: { size: 10 }, callback: v => v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v },
        },
      },
    },
  }, { exportName: opts.exportName || 'Credits by Usage Type per Week' });
  chart._stacked = stacked;
  if (opts.markerWeek) {
    chart.chart.$marker = { week: opts.markerWeek, label: opts.markerLabel || 'monthly caps' };
    chart.chart.update();
  }
  return chart;
}

/** Toggle a usage-type chart between stacked and grouped bars. */
function setUsageTypeStacked(chart, stacked) {
  if (!chart || !chart.chart) return;
  chart._stacked = stacked;
  chart.chart.options.scales.x.stacked = stacked;
  chart.chart.options.scales.y.stacked = stacked;
  chart.chart.update();
}

/** Toolbar handler: switch a named window chart's bar mode and toggle button state. */
function setUsageTypeMode(varName, stacked, btn) {
  setUsageTypeStacked(window[varName], stacked);
  if (btn && btn.parentElement) {
    Array.from(btn.parentElement.querySelectorAll('button'))
      .forEach(b => b.classList.toggle('active', b === btn));
  }
}

class BNLChart {
  /**
   * @param {string} canvasId
   * @param {object} config     Chart.js config
   * @param {object} [opts]     { exportName: string }
   */
  constructor(canvasId, config, opts = {}) {
    this.canvasId   = canvasId;
    this.exportName = opts.exportName || canvasId;
    const canvas    = document.getElementById(canvasId);
    if (!canvas) throw new Error(`BNLChart: no canvas #${canvasId}`);
    this.chart = new Chart(canvas, config);
  }

  zoom(f)   { this.chart.zoom(f); }
  pan(d)    { this.chart.pan(d); }
  resetZoom() { this.chart.resetZoom(); }
  destroy() { this.chart.destroy(); }
  update()  { this.chart.update(); }
  get data()    { return this.chart.data; }
  get options() { return this.chart.options; }

  /** Download chart as PNG. */
  exportPNG() {
    const a = document.createElement('a');
    a.download = this.exportName.replace(/\s+/g, '_') + '.png';
    a.href = this.chart.toBase64Image('image/png', 1);
    a.click();
  }

  /** Open a fullscreen copy in a Bootstrap modal. */
  openFullscreen() {
    const MODAL_ID = 'bnl-fs-modal';
    let modal = document.getElementById(MODAL_ID);
    if (!modal) {
      modal = document.createElement('div');
      modal.id = MODAL_ID;
      modal.className = 'modal fade';
      modal.tabIndex  = -1;
      modal.innerHTML = `
        <div class="modal-dialog modal-fullscreen">
          <div class="modal-content">
            <div class="modal-header py-2 px-3">
              <h6 class="modal-title mb-0 fw-semibold" id="${MODAL_ID}-title"></h6>
              <div class="ms-auto d-flex gap-2 me-2">
                <button class="btn btn-sm btn-outline-secondary" id="${MODAL_ID}-export">&#8681; Export PNG</button>
              </div>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body" style="padding:1.25rem; display:flex; flex-direction:column;">
              <div style="position:relative; flex:1; min-height:0;">
                <canvas id="${MODAL_ID}-canvas"></canvas>
              </div>
            </div>
          </div>
        </div>`;
      document.body.appendChild(modal);
    }

    document.getElementById(`${MODAL_ID}-title`).textContent = this.exportName;

    const bsModal = bootstrap.Modal.getOrCreateInstance(modal);
    let   fsChart = null;

    const onShown = () => {
      const src = this.chart;
      const datasets = src.data.datasets.map(ds => ({
        ...ds,
        data: Array.isArray(ds.data) ? [...ds.data] : ds.data,
      }));
      const cfg = {
        type: src.config.type,
        data: { labels: [...(src.data.labels || [])], datasets },
        options: JSON.parse(JSON.stringify(src.options || {})),
      };
      cfg.options.maintainAspectRatio = false;
      cfg.options.animation = false;
      // Disable zoom plugin in modal (pan state won't carry over cleanly)
      if (cfg.options.plugins) delete cfg.options.plugins.zoom;

      if (fsChart) { fsChart.destroy(); }
      fsChart = new Chart(document.getElementById(`${MODAL_ID}-canvas`), cfg);

      document.getElementById(`${MODAL_ID}-export`).onclick = () => {
        const a = document.createElement('a');
        a.download = this.exportName.replace(/\s+/g, '_') + '_fs.png';
        a.href = fsChart.toBase64Image('image/png', 1);
        a.click();
      };
    };

    const onHidden = () => {
      if (fsChart) { fsChart.destroy(); fsChart = null; }
    };

    // Remove old listeners then add fresh ones
    modal.removeEventListener('shown.bs.modal',  modal._bnlShown);
    modal.removeEventListener('hidden.bs.modal', modal._bnlHidden);
    modal._bnlShown  = onShown;
    modal._bnlHidden = onHidden;
    modal.addEventListener('shown.bs.modal',  onShown);
    modal.addEventListener('hidden.bs.modal', onHidden);

    bsModal.show();
  }
}
