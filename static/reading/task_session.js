var translateES = null;
var translateStatusPoll = null;
var usagePoll = null;
var usageSamples = [];
var usageLiveState = {
  initialized: false,
  totalTokens: 0,
  requestCount: 0,
  currentBp: null,
  updatedAt: 0,
};

function resetStreamDraftState() {
  dispatch('replace_stream_draft', { draft: createInitialStreamDraftState() });
}

function hasDraftErrorState(draft) {
  return !!(
    draft
    && Array.isArray(draft.paragraph_states)
    && draft.paragraph_states.some(function(state) { return state === 'error'; })
  );
}

function hasDraftVisibleText(draft) {
  return !!(
    draft
    && Array.isArray(draft.paragraphs)
    && draft.paragraphs.some(function(text) { return String(text || '').trim(); })
  );
}

function hasRestorableDraft(state) {
  var draft = (state && state.draft) || {};
  var draftBp = Number(draft.bp || 0);
  var status = String(draft.status || 'idle');
  if (!draftBp) return false;
  if (status !== 'aborted' && status !== 'error') return false;
  return hasDraftVisibleText(draft) || hasDraftErrorState(draft);
}

function hydrateStreamDraftFromSnapshot(snapshot) {
  var draft = (snapshot && snapshot.draft) || {};
  var paragraphs = Array.isArray(draft.paragraphs) ? draft.paragraphs.slice() : [];
  dispatch('replace_stream_draft', { draft: {
    active: !!draft.active,
    mode: draft.mode || (isFnmTaskState(snapshot) ? 'fnm_unit' : 'page'),
    bp: draft.bp || null,
    unitIdx: draft.unit_idx == null ? (snapshot && snapshot.current_unit_idx != null ? snapshot.current_unit_idx : null) : Number(draft.unit_idx || 0),
    unitId: draft.unit_id || ((snapshot && snapshot.current_unit_id) || ''),
    unitKind: draft.unit_kind || ((snapshot && snapshot.current_unit_kind) || ''),
    unitLabel: draft.unit_label || ((snapshot && snapshot.current_unit_label) || ''),
    unitPages: draft.unit_pages || ((snapshot && snapshot.current_unit_pages) || ''),
    unitError: draft.unit_error || '',
    unitItems: Array.isArray(draft.unit_items) ? draft.unit_items.slice() : (Array.isArray(snapshot && snapshot.unit_items) ? snapshot.unit_items.slice() : []),
    paraIdx: draft.para_idx === undefined || draft.para_idx === null ? null : draft.para_idx,
    paraTotal: Number(draft.para_total || 0),
    paraDone: Number(draft.para_done || 0),
    parallelLimit: Number(draft.parallel_limit || 0),
    activeParaIndices: Array.isArray(draft.active_para_indices) ? draft.active_para_indices.map(Number) : [],
    paragraphStates: Array.isArray(draft.paragraph_states) ? draft.paragraph_states.slice() : [],
    paragraphErrors: Array.isArray(draft.paragraph_errors) ? draft.paragraph_errors.slice() : [],
    paragraphs: paragraphs,
    status: draft.status || 'idle',
    note: draft.note || (isFnmTaskState(snapshot) ? '当前 unit 的流式草稿会显示在这里。' : '流式翻译开始后，这里会显示当前页正在生成的中文草稿。'),
    updatedAt: Number(draft.updated_at || 0),
    lastError: draft.last_error || '',
    restored: true,
  }});
}

function formatDraftStatusLabel(status) {
  return (
    status === 'streaming' ? '翻译中' :
    status === 'throttled' ? '等待中' :
    status === 'aborted' ? '已停止' :
    status === 'error' ? '失败' :
    status === 'done' ? '已完成' : '空闲'
  );
}

function renderStreamDraftState() {
  renderTaskSessionDetails({ snapshot: lastUsageSnapshot || store.taskSession.snapshot || {} });
}

function applyStreamDelta(data) {
  if (!data) return;
  dispatch('stream_para_delta', { data: data });
  renderStreamDraftState();
}


function getResumeStartBp(state) {
  if (!state) return null;
  var resumeBp = Number(state.resume_bp || 0);
  return resumeBp > 0 ? resumeBp : null;
}

