/**
 * Summary page charts. All server data arrives via the #summary-data JSON
 * island, so this file is plain cacheable JS with zero template interpolation.
 *
 * Each chart has its own client-side dropdown filters (time range, and for the
 * usage-type chart a type focus / for active users a contract scope). Filtering
 * mutates the existing chart in place — no page reload — so the controls feel
 * instant and stay independent per chart.
 */
'use strict';

(function () {
  const el = document.getElementById('summary-data');
  if (!el) return;
  let D;
  try { D = JSON.parse(el.textContent); } catch (_) { return; }

  // Keep the last `n` weeks of an array (n <= 0 means "all").
  const lastN = (arr, n) => (n > 0 ? arr.slice(-n) : arr);
  const weeksOf = sel => (sel ? parseInt(sel.value, 10) || 0 : 0);
  const emptyMsg = (canvasId, msg) => {
    const c = document.getElementById(canvasId);
    if (c) { const host = c.closest('.dash-section-body') || c.parentElement;
             if (host) host.innerHTML = `<p class="text-muted small mb-0 p-3">${msg}</p>`; }
  };

  // ===== Credits by usage type per week (stacked bar) =====
  (function initUsageType() {
    const data = D.usageType;
    const chart = renderUsageTypeChart('summaryUsageTypeChart', data);
    window.summaryUsageTypeChart = chart;
    if (!chart) return;  // renderUsageTypeChart already showed an empty state

    // Preserve each type's original palette color when filtering.
    const colorByName = {};
    data.series.forEach((s, i) => { colorByName[s.name] = BNL_PALETTE[i % BNL_PALETTE.length]; });

    const typeSel = document.getElementById('ut-type-filter');
    const weeksSel = document.getElementById('ut-weeks-filter');
    const scopeSel = document.getElementById('ut-scope-filter');
    const inC = data.in_contract || data.weeks.map(() => true);
    if (typeSel) {
      typeSel.insertAdjacentHTML('beforeend',
        data.series.map(s => `<option value="${s.name}">${s.name}</option>`).join(''));
    }

    function apply() {
      const type = typeSel ? typeSel.value : '__all__';
      // Visible week indices: drop pre-contract weeks (if scoped), then last-N.
      let idx = data.weeks.map((_, i) => i);
      if (scopeSel && scopeSel.value === 'contract') idx = idx.filter(i => inC[i]);
      const n = weeksOf(weeksSel);
      if (n > 0) idx = idx.slice(-n);
      const series = (type === '__all__') ? data.series : data.series.filter(s => s.name === type);
      const c = chart.chart;
      c.data.labels = idx.map(i => data.weeks[i]);
      c.data.datasets = series.map(s => ({
        label: s.name,
        data: idx.map(i => s.data[i]),
        backgroundColor: colorByName[s.name],
        borderWidth: 0,
        borderRadius: 2,
      }));
      c.update();
    }
    [typeSel, weeksSel, scopeSel].forEach(s => s && s.addEventListener('change', apply));
  })();

  // ===== Weekly credit burn =====
  (function initWeekly() {
    const raw = D.weeklyTrend || [];
    if (!raw.length) { emptyMsg('weeklyChart', 'No date data available to plot.'); return; }

    // Pre-contract weeks render gray (matching the Active Users chart).
    const IN_BG = 'rgba(13,110,253,0.65)', IN_BD = 'rgba(13,110,253,1)';
    const PRE_BG = 'rgba(108,117,125,0.45)', PRE_BD = 'rgba(108,117,125,0.85)';
    const bgFor = rows => rows.map(d => (d.in_contract ? IN_BG : PRE_BG));
    const bdFor = rows => rows.map(d => (d.in_contract ? IN_BD : PRE_BD));
    let curIc = raw.map(d => d.in_contract);

    window.summaryWeeklyChart = new BNLChart('weeklyChart', {
      type: 'bar',
      data: {
        labels: raw.map(d => d.week),
        datasets: [{
          label: 'Credits used',
          data: raw.map(d => d.total_credits),
          backgroundColor: bgFor(raw),
          borderColor: bdFor(raw),
          borderWidth: 1,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            footer: items => (curIc[items[0].dataIndex] ? '' : 'Pre-contract'),
          } },
        },
        scales: {
          y: { beginAtZero: true, ticks: { callback: v => v.toLocaleString() } },
          x: { ticks: { maxRotation: 45, font: { size: 10 } } },
        },
      },
    }, { exportName: 'Weekly Credit Burn' });

    const weeksSel = document.getElementById('wb-weeks-filter');
    const scopeSel = document.getElementById('wb-scope-filter');
    function apply() {
      let rows = raw;
      if (scopeSel && scopeSel.value === 'contract') rows = rows.filter(d => d.in_contract);
      rows = lastN(rows, weeksOf(weeksSel));
      curIc = rows.map(d => d.in_contract);
      const c = window.summaryWeeklyChart.chart;
      c.data.labels = rows.map(d => d.week);
      c.data.datasets[0].data = rows.map(d => d.total_credits);
      c.data.datasets[0].backgroundColor = bgFor(rows);
      c.data.datasets[0].borderColor = bdFor(rows);
      c.update();
    }
    [weeksSel, scopeSel].forEach(s => s && s.addEventListener('change', apply));
  })();

  // ===== Active users per week =====
  (function initActiveUsers() {
    const auData = D.activeUsers || [];
    if (!auData.length) { emptyMsg('activeUsersChart', 'No active user data available.'); return; }

    // `curIc` tracks the in-contract flags for the rows CURRENTLY shown, so the
    // tooltip footer stays correct after filtering.
    let curIc = auData.map(d => d.in_contract);
    const bgFor = ic => ic.map(v => (v ? 'rgba(111,66,193,0.7)' : 'rgba(108,117,125,0.35)'));

    window.summaryActiveUsersChart = new BNLChart('activeUsersChart', {
      type: 'bar',
      data: {
        labels: auData.map(d => d.week_start),
        datasets: [{ label: 'Active users', data: auData.map(d => d.active_users),
                     backgroundColor: bgFor(curIc), borderRadius: 3 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            title: items => 'Week of ' + items[0].label,
            label: ctx => `  Active users: ${ctx.parsed.y}`,
            footer: items => curIc[items[0].dataIndex] ? 'In contract period' : 'Pre-contract',
          } },
        },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
          x: { ticks: { maxRotation: 45, maxTicksLimit: 16, font: { size: 10 } }, grid: { display: false } },
        },
      },
    }, { exportName: 'Active Users per Week' });

    const weeksSel = document.getElementById('au-weeks-filter');
    const scopeSel = document.getElementById('au-scope-filter');
    function apply() {
      let rows = auData;
      if (scopeSel && scopeSel.value === 'contract') rows = rows.filter(d => d.in_contract);
      rows = lastN(rows, weeksOf(weeksSel));
      curIc = rows.map(d => d.in_contract);
      const c = window.summaryActiveUsersChart.chart;
      c.data.labels = rows.map(d => d.week_start);
      c.data.datasets[0].data = rows.map(d => d.active_users);
      c.data.datasets[0].backgroundColor = bgFor(curIc);
      c.update();
    }
    [weeksSel, scopeSel].forEach(s => s && s.addEventListener('change', apply));
  })();
})();
