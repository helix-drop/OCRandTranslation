var pageNavRenderSignature = '';
var pageNavButtonLabel = '';

function submitPostAction(url, fields) {
  var form = document.createElement('form');
  form.method = 'POST';
  form.action = url;
  var csrfInput = document.createElement('input');
  csrfInput.type = 'hidden';
  csrfInput.name = '_csrf_token';
  csrfInput.value = getCsrfToken();
  form.appendChild(csrfInput);
  Object.keys(fields || {}).forEach(function(key) {
    var value = fields[key];
    if (value === undefined || value === null || value === '') return;
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = key;
    input.value = String(value);
    form.appendChild(input);
  });
  document.body.appendChild(form);
  form.submit();
}

function setCurrentReadingBp(bp) {
  dispatch('set_reading_bp', { bp: bp });
}

function setCurrentPdfBp(bp) {
  dispatch('set_pdf_bp', { bp: bp });
}

function setManualNavigationTargetBp(bp) {
  dispatch('set_manual_navigation_target', { bp: bp });
}

function setReadingAutoStart(value) {
  dispatch('set_auto_start', { value: value });
}

function setReadingStartBp(bp) {
  dispatch('set_start_bp', { bp: bp });
}

function getVisiblePdfBp() {
  return Number(store.reading.pdfBp || 0) || null;
}

function setVisiblePdfBp(bp, source) {
  var nextBp = Number(bp || 0);
  if (!nextBp) return null;
  if (source === 'observer') {
    if (isObserverNavigationSuppressed() || store.guards.manualNavigationInFlight) {
      return null;
    }
    pendingObserverBp = nextBp;
    setCurrentPdfBp(nextBp);
    clearTimeout(observerNavigateTimer);
    observerNavigateTimer = setTimeout(function() {
      if (!pendingObserverBp) return;
      dispatch('navigate', { bp: pendingObserverBp, source: 'observer' });
      renderPageNavigationState();
    }, OBSERVER_NAV_DEBOUNCE_MS);
  } else {
    pendingObserverBp = null;
    clearTimeout(observerNavigateTimer);
    setCurrentPdfBp(nextBp);
  }
  updatePdfVirtualWindow(nextBp);
  updatePdfPageInfo(nextBp);
  return source || 'internal';
}

function syncReadingBpFromPdf(source) {
  var visibleBp = getVisiblePdfBp();
  if (!visibleBp || source === 'reading') return;
  dispatch('navigate', { bp: visibleBp, source: source || 'observer' });
}

function syncPdfBpFromReading(source) {
  if (source === 'pdf') return;
  alignPdfToReading({
    bp: store.reading.currentBp,
    source: source || 'reading',
    behavior: 'auto',
    forceScroll: true,
    suppressMs: OBSERVER_NAV_SUPPRESS_MS,
  });
}

function setupPdfScrollObserver() {
  if (pdfScrollObserver || typeof IntersectionObserver === 'undefined') return;
  var container = document.getElementById('pdfScrollContainer');
  if (!container) return;
  pdfScrollObserver = new IntersectionObserver(function(entries) {
    var bestEntry = null;
    entries.forEach(function(entry) {
      if (!entry.isIntersecting) return;
      if (!bestEntry || entry.intersectionRatio > bestEntry.intersectionRatio) {
        bestEntry = entry;
      }
    });
    if (!bestEntry) return;
    var bp = Number(bestEntry.target.getAttribute('data-pdf-bp') || 0);
    if (!bp) return;
    setVisiblePdfBp(bp, 'observer');
  }, {
    root: container,
    threshold: [0.35, 0.6, 0.85],
  });
  container.querySelectorAll('.pdf-page-item[data-pdf-bp]').forEach(function(el) {
    pdfScrollObserver.observe(el);
  });
}