function getResumeActionLabel(state) {
  if (!state) return '继续翻译';
  var resumeBp = getResumeStartBp(state);
  if (state.phase === 'partial_failed') return resumeBp ? ('重试' + formatTaskPositionLabel(state, resumeBp)) : '重试失败项';
  if (state.phase === 'error') return resumeBp ? ('从' + formatTaskPositionLabel(state, resumeBp) + '继续') : '从出错位置继续';
  return resumeBp ? ('继续到' + formatTaskPositionLabel(state, resumeBp)) : '继续翻译';
}

function resumeTranslateFromSnapshot(state) {
  var nextBp = getResumeStartBp(state);
  if (!nextBp) {
    refreshTranslateStatus();
    return;
  }
  var task = (state && state.task) || {};
  if (String(task.kind || '') === 'glossary_retranslate') {
    var nextSegmentIndex = Number(task.start_segment_index || 0);
    if (Number(task.start_bp || 0) !== Number(nextBp)) {
      nextSegmentIndex = 0;
    }
    startGlossaryRetranslate(nextBp, nextSegmentIndex);
    return;
  }
  if (String(task.kind || '') === 'fnm') {
    startFnmTranslate(true, nextBp);
    return;
  }
  startTranslateAll(nextBp);
}

function formatUsageNumber(value) {
  return (value || 0).toLocaleString('zh-CN');
}

function trimUsageSamples(nowMs) {
  var cutoff = Number(nowMs || Date.now()) - 60000;
  usageSamples = usageSamples.filter(function(sample) {
    return Number(sample.ts || 0) >= cutoff;
  });
}

function recordUsageSample(totalTokens, tsMs) {
  var ts = Number(tsMs || Date.now());
  var total = Math.max(0, Number(totalTokens || 0));
  trimUsageSamples(ts);
  var last = usageSamples[usageSamples.length - 1];
  if (last && Number(last.total || 0) === total) {
    last.ts = ts;
    return;
  }
  usageSamples.push({ ts: ts, total: total });
  trimUsageSamples(ts);
}

function resetUsageTracking(snapshot) {
  var base = snapshot || {};
  var updatedAtMs = Number(base.updated_at || 0) ? Number(base.updated_at) * 1000 : Date.now();
  usageLiveState.initialized = true;
  usageLiveState.totalTokens = Math.max(0, Number(base.total_tokens || 0));
  usageLiveState.requestCount = Math.max(0, Number(base.request_count || 0));
  usageLiveState.currentBp = Number(base.current_bp || 0) || null;
  usageLiveState.updatedAt = updatedAtMs;
  usageSamples = [];
  recordUsageSample(usageLiveState.totalTokens, updatedAtMs);
}

function syncUsageTracking(snapshot) {
  var base = snapshot || {};
  var phase = String(base.phase || 'idle');
  var snapshotTotal = Math.max(0, Number(base.total_tokens || 0));
  var snapshotRequestCount = Math.max(0, Number(base.request_count || 0));
  var snapshotUpdatedAtMs = Number(base.updated_at || 0) ? Number(base.updated_at) * 1000 : Date.now();
  if (!usageLiveState.initialized) {
    resetUsageTracking(base);
    return;
  }
  if (!isActiveTranslatePhase(phase)) {
    resetUsageTracking(base);
    return;
  }
  if (snapshotTotal < usageLiveState.totalTokens || snapshotRequestCount < usageLiveState.requestCount) {
    return;
  }
  if (
    snapshotTotal > usageLiveState.totalTokens
    || snapshotRequestCount > usageLiveState.requestCount
    || Number(base.current_bp || 0) !== Number(usageLiveState.currentBp || 0)
  ) {
    usageLiveState.totalTokens = snapshotTotal;
    usageLiveState.requestCount = snapshotRequestCount;
    usageLiveState.currentBp = Number(base.current_bp || 0) || null;
    usageLiveState.updatedAt = snapshotUpdatedAtMs;
    recordUsageSample(snapshotTotal, snapshotUpdatedAtMs);
  }
}

function getUsageDisplaySnapshot(snapshot) {
  var base = Object.assign({}, snapshot || {});
  if (!isActiveTranslatePhase(base.phase) || !usageLiveState.initialized) {
    return base;
  }
  base.total_tokens = Math.max(Math.max(0, Number(base.total_tokens || 0)), usageLiveState.totalTokens);
  base.request_count = Math.max(Math.max(0, Number(base.request_count || 0)), usageLiveState.requestCount);
  if (usageLiveState.currentBp) {
    base.current_bp = usageLiveState.currentBp;
  }
  if (usageLiveState.updatedAt) {
    base.updated_at = Math.max(Math.max(0, Number(base.updated_at || 0)), Math.floor(usageLiveState.updatedAt / 1000));
  }
  return base;
}

