function togglePdfPanel() {
  var panel = document.getElementById('pdfPanel');
  if (!panel) return;

  dispatch('toggle_pdf_panel');
  applyPdfPanelVisibilityState();
  if (store.ui.pdfVisible) {
    initPdfVirtualScroll();
    applyPdfPagePlaceholders();
    setupPdfScrollObserver();
    alignPdfToReading({
      bp: store.reading.currentBp,
      source: 'reading',
      behavior: 'auto',
      forceScroll: true,
      suppressMs: OBSERVER_NAV_SUPPRESS_MS,
    });
  }
  syncReadingUrl();
}

function applyPdfPanelVisibilityState() {
  var panel = document.getElementById('pdfPanel');
  var toggleBtn = document.getElementById('pdfToggleBtn');
  var layout = document.getElementById('readingLayout');
  var btn = document.getElementById('pdfBtn');
  var modeBtn = document.getElementById('pdfPanelModeBtn');
  var resizer = document.getElementById('pdfResizer');
  if (!panel || !layout) return;
  panel.style.display = store.ui.pdfVisible ? '' : 'none';
  if (resizer) {
    resizer.style.display = store.ui.pdfVisible ? '' : 'none';
  }
  layout.classList.toggle('with-pdf', store.ui.pdfVisible);
  panel.setAttribute('data-panel-mode', store.ui.pdfPanelMode);
  if (toggleBtn) {
    toggleBtn.classList.toggle('hidden', store.ui.pdfVisible);
  }
  if (btn) {
    btn.classList.toggle('active', store.ui.pdfVisible);
    btn.title = store.ui.pdfVisible ? '收起 PDF 原页' : '显示 PDF 原页';
  }
  if (modeBtn) {
    var modeLabelMap = { compact: '紧凑', balanced: '平衡', inspect: '核对' };
    modeBtn.textContent = modeLabelMap[store.ui.pdfPanelMode] || '平衡';
    modeBtn.title = '切换 PDF 面板宽度';
  }
  updatePdfZoomUi();
}

function getPdfPageElement(bp) {
  return document.querySelector('.pdf-page-item[data-pdf-bp="' + Number(bp) + '"]');
}

function getPdfImageForItem(pageEl) {
  return pageEl ? pageEl.querySelector('.pdf-img') : null;
}

function normalizePdfScale(scale) {
  var nextScale = Math.round(Number(scale || 0) * 100) / 100;
  if (nextScale <= 0) return 2;
  return nextScale;
}

