/**
 * Forecast page logic. All server data arrives via the #forecast-data JSON
 * island; this file is plain cacheable JS with no template interpolation.
 *
 * Functions are intentionally declared at the top level (global) so the inline
 * onclick handlers in the markup resolve. Chart-building IIFEs guard on canvas
 * existence so they self-skip on the no-data page.
 */
'use strict';

const D = (function () {
  const el = document.getElementById('forecast-data');
  try { return el ? JSON.parse(el.textContent) : {}; } catch (_) { return {}; }
})();
D.urls = D.urls || {};

/* ===================================================================== *
 * Snapshot comparison + overlays
 * ===================================================================== */
const selectedSnaps  = new Map();
const seriesCache    = new Map();
const SNAP_COLORS    = ['#20c997','#6f42c1','#d63384','#ffc107','#0dcaf0','#198754'];
const CURRENT_REMAINING = D.currentRemaining || 0;
let compareChart     = null;

function fmtN(v) { const n = parseFloat(v); return isNaN(n) ? '—' : Math.round(n).toLocaleString(); }
function fmtPct(v) { const n = parseFloat(v); return isNaN(n) ? '—' : Math.round(n * 100) + '%'; }
function truncLabel(s, max) { max = max || 12; return s && s.length > max ? s.slice(0, max) + '…' : (s || ''); }

function snapRemainingAt(h, dateStr) {
  const snap   = new Date(h.snapshot_date);
  const target = new Date(dateStr);
  const weeks  = (target - snap) / (7 * 24 * 3600 * 1000);
  if (weeks < 0) return null;
  return Math.max(parseFloat(h.credits_remaining || 0) - parseFloat(h.forecast_weekly_burn || 0) * weeks, 0);
}

async function fetchSnapSeries(snap) {
  const ts = snap.snapshot_ts;
  if (!ts || seriesCache.has(ts)) { updateBurndownOverlays(); return; }
  try {
    const resp = await fetch(D.urls.snapshotSeries + '?ts=' + encodeURIComponent(ts));
    if (!resp.ok) return;
    seriesCache.set(ts, await resp.json());
    updateBurndownOverlays();
    renderComparePanel();
  } catch (_) {}
}

function interpSeriesData(pts, allLabels, dateKey, valKey) {
  if (!pts || !pts.length) return allLabels.map(() => null);
  const start = pts[0][dateKey], end = pts[pts.length - 1][dateKey];
  return allLabels.map(l => {
    if (l < start || l > end) return null;
    const idx = pts.findIndex(p => p[dateKey] > l);
    if (idx === -1) return pts[pts.length - 1][valKey];
    if (idx === 0)  return pts[0][valKey];
    const a = pts[idx - 1], b = pts[idx];
    const t = (new Date(l) - new Date(a[dateKey])) / (new Date(b[dateKey]) - new Date(a[dateKey]));
    return a[valKey] + t * (b[valKey] - a[valKey]);
  });
}

function updateBurndownOverlays() {
  const bc = window.burndownChart;
  if (!bc) return;
  bc.data.datasets = bc.data.datasets.filter(d => !d._snapOverlay);
  const snaps = [...selectedSnaps.values()];
  let maxRemaining = window.burndownMaxY || 0;
  const allLabels  = window.burndownLabels || [];

  snaps.forEach((h, i) => {
    maxRemaining = Math.max(maxRemaining, parseFloat(h.credits_remaining || 0));
    const color     = h.color || SNAP_COLORS[i % SNAP_COLORS.length];
    const snapLabel = h.label ? truncLabel(h.label) : h.snapshot_date;
    const series    = seriesCache.get(h.snapshot_ts);
    const fb        = series && series.forecast_burndown && series.forecast_burndown.length
      ? series.forecast_burndown : null;

    if (fb) {
      const forecastData = interpSeriesData(fb, allLabels, 'date', 'remaining');
      const startIdx = forecastData.findIndex(v => v !== null);
      bc.data.datasets.push({
        label: snapLabel + ' · forecast',
        data: forecastData,
        borderColor: color, borderDash: [5, 4], borderWidth: 2,
        backgroundColor: 'transparent', fill: false, tension: 0.05,
        pointRadius: forecastData.map((v, j) => j === startIdx ? 7 : 0),
        pointBackgroundColor: color,
        spanGaps: false, _snapOverlay: true,
      });

      const mc = series && series.mc;
      if (window.showSnapMc && mc && mc.p50 && mc.p50.length) {
        const p10d = interpSeriesData(mc.p10 || [], allLabels, 'date', 'value');
        const p50d = interpSeriesData(mc.p50,       allLabels, 'date', 'value');
        const p90d = interpSeriesData(mc.p90 || [], allLabels, 'date', 'value');
        const alpha = hexToRgba(color, 0.12);
        bc.data.datasets.push({
          label: snapLabel + ' · MC P90', data: p90d,
          borderColor: hexToRgba(color, 0.45), borderWidth: 1, borderDash: [2, 3],
          backgroundColor: alpha, fill: '+2', tension: 0.1, pointRadius: 0, spanGaps: false, _snapOverlay: true,
        });
        bc.data.datasets.push({
          label: snapLabel + ' · MC P50', data: p50d,
          borderColor: hexToRgba(color, 0.7), borderWidth: 1.5, borderDash: [4, 3],
          backgroundColor: 'transparent', fill: false, tension: 0.1, pointRadius: 0, spanGaps: false, _snapOverlay: true,
        });
        bc.data.datasets.push({
          label: snapLabel + ' · MC P10', data: p10d,
          borderColor: hexToRgba(color, 0.45), borderWidth: 1, borderDash: [2, 3],
          backgroundColor: 'transparent', fill: false, tension: 0.1, pointRadius: 0, spanGaps: false, _snapOverlay: true,
        });
      }
    } else {
      const data     = allLabels.map(l => snapRemainingAt(h, l));
      const firstIdx = data.findIndex(v => v !== null);
      bc.data.datasets.push({
        label: snapLabel + ' · forecast', data,
        borderColor: color, borderDash: [4, 3], borderWidth: 2,
        backgroundColor: 'transparent', fill: false, tension: 0.05,
        pointRadius:          data.map((v, j) => j === firstIdx ? 7 : 0),
        pointBackgroundColor: data.map((v, j) => j === firstIdx ? color : 'transparent'),
        spanGaps: false, _snapOverlay: true,
      });
    }
  });

  bc.update();
}

