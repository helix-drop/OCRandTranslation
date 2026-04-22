function createInitialStreamDraftState() {
  return {
    active: false,
    mode: 'page',
    bp: null,
    unitIdx: null,
    unitId: '',
    unitKind: '',
    unitLabel: '',
    unitPages: '',
    unitError: '',
    unitItems: [],
    paraIdx: null,
    paraTotal: 0,
    paraDone: 0,
    parallelLimit: 0,
    activeParaIndices: [],
    paragraphStates: [],
    paragraphErrors: [],
    paragraphs: [],
    status: 'idle',
    note: '流式翻译开始后，这里会显示当前页正在生成的中文草稿。',
    updatedAt: 0,
    lastError: '',
    restored: false,
  };
}

var BOOTSTRAP = window.READING_BOOTSTRAP || {};
var ROUTES = BOOTSTRAP.routes || {};
var INITIAL_TASK_SNAPSHOT = BOOTSTRAP.taskSnapshot || {};
var INITIAL_READING_VIEW_STATE = BOOTSTRAP.readingViewState || {};
var PAGE_DIMENSIONS = BOOTSTRAP.pageDimensions || {};

var store = {
  reading: {
    currentBp: Number(BOOTSTRAP.currentBp || 0),
    pdfBp: Number(BOOTSTRAP.currentBp || 0),
    manualNavigationTargetBp: null,
    autoStart: String(BOOTSTRAP.autoStart || '0'),
    startBp: String(BOOTSTRAP.startBp || ''),
  },
  readingView: {
    mode: String(BOOTSTRAP.currentView || 'standard'),
    translatedBps: (Array.isArray(INITIAL_READING_VIEW_STATE.translated_bps) ? INITIAL_READING_VIEW_STATE.translated_bps : (BOOTSTRAP.translatedBps || [])).map(function(bp) { return Number(bp); }),
    partialFailedBps: (Array.isArray(INITIAL_READING_VIEW_STATE.partial_failed_bps) ? INITIAL_READING_VIEW_STATE.partial_failed_bps : (BOOTSTRAP.partialFailedBps || [])).map(function(bp) { return Number(bp); }),
    failedBps: (Array.isArray(INITIAL_READING_VIEW_STATE.failed_bps) ? INITIAL_READING_VIEW_STATE.failed_bps : (BOOTSTRAP.failedBps || [])).map(function(bp) { return Number(bp); }),
    sourceOnlyBps: (INITIAL_READING_VIEW_STATE.source_only_bps || []).map(function(bp) { return Number(bp); }),
    allBps: (BOOTSTRAP.pageBps || []).map(function(bp) { return Number(bp); }),
    readingStatsDonePages: Number(INITIAL_READING_VIEW_STATE.reading_stats_done_pages || 0),
  },
  pages: null,
  taskSession: {
    snapshot: INITIAL_TASK_SNAPSHOT,
  },
  pageEditor: {
    open: false,
    loading: false,
    saving: false,
    historyOpen: false,
    historyLoaded: false,
    view: 'standard',
    page: null,
    rows: [],
    history: [],
  },
  streamDraft: createInitialStreamDraftState(),
  guards: {
    pendingCommittedRefreshBp: null,
    committedRefreshInFlight: false,
    manualNavigationInFlight: false,
  },
  ui: {
    showOriginal: !!BOOTSTRAP.showOriginal,
    pdfVisible: !!BOOTSTRAP.pdfVisible,
    pdfZoom: 1,
    pdfPanelMode: 'balanced',
    taskDetailsOpen: !!BOOTSTRAP.taskDetailsOpen,
  },
};
store.pages = store.readingView;

