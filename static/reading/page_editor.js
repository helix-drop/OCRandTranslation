function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function setPageEditorStatus(message, isError) {
  var node = document.getElementById('pageEditorStatus');
  if (!node) return;
  node.textContent = message || '';
  node.style.color = isError ? 'var(--red)' : 'var(--txL)';
}

function defaultFnmRefRow() {
  return { kind: 'footnote', note_id: '' };
}

function fetchJsonWithMeta(url, options) {
  return fetch(url, options)
    .then(function(response) {
      return response.json().then(function(data) {
        return {
          ok: response.ok,
          data: data,
        };
      });
    });
}

function normalizePageEditorRows(rows) {
  return (Array.isArray(rows) ? rows : []).map(function(row, idx) {
    var sectionPath = Array.isArray(row && row.section_path)
      ? row.section_path.filter(Boolean).map(function(item) { return String(item); })
      : (typeof (row && row.section_path) === 'string'
        ? String(row.section_path || '').split('>').map(function(item) { return String(item || '').trim(); }).filter(Boolean)
        : []);
    var fnmRefs = Array.isArray(row && row.fnm_refs)
      ? row.fnm_refs.map(function(item) {
          return {
            kind: String(item && item.kind || ''),
            note_id: String(item && item.note_id || '')
          };
        })
      : [];
    return {
      order: idx,
      kind: String(row && row.kind || 'body'),
      heading_level: Number(row && row.heading_level || 0),
      original: String(row && row.original || ''),
      translation: String(row && row.translation || ''),
      pages: String(row && row.pages || store.reading.currentBp || ''),
      start_bp: Number(row && row.start_bp || store.reading.currentBp || 0),
      end_bp: Number(row && row.end_bp || store.reading.currentBp || 0),
      print_page_label: String(row && row.print_page_label || ''),
      footnotes: String(row && row.footnotes || ''),
      footnotes_translation: String(row && row.footnotes_translation || ''),
      note_kind: String(row && row.note_kind || ''),
      note_marker: String(row && row.note_marker || ''),
      note_number: row && row.note_number != null ? row.note_number : null,
      note_section_title: String(row && row.note_section_title || ''),
      note_confidence: Number(row && row.note_confidence || 0),
      cross_page: row && row.cross_page ? String(row.cross_page) : null,
      section_path: sectionPath,
      fnm_refs: fnmRefs,
    };
  });
}

function defaultPageEditorRow() {
  return {
    order: store.pageEditor.rows.length,
    kind: 'body',
    heading_level: 0,
    original: '',
    translation: '',
    pages: String(store.reading.currentBp || ''),
    start_bp: Number(store.reading.currentBp || 0),
    end_bp: Number(store.reading.currentBp || 0),
    print_page_label: '',
    footnotes: '',
    footnotes_translation: '',
    note_kind: '',
    note_marker: '',
    note_number: null,
    note_section_title: '',
    note_confidence: 0,
    cross_page: null,
    section_path: [],
    fnm_refs: [],
  };
}

function isFnmPageEditorView() {
  return String(store.pageEditor.view || store.readingView.mode || 'standard') === 'fnm';
}

function pageEditorSectionPathInputValue(sectionPath) {
  return (Array.isArray(sectionPath) ? sectionPath : []).filter(Boolean).join(' > ');
}

function renderPageEditorCrossPageOptions(value) {
  var selected = value || '';
  return [
    ['', 'none'],
    ['cont_prev', 'cont_prev'],
    ['cont_next', 'cont_next'],
    ['cont_both', 'cont_both'],
    ['merged_next', 'merged_next']
  ].map(function(item) {
    return '<option value="' + item[0] + '"' + (selected === item[0] ? ' selected' : '') + '>' + item[1] + '</option>';
  }).join('');
}

function renderPageEditorFnmRefs(idx, row) {
  var refs = Array.isArray(row.fnm_refs) && row.fnm_refs.length ? row.fnm_refs : [defaultFnmRefRow()];
  return refs.map(function(ref, refIdx) {
    return '<div class="page-editor-ref-row">'
      + '<select class="inp" onchange="updatePageEditorFnmRefField(' + idx + ', ' + refIdx + ', \'kind\', this.value)">'
      + '<option value="footnote"' + (String(ref.kind || '') === 'footnote' ? ' selected' : '') + '>footnote</option>'
      + '<option value="endnote"' + (String(ref.kind || '') === 'endnote' ? ' selected' : '') + '>endnote</option>'
      + '</select>'
      + '<input class="inp" type="text" placeholder="note_id" value="' + escapeHtml(ref.note_id || '') + '" oninput="updatePageEditorFnmRefField(' + idx + ', ' + refIdx + ', \'note_id\', this.value)">'
      + '<button type="button" class="btn btn-gho" onclick="insertPageEditorFnmRef(' + idx + ', ' + refIdx + ');">新增</button>'
      + '<button type="button" class="btn btn-gho" onclick="removePageEditorFnmRef(' + idx + ', ' + refIdx + ');">删除</button>'
      + '</div>';
  }).join('');
}