function getUsageSampleStats() {
  trimUsageSamples(Date.now());
  if (!usageSamples.length) {
    return { recentTokens: 0, tokenRate: 0 };
  }
  var first = usageSamples[0];
  var last = usageSamples[usageSamples.length - 1];
  var recentTokens = Math.max(0, Number(last.total || 0) - Number(first.total || 0));
  var spanSeconds = Math.max(0, (Number(last.ts || 0) - Number(first.ts || 0)) / 1000);
  return {
    recentTokens: recentTokens,
    tokenRate: spanSeconds > 0 ? (recentTokens / spanSeconds) : 0,
  };
}

function formatTokenRate(value) {
  var rate = Math.max(0, Number(value || 0));
  return rate.toFixed(rate >= 10 ? 0 : 1);
}

function applyStreamUsage(eventData) {
  var payload = eventData || {};
  var usage = payload.usage || {};
  var deltaTokens = Math.max(0, Number(usage.total_tokens || 0));
  var deltaRequests = Math.max(0, Number(usage.request_count || 0));
  if (!usageLiveState.initialized) {
    resetUsageTracking(lastUsageSnapshot || {});
  }
  usageLiveState.totalTokens += deltaTokens;
  usageLiveState.requestCount += deltaRequests;
  usageLiveState.currentBp = Number(payload.bp || usageLiveState.currentBp || 0) || usageLiveState.currentBp;
  usageLiveState.updatedAt = Date.now();
  recordUsageSample(usageLiveState.totalTokens, usageLiveState.updatedAt);
  if (store.ui.taskDetailsOpen) {
    renderTaskSessionDetails({ snapshot: lastUsageSnapshot || {} });
  }
}

function formatUsagePhase(phase) {
  var labels = {
    idle: '空闲',
    running: '翻译中',
    stopping: '停止中',
    stopped: '已停止',
    done: '已完成',
    partial_failed: '部分完成',
    error: '失败'
  };
  return labels[phase] || '-';
}

function _draftListHtml(snapshot, draft) {
  var items = [];
  if (isFnmTaskState(snapshot)) {
    var unitItems = Array.isArray((draft && draft.unitItems) && draft.unitItems.length ? draft.unitItems : snapshot.unit_items)
      ? ((draft && draft.unitItems) && draft.unitItems.length ? draft.unitItems : snapshot.unit_items)
      : [];
    unitItems.forEach(function(item) {
      items.push(
        '<div class="translation-detail-item">'
        + '<div class="translation-detail-item-title">' + escapeHtml(item.label || formatFnmUnitIndex(item.unit_idx)) + '</div>'
        + '<div class="translation-detail-item-meta">状态：' + escapeHtml(formatDraftStatusLabel(item.status || 'pending')) + (item.pages ? (' · p.' + escapeHtml(item.pages)) : '') + '</div>'
        + (item.preview ? ('<div class="translation-detail-item-preview">' + escapeHtml(item.preview) + '</div>') : '')
        + ((item.status === 'error' && item.unit_idx)
          ? ('<div class="translation-session-actions" style="margin-top:8px;"><button type="button" class="btn btn-gho" onclick="startFnmTranslate(false, ' + Number(item.unit_idx) + ');">重试 ' + formatFnmUnitIndex(item.unit_idx) + '</button></div>')
          : '')
        + '</div>'
      );
    });
    return items.length ? items.join('') : '<div class="translation-detail-copy">当前还没有可展示的 unit 草稿。</div>';
  }
  var paragraphs = Array.isArray(draft && draft.paragraphs) ? draft.paragraphs : [];
  var paragraphStates = Array.isArray(draft && draft.paragraphStates) ? draft.paragraphStates : [];
  var paragraphErrors = Array.isArray(draft && draft.paragraphErrors) ? draft.paragraphErrors : [];
  paragraphs.forEach(function(text, idx) {
    var state = paragraphStates[idx] || 'pending';
    var errorText = paragraphErrors[idx] || '';
    items.push(
      '<div class="translation-detail-item">'
      + '<div class="translation-detail-item-title">第 ' + (idx + 1) + ' 段 · ' + escapeHtml(formatDraftStatusLabel(state)) + '</div>'
      + (text ? ('<div class="translation-detail-item-preview">' + escapeHtml(text) + '</div>') : '')
      + (errorText ? ('<div class="translation-detail-item-meta" style="color:var(--red);">错误：' + escapeHtml(errorText) + '</div>') : '')
      + '</div>'
    );
  });
  return items.length ? items.join('') : '<div class="translation-detail-copy">当前还没有段落草稿。</div>';
}