function forecastAccuracyHtml(h) {
  const series = seriesCache.get(h.snapshot_ts);
  if (!series || !series.forecast_burndown || !series.forecast_burndown.length) return '';
  const todayStr = new Date().toISOString().slice(0, 10);
  if (h.snapshot_date >= todayStr) return '';

  const fb  = series.forecast_burndown;
  let predictedNow;
  const idx = fb.findIndex(p => p.date >= todayStr);
  if (idx === -1) {
    predictedNow = fb[fb.length - 1].remaining;
  } else if (idx === 0) {
    predictedNow = fb[0].remaining;
  } else {
    const a = fb[idx - 1], b = fb[idx];
    const t = (new Date(todayStr) - new Date(a.date)) / (new Date(b.date) - new Date(a.date));
    predictedNow = a.remaining + t * (b.remaining - a.remaining);
  }

  const error    = predictedNow - CURRENT_REMAINING;
  const errorPct = CURRENT_REMAINING > 0 ? error / CURRENT_REMAINING * 100 : 0;
  const sign     = error >= 0 ? '+' : '';
  const cls      = Math.abs(errorPct) < 5 ? 'text-success' : Math.abs(errorPct) < 15 ? 'text-warning' : 'text-danger';
  const note     = error > 0 ? 'forecast overestimated remaining' : 'forecast underestimated remaining';

  return `<div style="margin-top:.5rem;padding-top:.5rem;border-top:1px solid #eee;">
    <div style="font-size:.65rem;font-weight:700;color:#8a92a0;letter-spacing:.06em;margin-bottom:.25rem;">FORECAST ACCURACY TODAY</div>
    <div class="d-flex justify-content-between"><span class="text-muted">Predicted now</span><strong>${fmtN(predictedNow)}</strong></div>
    <div class="d-flex justify-content-between mt-1"><span class="text-muted">Actual now</span><strong>${fmtN(CURRENT_REMAINING)}</strong></div>
    <div class="d-flex justify-content-between mt-1"><span class="text-muted">Error</span><strong class="${cls}">${sign}${fmtN(error)} (${sign}${Math.round(errorPct)}%)</strong></div>
    <div style="font-size:.65rem;color:#8a92a0;margin-top:.2rem;">${note}</div>
  </div>`;
}

// Comparison bar chart is off by default (the cards already show the data);
// the "Chart" checkbox in the compare panel turns it on.
let showCompareChart = false;
function toggleCompareChart(on) {
  showCompareChart = !!on;
  updateCompareChart([...selectedSnaps.values()]);
}