function applyPdfPagePlaceholders(options) {
  var opts = options || {};
  var container = document.getElementById('pdfScrollContainer');
  if (!container) return;
  container.querySelectorAll('.pdf-page-item[data-pdf-bp]').forEach(function(el) {
    var bp = Number(el.getAttribute('data-pdf-bp') || 0);
    var metrics = pdfPageMetrics[String(bp)] || {};
    var pageImgW = Number(metrics.imgW || 0);
    var pageImgH = Number(metrics.imgH || 0);
    var targetWidth = getPdfItemWidth(container, pageImgW, pageImgH);
    el.style.width = targetWidth + 'px';
    el.style.minWidth = targetWidth + 'px';
    if (pageImgW > 0 && pageImgH > 0) {
      el.style.aspectRatio = pageImgW + ' / ' + pageImgH;
      var expectedHeight = Math.round(targetWidth * pageImgH / pageImgW);
      el.style.minHeight = Math.max(240, expectedHeight) + 'px';
    } else {
      el.style.minHeight = '420px';
    }
    var img = getPdfImageForItem(el);
    if (img && opts.syncImageSrc !== false) syncPdfImageSrc(el, img);
  });
}

function getPdfItemWidth(container, pageImgW, pageImgH) {
  var containerWidth = Math.max(280, (container && container.clientWidth) || 0);
  var zoom = Math.max(1, Number(store.ui.pdfZoom || 1));
  var usableWidth = Math.max(260, containerWidth - 24);
  if (pageImgW > 0 && pageImgH > 0) {
    var aspectRatio = pageImgW / Math.max(1, pageImgH);
    var preferredWidth = Math.round(usableWidth * zoom);
    if (aspectRatio > 0.92) {
      preferredWidth = Math.round(preferredWidth * 0.94);
    }
    return Math.max(260, preferredWidth);
  }
  return Math.max(260, Math.round(usableWidth * zoom));
}

function pageStateLabel(bp) {
  bp = Number(bp);
  if (store.readingView.mode === 'fnm') {
    return store.pages.translatedBps.indexOf(bp) >= 0 ? '已投影' : '仅 source';
  }
  if (String(store.streamDraft.mode || '') !== 'fnm_unit' && store.streamDraft.bp === bp && (store.streamDraft.status === 'streaming' || store.streamDraft.status === 'aborted' || store.streamDraft.status === 'error')) {
    if (store.streamDraft.status === 'aborted') return '已停止';
    if (store.streamDraft.status === 'error') return '失败';
    return '翻译中';
  }
  if (store.pages.failedBps.indexOf(bp) >= 0) return '失败';
  if (store.pages.partialFailedBps.indexOf(bp) >= 0) return '部分完成';
  return store.pages.translatedBps.indexOf(bp) >= 0 ? '已译' : '待译';
}

function getReadingUiStateParams() {
  return {
    usage: store.ui.taskDetailsOpen ? '1' : '0',
    orig: store.ui.showOriginal ? '1' : '0',
    pdf: store.ui.pdfVisible ? '1' : '0',
    view: store.readingView.mode === 'fnm' ? 'fnm' : '',
  };
}

function getReadingDocIdParam() {
  var raw = String(currentDocId || '').trim();
  if (!raw || raw === 'undefined' || raw === 'null' || raw === 'None') {
    return '';
  }
  return raw;
}

function requireReadingDocId(actionLabel, onMissing) {
  var docId = getReadingDocIdParam();
  if (docId) return docId;
  var message = (actionLabel || '当前操作') + '失败：未找到当前文档，请刷新页面后重试。';
  if (typeof onMissing === 'function') {
    onMissing(message);
  } else {
    alert(message);
  }
  return '';
}

function buildReadingUrl(bp, autoStart, startBp) {
  var url = new URL(ROUTES.reading || '/reading', window.location.origin);
  if (bp !== undefined && bp !== null && bp !== '') {
    url.searchParams.set('bp', bp);
  }
  var docId = getReadingDocIdParam();
  if (docId) {
    url.searchParams.set('doc_id', docId);
  }
  var uiParams = getReadingUiStateParams();
  url.searchParams.set('usage', uiParams.usage);
  url.searchParams.set('orig', uiParams.orig);
  url.searchParams.set('pdf', uiParams.pdf);
  if (uiParams.view === 'fnm') {
    url.searchParams.set('view', 'fnm');
  } else {
    url.searchParams.delete('view');
  }
  var curSearch = new URLSearchParams(window.location.search);
  var layoutParam = curSearch.get('layout');
  if (layoutParam === 'side' || layoutParam === 'stack') {
    url.searchParams.set('layout', layoutParam);
  }
  if (autoStart === '1') {
    url.searchParams.set('auto', '1');
  }
  if (startBp) {
    url.searchParams.set('start_bp', startBp);
  }
  return url.pathname + (url.search ? url.search : '');
}

