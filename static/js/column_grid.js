'use strict';

(function () {
  const STORAGE_PREFIX = 'cue-column-grid:';

  function loadState(key) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : {};
    } catch (err) {
      return {};
    }
  }

  function saveState(key, state) {
    try {
      localStorage.setItem(key, JSON.stringify(state));
    } catch (err) {}
  }

  function getHeaders(table) {
    return Array.from(table.querySelectorAll('thead th[data-col]'));
  }

  function getTableKey(table, idx) {
    return `${STORAGE_PREFIX}${table.dataset.gridKey || table.id || `${location.pathname}:${idx}`}`;
  }

  function makeColgroup(table, order, widths) {
    let colgroup = table.querySelector('colgroup');
    if (!colgroup) {
      colgroup = document.createElement('colgroup');
      table.insertBefore(colgroup, table.firstChild);
    }
    colgroup.innerHTML = '';
    order.forEach((key) => {
      const col = document.createElement('col');
      col.dataset.col = key;
      if (widths && widths[key]) col.style.width = widths[key];
      colgroup.appendChild(col);
    });
    return colgroup;
  }

  function applyOrder(table, order) {
    const headRow = table.tHead && table.tHead.rows[0];
    const body = table.tBodies[0];
    if (!headRow || !body) return false;

    const currentHeaders = getHeaders(table);
    if (currentHeaders.length !== order.length) return false;

    const headerMap = new Map(currentHeaders.map((th) => [th.dataset.col, th]));
    if (order.some((key) => !headerMap.has(key))) return false;

    const currentOrder = currentHeaders.map((th) => th.dataset.col);
    const rowSpanHeaders = currentHeaders.some((th) => th.rowSpan && th.rowSpan > 1);
    if (rowSpanHeaders) return false;

    order.forEach((key) => headRow.appendChild(headerMap.get(key)));

    Array.from(body.rows).forEach((row) => {
      if (row.cells.length !== currentOrder.length) return;
      const cellMap = new Map();
      currentOrder.forEach((key, idx) => cellMap.set(key, row.cells[idx]));
      order.forEach((key) => {
        const cell = cellMap.get(key);
        if (cell) row.appendChild(cell);
      });
    });

    return true;
  }

  function applyWidths(table, state) {
    const headers = getHeaders(table);
    const order = headers.map((th) => th.dataset.col);
    const colgroup = makeColgroup(table, order, state.widths || {});
    const colsByKey = new Map(Array.from(colgroup.querySelectorAll('col')).map((col) => [col.dataset.col, col]));
    headers.forEach((th) => {
      const col = colsByKey.get(th.dataset.col);
      if (col && state.widths && state.widths[th.dataset.col]) {
        th.style.width = state.widths[th.dataset.col];
      } else {
        th.style.width = '';
      }
    });
  }

  function saveOrder(table, state, key, order) {
    state.order = order;
    saveState(key, state);
  }

  function saveWidth(table, state, key, colKey, widthPx) {
    state.widths = state.widths || {};
    state.widths[colKey] = `${Math.max(60, Math.round(widthPx))}px`;
    saveState(key, state);
  }

  function initTable(table, idx) {
    const headers = getHeaders(table);
    if (!headers.length) return;
    if (table.dataset.gridInit === '1') return;
    table.dataset.gridInit = '1';

    const key = getTableKey(table, idx);
    const state = loadState(key);
    const currentOrder = headers.map((th) => th.dataset.col);
    const targetOrder = Array.isArray(state.order) && state.order.length === currentOrder.length &&
      state.order.every((k) => currentOrder.includes(k))
      ? state.order.slice()
      : currentOrder.slice();

    applyOrder(table, targetOrder);
    applyWidths(table, state);

    let dragSession = null;
    let resizeActive = false;

    function clearDragTargets() {
      getHeaders(table).forEach((header) => header.classList.remove('grid-drag-over'));
    }

    function getClosestHeader(clientX) {
      const currentHeaders = getHeaders(table);
      if (!currentHeaders.length) return null;

      let closest = currentHeaders[0];
      let closestDistance = Number.POSITIVE_INFINITY;

      currentHeaders.forEach((header) => {
        const rect = header.getBoundingClientRect();
        const center = rect.left + rect.width / 2;
        const distance = Math.abs(clientX - center);
        if (distance < closestDistance) {
          closest = header;
          closestDistance = distance;
        }
      });

      return closest;
    }

    function getHeaderFromPoint(clientX, clientY) {
      const element = document.elementFromPoint(clientX, clientY);
      if (!element) return null;
      return element.closest && element.closest('th[data-col]');
    }

    function endDrag(commit) {
      if (!dragSession) return;
      const { handle, pointerId } = dragSession;
      if (pointerId != null && handle && handle.releasePointerCapture) {
        try {
          handle.releasePointerCapture(pointerId);
        } catch (err) {}
      }
      dragSession = null;
      document.body.style.cursor = '';
      clearDragTargets();
      if (!commit) return;
    }

    function moveColumn(sourceKey, targetKey) {
      if (!sourceKey || !targetKey || sourceKey === targetKey) return false;
      const order = getHeaders(table).map((header) => header.dataset.col);
      const fromIndex = order.indexOf(sourceKey);
      const toIndex = order.indexOf(targetKey);
      if (fromIndex < 0 || toIndex < 0) return false;
      order.splice(toIndex, 0, order.splice(fromIndex, 1)[0]);
      applyOrder(table, order);
      applyWidths(table, state);
      saveOrder(table, state, key, order);
      return true;
    }

    const decorate = () => {
      getHeaders(table).forEach((th) => {
        if (th.dataset.gridDecorated === '1') return;
        th.dataset.gridDecorated = '1';
        th.draggable = false;

        const drag = document.createElement('span');
        drag.className = 'grid-handle';
        drag.title = 'Move column';
        drag.setAttribute('aria-hidden', 'true');
        drag.addEventListener('pointerdown', (event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.stopPropagation();
          const sourceKey = th.dataset.col || '';
          dragSession = {
            source: th,
            handle: drag,
            sourceKey,
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            dragging: false,
            target: null,
          };
          document.body.style.cursor = 'grabbing';
          if (drag.setPointerCapture) {
            try {
              drag.setPointerCapture(event.pointerId);
            } catch (err) {}
          }
        });
        drag.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
        });

        const resize = document.createElement('span');
        resize.className = 'grid-resizer';
        resize.title = 'Resize column';
        resize.setAttribute('aria-hidden', 'true');
        resize.addEventListener('pointerdown', (event) => {
          event.preventDefault();
          event.stopPropagation();
          const colKey = th.dataset.col || '';
          const startX = event.clientX;
          const startWidth = th.getBoundingClientRect().width;
          resizeActive = true;
          document.body.style.cursor = 'col-resize';

          const onMove = (moveEvent) => {
            if (!resizeActive) return;
            const nextWidth = startWidth + (moveEvent.clientX - startX);
            saveWidth(table, state, key, colKey, nextWidth);
            applyWidths(table, state);
          };

          const onUp = () => {
            resizeActive = false;
            document.body.style.cursor = '';
            document.removeEventListener('pointermove', onMove);
            document.removeEventListener('pointerup', onUp);
          };

          document.addEventListener('pointermove', onMove);
          document.addEventListener('pointerup', onUp, { once: true });
        });

        th.insertBefore(drag, th.firstChild);
        th.appendChild(resize);
      });
    };

    decorate();

    document.addEventListener('pointermove', (event) => {
      if (!dragSession) return;
      const distance = Math.abs(event.clientX - dragSession.startX) + Math.abs(event.clientY - dragSession.startY);
      if (!dragSession.dragging && distance < 6) return;
      dragSession.dragging = true;
      event.preventDefault();

      let target = getHeaderFromPoint(event.clientX, event.clientY);
      if (!target || target === dragSession.source) {
        target = getClosestHeader(event.clientX);
        if (target === dragSession.source) target = null;
      }

      clearDragTargets();
      if (target) {
        dragSession.target = target;
        target.classList.add('grid-drag-over');
      } else {
        dragSession.target = null;
      }
    });

    document.addEventListener('pointerup', (event) => {
      if (!dragSession) return;
      const { source: sourceHeader, sourceKey, dragging, target } = dragSession;
      const finalTarget = target || getHeaderFromPoint(event.clientX, event.clientY) || getClosestHeader(event.clientX);
      const targetKey = finalTarget && finalTarget !== sourceHeader ? finalTarget.dataset.col || '' : '';
      const moved = dragging && targetKey ? moveColumn(sourceKey, targetKey) : false;
      endDrag(moved);
    });

    document.addEventListener('pointercancel', () => {
      endDrag(false);
    });

    window.addEventListener('resize', () => {
      if (!state.order || !state.order.length) return;
      applyWidths(table, state);
    }, { passive: true });
  }

  function init() {
    document.querySelectorAll('table.table-grid').forEach((table, idx) => initTable(table, idx));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