function updateCompareChart(snaps) {
  const wrap = document.getElementById('compare-chart-wrap');
  if (!showCompareChart || snaps.length < 2) {
    if (wrap) wrap.style.display = 'none';
    if (compareChart) { compareChart.destroy(); compareChart = null; }
    return;
  }
  wrap.style.display = '';
  const labels   = snaps.map(h => h.label ? truncLabel(h.label) : h.snapshot_date);
  const burnData = snaps.map(h => parseFloat(h.forecast_weekly_burn || 0));
  const remData  = snaps.map(h => parseFloat(h.credits_remaining || 0));
  const balData  = snaps.map(h => parseFloat(h.forecast_contract_end_balance || 0));
  const datasets = [
    { label: 'Weekly Burn',       data: burnData, backgroundColor: 'rgba(13,110,253,0.7)' },
    { label: 'Credits Remaining', data: remData,  backgroundColor: 'rgba(108,117,125,0.5)' },
    { label: 'End Balance',       data: balData,  backgroundColor: balData.map(v => v < 0 ? 'rgba(220,53,69,0.7)' : 'rgba(25,135,84,0.7)') },
  ];
  if (compareChart) { compareChart.destroy(); compareChart = null; }
  compareChart = new Chart(document.getElementById('compare-chart'), {
    type: 'bar', data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top', labels: { font: { size: 11 }, boxWidth: 12 } },
        tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${Math.round(ctx.raw ?? 0).toLocaleString()}` } },
      },
      scales: {
        y: { ticks: { callback: v => v.toLocaleString(), font: { size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
        x: { ticks: { font: { size: 10 } }, grid: { display: false } },
      },
    },
  });
}

function renderComparePanel() {
  const panel = document.getElementById('compare-panel');
  const grid  = document.getElementById('compare-grid');
  const count = document.getElementById('compare-count');
  const snaps = [...selectedSnaps.values()];
  const n     = snaps.length;
  if (panel) panel.style.display = n >= 2 ? '' : 'none';
  updateBurndownOverlays();
  syncQuickSelect();
  if (n < 2) { updateCompareChart([]); return; }
  count.textContent = n;
  grid.innerHTML = snaps.map((h, i) => {
    const color = h.color || SNAP_COLORS[i % SNAP_COLORS.length];
    return `<div class="col-sm-6 col-lg-3">
      <div style="background:#fff;border:2px solid ${color};border-radius:8px;padding:.75rem .9rem;font-size:.78rem;">
        <div style="font-weight:700;color:#1a1d23;margin-bottom:.1rem;">${h.snapshot_date}</div>
        ${h.label ? `<div style="font-size:.72rem;color:#6c757d;margin-bottom:.35rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${h.label}">${h.label}</div>` : '<div style="margin-bottom:.35rem;"></div>'}
        <div class="d-flex justify-content-between"><span class="text-muted">Pacing</span><span class="pacing-pill ${h.pacing_status}" style="font-size:.68rem;padding:.1rem .4rem;">${(h.pacing_status||'').replace(/_/g,' ')}</span></div>
        <div class="d-flex justify-content-between mt-1"><span class="text-muted">Forecast</span><span class="pacing-pill ${h.forecast_status}" style="font-size:.68rem;padding:.1rem .4rem;">${(h.forecast_status||'').replace(/_/g,' ')}</span></div>
        <div class="d-flex justify-content-between mt-1"><span class="text-muted">Weekly burn</span><strong>${fmtN(h.forecast_weekly_burn)}</strong></div>
        <div class="d-flex justify-content-between mt-1"><span class="text-muted">Remaining</span><strong>${fmtN(h.credits_remaining)}</strong></div>
        <div class="d-flex justify-content-between mt-1"><span class="text-muted">End balance</span><strong class="${parseFloat(h.forecast_contract_end_balance||0)<0?'text-danger':'text-success'}">${fmtN(h.forecast_contract_end_balance)}</strong></div>
        <div class="d-flex justify-content-between mt-1"><span class="text-muted">Exhaustion</span><strong>${h.forecast_exhaustion_date||'—'}</strong></div>
        ${h.mc_exhaustion_prob ? `<div class="d-flex justify-content-between mt-1"><span class="text-muted">MC Risk</span><strong class="${parseFloat(h.mc_exhaustion_prob)>0.5?'text-danger':parseFloat(h.mc_exhaustion_prob)>0.1?'text-warning':'text-success'}">${fmtPct(h.mc_exhaustion_prob)}</strong></div>` : ''}
        ${forecastAccuracyHtml(h)}
      </div></div>`;
  }).join('');
  updateCompareChart(snaps);
}

function snapKey(snap) { return snap.snapshot_ts || (snap.snapshot_date + '|' + (snap.label || '')); }

function setSnapColor(input) {
  const color = input.value;
  const row = input.closest('tr');
  if (row) {
    try {
      const snap = JSON.parse(row.dataset.snap || '{}');
      snap.color = color;
      row.dataset.snap = JSON.stringify(snap);
      const key = snapKey(snap);
      if (selectedSnaps.has(key)) {
        selectedSnaps.set(key, snap);
        renderComparePanel();
      }
    } catch (_) {}
  }
  fetch(D.urls.color, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      snapshot_ts: input.dataset.ts,
      snapshot_date: input.dataset.date,
      label: input.dataset.label,
      color,
    }),
  });
}

function toggleRow(tr) {
  const snap = JSON.parse(tr.dataset.snap);
  const cb   = tr.querySelector('.history-cb');
  const key  = snapKey(snap);
  if (selectedSnaps.has(key)) {
    selectedSnaps.delete(key);
    tr.style.background = '';
    if (cb) cb.checked = false;
  } else {
    const wasEmpty = selectedSnaps.size === 0;
    selectedSnaps.set(key, snap);
    tr.style.background = SNAP_COLORS[(selectedSnaps.size - 1) % SNAP_COLORS.length] + '22';
    if (cb) cb.checked = true;
    fetchSnapSeries(snap);
    if (wasEmpty) {
      const target = document.getElementById('burndown-chart-section');
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
  renderComparePanel();
}

function clearComparison() {
  selectedSnaps.clear();
  document.querySelectorAll('.history-row').forEach(r => {
    r.style.background = '';
    const cb = r.querySelector('.history-cb');
    if (cb) cb.checked = false;
  });
  renderComparePanel();
}

function selectAllSnaps() {
  document.querySelectorAll('.history-row').forEach(tr => {
    const snap = (() => { try { return JSON.parse(tr.dataset.snap); } catch(_){return null;} })();
    if (!snap) return;
    const key = snapKey(snap);
    if (!selectedSnaps.has(key)) toggleRow(tr);
  });
}

// ---- Quick-select dropdown (below the chart) ----
function findRowByKey(key) {
  return [...document.querySelectorAll('.history-row')].find(tr => {
    try { return snapKey(JSON.parse(tr.dataset.snap)) === key; } catch (_) { return false; }
  });
}

function quickToggle(cb) {
  const row = findRowByKey(cb.dataset.key);
  if (row) toggleRow(row);
}

function quickSelectAll() { selectAllSnaps(); }
function quickSelectNone() { clearComparison(); }

window.showSnapMc = false;
function toggleSnapMc(on) {
  window.showSnapMc = !!on;
  [...selectedSnaps.values()].forEach(h => fetchSnapSeries(h));
  updateBurndownOverlays();
}

function syncQuickSelect() {
  document.querySelectorAll('.quick-snap-cb').forEach(cb => {
    cb.checked = selectedSnaps.has(cb.dataset.key);
  });
  const n = selectedSnaps.size;
  const lbl = document.getElementById('quick-select-label');
  if (lbl) lbl.textContent = n === 0 ? 'Select snapshots…' : (n + ' selected');
  const pills = document.getElementById('quick-select-pills');
  if (pills) {
    pills.innerHTML = [...selectedSnaps.values()].map((h, i) => {
      const color = h.color || SNAP_COLORS[i % SNAP_COLORS.length];
      const text = h.label ? truncLabel(h.label, 18) : h.snapshot_date;
      return `<span class="badge d-inline-flex align-items-center" style="background:${color};font-size:.66rem;font-weight:600;gap:.25rem;">${text}`
        + `<span style="cursor:pointer;" title="Remove" onclick="removeQuickSnap('${h.snapshot_ts || (h.snapshot_date + '|' + (h.label||''))}')">&times;</span></span>`;
    }).join('');
  }
}

function removeQuickSnap(key) {
  const row = findRowByKey(key);
  if (row && selectedSnaps.has(key)) toggleRow(row);
}

function viewSnapForecast(tr, e) {
  e.stopPropagation();
  try {
    const snap = JSON.parse(tr.dataset.snap || '{}');
    const p = new URLSearchParams(window.location.search);
    if (snap.contract_start_date) p.set('contract_start_date', String(snap.contract_start_date).slice(0, 10));
    if (snap.contract_end_date)   p.set('contract_end_date',   String(snap.contract_end_date).slice(0, 10));
    if (snap.purchased_credits)   p.set('purchased_credits',   snap.purchased_credits);
    window.location.href = D.urls.forecastPage + '?' + p.toString();
  } catch (_) {}
}

function deleteSnapshot(btn, e) {
  e.stopPropagation();
  if (!confirm('Delete this snapshot?')) return;
  fetch(D.urls.delete, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ snapshot_ts: btn.dataset.ts, snapshot_date: btn.dataset.date, label: btn.dataset.label }),
  }).then(r => {
    if (r.status === 204) {
      const row = btn.closest('tr');
      const key = btn.dataset.ts || (btn.dataset.date + '|' + btn.dataset.label);
      selectedSnaps.delete(key);
      seriesCache.delete(btn.dataset.ts);
      row.remove();
      renderComparePanel();
    } else { r.text().then(msg => alert('Delete failed: ' + (msg || r.status))); }
  }).catch(() => alert('Delete request failed.'));
}

// Restore snapshot selections active before an exclude-partial page reload
(function () {
  const saved = sessionStorage.getItem('forecast-snap-keys');
  if (!saved) return;
  sessionStorage.removeItem('forecast-snap-keys');
  let keys;
  try { keys = JSON.parse(saved); } catch (_) { return; }
  if (!keys.length) return;
  document.querySelectorAll('.history-row').forEach(tr => {
    try {
      const snap = JSON.parse(tr.dataset.snap);
      if (keys.includes(snapKey(snap))) toggleRow(tr);
    } catch (_) {}
  });
})();

/* ===================================================================== *
 * Chart color helpers
 * ===================================================================== */
const CHART_COLOR_DEFAULTS = { actual: '#0d6efd', proj: '#dc3545', weekly: '#0d6efd' };
function getChartColor(key) {
  return localStorage.getItem('fc-color-' + key) || CHART_COLOR_DEFAULTS[key];
}
function setChartColor(key, val) { localStorage.setItem('fc-color-' + key, val); }
function resetChartColors() {
  Object.keys(CHART_COLOR_DEFAULTS).forEach(k => localStorage.removeItem('fc-color-' + k));
  Object.keys(CHART_COLOR_DEFAULTS).forEach(k => {
    const el = document.getElementById('color-' + k);
    if (el) el.value = CHART_COLOR_DEFAULTS[k];
  });
  applyAllChartColors();
}
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}
function applyAllChartColors() {
  const bc = window.burndownChart;
  if (bc) {
    bc.data.datasets.forEach(ds => {
      if (!ds._mcOverlay && !ds._snapOverlay) {
        if (ds.label === 'Actual remaining') {
          ds.borderColor = getChartColor('actual');
          ds.backgroundColor = hexToRgba(getChartColor('actual'), 0.07);
        } else if (ds.label === 'Projected remaining') {
          ds.borderColor = getChartColor('proj');
        }
      }
    });
    bc.update('none');
  }
  const wc = window.weeklyChart;
  if (wc) {
    const wCol = getChartColor('weekly');
    wc.data.datasets[0].backgroundColor = wc.data.datasets[0].backgroundColor.map((c, i) =>
      window._weeklyInContract && window._weeklyInContract[i] ? hexToRgba(wCol, 0.72) : c
    );
    wc.data.datasets[0].borderColor = wc.data.datasets[0].borderColor.map((c, i) =>
      window._weeklyInContract && window._weeklyInContract[i] ? wCol : c
    );
    wc.update('none');
  }
}
window.setBurndownColor = function(key, val) {
  setChartColor(key, val);
  applyAllChartColors();
};
(function() {
  ['actual','proj','weekly'].forEach(k => {
    const el = document.getElementById('color-' + k);
    if (el) el.value = getChartColor(k);
  });
})();

/* ===================================================================== *
 * Burndown chart
 * ===================================================================== */
(function () {
  if (!document.getElementById('burndownChart')) return;
  const rawData    = D.weeklyChartData || [];
  const purchased  = D.purchased;
  const remaining  = D.remaining;
  const weeklyBurn = D.weeklyBurn;
  const weeksLeft  = D.weeksLeft;
  const latestDate = D.latestDate;

  const inContractRaw = rawData.filter(w => w.in_contract).sort((a,b) => a.week_start < b.week_start ? -1 : 1);
  let r = purchased;
  const actualPts = inContractRaw.map(w => {
    r = Math.max(r - w.total_credits_used, 0);
    const d = new Date((w.week_end || w.week_start) + 'T12:00:00');
    d.setDate(d.getDate() + 1);
    return [d.toISOString().slice(0, 10), r];
  });
  actualPts.push([latestDate, remaining]);

  function buildProjPts(granularity) {
    const pts = [[latestDate, remaining]];
    const base = new Date(latestDate);
    if (granularity === 'daily') {
      const totalDays = Math.min(Math.ceil(weeksLeft * 7) + 1, 420);
      const dailyBurn = weeklyBurn / 7;
      for (let i = 1; i <= totalDays; i++) {
        const d = new Date(base);
        d.setDate(d.getDate() + i);
        const rem = Math.max(remaining - dailyBurn * i, 0);
        pts.push([d.toISOString().slice(0, 10), rem]);
      }
    } else {
      for (let i = 1; i <= Math.min(Math.ceil(weeksLeft) + 1, 60); i++) {
        const d = new Date(base);
        d.setDate(d.getDate() + i * 7);
        const rem = Math.max(remaining - weeklyBurn * i, 0);
        pts.push([d.toISOString().slice(0, 10), rem]);
      }
    }
    return pts;
  }

  let currentGranularity = localStorage.getItem('fc-gran') || 'weekly';
  let projPts = buildProjPts(currentGranularity);

  const lookup = (pts, lbl) => { const p = pts.find(x => x[0] === lbl); return p != null ? p[1] : null; };

  function buildAllLabels(ppts) {
    return [...new Set([...actualPts, ...ppts].map(p => p[0]))].sort();
  }

  let allLabels = buildAllLabels(projPts);
  window.burndownLabels = allLabels;
  window.burndownMaxY   = purchased;

  window.burndownChart = new BNLChart('burndownChart', {
    type: 'line',
    data: {
      labels: allLabels,
      datasets: [
        {
          label: 'Actual remaining',
          data: allLabels.map(l => lookup(actualPts, l)),
          borderColor: getChartColor('actual'), backgroundColor: hexToRgba(getChartColor('actual'), 0.07),
          fill: true, tension: 0.1, pointRadius: 3, pointHoverRadius: 6, spanGaps: false,
        },
        {
          label: 'Projected remaining',
          data: allLabels.map(l => lookup(projPts, l)),
          borderColor: getChartColor('proj'), borderDash: [5, 4], backgroundColor: 'transparent',
          tension: 0.05, pointRadius: 2, pointHoverRadius: 5, spanGaps: false,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top', labels: { font: { size: 11 }, boxWidth: 14, usePointStyle: true, pointStyleWidth: 10 } },
        tooltip: {
          itemSort: (a, b) => (b.raw ?? -Infinity) - (a.raw ?? -Infinity),
          callbacks: { label: ctx => `  ${ctx.dataset.label}: ${Math.round(ctx.raw ?? 0).toLocaleString()} credits` },
        },
        zoom: {
          zoom: { wheel: { enabled: true, modifierKey: 'ctrl' }, pinch: { enabled: true }, mode: 'x' },
          pan:  { enabled: true, mode: 'x' },
          limits: { y: { min: 0 } },
        },
      },
      scales: {
        y: {
          beginAtZero: true, suggestedMax: purchased,
          ticks: { callback: v => v >= 1000000 ? (v/1000000).toFixed(1)+'M' : v >= 1000 ? (v/1000).toFixed(0)+'k' : v, font: { size: 10 } },
          grid: { color: 'rgba(0,0,0,.05)' },
        },
        x: { ticks: { maxRotation: 40, maxTicksLimit: 14, font: { size: 10 } }, grid: { display: false } },
      },
    },
  }, { exportName: 'Credit Burndown' });

  window.setBurndownGranularity = function(gran) {
    if (gran === currentGranularity) return;
    currentGranularity = gran;
    localStorage.setItem('fc-gran', gran);
    projPts = buildProjPts(gran);
    allLabels = buildAllLabels(projPts);
    window.burndownLabels = allLabels;
    const bc = window.burndownChart;
    if (!bc) return;
    bc.data.labels = allLabels;
    bc.data.datasets.forEach(ds => {
      if (ds._mcOverlay || ds._snapOverlay) return;
      if (ds.label === 'Actual remaining')    ds.data = allLabels.map(l => lookup(actualPts, l));
      if (ds.label === 'Projected remaining') ds.data = allLabels.map(l => lookup(projPts, l));
    });
    bc.update();
    if (typeof updateBurndownOverlays === 'function') updateBurndownOverlays();
    if (typeof window.refreshMcBands    === 'function') window.refreshMcBands();
    if (typeof window.refreshLrOverlay  === 'function') window.refreshLrOverlay();
    document.getElementById('gran-weekly').classList.toggle('active', gran === 'weekly');
    document.getElementById('gran-daily').classList.toggle('active', gran === 'daily');
  };

  if (currentGranularity === 'daily') {
    document.getElementById('gran-weekly').classList.remove('active');
    document.getElementById('gran-daily').classList.add('active');
  }
})();

/* ===================================================================== *
 * Prediction model overlays (Monte Carlo + Linear Regression)
 * ===================================================================== */
(function () {
  if (!document.getElementById('burndownChart')) return;
  const MC_RUNS = D.mcRuns;
  let mcCache  = null;
  let mcLoading = null;
  let detDataset = null;
  let lrCache = null, lrLoading = null;

  window.toggleForecastModel = function (modelId, enabled) {
    localStorage.setItem('forecast-model-' + modelId, enabled ? '1' : '0');
    if (modelId === 'deterministic') {
      const bc = window.burndownChart;
      if (!bc) return;
      if (enabled) {
        if (detDataset) { bc.data.datasets.splice(1, 0, detDataset); detDataset = null; }
      } else {
        detDataset = bc.data.datasets.splice(1, 1)[0] || null;
      }
      bc.update();
    } else if (modelId === 'monte_carlo') {
      if (enabled) loadMcOverlay(); else removeMcOverlay();
    } else if (modelId === 'linear_regression') {
      if (enabled) loadLrOverlay(); else removeLrOverlay();
    }
  };

  // ── Linear Trend (ML) overlay ──
  function getLrData() {
    if (lrCache) return Promise.resolve(lrCache);
    if (!lrLoading) {
      const params = new URLSearchParams(window.location.search);
      params.set('model', 'linear_regression');
      lrLoading = fetch('/forecast/model-data?' + params.toString())
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(data => { lrCache = data; lrLoading = null; return data; })
        .catch(e => { lrLoading = null; throw e; });
    }
    return lrLoading;
  }

  function interpPts(pts, allLabels) {
    if (!pts || !pts.length) return allLabels.map(() => null);
    const start = pts[0].date, end = pts[pts.length - 1].date;
    return allLabels.map(l => {
      if (l < start || l > end) return null;
      const idx = pts.findIndex(p => p.date > l);
      if (idx === -1) return pts[pts.length - 1].value;
      if (idx === 0)  return pts[0].value;
      const a = pts[idx - 1], b = pts[idx];
      const t = (new Date(l) - new Date(a.date)) / (new Date(b.date) - new Date(a.date));
      return a.value + t * (b.value - a.value);
    });
  }

  function applyLrToChart(data) {
    const bc = window.burndownChart;
    if (!bc) return;
    bc.data.datasets = bc.data.datasets.filter(d => !d._lrOverlay);
    const allLabels = bc.data.labels;
    const C = '#198754';
    const p50 = interpPts(data.burndown, allLabels);
    const hasBand = data.p10 && data.p90 && data.p10.length && data.p90.length;
    if (hasBand) {
      bc.data.datasets.push({
        label: 'LR P90', data: interpPts(data.p90, allLabels),
        borderColor: hexToRgba(C, 0.4), borderWidth: 1, borderDash: [2, 3],
        backgroundColor: hexToRgba(C, 0.10), fill: '+1', tension: 0.1, pointRadius: 0,
        spanGaps: false, _lrOverlay: true,
      });
      bc.data.datasets.push({
        label: 'LR P10', data: interpPts(data.p10, allLabels),
        borderColor: hexToRgba(C, 0.4), borderWidth: 1, borderDash: [2, 3],
        backgroundColor: 'transparent', fill: false, tension: 0.1, pointRadius: 0,
        spanGaps: false, _lrOverlay: true,
      });
    }
    bc.data.datasets.push({
      label: 'Linear Trend (ML)', data: p50,
      borderColor: C, borderWidth: 2, borderDash: [6, 3],
      backgroundColor: 'transparent', fill: false, tension: 0.1,
      pointRadius: 0, pointHoverRadius: 4, spanGaps: false, _lrOverlay: true,
    });
    bc.update();
  }

  async function loadLrOverlay() {
    const status = document.getElementById('lr-status');
    if (status && !lrCache) status.textContent = 'loading…';
    try {
      const data = await getLrData();
      applyLrToChart(data);
      if (status) {
        const m = data.metadata || {};
        status.textContent = (m.slope_credits_per_week != null)
          ? `slope ${Math.round(m.slope_credits_per_week).toLocaleString()}/wk · R² ${m.r_squared}`
          : '';
      }
    } catch (e) {
      if (status) status.textContent = 'load failed';
      const cb = document.getElementById('model-lr');
      if (cb) cb.checked = false;
    }
  }

  function removeLrOverlay() {
    const bc = window.burndownChart;
    if (!bc) return;
    bc.data.datasets = bc.data.datasets.filter(d => !d._lrOverlay);
    bc.update();
    const status = document.getElementById('lr-status');
    if (status) status.textContent = '';
  }
  window.refreshLrOverlay = function () { if (lrCache) applyLrToChart(lrCache); };

  function getMcData() {
    if (mcCache) return Promise.resolve(mcCache);
    if (!mcLoading) {
      const params = new URLSearchParams(window.location.search);
      params.set('model', 'monte_carlo');
      params.set('runs', MC_RUNS);
      mcLoading = fetch('/forecast/model-data?' + params.toString())
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(data => { mcCache = data; mcLoading = null; return data; })
        .catch(e => { mcLoading = null; throw e; });
    }
    return mcLoading;
  }

  async function loadMcOverlay() {
    const bc = window.burndownChart;
    if (!bc) return;
    const status = document.getElementById('mc-status');
    if (status && !mcCache) { status.textContent = 'loading…'; status.style.display = ''; }
    try {
      const data = await getMcData();
      applyMcToChart(data);
      const ctrl = document.getElementById('mc-band-controls');
      if (ctrl) ctrl.style.display = '';
      if (status) {
        const ep = data.metadata && data.metadata.exhaustion_probability != null
          ? Math.round(data.metadata.exhaustion_probability * 100) + '% exhaustion risk  ·  '
            + (data.metadata.runs || 0).toLocaleString() + ' runs'
          : '';
        status.textContent = ep;
        status.style.display = ep ? '' : 'none';
      }
    } catch (e) {
      console.error('MC fetch failed:', e);
      if (status) { status.textContent = 'load failed'; status.style.display = ''; }
      const cb = document.getElementById('model-mc');
      if (cb) cb.checked = false;
    }
  }

  window.toggleMcBand = function (band, visible) {
    localStorage.setItem('forecast-mc-' + band, visible ? '1' : '0');
    applyMcBands(visible ? 'show' : 'default');
  };

  function updateMcStats(data) {
    const ep     = data.metadata && data.metadata.exhaustion_probability != null ? data.metadata.exhaustion_probability : null;
    const runs   = (data.metadata && data.metadata.runs) || 0;
    const p10End = data.p10     && data.p10.length     ? data.p10[data.p10.length - 1].value         : null;
    const p50End = data.burndown && data.burndown.length ? data.burndown[data.burndown.length - 1].value : null;
    const p90End = data.p90     && data.p90.length     ? data.p90[data.p90.length - 1].value         : null;

    const riskCls = ep === null ? '' : ep > 0.5 ? 'text-danger' : ep > 0.1 ? 'text-warning' : 'text-success';
    const balCls  = v => v !== null && v < 0 ? 'text-danger' : v !== null ? 'text-success' : '';
    const fmtBal  = v => v !== null ? Math.round(v).toLocaleString() : '—';

    const probEl = document.getElementById('mc-kpi-prob');
    const subEl  = document.getElementById('mc-kpi-sub');
    if (probEl) {
      if (ep !== null) {
        probEl.innerHTML = `<span class="${riskCls}">${Math.round(ep * 100)}%</span>`;
        if (subEl) subEl.textContent = `P50 end: ${p50End !== null ? Math.round(p50End).toLocaleString() : '—'}`;
      } else {
        probEl.textContent = '—';
      }
    }

    const badge = document.getElementById('mc-acc-badge');
    if (badge && ep !== null) {
      badge.textContent = Math.round(ep * 100) + '% risk';
      badge.className   = `ms-2 badge bg-${ep > 0.5 ? 'danger' : ep > 0.1 ? 'warning' : 'success'}`;
      badge.style.display = '';
    }

    const body = document.getElementById('mc-acc-body');
    if (body) {
      const interp = ep === null ? '' : ep > 0.5
        ? 'High risk — credits likely exhausted before contract end at current burn rate.'
        : ep > 0.1
        ? 'Moderate risk — some probability of exhaustion; monitor burn rate closely.'
        : 'Low risk — credits expected to last through contract end in most scenarios.';
      body.innerHTML = `
        <div class="row g-3">
          <div class="col-md-5">
            <p class="text-muted small mb-1 fw-semibold">Simulation Summary</p>
            <table class="table table-sm mb-2">
              <tr><td>Exhaustion probability</td><td class="text-end fw-semibold ${riskCls}">${ep !== null ? Math.round(ep * 100) + '%' : '—'}</td></tr>
              <tr><td>Simulation runs</td><td class="text-end">${runs.toLocaleString()}</td></tr>
            </table>
            ${interp ? `<p class="mb-0 small ${riskCls}">${interp}</p>` : ''}
          </div>
          <div class="col-md-7">
            <p class="text-muted small mb-1 fw-semibold">End Balance Distribution</p>
            <table class="table table-sm mb-0">
              <thead><tr><th>Percentile</th><th class="text-end">End Balance</th><th class="text-muted text-end" style="font-size:.7rem;">Interpretation</th></tr></thead>
              <tbody>
                <tr><td>P10 <span class="text-muted small">(pessimistic)</span></td><td class="text-end ${balCls(p10End)}">${fmtBal(p10End)}</td><td class="text-muted text-end small">90% of runs end higher</td></tr>
                <tr><td>P50 <span class="text-muted small">(median)</span></td><td class="text-end ${balCls(p50End)}">${fmtBal(p50End)}</td><td class="text-muted text-end small">most likely outcome</td></tr>
                <tr><td>P90 <span class="text-muted small">(optimistic)</span></td><td class="text-end ${balCls(p90End)}">${fmtBal(p90End)}</td><td class="text-muted text-end small">10% of runs end higher</td></tr>
              </tbody>
            </table>
          </div>
        </div>`;
    }
  }

  function applyMcToChart(_data) {
    applyMcBands('show');
  }

  function applyMcBands(mode) {
    const bc = window.burndownChart;
    if (!bc || !mcCache) return;
    bc.data.datasets = bc.data.datasets.filter(d => !d._mcOverlay);

    const data      = mcCache;
    const allLabels = bc.data.labels;

    function interpMc(pts) {
      if (!pts || !pts.length) return allLabels.map(() => null);
      const start = pts[0].date, end = pts[pts.length - 1].date;
      return allLabels.map(l => {
        if (l < start || l > end) return null;
        const idx = pts.findIndex(p => p.date > l);
        if (idx === -1) return pts[pts.length - 1].value;
        if (idx === 0)  return pts[0].value;
        const a = pts[idx - 1], b = pts[idx];
        const t = (new Date(l) - new Date(a.date)) / (new Date(b.date) - new Date(a.date));
        return a.value + t * (b.value - a.value);
      });
    }

    const p90data = interpMc(data.p90);
    const p50data = interpMc(data.burndown);
    const p10data = interpMc(data.p10);

    const showP90 = localStorage.getItem('forecast-mc-p90') !== '0';
    const showP10 = localStorage.getItem('forecast-mc-p10') !== '0';
    const showP50 = localStorage.getItem('forecast-mc-p50') !== '0';

    const p90Fill = !showP10 ? false : showP50 ? '+2' : '+1';

    if (showP90) {
      bc.data.datasets.push({
        label: 'MC P90 (optimistic)',
        data: p90data,
        borderColor: 'rgba(253,126,20,0.55)', borderWidth: 1.5, borderDash: [3, 3],
        backgroundColor: showP10 ? 'rgba(253,126,20,0.18)' : 'transparent',
        fill: p90Fill,
        pointRadius: 0, tension: 0.1, spanGaps: false,
        _mcOverlay: true, _mcBand: 'p90',
      });
    }
    if (showP50) {
      bc.data.datasets.push({
        label: 'MC P50 (median)',
        data: p50data,
        borderColor: '#fd7e14', borderWidth: 2.5, borderDash: [6, 3],
        backgroundColor: 'transparent', fill: false,
        pointRadius: 0, pointHoverRadius: 4, tension: 0.1, spanGaps: false,
        _mcOverlay: true, _mcBand: 'p50',
      });
    }
    if (showP10) {
      bc.data.datasets.push({
        label: 'MC P10 (pessimistic)',
        data: p10data,
        borderColor: 'rgba(253,126,20,0.55)', borderWidth: 1.5, borderDash: [3, 3],
        backgroundColor: 'transparent', fill: false,
        pointRadius: 0, tension: 0.1, spanGaps: false,
        _mcOverlay: true, _mcBand: 'p10',
      });
    }

    ['p90', 'p50', 'p10'].forEach(band => {
      if (localStorage.getItem('forecast-mc-' + band) === '0') {
        const cb = document.getElementById('mc-show-' + band);
        if (cb) cb.checked = false;
      }
    });

    bc.chart.update(mode || 'default');
  }

  window.refreshMcBands = function() { if (mcCache) applyMcBands('none'); };

  function removeMcOverlay() {
    const bc = window.burndownChart;
    if (!bc) return;
    bc.data.datasets = bc.data.datasets.filter(d => !d._mcOverlay);
    bc.update();
    const ctrl = document.getElementById('mc-band-controls');
    if (ctrl) ctrl.style.display = 'none';
    mcCache = null;
  }

  // Restore checkbox states after page reload
  const savedDet = localStorage.getItem('forecast-model-deterministic');
  const savedMc  = localStorage.getItem('forecast-model-monte_carlo');
  if (savedDet === '0') {
    const cb = document.getElementById('model-det');
    if (cb) { cb.checked = false; window.toggleForecastModel('deterministic', false); }
  }
  if (savedMc === '1') {
    const cb = document.getElementById('model-mc');
    if (cb) { cb.checked = true; window.toggleForecastModel('monte_carlo', true); }
  }
  if (localStorage.getItem('forecast-model-linear_regression') === '1') {
    const cb = document.getElementById('model-lr');
    if (cb) { cb.checked = true; window.toggleForecastModel('linear_regression', true); }
  }

  // Auto-load MC stats on page load (also serves chart overlay if it was restored)
  getMcData().then(updateMcStats).catch(() => {
    const probEl = document.getElementById('mc-kpi-prob');
    if (probEl) probEl.textContent = '—';
    const body = document.getElementById('mc-acc-body');
    if (body) body.innerHTML = '<div class="text-muted small">Simulation data unavailable.</div>';
  });
})();

/* ===================================================================== *
 * Weekly / Active Users / Usage Type / Cumulative charts
 * ===================================================================== */
(function () {
  if (!document.getElementById('weeklyChart')) return;
  const rawData    = D.weeklyChartData || [];
  const labels     = rawData.map(d => d.week_start);
  const credits    = rawData.map(d => d.total_credits_used);
  const inContract = rawData.map(d => d.in_contract);
  window._weeklyInContract = inContract;
  const wCol = getChartColor('weekly');
  const bgColors   = inContract.map(ic => ic ? hexToRgba(wCol, 0.72) : 'rgba(108,117,125,0.35)');
  const bdColors   = inContract.map(ic => ic ? wCol                   : 'rgba(108,117,125,0.7)');

  window.weeklyChart = new BNLChart('weeklyChart', {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Credits used', data: credits, backgroundColor: bgColors, borderColor: bdColors, borderWidth: 1, borderRadius: 4 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => 'Week of ' + items[0].label,
            label: ctx => `  ${ctx.parsed.y.toLocaleString()} credits`,
            footer: items => inContract[items[0].dataIndex] ? 'In contract period' : 'Pre-contract',
          },
          footerColor: ctx => inContract[ctx[0]?.dataIndex] ? '#6ea8fe' : '#adb5bd',
        },
        zoom: {
          zoom: { wheel: { enabled: true, modifierKey: 'ctrl' }, pinch: { enabled: true }, mode: 'x' },
          pan:  { enabled: true, mode: 'x' },
        },
      },
      scales: {
        y: { beginAtZero: true, ticks: { callback: v => v >= 1000 ? (v/1000).toFixed(0)+'k' : v, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
        x: { ticks: { maxRotation: 40, font: { size: 10 }, maxTicksLimit: 20 }, grid: { display: false } },
      },
    },
  }, { exportName: 'Weekly Credit Burn' });

  const firstContractIdx = inContract.indexOf(true);
  if (firstContractIdx > 0 && labels.length > firstContractIdx + 4) {
    try { window.weeklyChart.chart.zoomScale('x', { min: labels[Math.max(0, firstContractIdx - 1)], max: labels[labels.length - 1] }, 'none'); } catch (_) {}
  }
})();

(function () {
  if (!document.getElementById('activeUsersChart')) return;
  const auData = D.activeUsers || [];
  if (!auData.length) return;
  const labels   = auData.map(d => d.week_start);
  const values   = auData.map(d => d.active_users);
  const ic       = auData.map(d => d.in_contract);
  window.activeUsersChart = new BNLChart('activeUsersChart', {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Active users', data: values, backgroundColor: ic.map(v => v ? 'rgba(111,66,193,0.7)' : 'rgba(108,117,125,0.35)'), borderRadius: 4 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: items => 'Week of ' + items[0].label,
          label: ctx => `  Active users: ${ctx.parsed.y}`,
          footer: items => ic[items[0].dataIndex] ? 'In contract period' : 'Pre-contract',
        }},
      },
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
        x: { ticks: { maxRotation: 40, maxTicksLimit: 16, font: { size: 10 } }, grid: { display: false } },
      },
    },
  }, { exportName: 'Active Users per Week' });
})();

// Credits by Usage Type per Week (stacked bar)
window.forecastUsageTypeChart = renderUsageTypeChart('forecastUsageTypeChart', D.usageType);

(function () {
  if (!document.getElementById('cumulativeChart')) return;
  const cumData = D.cumulative || [];
  if (!cumData.length) return;
  const labels  = cumData.map(d => d.week_start);
  const values  = cumData.map(d => d.cumulative);
  const ic      = cumData.map(d => d.in_contract);
  window.cumulativeChart = new BNLChart('cumulativeChart', {
    type: 'line',
    data: { labels, datasets: [{
      label: 'Cumulative credits used', data: values,
      borderColor: '#198754', backgroundColor: 'rgba(25,135,84,0.08)',
      fill: true, tension: 0.1, pointRadius: 2, pointHoverRadius: 5,
      pointBackgroundColor: ic.map(v => v ? '#198754' : '#6c757d'),
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `  Cumulative: ${Math.round(ctx.raw).toLocaleString()} credits` } },
      },
      scales: {
        y: { beginAtZero: true, ticks: { callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1000 ? (v/1000).toFixed(0)+'k' : v, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
        x: { ticks: { maxRotation: 40, maxTicksLimit: 16, font: { size: 10 } }, grid: { display: false } },
      },
    },
  }, { exportName: 'Cumulative Credit Burn' });
})();

/* ===================================================================== *
 * Page-level handlers (exclude-partial, data window, inline rename)
 * ===================================================================== */
(function () {
  const y = sessionStorage.getItem('forecast-scroll');
  if (y !== null) { sessionStorage.removeItem('forecast-scroll'); window.scrollTo(0, parseInt(y, 10)); }
})();

function applyExcludePartial(checked) {
  sessionStorage.setItem('forecast-scroll', window.scrollY);
  if (typeof selectedSnaps !== 'undefined' && selectedSnaps.size > 0) {
    sessionStorage.setItem('forecast-snap-keys', JSON.stringify([...selectedSnaps.keys()]));
  } else {
    sessionStorage.removeItem('forecast-snap-keys');
  }
  document.cookie = 'forecast_excl_partial=' + (checked ? '1' : '0') + '; path=/; max-age=31536000; SameSite=Lax';
  const url = new URL(window.location.href);
  url.searchParams.set('exclude_partial', checked ? '1' : '0');
  window.location.href = url.toString();
}

function applyDataWindow() {
  const from = document.getElementById('data-from').value;
  const to   = document.getElementById('data-to').value;
  const url  = new URL(window.location.href);
  if (from) url.searchParams.set('data_from', from);
  else      url.searchParams.delete('data_from');
  if (to)   url.searchParams.set('data_to', to);
  else      url.searchParams.delete('data_to');
  window.location.href = url.toString();
}

// Inline Snapshot Label Rename
function startRename(cell) {
  const display = cell.querySelector('.label-display');
  const input   = cell.querySelector('.label-edit');
  if (!display || !input) return;
  display.closest('.d-flex').style.display = 'none';
  input.style.display = '';
  input.focus(); input.select();
}

document.querySelectorAll('.snapshot-label-cell').forEach(cell => {
  const display = cell.querySelector('.label-display');
  const input   = cell.querySelector('.label-edit');
  if (!display || !input) return;

  function commitRename() {
    const newLabel = input.value.trim();
    const oldLabel = cell.dataset.oldLabel;
    const snapTs   = cell.dataset.ts;
    const snapDate = cell.dataset.date;
    if (newLabel === oldLabel) { cancelRename(); return; }
    fetch(D.urls.rename, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ snapshot_ts: snapTs, snapshot_date: snapDate, old_label: oldLabel, new_label: newLabel }),
    }).then(r => {
      if (r.status === 204) {
        display.textContent = newLabel || 'No label';
        display.title = newLabel;
        if (newLabel) display.classList.remove('label-empty'); else display.classList.add('label-empty');
        cell.dataset.oldLabel = newLabel;
        input.value = newLabel;
        const row = cell.closest('tr');
        if (row) { try { const snap = JSON.parse(row.dataset.snap || '{}'); snap.label = newLabel; row.dataset.snap = JSON.stringify(snap); } catch (_) {} }
      } else { r.text().then(msg => alert('Rename failed: ' + (msg || r.status))); }
      cancelRename();
    }).catch(() => { alert('Rename request failed.'); cancelRename(); });
  }

  function cancelRename() {
    const displayRow = display.closest('.d-flex');
    input.style.display = 'none';
    if (displayRow) displayRow.style.display = '';
    input.value = cell.dataset.oldLabel;
    display.textContent = cell.dataset.oldLabel || 'No label';
    if (cell.dataset.oldLabel) display.classList.remove('label-empty'); else display.classList.add('label-empty');
  }

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); commitRename(); }
    if (e.key === 'Escape') { e.preventDefault(); cancelRename(); }
  });
  input.addEventListener('blur', commitRename);
});