function renderTaskSessionDetails(payload) {
  var snapshot = (payload && payload.snapshot) || payload || {};
  lastUsageSnapshot = snapshot || {};
  store.taskSession.snapshot = snapshot || {};
  var details = document.getElementById('translationSessionDetails');
  if (!details) return;
  syncUsageTracking(snapshot);
  var display = getUsageDisplaySnapshot(snapshot);
  var sampleStats = isActiveTranslatePhase(display.phase) ? getUsageSampleStats() : { recentTokens: 0, tokenRate: 0 };
  var draft = store.streamDraft || createInitialStreamDraftState();
  var isFnm = isFnmTaskState(display);
  var metricHtml = [
    ['当前任务', (display.task && display.task.label) || '无'],
    ['任务日志', (display.task && display.task.log_relpath) || '-'],
    ['正文模型', display.translation_model_label || display.model || '-'],
    ['脚注回退模型', display.companion_model_label || '-'],
    ['请求数', formatUsageNumber(display.request_count)],
    ['Prompt Tokens', formatUsageNumber(display.prompt_tokens)],
    ['Completion Tokens', formatUsageNumber(display.completion_tokens)],
    ['总 Tokens', formatUsageNumber(display.total_tokens)],
    ['最近 1 分钟', formatUsageNumber(sampleStats.recentTokens) + ' tokens'],
    ['速率', formatTokenRate(sampleStats.tokenRate) + ' tokens/s'],
    ['最近更新', display.updated_at ? new Date(Number(display.updated_at) * 1000).toLocaleTimeString() : '-']
  ].map(function(item) {
    return '<div class="translation-detail-metric"><div class="translation-detail-label">'
      + escapeHtml(item[0]) + '</div><div class="translation-detail-value">'
      + escapeHtml(item[1]) + '</div></div>';
  }).join('');
  var currentLabel = isFnm
    ? (display.current_unit_label || (display.current_bp ? formatFnmUnitIndex(display.current_bp) : '等待 unit 进入翻译'))
    : formatPdfPageLabel(display.current_bp || draft.bp || store.reading.currentBp);
  var detailTitle = isFnm ? 'FNM 单元详情' : '普通翻译详情';
  var noteParts = [];
  if (draft.note) noteParts.push(draft.note);
  if (draft.lastError) noteParts.push('最近错误：' + draft.lastError);
  if (display.translation_model_label) {
    noteParts.unshift('正文模型：' + display.translation_model_label);
  }
  if (display.companion_model_label) {
    noteParts.push('脚注/尾注回退：' + display.companion_model_label);
  }
  if (isFnm && display.current_unit_pages) {
    noteParts.unshift('页范围：p.' + display.current_unit_pages);
  }
  details.innerHTML =
    '<div class="translation-detail-grid">' + metricHtml + '</div>'
    + '<div class="translation-detail-section">'
    + '<div class="translation-detail-section-title">' + escapeHtml(detailTitle) + '</div>'
    + '<div class="translation-detail-copy">当前位置：' + escapeHtml(currentLabel)
    + (noteParts.length ? ('<br>' + escapeHtml(noteParts.join(' · '))) : '')
    + '</div>'
    + '<div class="translation-detail-list">' + _draftListHtml(display, draft) + '</div>'
    + '</div>';
}

function refreshTaskSessionDetails() {
  renderTaskSessionDetails({ snapshot: lastUsageSnapshot || store.taskSession.snapshot || {} });
  return Promise.resolve(lastUsageSnapshot || store.taskSession.snapshot || {});
}

function startTaskDetailsPolling() {
  if (usagePoll) return;
  usagePoll = setInterval(function() {
    refreshTaskSessionDetails();
  }, 1000);
}

function stopTaskDetailsPolling() {
  if (!usagePoll) return;
  clearInterval(usagePoll);
  usagePoll = null;
}