function renderPageEditorAdvancedFields(idx, row) {
  if (!isFnmPageEditorView()) {
    return '';
  }
  return '<div class="page-editor-row-advanced">'
    + '<div class="page-editor-row-field"><label>跨页关系</label><select class="inp" onchange="updatePageEditorField(' + idx + ', \'cross_page\', this.value)">' + renderPageEditorCrossPageOptions(row.cross_page) + '</select></div>'
    + '<div class="page-editor-row-field"><label>章节路径</label><input class="inp" type="text" placeholder="Chapter > Section > Subsection" value="' + escapeHtml(pageEditorSectionPathInputValue(row.section_path)) + '" oninput="updatePageEditorSectionPath(' + idx + ', this.value)"></div>'
    + '<div class="page-editor-row-field page-editor-row-field-wide"><label>引用的注释</label><div class="page-editor-ref-list">' + renderPageEditorFnmRefs(idx, row) + '</div></div>'
    + '</div>';
}

function renderPageEditorHeadingLevelOptions(row) {
  return [0, 1, 2, 3].map(function(level) {
    var label = level === 0 ? '正文' : ('标题 H' + level);
    return '<option value="' + level + '"' + (Number(row.heading_level || 0) === level ? ' selected' : '') + '>' + label + '</option>';
  }).join('');
}

function renderPageEditorRowMeta(idx, row) {
  return '<div class="page-editor-row-meta"><span class="reading-page-chip">第 ' + (idx + 1) + ' 段</span><span class="reading-page-chip">' + escapeHtml(row.kind === 'heading' ? '标题' : '正文') + '</span></div>';
}

function renderPageEditorRowActions(idx) {
  return '<div class="page-editor-row-actions">'
    + '<button type="button" class="btn btn-gho" onclick="insertPageEditorRow(' + idx + ', false);">上方插入</button>'
    + '<button type="button" class="btn btn-gho" onclick="insertPageEditorRow(' + idx + ', true);">下方插入</button>'
    + '<button type="button" class="btn btn-gho" onclick="movePageEditorRow(' + idx + ', -1);"' + (idx === 0 ? ' disabled' : '') + '>上移</button>'
    + '<button type="button" class="btn btn-gho" onclick="movePageEditorRow(' + idx + ', 1);"' + (idx === store.pageEditor.rows.length - 1 ? ' disabled' : '') + '>下移</button>'
    + '<button type="button" class="btn btn-gho" onclick="removePageEditorRow(' + idx + ');">删除</button>'
    + '</div>';
}

function renderPageEditorBasicFields(idx, row) {
  return '<div class="page-editor-row-fields">'
    + '<div class="page-editor-row-field"><label>段落类型</label><select class="inp" onchange="updatePageEditorField(' + idx + ', \'kind\', this.value)"><option value="body"' + (row.kind === 'body' ? ' selected' : '') + '>正文</option><option value="heading"' + (row.kind === 'heading' ? ' selected' : '') + '>标题</option></select></div>'
    + '<div class="page-editor-row-field"><label>标题级别</label><select class="inp" onchange="updatePageEditorField(' + idx + ', \'heading_level\', this.value)">' + renderPageEditorHeadingLevelOptions(row) + '</select></div>'
    + '<div class="page-editor-row-field"><label>原文</label><textarea class="inp" oninput="updatePageEditorField(' + idx + ', \'original\', this.value)">' + escapeHtml(row.original) + '</textarea></div>'
    + '<div class="page-editor-row-field"><label>译文</label><textarea class="inp" oninput="updatePageEditorField(' + idx + ', \'translation\', this.value)">' + escapeHtml(row.translation) + '</textarea></div>'
    + '</div>';
}

function renderPageEditorRow(idx, row) {
  return '<div class="page-editor-row">'
    + '<div class="page-editor-row-head">'
    + renderPageEditorRowMeta(idx, row)
    + renderPageEditorRowActions(idx)
    + '</div>'
    + renderPageEditorBasicFields(idx, row)
    + renderPageEditorAdvancedFields(idx, row)
    + '</div>';
}

function reindexPageEditorRows() {
  store.pageEditor.rows = normalizePageEditorRows(store.pageEditor.rows);
}

