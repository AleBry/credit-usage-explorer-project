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
    if (typeSel) {
      typeSel.insertAdjacentHTML('beforeend',
        data.series.map(s => `<option value="${s.name}">${s.name}</option>`).join(''));
    }

    function apply() {
      const type = typeSel ? typeSel.value : '__all__';
      const start = (n => (n > 0 ? Math.max(0, data.weeks.length - n) : 0))(weeksOf(weeksSel));
      const series = (type === '__all__') ? data.series : data.series.filter(s => s.name === type);
      const c = chart.chart;
      c.data.labels = data.weeks.slice(start);
      c.data.datasets = series.map(s => ({
        label: s.name,
        data: s.data.slice(start),
        backgroundColor: colorByName[s.name],
        borderWidth: 0,
        borderRadius: 2,
      }));
      c.update();
    }
    [typeSel, weeksSel].forEach(s => s && s.addEventListener('change', apply));
  })();

  // ===== Weekly credit burn =====
  (function initWeekly() {
    const raw = D.weeklyTrend || [];
    if (!raw.length) { emptyMsg('weeklyChart', 'No date data available to plot.'); return; }
    window.summaryWeeklyChart = new BNLChart('weeklyChart', {
      type: 'bar',
      data: {
        labels: raw.map(d => d.week),
        datasets: [{
          label: 'Credits used',
          data: raw.map(d => d.total_credits),
          backgroundColor: 'rgba(13,110,253,0.65)',
          borderColor: 'rgba(13,110,253,1)',
          borderWidth: 1,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { callback: v => v.toLocaleString() } },
          x: { ticks: { maxRotation: 45, font: { size: 10 } } },
        },
      },
    }, { exportName: 'Weekly Credit Burn' });

    const weeksSel = document.getElementById('wb-weeks-filter');
    function apply() {
      const slice = lastN(raw, weeksOf(weeksSel));
      const c = window.summaryWeeklyChart.chart;
      c.data.labels = slice.map(d => d.week);
      c.data.datasets[0].data = slice.map(d => d.total_credits);
      c.update();
    }
    if (weeksSel) weeksSel.addEventListener('change', apply);
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
        responsive: true,
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