function formatPdfScale(scale) {
  return normalizePdfScale(scale).toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function getPdfRenderScale(bp) {
  var container = document.getElementById('pdfScrollContainer');
  if (!container) return 2;
  var metrics = pdfPageMetrics[String(Number(bp) || 0)] || {};
  var pageImgW = Number(metrics.imgW || 0);
  if (pageImgW <= 0) return 2;
  var pageEl = getPdfPageElement(bp);
  var cssWidth = Math.max(1, (pageEl && pageEl.clientWidth) || container.clientWidth || 1);
  var pixelRatio = Math.max(2, window.devicePixelRatio || 1) * Math.max(1, Number(store.ui.pdfZoom || 1));
  var scale = (cssWidth * pixelRatio) / pageImgW;
  if (scale < 1) scale = 1;
  if (scale > 3.2) scale = 3.2;
  return normalizePdfScale(scale);
}

function updatePdfZoomUi() {
  var container = document.getElementById('pdfScrollContainer');
  var info = document.getElementById('pdfZoomInfo');
  var zoom = Math.max(1, Number(store.ui.pdfZoom || 1));
  if (container) {
    container.style.setProperty('--pdf-zoom', String(zoom));
    container.dataset.zoomed = zoom > 1.05 ? '1' : '0';
  }
  if (info) {
    info.textContent = Math.round(zoom * 100) + '%';
  }
}

function rerenderMountedPdfImages() {
  document.querySelectorAll('.pdf-page-item[data-pdf-bp]').forEach(function(el) {
    var img = getPdfImageForItem(el);
    if (img) syncPdfImageSrc(el, img);
  });
}

function buildPdfZoomAnchor(container, event) {
  if (!container) return null;
  var rect = container.getBoundingClientRect();
  var anchorX = rect.left + (container.clientWidth / 2);
  var anchorY = rect.top + (container.clientHeight / 2);
  if (event) {
    if (typeof event.clientX === 'number') anchorX = event.clientX;
    if (typeof event.clientY === 'number') anchorY = event.clientY;
  }
  return {
    xRatio: (container.scrollLeft + Math.max(0, anchorX - rect.left)) / Math.max(1, container.scrollWidth),
    yRatio: (container.scrollTop + Math.max(0, anchorY - rect.top)) / Math.max(1, container.scrollHeight),
  };
}

function restorePdfZoomAnchor(container, anchor) {
  if (!container || !anchor) return;
  var targetLeft = anchor.xRatio * Math.max(0, container.scrollWidth) - (container.clientWidth / 2);
  var targetTop = anchor.yRatio * Math.max(0, container.scrollHeight) - (container.clientHeight / 2);
  container.scrollLeft = Math.max(0, targetLeft);
  container.scrollTop = Math.max(0, targetTop);
}

function setPdfZoom(value, anchor) {
  var container = document.getElementById('pdfScrollContainer');
  dispatch('set_pdf_zoom', { value: value });
  updatePdfZoomUi();
  applyPdfPagePlaceholders();
  restorePdfZoomAnchor(container, anchor);
  rerenderMountedPdfImages();
  maybeRestoreHighlight();
}

function stepPdfZoom(delta, anchor) {
  setPdfZoom(Number(store.ui.pdfZoom || 1) + Number(delta || 0), anchor);
}

function cyclePdfPanelMode() {
  var panel = document.getElementById('pdfPanel');
  if (panel) {
    panel.style.width = '';
    panel.style.maxWidth = '';
  }
  dispatch('cycle_pdf_panel_mode');
  applyPdfPanelVisibilityState();
  applyPdfPagePlaceholders();
  rerenderMountedPdfImages();
  maybeRestoreHighlight();
}

function resetPdfZoom() {
  setPdfZoom(1);
}

function togglePdfZoomFromGesture(pageEl, anchor) {
  if (!pageEl) return;
  var currentZoom = Math.max(1, Number(store.ui.pdfZoom || 1));
  if (currentZoom > 1.05) {
    setPdfZoom(1, anchor);
    return;
  }
  setPdfZoom(1.8, anchor);
}

function initPdfZoomInteractions() {
  var container = document.getElementById('pdfScrollContainer');
  if (!container || container.dataset.zoomInteractionsReady === '1') return;
  container.dataset.zoomInteractionsReady = '1';
  container.addEventListener('dblclick', function(event) {
    var pageItem = event.target && event.target.closest('.pdf-page-item');
    if (!pageItem) return;
    var anchor = buildPdfZoomAnchor(container, event);
    togglePdfZoomFromGesture(pageItem, anchor);
  });
  container.addEventListener('wheel', function(event) {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    var anchor = buildPdfZoomAnchor(container, event);
    var delta = event.deltaY < 0 ? 0.1 : -0.1;
    stepPdfZoom(delta, anchor);
  }, { passive: false });
}

function buildPdfPageSrc(pageEl) {
  if (!pageEl) return '';
  var baseSrc = String(pageEl.getAttribute('data-pdf-src') || '');
  if (!baseSrc) return '';
  var bp = Number(pageEl.getAttribute('data-pdf-bp') || 0);
  var url = new URL(baseSrc, window.location.origin);
  var docId = getReadingDocIdParam();
  if (docId) {
    url.searchParams.set('doc_id', docId);
  }
  url.searchParams.set('scale', formatPdfScale(getPdfRenderScale(bp)));
  return url.pathname + url.search;
}

function syncPdfImageSrc(pageEl, img) {
  if (!pageEl || !img) return;
  var nextSrc = buildPdfPageSrc(pageEl);
  if (!nextSrc || img.getAttribute('src') === nextSrc) return;
  img.addEventListener('load', function() {
    maybeRestoreHighlight();
  }, { once: true });
  img.src = nextSrc;
}

function mountPdfImage(pageEl) {
  if (!pageEl) return;
  var alt = String(pageEl.getAttribute('data-pdf-alt') || 'PDF');
  var img = getPdfImageForItem(pageEl);
  if (!img) {
    img = document.createElement('img');
    img.className = 'pdf-img';
    img.loading = 'lazy';
    img.alt = alt;
    var highlight = pageEl.querySelector('.pdf-highlights');
    if (highlight) {
      pageEl.insertBefore(img, highlight);
    } else {
      pageEl.appendChild(img);
    }
  }
  img.alt = alt;
  syncPdfImageSrc(pageEl, img);
}

function unmountPdfImage(pageEl) {
  var img = getPdfImageForItem(pageEl);
  if (!img) return;
  img.remove();
}

function initPdfVirtualScroll() {
  var container = document.getElementById('pdfScrollContainer');
  if (!container || virtualPdfState.initialized) return;
  var items = container.querySelectorAll('.pdf-page-item[data-pdf-bp]');
  virtualPdfState.enabled = items.length >= VIRTUAL_SCROLL_MIN_PAGES;
  virtualPdfState.initialized = true;
}

function updatePdfVirtualWindow(centerBp) {
  initPdfVirtualScroll();
  if (!virtualPdfState.enabled) return;
  var center = Number(centerBp || store.reading.pdfBp || store.reading.currentBp || 0);
  if (!center) return;
  var centerIdx = store.pages.allBps.indexOf(center);
  if (centerIdx < 0) return;
  var minIdx = Math.max(0, centerIdx - VIRTUAL_WINDOW_RADIUS);
  var maxIdx = Math.min(store.pages.allBps.length - 1, centerIdx + VIRTUAL_WINDOW_RADIUS);
  var keepSet = {};
  for (var i = minIdx; i <= maxIdx; i += 1) {
    keepSet[store.pages.allBps[i]] = true;
  }
  document.querySelectorAll('.pdf-page-item[data-pdf-bp]').forEach(function(el) {
    var bp = Number(el.getAttribute('data-pdf-bp') || 0);
    if (!bp) return;
    if (keepSet[bp]) {
      mountPdfImage(el);
    } else {
      unmountPdfImage(el);
      var layer = el.querySelector('.pdf-highlights');
      if (layer) layer.innerHTML = '';
    }
  });
  maybeRestoreHighlight();
}

function getPdfHighlightLayer(bp) {
  return document.querySelector('.pdf-highlights[data-pdf-highlight-bp="' + Number(bp) + '"]');
}

function updatePdfPageInfo(bp) {
  var info = document.getElementById('pdfPageInfo');
  if (info && bp) info.textContent = formatPdfPageLabel(bp);
}

function pdfGoToBp(bp) {
  alignPdfToReading({
    bp: bp,
    source: 'pdf',
    behavior: 'smooth',
    forceScroll: true,
    suppressMs: OBSERVER_NAV_SUPPRESS_MS,
  });
  clearHighlights();
}

function pdfPrevPage() {
  var i = store.pages.allBps.indexOf(store.reading.pdfBp);
  if (i > 0) pdfGoToBp(store.pages.allBps[i - 1]);
}

function pdfNextPage() {
  var i = store.pages.allBps.indexOf(store.reading.pdfBp);
  if (i >= 0 && i < store.pages.allBps.length - 1) pdfGoToBp(store.pages.allBps[i + 1]);
}

// ===== PDF 高亮层 =====
var activePara = -1;

function clearHighlights() {
  document.querySelectorAll('.pdf-highlights').forEach(function(layer) {
    layer.innerHTML = '';
  });
  activePara = -1;
  currentHighlightState = {
    active: false,
    paraIdx: null,
    bboxes: [],
    targetBp: null,
  };
  document.querySelectorAll('.para-block.active-para, .heading-block.active-para').forEach(function(el) {
    el.classList.remove('active-para');
  });
}

function maybeRestoreHighlight() {
  if (!currentHighlightState.active) return;
  var targetBp = Number(currentHighlightState.targetBp || 0);
  if (!targetBp) return;
  var pageEl = getPdfPageElement(targetBp);
  var img = pageEl ? pageEl.querySelector('.pdf-img') : null;
  if (!img || !img.complete || img.offsetHeight <= 0) return;
  showHighlights(currentHighlightState.paraIdx, currentHighlightState.bboxes, targetBp);
}

function resolveParagraphBp(el) {
  if (!el) return Number(store.reading.currentBp || getVisiblePdfBp() || 0);
  var raw = String(el.getAttribute('data-para-bp') || '').trim();
  if (!raw) return Number(store.reading.currentBp || getVisiblePdfBp() || 0);
  var m = raw.match(/\d+/);
  return m ? Number(m[0]) : Number(store.reading.currentBp || getVisiblePdfBp() || 0);
}

function isPdfPageVisible(bp) {
  var container = document.getElementById('pdfScrollContainer');
  var pageEl = getPdfPageElement(bp);
  if (!container || !pageEl) return false;
  var top = pageEl.offsetTop;
  var bottom = top + pageEl.offsetHeight;
  var viewTop = container.scrollTop;
  var viewBottom = viewTop + container.clientHeight;
  var overlap = Math.max(0, Math.min(bottom, viewBottom) - Math.max(top, viewTop));
  var ratio = overlap / Math.max(1, pageEl.offsetHeight);
  return ratio >= 0.45;
}

function scrollPdfPageIntoView(bp, behavior, onlyWhenHidden) {
  var pageEl = getPdfPageElement(bp);
  if (!pageEl) return;
  if (onlyWhenHidden && isPdfPageVisible(bp)) return;
  pageEl.scrollIntoView({block: 'center', behavior: behavior || 'smooth'});
}

function scrollPdfToHighlight(bp, bbox, behavior) {
  updatePdfVirtualWindow(bp);
  var container = document.getElementById('pdfScrollContainer');
  var pageEl = getPdfPageElement(bp);
  var img = pageEl ? pageEl.querySelector('.pdf-img') : null;
  var metrics = pdfPageMetrics[String(bp)] || {};
  if (!container || !pageEl || !img || !bbox || Number(metrics.imgH || 0) <= 0) return;
  var doScroll = function() {
    var pageTop = pageEl.offsetTop;
    var scrollY = pageTop + (bbox[1] / Number(metrics.imgH)) * Math.max(1, img.offsetHeight) - 60;
    container.scrollTo({ top: Math.max(0, scrollY), behavior: behavior || 'smooth' });
  };
  if (img.complete && img.offsetHeight > 0) {
    doScroll();
    return;
  }
  img.addEventListener('load', doScroll, { once: true });
}

function alignPdfToReading(options) {
  var opts = options || {};
  var targetBp = Number(opts.bp || store.reading.currentBp || getVisiblePdfBp() || 0);
  if (!targetBp) return;
  var source = opts.source || 'reading';
  var behavior = opts.behavior || 'auto';
  var suppressMs = Number(opts.suppressMs || OBSERVER_NAV_SUPPRESS_MS);
  var forceScroll = !!opts.forceScroll;

  suppressObserverNavigation(suppressMs);
  setVisiblePdfBp(targetBp, source);

  var targetEl = getPdfPageElement(targetBp);
  if (!targetEl) return;
  if (!forceScroll && isPdfPageVisible(targetBp)) return;
  targetEl.scrollIntoView({ block: 'center', behavior: behavior });
}

function showHighlights(paraIdx, bboxes, targetBp) {
  targetBp = Number(targetBp || store.reading.currentBp || getVisiblePdfBp() || 0);
  currentHighlightState = {
    active: true,
    paraIdx: paraIdx,
    bboxes: Array.isArray(bboxes) ? bboxes.slice() : [],
    targetBp: targetBp,
  };
  var c = getPdfHighlightLayer(targetBp);
  var metrics = pdfPageMetrics[String(targetBp)] || {};
  var pageImgW = Number(metrics.imgW || 0);
  var pageImgH = Number(metrics.imgH || 0);
  if (!c || !pageImgW || !pageImgH) return;
  c.innerHTML = '';
  activePara = paraIdx;
  bboxes.forEach(function(bb) {
    var div = document.createElement('div');
    div.className = 'pdf-hl-box';
    div.style.left   = (bb[0] / pageImgW * 100) + '%';
    div.style.top    = (bb[1] / pageImgH * 100) + '%';
    div.style.width  = ((bb[2] - bb[0]) / pageImgW * 100) + '%';
    div.style.height = ((bb[3] - bb[1]) / pageImgH * 100) + '%';
    c.appendChild(div);
  });
}

// 段落 hover/click → 高亮 PDF 区域
document.addEventListener('DOMContentLoaded', function() {
  var blocks = document.querySelectorAll('[data-para-idx]');
  blocks.forEach(function(el) {
    var idx = parseInt(el.getAttribute('data-para-idx'));
    var bboxes = [];
    try { bboxes = JSON.parse(el.getAttribute('data-bboxes') || '[]'); } catch(e) {}

    el.addEventListener('mouseenter', function() {
      if (bboxes.length && store.ui.pdfVisible) {
        var targetBp = resolveParagraphBp(el);
        setVisiblePdfBp(targetBp, 'reading');
        scrollPdfPageIntoView(targetBp, 'auto', true);
        showHighlights(idx, bboxes, targetBp);
        el.classList.add('active-para');
      }
    });
    el.addEventListener('mouseleave', function() {
      clearHighlights();
    });
    el.addEventListener('click', function() {
      if (bboxes.length && store.ui.pdfVisible) {
        var targetBp = resolveParagraphBp(el);
        setVisiblePdfBp(targetBp, 'reading');
        scrollPdfPageIntoView(targetBp, 'smooth', false);
        showHighlights(idx, bboxes, targetBp);
        if (bboxes[0]) scrollPdfToHighlight(targetBp, bboxes[0], 'smooth');
      }
    });
  });
});

function fetchGlossaryRetranslatePreview(startBp, startSegmentIndex) {
  var docId = requireReadingDocId('预览词典补重译范围');
  if (!docId) return Promise.resolve(null);
  var url = (ROUTES.glossaryPreview || '/api/glossary_retranslate_preview') + '?doc_id=' + encodeURIComponent(docId);
  if (startBp !== undefined && startBp !== null && startBp !== '') {
    url += '&start_bp=' + encodeURIComponent(startBp);
  }
  if (startSegmentIndex !== undefined && startSegmentIndex !== null && startSegmentIndex !== '') {
    url += '&start_segment_index=' + encodeURIComponent(startSegmentIndex);
  }
  return fetch(url).then(function(r) { return r.json(); });
}

function buildGlossaryProblemLines(preview, limit) {
  var items = Array.isArray(preview && preview.problem_segments) ? preview.problem_segments.slice(0, limit) : [];
  return items.map(function(item) {
    var missing = Array.isArray(item.missing_terms) ? item.missing_terms.map(function(term) {
      return String(term.defn || term.term || '').trim();
    }).filter(Boolean) : [];
    var pageLabel = String(item.pages || '').trim() || ('PDF 第' + Number(item.bp || 0) + '页');
    var source = String(item.source_excerpt || '').trim();
    var translation = String(item.translation_excerpt || '').trim();
    return (
      pageLabel
      + ' 第' + (Number(item.segment_index || 0) + 1) + '段缺少术语：'
      + (missing.join('、') || '未指定')
      + '。原文：' + source
      + '；现译：' + translation
    );
  });
}

function buildGlossaryRetranslateConfirmText(preview) {
  var parts = [
    '预计影响 ' + Number(preview.affected_pages || 0) + ' 页、' + Number(preview.affected_segments || 0) + ' 段词典未生效的机器译文。'
  ];
  var skippedManual = Number(preview.skipped_manual_segments || 0);
  if (skippedManual > 0) {
    parts.push('其中 ' + skippedManual + ' 段人工修订会被跳过，不会覆盖。');
  }
  var problemLines = buildGlossaryProblemLines(preview, 5);
  if (problemLines.length) {
    parts.push('将处理这些问题段：\n' + problemLines.join('\n'));
  }
  if (preview && preview.problem_list_truncated) {
    parts.push('其余问题段将在后台按同样规则定向处理。');
  }
  parts.push('确认按当前词典开始补重译？');
  return parts.join('\n\n');
}

function startGlossaryRetranslate(startBp, startSegmentIndex, onStarted) {
  var docId = requireReadingDocId('启动词典补重译');
  if (!docId) return Promise.resolve(null);
  var form = new FormData();
  form.append('doc_id', docId);
  form.append('start_bp', Number(startBp || 0));
  form.append('start_segment_index', Number(startSegmentIndex || 0));
  form.append('doc_title', BOOTSTRAP.docTitle || '');
  return fetch(ROUTES.startGlossaryRetranslate || '/start_glossary_retranslate', {
    method: 'POST',
    headers: withCsrfHeaders(),
    body: form
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !data.ok) {
        alert((data && (data.message || data.reason)) || '词典补重译启动失败');
        return data;
      }
      if (typeof onStarted === 'function') {
        onStarted(data);
      } else {
        refreshTranslateStatus();
      }
      return data;
    });
}