function forceReloadReadingPage(bp) {
  if (store.guards.manualNavigationInFlight) return;
  var targetUrl = buildReadingUrl(bp, '0', '');
  var currentUrl = window.location.pathname + window.location.search;
  if (currentUrl === targetUrl) {
    window.location.reload();
    return;
  }
  window.location.replace(targetUrl);
}

function syncReadingUrl() {
  history.replaceState(null, '', buildReadingUrl(store.reading.currentBp, store.reading.autoStart, store.reading.startBp));
}

function handleReadingNavClick(event, bp) {
  if (event) event.preventDefault();
  goReadingPage(bp);
  return false;
}

function goReadingPage(bp) {
  bp = Number(bp || 0);
  if (!bp) return;
  pendingObserverBp = null;
  clearTimeout(observerNavigateTimer);
  if (bp === Number(store.reading.currentBp || 0)) {
    if (store.ui.pdfVisible) {
      pdfGoToBp(bp);
    }
    syncReadingUrl();
    return;
  }
  dispatch('navigate', { bp: bp, source: 'manual' });
  syncPdfBpFromReading('reading');
  window.location.href = buildReadingUrl(bp, '0', '');
}

function shouldRefreshCommittedCurrentPage(bp) {
  bp = Number(bp);
  return !!bp && bp === Number(store.reading.currentBp) && !currentPageHasEntry;
}

function scheduleCommittedPageRefresh(bp) {
  bp = Number(bp);
  if (store.guards.manualNavigationInFlight) return;
  if (!shouldRefreshCommittedCurrentPage(bp)) return;
  dispatch('set_pending_committed_refresh_bp', { bp: bp });
}

function maybeRefreshCommittedCurrentPage(state) {
  if (store.guards.manualNavigationInFlight) return;
  if (String((state && state.task && state.task.kind) || '') === 'fnm') return;
  var translatedFromState = Array.isArray(state && state.translated_bps)
    ? state.translated_bps.map(function(bp) { return Number(bp); })
    : [];
  var targetBp = Number(store.guards.pendingCommittedRefreshBp || 0);

  if (!targetBp && !currentPageHasEntry && translatedFromState.indexOf(Number(store.reading.currentBp)) >= 0) {
    targetBp = Number(store.reading.currentBp);
    dispatch('set_pending_committed_refresh_bp', { bp: targetBp });
  }
  if (!targetBp) return;

  if (!shouldRefreshCommittedCurrentPage(targetBp)) {
    if (currentPageHasEntry || Number(store.reading.currentBp) !== targetBp) {
      dispatch('set_pending_committed_refresh_bp', { bp: null });
      dispatch('set_committed_refresh_in_flight', { value: false });
    }
    return;
  }

  var translatedNow = store.pages.translatedBps.indexOf(targetBp) >= 0 || translatedFromState.indexOf(targetBp) >= 0;
  if (!translatedNow || store.guards.committedRefreshInFlight) return;

  dispatch('set_committed_refresh_in_flight', { value: true });
  dispatch('set_pending_committed_refresh_bp', { bp: null });
  forceReloadReadingPage(targetBp);
}