function toggleTaskSessionDetails(forceOpen) {
  if (typeof forceOpen === 'boolean') {
    dispatch('set_task_details_open', { value: forceOpen });
  } else {
    dispatch('toggle_task_details');
  }
  var panel = document.getElementById('translationSessionDetails');
  var btn = document.getElementById('translationSessionToggleBtn');
  if (panel) {
    panel.classList.toggle('hidden', !store.ui.taskDetailsOpen);
  }
  if (btn) {
    btn.textContent = store.ui.taskDetailsOpen ? '收起详情' : '展开详情';
  }
  if (store.ui.taskDetailsOpen) {
    refreshTaskSessionDetails();
    startTaskDetailsPolling();
  } else {
    stopTaskDetailsPolling();
  }
  syncReadingUrl();
}

function showProgress(show) {
  var card = document.getElementById('translationSessionCard');
  if (card) {
    card.style.display = show ? '' : '';
  }
}

function setTranslateProgress(pct, label, stats, detail) {
  var bar = document.getElementById('translationSessionBar');
  var phase = document.getElementById('translationSessionPhase');
  var pctEl = document.getElementById('translationSessionPct');
  var summary = document.getElementById('translationSessionSummary');
  if (bar) bar.style.width = pct + '%';
  if (phase && label) phase.textContent = label;
  if (pctEl) pctEl.textContent = Math.round(pct) + '%';
  if (summary) {
    var parts = [];
    if (stats) parts.push(stats);
    if (detail) parts.push(detail);
    summary.textContent = parts.join(' · ');
  }
}

function closeTranslateSSE() {
  if (!translateES) return;
  translateES.close();
  translateES = null;
}

function startTranslateStatusPolling() {
  if (translateStatusPoll) return;
  translateStatusPoll = setInterval(function() {
    refreshTranslateStatus();
  }, 2000);
}

function stopTranslateStatusPolling() {
  if (!translateStatusPoll) return;
  clearInterval(translateStatusPoll);
  translateStatusPoll = null;
}

function isActiveTranslatePhase(phase) {
  return phase === 'running' || phase === 'stopping';
}

function hasPageProgressInStore() {
  return (
    (Array.isArray(store.pages.translatedBps) && store.pages.translatedBps.length > 0) ||
    (Array.isArray(store.pages.partialFailedBps) && store.pages.partialFailedBps.length > 0) ||
    (Array.isArray(store.pages.failedBps) && store.pages.failedBps.length > 0)
  );
}

function hasPageProgressInSnapshot(state) {
  return !!(
    state && (
      (Array.isArray(state.translated_bps) && state.translated_bps.length > 0) ||
      (Array.isArray(state.partial_failed_bps) && state.partial_failed_bps.length > 0) ||
      (Array.isArray(state.failed_bps) && state.failed_bps.length > 0)
    )
  );
}

function shouldHydrateTranslateDraft(state) {
  if (!state || !state.draft) return false;
  return !!(
    state.draft.active
    || (state.draft.status === 'throttled')
    || translateSessionActivated
    || hasRestorableDraft(state)
  );
}

function shouldShowTranslateSnapshot(state) {
  if (!state) return hasPageProgressInStore();
  if (!state.phase) return hasPageProgressInSnapshot(state) || hasPageProgressInStore();
  if (state.phase === 'idle') {
    return hasPageProgressInSnapshot(state) || hasPageProgressInStore();
  }
  if (isActiveTranslatePhase(state.phase)) return true;
  return translateSessionActivated || hasPageProgressInSnapshot(state) || hasPageProgressInStore();
}

function formatTranslatePhaseLabel(state) {
  var phase = state && state.phase ? state.phase : 'idle';
  var task = (state && state.task) || {};
  var label = formatUsagePhase(phase);
  if (task && task.label) {
    label = task.label + ' · ' + label;
  }
  if (phase === 'running' || phase === 'stopping') {
    if (isFnmTaskState(state)) {
      if (state && state.current_unit_label) {
        return label + ' · ' + state.current_unit_label;
      }
      if (state && state.current_bp) {
        return label + ' · ' + formatFnmUnitIndex(state.current_bp);
      }
      return label;
    }
    if (state && state.current_bp) {
      return label + ' · ' + formatPdfPageLabel(state.current_bp);
    }
  }
  return label;
}