function triggerGlossaryRetranslatePreview(startBp, startSegmentIndex, btn) {
  fetchGlossaryRetranslatePreview(startBp, startSegmentIndex)
    .then(function(preview) {
      if (!preview) return;
      if (!preview.can_start) {
        alert(preview.reason || '当前无法启动词典补重译');
        return;
      }
      if (!window.confirm(buildGlossaryRetranslateConfirmText(preview))) {
        return;
      }
      if (btn) {
        btn.disabled = true;
      }
      startGlossaryRetranslate(preview.start_bp, preview.start_segment_index, function() {
        refreshTranslateStatus();
      }).catch(function(err) {
        alert('词典补重译启动失败: ' + err);
      }).finally(function() {
        if (btn) {
          btn.disabled = false;
        }
      });
    })
    .catch(function(err) {
      alert('词典补重译预览失败: ' + err);
    });
}

// ===== 重译前人工修订警告 =====
function confirmRetranslate(retranslateUrl, btn) {
  var docId = requireReadingDocId('检查重译覆盖风险');
  if (!docId) return;
  function submitRetranslateAction() {
    if (btn) {
      btn.innerHTML = '<span class=spinner></span> 重译中&hellip;';
      btn.style.pointerEvents = 'none';
    }
    submitPostAction(retranslateUrl, {doc_id: docId});
  }

  var bp = Number(BOOTSTRAP.currentBp || 0);
  fetch((ROUTES.checkRetranslateWarnings || '/check_retranslate_warnings') + '?doc_id=' + encodeURIComponent(docId) + '&bp=' + bp)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var count = (data && data.ok) ? (data.manual_count || 0) : 0;
      if (count > 0) {
        var ok = window.confirm(
          '本页有 ' + count + ' 段人工修订，重译后将被机器译文覆盖（修订内容可在历史记录中查阅）。\n\n确认重译？'
        );
        if (!ok) return;
      }
      submitRetranslateAction();
    })
    .catch(function() {
      // 检查失败时直接跳转，不阻断操作
      submitRetranslateAction();
    });
}

