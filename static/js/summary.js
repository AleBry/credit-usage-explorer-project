/**
 * Summary page charts. All server data arrives via the #summary-data JSON
 * island, so this file is plain cacheable JS with zero template interpolation.
 */
'use strict';

(function () {
  const el = document.getElementById('summary-data');
  if (!el) return;
  let D;
  try { D = JSON.parse(el.textContent); } catch (_) { return; }

  // Credits by usage type per week (stacked bar)
  window.summaryUsageTypeChart = renderUsageTypeChart('summaryUsageTypeChart', D.usageType);

  // Weekly credit burn
  const raw = D.weeklyTrend || [];
  if (raw.length) {
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
  } else {
    const c = document.getElementById('weeklyChart');
    if (c) c.closest('.dash-section-body').innerHTML =
      '<p class="text-muted small mb-0">No date data available to plot.</p>';
  }

  // Active users per week
  (function () {
    const auData = D.activeUsers || [];
    const canvas = document.getElementById('activeUsersChart');
    if (!canvas) return;
    if (!auData.length) {
      canvas.closest('.dash-section-body').innerHTML =
        '<p class="text-muted small mb-0">No active user data available.</p>';
      return;
    }
    const labels = auData.map(d => d.week_start);
    const values = auData.map(d => d.active_users);
    const ic     = auData.map(d => d.in_contract);
    const bg     = ic.map(v => v ? 'rgba(111,66,193,0.7)' : 'rgba(108,117,125,0.35)');
    window.summaryActiveUsersChart = new BNLChart('activeUsersChart', {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Active users', data: values, backgroundColor: bg, borderRadius: 3 }] },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            title: items => 'Week of ' + items[0].label,
            label: ctx => `  Active users: ${ctx.parsed.y}`,
            footer: items => ic[items[0].dataIndex] ? 'In contract period' : 'Pre-contract',
          } },
        },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, font: { size: 10 } }, grid: { color: 'rgba(0,0,0,.05)' } },
          x: { ticks: { maxRotation: 45, maxTicksLimit: 16, font: { size: 10 } }, grid: { display: false } },
        },
      },
    }, { exportName: 'Active Users per Week' });
  })();
})();