function renderPageEditorRows() {
  var container = document.getElementById('pageEditorRows');
  if (!container) return;
  reindexPageEditorRows();
  container.innerHTML = store.pageEditor.rows.map(function(row, idx) {
    return renderPageEditorRow(idx, row);
  }).join('');
}

function updatePageEditorField(idx, key, value) {
  if (!store.pageEditor.rows[idx]) return;
  if (key === 'heading_level') {
    store.pageEditor.rows[idx][key] = Number(value || 0);
  } else {
    store.pageEditor.rows[idx][key] = value || null;
  }
  if (key === 'kind' && value !== 'heading') {
    store.pageEditor.rows[idx].heading_level = 0;
  }
}

function updatePageEditorSectionPath(idx, value) {
  if (!store.pageEditor.rows[idx]) return;
  store.pageEditor.rows[idx].section_path = String(value || '')
    .split('>')
    .map(function(item) { return String(item || '').trim(); })
    .filter(Boolean);
}

function updatePageEditorFnmRefField(idx, refIdx, key, value) {
  if (!store.pageEditor.rows[idx]) return;
  if (!Array.isArray(store.pageEditor.rows[idx].fnm_refs) || !store.pageEditor.rows[idx].fnm_refs.length) {
    store.pageEditor.rows[idx].fnm_refs = [defaultFnmRefRow()];
  }
  if (!store.pageEditor.rows[idx].fnm_refs[refIdx]) {
    store.pageEditor.rows[idx].fnm_refs[refIdx] = defaultFnmRefRow();
  }
  store.pageEditor.rows[idx].fnm_refs[refIdx][key] = String(value || '');
}

function insertPageEditorFnmRef(idx, refIdx) {
  if (!store.pageEditor.rows[idx]) return;
  if (!Array.isArray(store.pageEditor.rows[idx].fnm_refs)) {
    store.pageEditor.rows[idx].fnm_refs = [];
  }
  store.pageEditor.rows[idx].fnm_refs.splice(Number(refIdx || 0) + 1, 0, defaultFnmRefRow());
  renderPageEditorRows();
}

function removePageEditorFnmRef(idx, refIdx) {
  if (!store.pageEditor.rows[idx] || !Array.isArray(store.pageEditor.rows[idx].fnm_refs)) return;
  store.pageEditor.rows[idx].fnm_refs.splice(refIdx, 1);
  if (!store.pageEditor.rows[idx].fnm_refs.length) {
    store.pageEditor.rows[idx].fnm_refs = [defaultFnmRefRow()];
  }
  renderPageEditorRows();
}

function insertPageEditorRow(idx, after) {
  var nextRow = defaultPageEditorRow();
  if (idx < 0 || idx >= store.pageEditor.rows.length) {
    store.pageEditor.rows.push(nextRow);
  } else {
    store.pageEditor.rows.splice(idx + (after ? 1 : 0), 0, nextRow);
  }
  renderPageEditorRows();
}

function movePageEditorRow(idx, delta) {
  var target = idx + Number(delta || 0);
  if (target < 0 || target >= store.pageEditor.rows.length) return;
  var current = store.pageEditor.rows[idx];
  store.pageEditor.rows[idx] = store.pageEditor.rows[target];
  store.pageEditor.rows[target] = current;
  renderPageEditorRows();
}

function removePageEditorRow(idx) {
  store.pageEditor.rows.splice(idx, 1);
  if (!store.pageEditor.rows.length) {
    store.pageEditor.rows.push(defaultPageEditorRow());
  }
  renderPageEditorRows();
}

function closePageEditor() {
  var modal = document.getElementById('pageEditorModal');
  if (modal) {
    modal.classList.add('hidden');
  }
  store.pageEditor.open = false;
  store.pageEditor.view = 'standard';
  setPageEditorStatus('');
}

function renderPageEditorHistory() {
  var panel = document.getElementById('pageEditorHistoryPanel');
  if (!panel) return;
  if (!store.pageEditor.historyOpen) {
    panel.classList.add('hidden');
    return;
  }
  panel.classList.remove('hidden');
  if (!store.pageEditor.history.length) {
    panel.innerHTML = '<div class="translation-detail-copy">还没有本页整页编辑历史。</div>';
    return;
  }
  panel.innerHTML = store.pageEditor.history.map(function(item) {
    var entry = item.entry || {};
    var segments = Array.isArray(entry._page_entries) ? entry._page_entries : [];
    var preview = segments.slice(0, 2).map(function(seg) {
      return escapeHtml((seg.translation || seg.original || '').slice(0, 80));
    }).join('<br>');
    return '<div class="translation-detail-item">'
      + '<div class="translation-detail-item-title">' + new Date(Number(item.created_at || 0) * 1000).toLocaleString() + '</div>'
      + '<div class="translation-detail-item-meta">来源：' + escapeHtml(item.revision_source || 'page_editor') + '</div>'
      + '<div class="translation-detail-item-preview">' + preview + '</div>'
      + '</div>';
  }).join('');
}