function renderPageNavigationState() {
  var navBtn = document.getElementById('pageNavBtn');
  if (navBtn) {
    var nextLabel = formatPdfPageLabel(store.reading.currentBp) + ' · ' + pageStateLabel(store.reading.currentBp);
    if (pageNavButtonLabel !== nextLabel) {
      navBtn.textContent = nextLabel;
      pageNavButtonLabel = nextLabel;
    }
  }

  var navList = document.getElementById('pageNavList');
  var navPanel = document.getElementById('pageNavPanel');
  if (navList && navPanel && !navPanel.classList.contains('hidden')) {
    var currentIndex = store.pages.allBps.indexOf(store.reading.currentBp);
    var start = Math.max(0, currentIndex - 4);
    var end = Math.min(store.pages.allBps.length, currentIndex + 5);
    var visible = store.pages.allBps.slice(start, end);
    var items = [];

    if (start > 0) {
      items.push(renderPageNavItem(store.pages.allBps[0]));
      if (start > 1) items.push('<div class="page-nav-ellipsis">…</div>');
    }
    visible.forEach(function(bp) {
      items.push(renderPageNavItem(bp));
    });
    if (end < store.pages.allBps.length) {
      if (end < store.pages.allBps.length - 1) items.push('<div class="page-nav-ellipsis">…</div>');
      items.push(renderPageNavItem(store.pages.allBps[store.pages.allBps.length - 1]));
    }
    var nextSignature = items.join('');
    if (pageNavRenderSignature !== nextSignature) {
      navList.innerHTML = nextSignature;
      pageNavRenderSignature = nextSignature;
    }
  }

  document.querySelectorAll('.progress-dot[data-page-bp]').forEach(function(dot) {
    var bp = Number(dot.getAttribute('data-page-bp'));
    dot.classList.remove('done', 'pending', 'streaming', 'failed');
    dot.title = formatPdfPageLabel(bp) + ' · ' + pageStateLabel(bp);
    if (bp === store.reading.currentBp) {
      return;
    }
    if (String(store.streamDraft.mode || '') !== 'fnm_unit' && store.streamDraft.bp === bp && store.streamDraft.status === 'streaming') {
      dot.classList.add('streaming');
    } else if (store.pages.failedBps.indexOf(bp) >= 0) {
      dot.classList.add('failed');
    } else if (store.pages.partialFailedBps.indexOf(bp) >= 0) {
      dot.classList.add('failed');
    } else if (store.pages.translatedBps.indexOf(bp) >= 0) {
      dot.classList.add('done');
    } else {
      dot.classList.add('pending');
    }
  });
}

function renderPageNavItem(bp) {
  bp = Number(bp);
  var cls = bp === store.reading.currentBp ? 'page-nav-item current' : 'page-nav-item';
  return '<a href="' + buildReadingUrl(bp, '0', '') + '" data-reading-bp="' + bp + '" onclick="return handleReadingNavClick(event, ' + bp + ');" class="' + cls + '">' +
    '<span>' + formatPdfPageLabel(bp) + '</span>' +
    '<span class="page-nav-item-status">' + pageStateLabel(bp) + '</span>' +
  '</a>';
}

function togglePageNav(forceOpen) {
  var panel = document.getElementById('pageNavPanel');
  if (!panel) return;
  var shouldOpen = typeof forceOpen === 'boolean' ? forceOpen : panel.classList.contains('hidden');
  panel.classList.toggle('hidden', !shouldOpen);
  if (shouldOpen) {
    pageNavRenderSignature = '';
    renderPageNavigationState();
    var input = document.getElementById('pageJumpInput');
    if (input) input.focus();
  }
}

function jumpToPageInput() {
  var input = document.getElementById('pageJumpInput');
  if (!input) return;
  var bp = Number(input.value || 0);
  if (!bp || store.pages.allBps.indexOf(bp) < 0) return;
  goReadingPage(bp);
}


function updateProgressStatsText(d) {
  var el = document.getElementById('readingProgressStats');
  if (!el) return;
  var current = Number(store.reading.currentBp || 0);
  var totalPdfPages = Number(store.pages.allBps.length || 0);
  if (store.readingView.mode === 'fnm') {
    var projectedPages = Array.isArray(store.pages.translatedBps) ? store.pages.translatedBps.length : 0;
    var doneUnits = Number(d && d.done_units || 0);
    var totalUnits = Number(d && d.total_units || 0);
    var failedUnits = Number(d && d.error_units || 0);
    var suffix = totalUnits ? '（任务共 ' + totalUnits + ' 个 unit）' : '';
    el.textContent = '已投影' + projectedPages + '页 · 已完成' + doneUnits + '个 unit · 失败' + failedUnits + '个 unit · 当前 PDF 第' + current + '页 / 第' + totalPdfPages + '页' + suffix;
    return;
  }
  var doneForStats = Number(store.readingView.readingStatsDonePages || 0);
  var partial = Array.isArray(store.pages.partialFailedBps) ? store.pages.partialFailedBps.length : 0;
  var failed = Array.isArray(store.pages.failedBps) ? store.pages.failedBps.length : 0;
  el.textContent = '已译' + doneForStats + '页 · 部分完成' + partial + '页 · 失败' + failed + '页 · 当前 PDF 第' + current + '页 / 第' + totalPdfPages + '页';
}
