// Client-side, in-place table sort shared by every page with a `data-col`
// sortable <thead> (Records on user-summary, Recommended Tier Actions on
// Optimization). Clicking a header re-sorts the already-rendered rows without
// a page reload; hidden sort_by/sort_order fields on the given form are kept
// in sync so the server re-applies the same sort on the next filter reload.
function initTableSort({ formId, initialCol = '', initialOrder = 'asc' }) {
  const sortState = { col: initialCol, order: initialOrder };
  const form = formId ? document.getElementById(formId) : null;

  function updateIndicators() {
    document.querySelectorAll('.records-table thead th[data-col]').forEach(th => {
      const ind = th.querySelector('.sort-indicator');
      if (!ind) return;
      if (th.dataset.col === sortState.col) {
        ind.textContent = sortState.order === 'asc' ? '↑' : '↓';
        ind.classList.add('active');
        th.classList.add('sorted');
      } else {
        ind.textContent = '';
        ind.classList.remove('active');
        th.classList.remove('sorted');
      }
    });
  }

  function syncField(name, value) {
    if (!form) return;
    let el = form.querySelector(`input[name="${name}"]`);
    if (!el) {
      el = document.createElement('input');
      el.type = 'hidden';
      el.name = name;
      form.appendChild(el);
    }
    el.value = value;
  }

  window.sortByCol = function (th) {
    const col = th.dataset.col;
    const idx = Array.from(th.parentElement.children).indexOf(th);

    sortState.order = (sortState.col === col && sortState.order === 'asc') ? 'desc' : 'asc';
    sortState.col = col;

    const tbody = th.closest('table').querySelector('tbody');
    const rows = Array.from(tbody.rows);

    // Nothing to sort if the only row is the empty-state message.
    if (rows.length === 1 && rows[0].querySelector('td[colspan]')) return;

    rows.sort((a, b) => {
      const av = a.cells[idx]?.textContent.trim() ?? '';
      const bv = b.cells[idx]?.textContent.trim() ?? '';
      const an = parseFloat(av.replace(/,/g, ''));
      const bn = parseFloat(bv.replace(/,/g, ''));
      // Use numeric comparison only when both values are real numbers that differ.
      // Dates like "2024-06-15" parse to 2024 for every row in the same year, so
      // if the numbers are equal but the raw strings differ, fall back to
      // localeCompare which sorts ISO date strings correctly.
      const cmp = (!isNaN(an) && !isNaN(bn) && an !== bn)
        ? (an - bn)
        : av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
      return sortState.order === 'asc' ? cmp : -cmp;
    });

    rows.forEach(r => tbody.appendChild(r));
    updateIndicators();

    // Keep hidden fields in sync for server-side sort on next filter reload.
    syncField('sort_by', sortState.col);
    syncField('sort_order', sortState.order);
  };

  // Reflect any server-applied initial sort in the header indicators.
  updateIndicators();
}