function confirmReparsePage(pageBp) {
  var bp = Number(pageBp || BOOTSTRAP.currentBp || 0);
  var docId = requireReadingDocId('检查重解析覆盖风险');
  if (!docId) return;
  fetch((ROUTES.checkRetranslateWarnings || '/check_retranslate_warnings') + '?doc_id=' + encodeURIComponent(docId) + '&bp=' + bp)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var count = (data && data.ok) ? (data.manual_count || 0) : 0;
      if (count > 0) {
        var ok = window.confirm(
          '本页有 ' + count + ' 段人工修订，重解析并重译后将被新的机器译文覆盖（修订内容可在历史记录中查阅）。\n\n确认重解析？'
        );
        if (!ok) return;
      }
      startReparsePage(pageBp);
    })
    .catch(function() {
      startReparsePage(pageBp);
    });
}

// ===== 单页重新解析 =====
function startReparsePage(pageBp) {
  var btn = document.getElementById('reparsePageBtn');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ OCR 重解析并重译中…';

  var reparseUrl = String(ROUTES.reparsePageBase || '/reparse_page/0').replace('/0', '/' + pageBp);
  var reparseDocId = requireReadingDocId('重解析当前页', function(message) {
    alert(message);
    btn.disabled = false;
    btn.textContent = '🔄 强制 OCR 重解析本页';
  });
  if (!reparseDocId) return;
  reparseUrl += '?doc_id=' + encodeURIComponent(reparseDocId);
  fetch(reparseUrl, {
    method: 'POST',
    headers: withCsrfHeaders()
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        alert(data.error);
        btn.disabled = false;
        btn.textContent = '🔄 强制 OCR 重解析本页';
        return;
      }
      if (data.task_id) {
        listenReparseSSE(data.task_id, pageBp);
      }
    })
    .catch(function(err) {
      alert('请求失败: ' + err);
      btn.disabled = false;
      btn.textContent = '🔄 强制 OCR 重解析本页';
    });
}