var TOC_OFFSET = Number(BOOTSTRAP.tocOffset || 0);
var pageMap = BOOTSTRAP.pageMap || {};
var pdfPageMetrics = PAGE_DIMENSIONS;
var VIRTUAL_WINDOW_RADIUS = Number(BOOTSTRAP.pdfVirtualWindowRadius || 0);
var VIRTUAL_SCROLL_MIN_PAGES = Number(BOOTSTRAP.pdfVirtualScrollMinPages || 0);
var initialTranslateSnapshot = INITIAL_TASK_SNAPSHOT;
var readingPageBpFallback = Number(BOOTSTRAP.currentPageFallbackBp || BOOTSTRAP.currentBp || 0);
var translateSessionActivated = !!BOOTSTRAP.showInitialTaskSnapshot;
var lastUsageSnapshot = INITIAL_TASK_SNAPSHOT;
var currentPageHasEntry = !!BOOTSTRAP.hasCurrentEntry;
var currentDocId = String(BOOTSTRAP.currentDocId || '');
var currentModelTarget = String(BOOTSTRAP.currentModelTarget || '');

function formatPdfPageLabel(bp) {
  var value = Number(bp || 0);
  return value ? ('PDF 第' + value + '页') : 'PDF 页';
}

function isFnmTaskState(state) {
  return String((state && state.task && state.task.kind) || '') === 'fnm';
}

function isFnmDraftMode(draft, state) {
  return String((draft && draft.mode) || '') === 'fnm_unit' || isFnmTaskState(state || lastUsageSnapshot || {});
}

function formatFnmUnitIndex(unitIdx) {
  var value = Number(unitIdx || 0);
  return value ? ('Unit #' + value) : 'Unit';
}

function formatTaskPositionLabel(state, pos) {
  if (isFnmTaskState(state)) {
    return formatFnmUnitIndex(pos);
  }
  return formatPdfPageLabel(pos);
}