function togglePageEditorHistory() {
  if (!store.pageEditor.open) return;
  store.pageEditor.historyOpen = !store.pageEditor.historyOpen;
  if (store.pageEditor.historyOpen && !store.pageEditor.historyLoaded) {
    var docId = requireReadingDocId('加载本页历史');
    if (!docId) return;
    var historyUrl = (ROUTES.pageEditorHistory || '/api/page_editor/history')
      + '?doc_id=' + encodeURIComponent(docId)
      + '&bp=' + encodeURIComponent(store.reading.currentBp);
    if (isFnmPageEditorView()) {
      historyUrl += '&view=fnm';
    }
    fetchJsonWithMeta(historyUrl)
      .then(function(data) {
        store.pageEditor.history = Array.isArray(data && data.data && data.data.revisions) ? data.data.revisions : [];
        store.pageEditor.historyLoaded = true;
        renderPageEditorHistory();
      })
      .catch(function(err) {
        setPageEditorStatus('加载本页历史失败：' + err, true);
      });
    return;
  }
  renderPageEditorHistory();
}

function openPageEditor() {
  var modal = document.getElementById('pageEditorModal');
  if (!modal) return;
  var docId = requireReadingDocId('打开页编辑器');
  if (!docId) return;
  store.pageEditor.loading = true;
  setPageEditorStatus('正在加载本页段落…');
  var editorUrl = (ROUTES.pageEditor || '/api/page_editor')
    + '?doc_id=' + encodeURIComponent(docId)
    + '&bp=' + encodeURIComponent(store.reading.currentBp);
  if (store.readingView.mode === 'fnm') {
    editorUrl += '&view=fnm';
  }
  fetchJsonWithMeta(editorUrl)
    .then(function(result) {
      if (!result.ok || !result.data || result.data.ok === false) {
        throw new Error((result.data && result.data.error) || '当前页还没有可编辑内容');
      }
      store.pageEditor.page = result.data.page || null;
      store.pageEditor.view = String(result.data.view || store.readingView.mode || 'standard');
      store.pageEditor.rows = normalizePageEditorRows(result.data.rows || []);
      store.pageEditor.history = [];
      store.pageEditor.historyLoaded = false;
      store.pageEditor.historyOpen = false;
      renderPageEditorRows();
      renderPageEditorHistory();
      modal.classList.remove('hidden');
      store.pageEditor.open = true;
      var subtitle = document.getElementById('pageEditorSubtitle');
      if (subtitle) {
        subtitle.textContent = isFnmPageEditorView()
          ? '整页原子保存。可修改段落、章节路径、跨页关系和引用到的脚注/尾注。'
          : '整页原子保存。新增段落需要同时填写原文与译文。';
      }
      setPageEditorStatus(isFnmPageEditorView()
        ? '已载入当前页 FNM 投影，可增删段落并整页保存。'
        : '已载入当前页，可增删段落并整页保存。');
    })
    .catch(function(err) {
      setPageEditorStatus(String(err || '打开页编辑器失败'), true);
      alert(String(err || '打开页编辑器失败'));
    })
    .finally(function() {
      store.pageEditor.loading = false;
    });
}

function savePageEditor() {
  if (!store.pageEditor.page) return;
  var docId = requireReadingDocId('保存本页段落');
  if (!docId) return;
  store.pageEditor.saving = true;
  setPageEditorStatus('正在保存本页段落…');
  fetchJsonWithMeta((ROUTES.pageEditor || '/api/page_editor') + '?doc_id=' + encodeURIComponent(docId), {
    method: 'POST',
    headers: withCsrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      bp: store.reading.currentBp,
      view: isFnmPageEditorView() ? 'fnm' : 'standard',
      base_updated_at: store.pageEditor.page.updated_at,
      rows: normalizePageEditorRows(store.pageEditor.rows),
    }),
  })
    .then(function(result) {
      if (!result.ok || !result.data || result.data.ok === false) {
        throw new Error((result.data && result.data.error) || '保存失败');
      }
      setPageEditorStatus('保存成功，正在刷新当前页…');
      window.location.reload();
    })
    .catch(function(err) {
      setPageEditorStatus(String(err || '保存失败'), true);
    })
    .finally(function() {
      store.pageEditor.saving = false;
    });
}