function listenReparseSSE(taskId, pageBp) {
  var es = new EventSource((ROUTES.processSse || '/process_sse') + '?task_id=' + taskId);
  var btn = document.getElementById('reparsePageBtn');

  es.addEventListener('progress', function(e) {
    var d = JSON.parse(e.data);
    // 显示进度在按钮上
    if (btn && d.label) {
      btn.textContent = '⏳ ' + d.label;
    }
  });

  es.addEventListener('done', function(e) {
    es.close();
    if (btn) {
      btn.textContent = '✓ OCR 重解析并重译完成';
      btn.style.color = 'var(--grn)';
    }
    // 刷新页面以显示新的解析和重译内容
    setTimeout(function() {
      window.location.reload();
    }, 800);
  });

  es.addEventListener('error_msg', function(e) {
    es.close();
    var d = JSON.parse(e.data);
    alert(d.error || '未知错误');
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 强制 OCR 重解析本页';
    }
  });

  es.onerror = function() {
    es.close();
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 强制 OCR 重解析本页';
    }
  };
}

function initPdfResizer() {
  var resizer = document.getElementById('pdfResizer');
  var panel = document.getElementById('pdfPanel');
  if (!resizer || !panel) return;

  var isResizing = false;
  var startX = 0;
  var startWidth = 0;

  resizer.addEventListener('mousedown', function(e) {
    e.preventDefault();
    isResizing = true;
    startX = e.clientX;
    startWidth = panel.offsetWidth;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  window.addEventListener('mousemove', function(e) {
    if (!isResizing) return;
    var currentX = e.clientX;
    var newWidth = startWidth + (currentX - startX);
    if (newWidth < 200) newWidth = 200;
    if (newWidth > 800) newWidth = 800;
    panel.style.maxWidth = 'none';
    panel.style.width = newWidth + 'px';
    applyPdfPagePlaceholders({ syncImageSrc: false });
    maybeRestoreHighlight();
  });

  window.addEventListener('mouseup', function(e) {
    if (!isResizing) return;
    isResizing = false;
    applyPdfPagePlaceholders();
    maybeRestoreHighlight();
    resizer.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
}

// ===== 导出功能 =====
var _exportChapters = [];   // [{index, title, start_bp, end_bp}, ...]
var _exportDebounceTimer = null;

function _selectedExportFormat() {
  var checked = document.querySelector('input[name="exportFormat"]:checked');
  return checked ? checked.value : 'standard';
}

function _updateExportFormatUi() {
  var section = document.getElementById('exportChapterSection');
  var excludeWrap = document.getElementById('exportExcludeBoilerplateWrap');
  var copyBtn = document.getElementById('exportCopyBtn');
  var downloadBtn = document.getElementById('exportDownloadBtn');
  var format = _selectedExportFormat();
  if (format === 'fnm_obsidian') {
    section.classList.add('hidden');
    excludeWrap.classList.add('hidden');
    if (copyBtn) {
      copyBtn.disabled = true;
      copyBtn.style.opacity = '0.5';
      copyBtn.style.cursor = 'not-allowed';
      copyBtn.title = 'FNM Obsidian 章节包导出仅支持下载 .zip';
    }
    if (downloadBtn) {
      downloadBtn.textContent = '下载 .zip';
    }
    return;
  }
  excludeWrap.classList.remove('hidden');
  if (copyBtn) {
    copyBtn.disabled = false;
    copyBtn.style.opacity = '';
    copyBtn.style.cursor = '';
    copyBtn.title = '';
  }
  if (downloadBtn) {
    downloadBtn.textContent = '下载 .md';
  }
  if (_exportChapters.length) {
    section.classList.remove('hidden');
  } else {
    section.classList.add('hidden');
  }
}

function openExportModal() {
  document.getElementById('exportModal').classList.remove('hidden');
  _updateExportFormatUi();
  _loadExportChapters();
}

function _loadExportChapters() {
  var docId = requireReadingDocId('导出文稿', function() {});
  if (!docId) return;
  fetch((ROUTES.tocChapters || '/api/toc_chapters') + '?doc_id=' + encodeURIComponent(docId))
    .then(function(r) { return r.json(); })
    .then(function(d) {
      _exportChapters = d.chapters || [];
      _renderExportChapterList();
      loadExportContent();
    })
    .catch(function() {
      _exportChapters = [];
      loadExportContent();
    });
}

function _renderExportChapterList() {
  var section = document.getElementById('exportChapterSection');
  var list = document.getElementById('exportChapterList');
  if (!_exportChapters.length || _selectedExportFormat() === 'fnm_obsidian') {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  list.innerHTML = '';
  _exportChapters.forEach(function(ch) {
    var row = document.createElement('label');
    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 8px;cursor:pointer;font-size:12px;';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.dataset.idx = ch.index;
    cb.addEventListener('change', function() { _scheduleExportReload(); });
    var label = document.createElement('span');
    label.style.cssText = 'flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
    label.textContent = ch.title;
    var pages = document.createElement('span');
    pages.style.cssText = 'color:var(--txS);flex-shrink:0;';
    pages.textContent = 'p.' + ch.start_bp + (ch.end_bp !== ch.start_bp ? '–' + ch.end_bp : '');
    row.appendChild(cb);
    row.appendChild(label);
    row.appendChild(pages);
    list.appendChild(row);
  });
}

function exportSelectAll(checked) {
  var list = document.getElementById('exportChapterList');
  list.querySelectorAll('input[type=checkbox]').forEach(function(cb) { cb.checked = checked; });
  _scheduleExportReload();
}

function _scheduleExportReload() {
  clearTimeout(_exportDebounceTimer);
  _exportDebounceTimer = setTimeout(function() { loadExportContent(true); }, 300);
}

function _exportBpRanges() {
  if (!_exportChapters.length) return '';
  var list = document.getElementById('exportChapterList');
  var checked = Array.from(list.querySelectorAll('input[type=checkbox]:checked'));
  // 全选时不传参（等同全部导出）
  if (checked.length === _exportChapters.length) return '';
  if (!checked.length) return '__none__';
  return checked.map(function(cb) {
    var ch = _exportChapters[parseInt(cb.dataset.idx)];
    return ch.start_bp + '-' + ch.end_bp;
  }).join(',');
}

function _exportChapterName() {
  if (!_exportChapters.length) return '';
  var list = document.getElementById('exportChapterList');
  var checked = Array.from(list.querySelectorAll('input[type=checkbox]:checked'));
  if (checked.length === 1) {
    return _exportChapters[parseInt(checked[0].dataset.idx)].title;
  }
  return '';
}

function _excludeBoilerplateEnabled() {
  var checkbox = document.getElementById('exportExcludeBoilerplate');
  return !!(checkbox && checkbox.checked);
}

function loadExportContent(force) {
  var textarea = document.getElementById('exportText');
  var loading = document.getElementById('exportLoading');
  var docId = requireReadingDocId('导出文稿', function(message) {
    loading.textContent = message;
    loading.classList.remove('hidden');
    textarea.classList.add('hidden');
  });
  if (!docId) return;

  if (!force && textarea.value && textarea.value !== '加载中…') {
    return;
  }

  textarea.classList.add('hidden');
  loading.classList.remove('hidden');
  _updateExportFormatUi();

  var url = (ROUTES.exportMd || '/export_md') + '?doc_id=' + encodeURIComponent(docId);
  var exportFormat = _selectedExportFormat();
  if (exportFormat === 'fnm_obsidian') {
    url += '&format=fnm_obsidian';
  } else {
    var bpRanges = _exportBpRanges();
    if (bpRanges === '__none__') {
      textarea.value = '';
      loading.classList.add('hidden');
      textarea.classList.remove('hidden');
      return;
    }
    if (bpRanges) url += '&bp_ranges=' + encodeURIComponent(bpRanges);
    if (_excludeBoilerplateEnabled()) url += '&exclude_boilerplate=1';
  }

  fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var markdown = d.markdown || '';
      if (exportFormat === 'fnm_obsidian' && markdown) {
        textarea.value = '该格式将下载为 .zip 章节包。\n以下为导出内容预览：\n\n' + markdown;
      } else {
        textarea.value = markdown;
      }
      loading.classList.add('hidden');
      textarea.classList.remove('hidden');
    })
    .catch(function(err) {
      loading.textContent = '加载失败: ' + err;
    });
}

function downloadExportMd() {
  var docId = requireReadingDocId('导出文稿', function() {});
  if (!docId) return;
  var url = (ROUTES.downloadMd || '/download_md') + '?doc_id=' + encodeURIComponent(docId);
  var exportFormat = _selectedExportFormat();
  if (exportFormat === 'fnm_obsidian') {
    url += '&format=fnm_obsidian';
  } else {
    var bpRanges = _exportBpRanges();
    if (bpRanges === '__none__') { alert('请至少选择一个章节'); return; }
    if (bpRanges) {
      url += '&bp_ranges=' + encodeURIComponent(bpRanges);
      var name = _exportChapterName();
      if (name) url += '&chapter_name=' + encodeURIComponent(name);
    }
    if (_excludeBoilerplateEnabled()) {
      url += '&exclude_boilerplate=1';
    }
  }
  window.location.href = url;
}

function copyExport() {
  if (_selectedExportFormat() === 'fnm_obsidian') {
    alert('FNM Obsidian 章节包导出仅支持下载 .zip');
    return;
  }
  var textarea = document.getElementById('exportText');
  if (!textarea.value || textarea.value === '加载中…') {
    alert('内容尚未加载完成');
    return;
  }
  textarea.select();
  document.execCommand('copy');
  var btn = (typeof event !== 'undefined' && event && event.target)
    ? event.target
    : document.getElementById('exportCopyBtn');
  if (!btn) return;
  var originalText = btn.textContent;
  btn.textContent = '已复制';
  setTimeout(function() { btn.textContent = originalText; }, 1500);
}

// ===== 点击外部关闭 dropdown =====
document.addEventListener('click', function(e) {
  var mm = document.getElementById('moreMenu');
  if (mm && !mm.contains(e.target)) {
    mm.classList.remove('open');
  }
  var tocMenu = document.getElementById('tocMenu');
  if (tocMenu && !tocMenu.contains(e.target)) {
    tocMenu.classList.remove('open');
  }
  var pageNav = document.getElementById('pageNav');
  if (pageNav && !pageNav.contains(e.target)) {
    togglePageNav(false);
  }
});

// 页面加载时：检查是否需要自动启动翻译
(function() {
  resetStreamDraftState();
  applyOriginalVisibilityState();
  applyPdfPanelVisibilityState();
  initPdfZoomInteractions();
  initPdfResizer();
  if (store.ui.pdfVisible) {
    initPdfVirtualScroll();
    applyPdfPagePlaceholders();
    setupPdfScrollObserver();
    alignPdfToReading({
      bp: store.reading.currentBp,
      source: 'reading',
      behavior: 'auto',
      forceScroll: true,
      suppressMs: OBSERVER_NAV_SUPPRESS_MS,
    });
    setTimeout(function() {
      alignPdfToReading({
        bp: store.reading.currentBp,
        source: 'reading',
        behavior: 'auto',
        forceScroll: true,
        suppressMs: OBSERVER_NAV_SUPPRESS_MS,
      });
    }, OBSERVER_NAV_DEBOUNCE_MS);
  }
  var shouldRestoreDraft = shouldHydrateTranslateDraft(initialTranslateSnapshot);
  if (shouldRestoreDraft) {
    hydrateStreamDraftFromSnapshot(initialTranslateSnapshot);
    dispatch('set_pages_from_snapshot', {
      translatedBps: Array.isArray(initialTranslateSnapshot.translated_bps) ? initialTranslateSnapshot.translated_bps : null,
      failedBps: Array.isArray(initialTranslateSnapshot.failed_bps) ? initialTranslateSnapshot.failed_bps : null,
      partialFailedBps: Array.isArray(initialTranslateSnapshot.partial_failed_bps) ? initialTranslateSnapshot.partial_failed_bps : null,
    });
    renderStreamDraftState();
  }
  renderPageNavigationState();
  var params = new URLSearchParams(window.location.search);
  var autoStart = params.get('auto');
  var startBp = params.get('start_bp');

  if (autoStart === '1' && startBp) {
    startTranslateAll(startBp);
    setReadingAutoStart('0');
    setReadingStartBp('');
    syncReadingUrl();
  } else {
    refreshTranslateStatus();
  }

  if (store.ui.taskDetailsOpen) {
    refreshTaskSessionDetails();
    startTaskDetailsPolling();
  }
})();

window.addEventListener('resize', function() {
  applyPdfPagePlaceholders();
});