function dispatch(action, payload) {
  function ensureDraftBuffers(total) {
    var size = Math.max(0, Number(total || 0));
    if (!store.streamDraft.paragraphs.length && size > 0) {
      store.streamDraft.paragraphs = Array(size).fill('');
    }
    if (!store.streamDraft.paragraphStates.length && size > 0) {
      store.streamDraft.paragraphStates = Array(size).fill('pending');
    }
    if (!store.streamDraft.paragraphErrors.length && size > 0) {
      store.streamDraft.paragraphErrors = Array(size).fill('');
    }
  }
  if (action === 'set_reading_bp') {
    var nextBp = Number(payload && payload.bp || 0);
    if (nextBp) {
      store.reading.currentBp = nextBp;
    }
    return;
  }
  if (action === 'set_pdf_bp') {
    var nextPdfBp = Number(payload && payload.bp || 0);
    if (nextPdfBp) {
      store.reading.pdfBp = nextPdfBp;
    }
    return;
  }
  if (action === 'set_manual_navigation_target') {
    var targetBp = Number(payload && payload.bp || 0);
    store.reading.manualNavigationTargetBp = targetBp || null;
    return;
  }
  if (action === 'set_auto_start') {
    store.reading.autoStart = String(payload && payload.value || '0');
    return;
  }
  if (action === 'set_start_bp') {
    store.reading.startBp = payload && payload.bp ? String(payload.bp) : '';
    return;
  }
  if (action === 'set_manual_navigation_in_flight') {
    store.guards.manualNavigationInFlight = !!(payload && payload.value);
    return;
  }
  if (action === 'set_pending_committed_refresh_bp') {
    var pendingBp = Number(payload && payload.bp || 0);
    store.guards.pendingCommittedRefreshBp = pendingBp || null;
    return;
  }
  if (action === 'set_committed_refresh_in_flight') {
    store.guards.committedRefreshInFlight = !!(payload && payload.value);
    return;
  }
  if (action === 'replace_stream_draft') {
    store.streamDraft = payload && payload.draft ? payload.draft : createInitialStreamDraftState();
    return;
  }
  if (action === 'set_pages_from_snapshot') {
    if (payload && Array.isArray(payload.translatedBps)) {
      store.pages.translatedBps = payload.translatedBps.map(function(bp) { return Number(bp); });
    }
    if (payload && Array.isArray(payload.failedBps)) {
      store.pages.failedBps = payload.failedBps.map(function(bp) { return Number(bp); });
    }
    if (payload && Array.isArray(payload.partialFailedBps)) {
      store.pages.partialFailedBps = payload.partialFailedBps.map(function(bp) { return Number(bp); });
    }
    return;
  }
  if (action === 'mark_page_done') {
    var doneBp = Number(payload && payload.bp || 0);
    if (!doneBp) return;
    store.pages.failedBps = store.pages.failedBps.filter(function(bp) { return bp !== doneBp; });
    store.pages.partialFailedBps = store.pages.partialFailedBps.filter(function(bp) { return bp !== doneBp; });
    if (payload && payload.partialFailed) {
      store.pages.partialFailedBps.push(doneBp);
      store.pages.partialFailedBps.sort(function(a, b) { return a - b; });
    }
    if (store.pages.translatedBps.indexOf(doneBp) < 0) {
      store.pages.translatedBps.push(doneBp);
      store.pages.translatedBps.sort(function(a, b) { return a - b; });
    }
    return;
  }
  if (action === 'mark_pages_done') {
    var donePages = payload && Array.isArray(payload.bps) ? payload.bps : [];
    donePages.forEach(function(rawBp) {
      var pageBp = Number(rawBp || 0);
      if (!pageBp) return;
      store.pages.failedBps = store.pages.failedBps.filter(function(bp) { return bp !== pageBp; });
      store.pages.partialFailedBps = store.pages.partialFailedBps.filter(function(bp) { return bp !== pageBp; });
      if (store.pages.translatedBps.indexOf(pageBp) < 0) {
        store.pages.translatedBps.push(pageBp);
      }
    });
    store.pages.translatedBps.sort(function(a, b) { return a - b; });
    return;
  }
  if (action === 'mark_page_error') {
    var errBp = Number(payload && payload.bp || 0);
    if (!errBp) return;
    if (store.pages.failedBps.indexOf(errBp) < 0) {
      store.pages.failedBps.push(errBp);
      store.pages.failedBps.sort(function(a, b) { return a - b; });
    }
    return;
  }
  if (action === 'stream_page_init') {
    var init = payload && payload.data ? payload.data : {};
    var isFnmTask = isFnmTaskState(lastUsageSnapshot || {});
    var initDraft = createInitialStreamDraftState();
    initDraft.active = true;
    initDraft.status = 'streaming';
    initDraft.mode = isFnmTask ? 'fnm_unit' : 'page';
    initDraft.bp = init.bp || null;
    initDraft.unitIdx = isFnmTask ? Number((store.streamDraft.unitIdx || (lastUsageSnapshot && lastUsageSnapshot.current_unit_idx) || init.bp || 0)) || null : null;
    initDraft.unitId = isFnmTask ? (store.streamDraft.unitId || (lastUsageSnapshot && lastUsageSnapshot.current_unit_id) || '') : '';
    initDraft.unitKind = isFnmTask ? (store.streamDraft.unitKind || (lastUsageSnapshot && lastUsageSnapshot.current_unit_kind) || '') : '';
    initDraft.unitLabel = isFnmTask ? (store.streamDraft.unitLabel || (lastUsageSnapshot && lastUsageSnapshot.current_unit_label) || '') : '';
    initDraft.unitPages = isFnmTask ? (store.streamDraft.unitPages || (lastUsageSnapshot && lastUsageSnapshot.current_unit_pages) || '') : '';
    initDraft.unitItems = isFnmTask && Array.isArray(lastUsageSnapshot && lastUsageSnapshot.unit_items)
      ? lastUsageSnapshot.unit_items.slice()
      : [];
    initDraft.paraIdx = 0;
    initDraft.paraTotal = Number(init.para_total || 0);
    initDraft.parallelLimit = Number(init.parallel_limit || 0);
    initDraft.paragraphStates = Array(initDraft.paraTotal).fill('pending');
    initDraft.paragraphErrors = Array(initDraft.paraTotal).fill('');
    initDraft.paragraphs = Array(initDraft.paraTotal).fill('');
    initDraft.note = isFnmTask
      ? '当前 unit 正在流式翻译，完整结束后才会提交到硬盘。'
      : '当前页正在流式翻译，完整结束后才会写入硬盘。';
    initDraft.updatedAt = Math.floor(Date.now() / 1000);
    dispatch('replace_stream_draft', { draft: initDraft });
    return;
  }
  if (action === 'stream_para_start') {
    var ps = payload && payload.data ? payload.data : {};
    store.streamDraft.active = true;
    store.streamDraft.status = 'streaming';
    store.streamDraft.bp = ps.bp || store.streamDraft.bp;
    store.streamDraft.paraIdx = ps.para_idx;
    ensureDraftBuffers(store.streamDraft.paraTotal);
    if (store.streamDraft.activeParaIndices.indexOf(Number(ps.para_idx)) < 0) {
      store.streamDraft.activeParaIndices.push(Number(ps.para_idx));
      store.streamDraft.activeParaIndices.sort(function(a, b) { return a - b; });
    }
    store.streamDraft.paragraphStates[ps.para_idx] = 'running';
    store.streamDraft.paragraphErrors[ps.para_idx] = '';
    store.streamDraft.updatedAt = Math.floor(Date.now() / 1000);
    store.streamDraft.restored = false;
    return;
  }
  if (action === 'stream_para_delta') {
    var pd = payload && payload.data ? payload.data : {};
    store.streamDraft.active = true;
    store.streamDraft.status = 'streaming';
    store.streamDraft.bp = pd.bp || store.streamDraft.bp;
    store.streamDraft.paraIdx = pd.para_idx;
    store.streamDraft.updatedAt = Math.floor(Date.now() / 1000);
    ensureDraftBuffers(store.streamDraft.paraTotal);
    if (store.streamDraft.activeParaIndices.indexOf(Number(pd.para_idx)) < 0) {
      store.streamDraft.activeParaIndices.push(Number(pd.para_idx));
      store.streamDraft.activeParaIndices.sort(function(a, b) { return a - b; });
    }
    store.streamDraft.paragraphStates[pd.para_idx] = 'running';
    store.streamDraft.paragraphs[pd.para_idx] = pd.translation_so_far || '';
    store.streamDraft.paragraphErrors[pd.para_idx] = '';
    store.streamDraft.note = '当前页尚未提交到硬盘；停止后会丢弃这一页草稿。';
    store.streamDraft.restored = false;
    return;
  }
  if (action === 'stream_para_done') {
    var done = payload && payload.data ? payload.data : {};
    store.streamDraft.active = true;
    store.streamDraft.status = 'streaming';
    store.streamDraft.bp = done.bp || store.streamDraft.bp;
    store.streamDraft.paraIdx = done.para_idx;
    store.streamDraft.paraDone = Math.max(store.streamDraft.paraDone || 0, Number(done.para_idx || 0) + 1);
    ensureDraftBuffers(store.streamDraft.paraTotal);
    store.streamDraft.activeParaIndices = store.streamDraft.activeParaIndices.filter(function(idx) { return idx !== Number(done.para_idx); });
    store.streamDraft.paragraphStates[done.para_idx] = 'done';
    store.streamDraft.paragraphs[done.para_idx] = done.translation || store.streamDraft.paragraphs[done.para_idx] || '';
    store.streamDraft.paragraphErrors[done.para_idx] = '';
    store.streamDraft.note = '该段已完成，正在继续翻译后续段落。';
    store.streamDraft.updatedAt = Math.floor(Date.now() / 1000);
    store.streamDraft.lastError = '';
    store.streamDraft.restored = false;
    return;
  }
  if (action === 'stream_para_error') {
    var pe = payload && payload.data ? payload.data : {};
    store.streamDraft.active = true;
    store.streamDraft.status = 'streaming';
    store.streamDraft.bp = pe.bp || store.streamDraft.bp;
    store.streamDraft.paraIdx = pe.para_idx;
    store.streamDraft.paraDone = Math.max(store.streamDraft.paraDone || 0, Number(pe.para_idx || 0) + 1);
    ensureDraftBuffers(store.streamDraft.paraTotal);
    store.streamDraft.activeParaIndices = store.streamDraft.activeParaIndices.filter(function(idx) { return idx !== Number(pe.para_idx); });
    store.streamDraft.paragraphStates[pe.para_idx] = 'error';
    store.streamDraft.paragraphs[pe.para_idx] = pe.translation || store.streamDraft.paragraphs[pe.para_idx] || '';
    store.streamDraft.paragraphErrors[pe.para_idx] = pe.error || '';
    store.streamDraft.note = '该段翻译失败，已记录失败占位文本。';
    store.streamDraft.updatedAt = Math.floor(Date.now() / 1000);
    store.streamDraft.lastError = pe.error || '';
    store.streamDraft.restored = false;
    return;
  }
  if (action === 'stream_page_aborted') {
    var aborted = payload && payload.data ? payload.data : {};
    store.streamDraft.active = false;
    store.streamDraft.status = 'aborted';
    store.streamDraft.bp = aborted.bp || store.streamDraft.bp;
    store.streamDraft.paraIdx = aborted.para_idx;
    store.streamDraft.activeParaIndices = [];
    store.streamDraft.note = '当前页已停止，草稿未提交到硬盘。点击“继续翻译”会从这一页重新开始。';
    store.streamDraft.updatedAt = Math.floor(Date.now() / 1000);
    store.streamDraft.restored = false;
    return;
  }
  if (action === 'rate_limit_wait') {
    var wait = payload && payload.data ? payload.data : {};
    var waitIsFnm = isFnmTaskState(lastUsageSnapshot || {});
    var waitDraft = createInitialStreamDraftState();
    waitDraft.active = false;
    waitDraft.status = 'throttled';
    waitDraft.mode = waitIsFnm ? 'fnm_unit' : 'page';
    waitDraft.bp = Number(wait.bp || 0) || null;
    waitDraft.unitIdx = waitIsFnm ? Number((store.streamDraft.unitIdx || (lastUsageSnapshot && lastUsageSnapshot.current_unit_idx) || wait.bp || 0)) || null : null;
    waitDraft.unitId = waitIsFnm ? (store.streamDraft.unitId || (lastUsageSnapshot && lastUsageSnapshot.current_unit_id) || '') : '';
    waitDraft.unitKind = waitIsFnm ? (store.streamDraft.unitKind || (lastUsageSnapshot && lastUsageSnapshot.current_unit_kind) || '') : '';
    waitDraft.unitLabel = waitIsFnm ? (store.streamDraft.unitLabel || (lastUsageSnapshot && lastUsageSnapshot.current_unit_label) || '') : '';
    waitDraft.unitPages = waitIsFnm ? (store.streamDraft.unitPages || (lastUsageSnapshot && lastUsageSnapshot.current_unit_pages) || '') : '';
    waitDraft.unitItems = waitIsFnm && Array.isArray(lastUsageSnapshot && lastUsageSnapshot.unit_items)
      ? lastUsageSnapshot.unit_items.slice()
      : [];
    waitDraft.paraIdx = null;
    waitDraft.paraTotal = Number(wait.para_total || 0);
    waitDraft.paraDone = Number(wait.para_done || 0);
    waitDraft.parallelLimit = Number(wait.parallel_limit || 0);
    waitDraft.note = wait.message || ('触发限流，等待 ' + Number(wait.wait_seconds || 0) + ' 秒后自动重试。');
    waitDraft.lastError = '';
    waitDraft.updatedAt = Math.floor(Date.now() / 1000);
    waitDraft.restored = false;
    dispatch('replace_stream_draft', { draft: waitDraft });
    return;
  }
  if (action === 'stream_page_done') {
    var donePage = payload && payload.data ? payload.data : {};
    var hasDraftError = !!donePage.partial_failed || (
      Array.isArray(store.streamDraft.paragraphStates)
      && store.streamDraft.paragraphStates.some(function(state) { return state === 'error'; })
    );
    store.streamDraft.active = false;
    store.streamDraft.status = 'done';
    store.streamDraft.bp = donePage.bp || store.streamDraft.bp;
    store.streamDraft.paraDone = store.streamDraft.paraTotal;
    store.streamDraft.activeParaIndices = [];
    store.streamDraft.note = hasDraftError ? '当前页已完成，但仍有失败段，可直接重译本页。' : '当前页已完成并写入硬盘。';
    store.streamDraft.updatedAt = Math.floor(Date.now() / 1000);
    store.streamDraft.restored = false;
    return;
  }
  if (action === 'toggle_pdf_panel') {
    store.ui.pdfVisible = !store.ui.pdfVisible;
    return;
  }
  if (action === 'set_pdf_zoom') {
    var nextZoom = Number(payload && payload.value || 1);
    if (nextZoom < 1) nextZoom = 1;
    if (nextZoom > 2.4) nextZoom = 2.4;
    store.ui.pdfZoom = Math.round(nextZoom * 100) / 100;
    return;
  }
  if (action === 'cycle_pdf_panel_mode') {
    var modes = ['compact', 'balanced', 'inspect'];
    var currentIdx = modes.indexOf(store.ui.pdfPanelMode);
    store.ui.pdfPanelMode = modes[(currentIdx + 1 + modes.length) % modes.length];
    return;
  }
  if (action === 'toggle_original') {
    store.ui.showOriginal = !store.ui.showOriginal;
    return;
  }
  if (action === 'set_task_details_open') {
    store.ui.taskDetailsOpen = !!(payload && payload.value);
    return;
  }
  if (action === 'toggle_task_details') {
    store.ui.taskDetailsOpen = !store.ui.taskDetailsOpen;
    return;
  }
  if (action === 'navigate') {
    var nextNavBp = Number(payload && payload.bp || 0);
    var source = payload && payload.source ? payload.source : 'internal';
    if (!nextNavBp) return;
    dispatch('set_reading_bp', { bp: nextNavBp });
    if (source !== 'pdf') {
      dispatch('set_pdf_bp', { bp: nextNavBp });
    }
    if (source === 'manual') {
      dispatch('set_manual_navigation_in_flight', { value: true });
      dispatch('set_manual_navigation_target', { bp: nextNavBp });
      dispatch('set_pending_committed_refresh_bp', { bp: null });
      dispatch('set_committed_refresh_in_flight', { value: false });
    }
  }
}