function _renderTaskSessionActions(state) {
  var container = document.getElementById('translationSessionActions');
  if (!container) return;
  var html = [];
  var running = isActiveTranslatePhase(state && state.phase);
  if (!running) {
    html.push('<button type="button" class="btn btn-pri" onclick="startTranslateAll(' + Number(store.reading.currentBp || readingPageBpFallback || 1) + ');">启动普通翻译</button>');
    html.push('<button type="button" class="btn btn-gho" onclick="triggerGlossaryRetranslatePreview(' + Number(store.reading.currentBp || readingPageBpFallback || 1) + ', 0, this);">从本页起按词典补重译</button>');
    var resumeBp = getResumeStartBp(state);
    if (resumeBp) {
      html.push('<button type="button" class="btn btn-gho" onclick="resumeTranslateFromSnapshot(lastUsageSnapshot || {});">' + escapeHtml(getResumeActionLabel(state)) + '</button>');
    }
  } else {
    html.push('<button type="button" class="btn btn-pri" onclick="stopTranslate();" id="taskStopBtn">停止当前任务</button>');
  }
  container.innerHTML = html.join('');
}

function renderTranslateSnapshot(state) {
  state = state || {};
  if (isActiveTranslatePhase(state && state.phase)) {
    translateSessionActivated = true;
  }
  lastUsageSnapshot = state || lastUsageSnapshot;
  syncUsageTracking(state || {});
  if (shouldHydrateTranslateDraft(state)) {
    hydrateStreamDraftFromSnapshot(state);
  } else {
    resetStreamDraftState();
  }
  renderStreamDraftState();
  var subtitle = document.getElementById('translationSessionSubtitle');
  if (subtitle) {
    subtitle.textContent = state.task && state.task.label
      ? ('当前任务：' + state.task.label)
      : '当前无任务，可从这里启动普通翻译或词典补重译。';
  }
  _renderTaskSessionActions(state);
  var isFnmTask = isFnmTaskState(state);
  var totalPages = isFnmTask ? Number(state.total_units || 0) : Number(state.total_pages || 0);
  var processedPages = isFnmTask ? Number(state.processed_units || 0) : Number(state.processed_pages || 0);
  if (!isFnmTask && !totalPages) {
    totalPages = Number(store.pages.allBps.length || 0);
  }
  if (totalPages && processedPages > totalPages) {
    processedPages = totalPages;
  }
  var pct = totalPages ? (processedPages / totalPages) * 100 : 0;
  var stats = totalPages
    ? ('已处理 ' + processedPages + '/' + totalPages + (isFnmTask ? ' 个 unit' : ' 页'))
    : '当前没有活动任务';
  var detail = '已译 ' + Number(state.translated_paras || 0) + ' 段 / ' + Number(state.translated_chars || 0) + ' 字';
  if (Number(state.total_tokens || 0) > 0) {
    detail += ' · ' + Number(state.total_tokens || 0) + ' tokens';
  }
  setTranslateProgress(pct, formatTranslatePhaseLabel(state), stats, detail);
  renderTaskSessionDetails({ snapshot: state });
  if (isActiveTranslatePhase(state.phase)) {
    startTranslateStatusPolling();
    if (!translateES) {
      listenTranslateSSE();
    }
  } else {
    stopTranslateStatusPolling();
    closeTranslateSSE();
  }
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

function refreshReadingViewState() {
  var docId = requireReadingDocId('刷新阅读视图状态');
  if (!docId) return Promise.resolve(null);
  var url = (ROUTES.readingViewState || '/api/reading_view_state')
    + '?doc_id=' + encodeURIComponent(docId)
    + '&view=' + encodeURIComponent(store.readingView.mode || 'standard');
  return fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d || d.ok === false) {
        return d;
      }
      store.pages.translatedBps = Array.isArray(d.translated_bps) ? d.translated_bps.map(function(bp) { return Number(bp); }) : [];
      store.pages.failedBps = Array.isArray(d.failed_bps) ? d.failed_bps.map(function(bp) { return Number(bp); }) : [];
      store.pages.partialFailedBps = Array.isArray(d.partial_failed_bps) ? d.partial_failed_bps.map(function(bp) { return Number(bp); }) : [];
      store.pages.sourceOnlyBps = Array.isArray(d.source_only_bps) ? d.source_only_bps.map(function(bp) { return Number(bp); }) : [];
      store.pages.readingStatsDonePages = Number(d.reading_stats_done_pages || 0);
      renderPageNavigationState();
      updateProgressStatsText(lastUsageSnapshot || {});
      return d;
    });
}