function toggleOriginal() {
  dispatch('toggle_original');
  applyOriginalVisibilityState();
  syncReadingUrl();
}

function applyOriginalVisibilityState() {
  document.body.classList.toggle('hide-original', !store.ui.showOriginal);
  var btn = document.getElementById('origBtn');
  if (btn) {
    btn.classList.toggle('active', store.ui.showOriginal);
    btn.style.opacity = store.ui.showOriginal ? '1' : '0.5';
    btn.title = store.ui.showOriginal ? '隐藏原文' : '显示原文';
  }
}

// ===== TOC Navigation =====
function toggleTocMenu() {
  var menu = document.getElementById('tocMenu');
  if (menu) {
    menu.classList.toggle('open');
  }
}

function tocJumpToPage(targetPage) {
  var targetBp = Number(targetPage || 0);
  if (targetBp) {
    document.getElementById('tocMenu').classList.remove('open');
    goReadingPage(targetBp);
  }
}

function tocUpdateCurrentChapter() {
  var items = document.querySelectorAll('.toc-item');
  var activeItem = null;
  items.forEach(function(item) {
    item.classList.remove('toc-active');
    var targetPage = Number(item.dataset.targetPage || 0);
    if (targetPage && targetPage <= Number(store.reading.currentBp || 0)) { activeItem = item; }
  });
  if (activeItem) {
    activeItem.classList.add('toc-active');
    // 若下拉已打开则滚动到高亮项
    var dd = document.getElementById('tocDropdown');
    if (dd && document.getElementById('tocMenu').classList.contains('open')) {
      activeItem.scrollIntoView({block: 'nearest'});
    }
  }
}
tocUpdateCurrentChapter();

function tocSaveOffset() {
  var raw = document.getElementById('tocOffsetReadingInput').value;
  var newOffset = parseInt(raw, 10);
  var msgEl = document.getElementById('tocOffsetReadingMsg');
  if (String(raw || '').trim() === '' || isNaN(newOffset)) {
    msgEl.style.display = '';
    msgEl.textContent = '请输入整数 offset，可为负数';
    msgEl.style.color = 'var(--red)';
    return;
  }
  fetch(ROUTES.tocSetOffset + '?doc_id=' + encodeURIComponent(currentDocId), {
    method: 'POST',
    headers: Object.assign({'Content-Type': 'application/json'}, withCsrfHeaders()),
    body: JSON.stringify({ offset: newOffset })
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      msgEl.style.display = '';
      if (d.ok) {
        TOC_OFFSET = newOffset;
        tocUpdateCurrentChapter();
        msgEl.textContent = '已保存';
        msgEl.style.color = 'var(--grn)';
        setTimeout(function() { msgEl.style.display = 'none'; }, 2000);
      } else {
        msgEl.textContent = d.error || '保存失败';
        msgEl.style.color = 'var(--red)';
      }
    })
    .catch(function(err) {
      msgEl.style.display = '';
      msgEl.textContent = '失败：' + err;
      msgEl.style.color = 'var(--red)';
    });
}