function refreshTranslateStatus() {
  var docId = requireReadingDocId('刷新翻译状态');
  if (!docId) return Promise.resolve(null);
  var url = (ROUTES.translateStatus || '/translate_status') + '?doc_id=' + encodeURIComponent(docId);
  return fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      renderTranslateSnapshot(d);
      return refreshReadingViewState()
        .catch(function() { return null; })
        .then(function() {
          updateProgressStatsText(d);
          if (store.ui.taskDetailsOpen) {
            refreshTaskSessionDetails();
          }
          return d;
        });
    });
}

function startTranslateAll(startBp, forceRestart) {
  translateSessionActivated = true;
  setReadingStartBp(startBp);
  showProgress(true);
  setTranslateProgress(0, forceRestart ? '切换并启动普通翻译…' : '启动翻译…', '', '');
  var docId = requireReadingDocId('启动翻译', function(message) {
    setTranslateProgress(0, '启动失败', message, '');
  });
  if (!docId) return;

  var form = new FormData();
  form.append('start_bp', startBp);
  form.append('doc_title', BOOTSTRAP.docTitle || '');
  form.append('doc_id', docId);
  if (forceRestart) {
    form.append('force_restart', '1');
  }

  fetch(ROUTES.startTranslateAll || '/start_translate_all', {
    method: 'POST',
    headers: withCsrfHeaders(),
    body: form
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.status === 'already_running') {
        if (forceRestart) {
          setTranslateProgress(0, '启动失败', '当前翻译任务仍未停止，请稍后重试。', '');
          return;
        }
        var shouldSwitch = window.confirm('当前已有翻译任务在运行。要停止当前任务并启动普通连续翻译吗？');
        if (shouldSwitch) {
          startTranslateAll(startBp, true);
        } else {
          setTranslateProgress(0, '未切换', '保留当前翻译任务。', '');
        }
        return;
      }
      if (d.status === 'switch_timeout') {
        setTranslateProgress(0, '启动失败', '停止当前翻译超时，请稍后重试。', '');
        return;
      }
      if (d.error) {
        setTranslateProgress(0, '启动失败', d.message || d.error, '');
        return;
      }
      refreshTranslateStatus();
    });
}

function startFnmTranslate(forceRestart, startUnitIdx) {
  translateSessionActivated = true;
  showProgress(true);
  setTranslateProgress(0, '启动 FNM 翻译…', '', '');

  var docId = requireReadingDocId('启动 FNM 翻译', function(message) {
    setTranslateProgress(0, '启动失败', message, '');
  });
  if (!docId) return;

  var form = new FormData();
  form.append('doc_title', BOOTSTRAP.docTitle || '');
  if (forceRestart) {
    form.append('force_restart', '1');
  }
  if (startUnitIdx !== undefined && startUnitIdx !== null) {
    form.append('start_unit_idx', String(startUnitIdx));
  }

  fetch(ROUTES.fnmTranslate || ('/api/doc/' + encodeURIComponent(docId) + '/fnm/translate'), {
    method: 'POST',
    headers: withCsrfHeaders(),
    body: form
  })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.status === 'already_running') {
        if (forceRestart) {
          setTranslateProgress(0, '启动失败', '当前翻译任务仍未停止，请稍后重试。', '');
          return;
        }
        var shouldRestart = window.confirm('当前已有翻译任务在运行。要停止当前任务并切换到 FNM 翻译吗？');
        if (shouldRestart) {
          startFnmTranslate(true);
        } else {
          setTranslateProgress(0, '未切换', '保留当前翻译任务。', '');
        }
        return;
      }
      if (d.error) {
        setTranslateProgress(0, '启动失败', d.message || d.error, '');
        return;
      }
      refreshTranslateStatus();
    })
    .catch(function(err) {
      setTranslateProgress(0, '启动失败', String(err || 'unknown_error'), '');
    });
}