function tocResolveVisualItem(itemId) {
  var input = document.getElementById('tocResolveInput-' + itemId);
  var msgEl = document.getElementById('tocResolveMsg-' + itemId);
  var pdfPage = parseInt((input && input.value) || '', 10);
  if (!msgEl) return;
  if (isNaN(pdfPage) || pdfPage < 1) {
    msgEl.style.display = '';
    msgEl.textContent = '请输入 ≥ 1 的 PDF 页码';
    msgEl.style.color = 'var(--red)';
    return;
  }
  fetch(ROUTES.tocResolveVisualItem + '?doc_id=' + encodeURIComponent(currentDocId), {
    method: 'POST',
    headers: Object.assign({'Content-Type': 'application/json'}, withCsrfHeaders()),
    body: JSON.stringify({ item_id: itemId, pdf_page: pdfPage })
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      msgEl.style.display = '';
      if (d.ok) {
        msgEl.textContent = '已保存';
        msgEl.style.color = 'var(--grn)';
        setTimeout(function() { window.location.reload(); }, 400);
      } else {
        msgEl.textContent = d.error || '保存失败';
        msgEl.style.color = 'var(--red)';
      }
    })
    .catch(function(err) {
      msgEl.style.display = '';
      msgEl.textContent = '失败：' + err;
      msgEl.style.color = 'var(--red)';
    });
}

// ===== PDF Preview Panel (图片模式) =====
var pdfScrollObserver = null;
var virtualPdfState = {
  enabled: false,
  initialized: false,
};
var observerNavigateTimer = null;
var pendingObserverBp = null;
var OBSERVER_NAV_DEBOUNCE_MS = 180;
var OBSERVER_NAV_SUPPRESS_MS = 420;
var observerNavigationSuppressUntil = 0;
var currentHighlightState = {
  active: false,
  paraIdx: null,
  bboxes: [],
  targetBp: null,
};

function suppressObserverNavigation(ms) {
  var holdMs = Number(ms || OBSERVER_NAV_SUPPRESS_MS);
  if (holdMs < 0) holdMs = 0;
  observerNavigationSuppressUntil = Date.now() + holdMs;
  pendingObserverBp = null;
  clearTimeout(observerNavigateTimer);
}

function isObserverNavigationSuppressed() {
  return Date.now() < observerNavigationSuppressUntil;
}