function listenTranslateSSE() {
  closeTranslateSSE();
  var docId = requireReadingDocId('订阅翻译进度');
  if (!docId) return;
  translateES = new EventSource((ROUTES.translateSse || '/translate_all_sse') + '?doc_id=' + encodeURIComponent(docId));

  translateES.addEventListener('init', function(e) {
    refreshTranslateStatus();
  });

  translateES.addEventListener('page_start', function(e) {
    resetStreamDraftState();
    refreshTranslateStatus();
  });

  translateES.addEventListener('stream_page_init', function(e) {
    var d = JSON.parse(e.data);
    dispatch('stream_page_init', { data: d });
    renderStreamDraftState();
  });

  translateES.addEventListener('stream_para_delta', function(e) {
    applyStreamDelta(JSON.parse(e.data));
  });

  translateES.addEventListener('stream_para_start', function(e) {
    var d = JSON.parse(e.data);
    dispatch('stream_para_start', { data: d });
    renderStreamDraftState();
  });

  translateES.addEventListener('stream_para_done', function(e) {
    var d = JSON.parse(e.data);
    dispatch('stream_para_done', { data: d });
    renderStreamDraftState();
  });

  translateES.addEventListener('stream_para_error', function(e) {
    var d = JSON.parse(e.data);
    dispatch('stream_para_error', { data: d });
    renderStreamDraftState();
  });

  translateES.addEventListener('stream_page_aborted', function(e) {
    var d = JSON.parse(e.data);
    dispatch('stream_page_aborted', { data: d });
    renderStreamDraftState();
  });

  translateES.addEventListener('stream_usage', function(e) {
    applyStreamUsage(JSON.parse(e.data));
  });

  translateES.addEventListener('rate_limit_wait', function(e) {
    var d = JSON.parse(e.data);
    dispatch('rate_limit_wait', { data: d });
    renderStreamDraftState();
  });

  translateES.addEventListener('page_done', function(e) {
    var d = JSON.parse(e.data);
    dispatch('stream_page_done', { data: d });
    if (isFnmDraftMode(store.streamDraft, lastUsageSnapshot || {})) {
      var affectedBps = Array.isArray(d.affected_bps) ? d.affected_bps.map(function(bp) { return Number(bp); }).filter(Boolean) : [];
      if (affectedBps.length) {
        dispatch('mark_pages_done', { bps: affectedBps });
        if (affectedBps.indexOf(Number(store.reading.currentBp || 0)) >= 0
            && !store.guards.manualNavigationInFlight
            && !currentPageHasEntry) {
          forceReloadReadingPage(store.reading.currentBp);
        }
      }
    } else {
      var hasDraftError = !!d.partial_failed || (
        Array.isArray(store.streamDraft.paragraphStates)
        && store.streamDraft.paragraphStates.some(function(state) { return state === 'error'; })
      );
      dispatch('mark_page_done', { bp: d.bp, partialFailed: hasDraftError });
      scheduleCommittedPageRefresh(d.bp);
    }
    renderStreamDraftState();
    refreshTranslateStatus();
  });

  translateES.addEventListener('page_error', function(e) {
    var d = JSON.parse(e.data);
    if (!isFnmDraftMode(store.streamDraft, lastUsageSnapshot || {})) {
      dispatch('mark_page_error', { bp: d.bp });
    }
    refreshTranslateStatus();
  });

  translateES.addEventListener('all_done', function(e) {
    resetStreamDraftState();
    renderStreamDraftState();
    refreshTranslateStatus();
  });

  translateES.addEventListener('stopped', function(e) {
    refreshTranslateStatus();
  });

  translateES.addEventListener('error', function() {
    if (document.hidden) return;
    refreshTranslateStatus();
  });

  translateES.addEventListener('idle', function() {
    closeTranslateSSE();
    refreshTranslateStatus();
  });
}

function stopTranslate() {
  var btn = document.getElementById('taskStopBtn');
  if (btn) {
    btn.textContent = '停止中…';
    btn.disabled = true;
  }
  var docId = requireReadingDocId('停止翻译', function(message) {
    if (btn) {
      btn.textContent = '停止当前任务';
      btn.disabled = false;
    }
    console.error(message);
  });
  if (!docId) return;

  fetch(ROUTES.stopTranslate || '/stop_translate', {
    method: 'POST',
    headers: withCsrfHeaders({'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}),
    body: 'doc_id=' + encodeURIComponent(docId)
  })
    .then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(d) {
      if (d.status !== 'stopping') {
        throw new Error('stop rejected');
      }
    })
    .catch(function(err) {
      if (btn) {
        btn.textContent = '停止当前任务';
        btn.disabled = false;
      }
      console.error('停止请求失败:', err);
    });
}
