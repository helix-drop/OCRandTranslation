// Settings page — panel navigation, slot mode sync, providers bulk save.
// No framework; relies on window.withCsrfHeaders / getCsrfToken from base.html.

(function () {
  'use strict';

  var HASH_ALIAS = {
    'glossary': 'glossary',
    'toc-file': 'toc',
    'toc-offset': 'toc'
  };
  var DEFAULT_PANEL = 'providers';

  function activatePanel(key) {
    var panels = document.querySelectorAll('[data-panel]');
    var items = document.querySelectorAll('[data-nav]');
    var found = false;
    panels.forEach(function (p) {
      var match = p.getAttribute('data-panel') === key;
      p.classList.toggle('active', match);
      if (match) found = true;
    });
    items.forEach(function (i) {
      i.classList.toggle('active', i.getAttribute('data-nav') === key);
    });
    if (!found) return false;
    if (history.replaceState) {
      history.replaceState(null, '', '#' + key);
    }
    return true;
  }

  function initNav() {
    document.querySelectorAll('[data-nav]').forEach(function (el) {
      el.addEventListener('click', function () {
        activatePanel(el.getAttribute('data-nav'));
      });
    });
    var raw = (window.location.hash || '').replace(/^#/, '');
    var target = HASH_ALIAS[raw] || raw || DEFAULT_PANEL;
    if (!activatePanel(target)) {
      activatePanel(DEFAULT_PANEL);
    }
  }

  function syncModelPoolSlotCard(card) {
    if (!card) return;
    var mode = card.getAttribute('data-mode') || 'builtin';
    var provider = '';
    var providerSel = card.querySelector('[data-slot-provider]');
    if (providerSel) provider = providerSel.value;

    card.querySelectorAll('[data-slot-mode-panel]').forEach(function (panel) {
      panel.style.display = panel.getAttribute('data-slot-mode-panel') === mode ? '' : 'none';
    });
    card.querySelectorAll('[data-slot-thinking-row]').forEach(function (row) {
      row.style.display = mode === 'empty' ? 'none' : '';
    });
    card.querySelectorAll('[data-provider-field]').forEach(function (field) {
      var name = field.getAttribute('data-provider-field');
      var show = false;
      if (mode === 'custom' && name === 'qwen_region') {
        show = provider === 'qwen' || provider === 'qwen_mt';
      }
      if (mode === 'custom' && name === 'endpoint') {
        show = provider === 'openai_compatible' || provider === 'mimo_token_plan';
      }
      field.style.display = show ? '' : 'none';
    });
    card.querySelectorAll('.seg-tabs .seg').forEach(function (seg) {
      seg.classList.toggle('active', seg.getAttribute('data-mode') === mode);
    });
  }

  function initSlotCards() {
    document.querySelectorAll('[data-slot-card]').forEach(function (card) {
      card.querySelectorAll('.seg-tabs .seg').forEach(function (seg) {
        seg.addEventListener('click', function () {
          var newMode = seg.getAttribute('data-mode');
          card.setAttribute('data-mode', newMode);
          var hidden = card.querySelector('[data-slot-mode-input]');
          if (hidden) hidden.value = newMode;
          syncModelPoolSlotCard(card);
        });
      });
      var providerSel = card.querySelector('[data-slot-provider]');
      if (providerSel) {
        providerSel.addEventListener('change', function () { syncModelPoolSlotCard(card); });
      }
      syncModelPoolSlotCard(card);
    });
  }

  var PROVIDER_SECTIONS = [
    { section: 'paddle',    field: 'paddle_token' },
    { section: 'deepseek',  field: 'deepseek_key' },
    { section: 'dashscope', field: 'dashscope_key' },
    { section: 'glm',       field: 'glm_api_key' },
    { section: 'kimi',      field: 'kimi_api_key' },
    { section: 'mimo',      field: 'mimo_api_key' }
  ];

  function setRowStatus(row, kind) {
    var pill = row.querySelector('[data-status]');
    if (!pill) return;
    pill.classList.remove('ok', 'no', 'dirty');
    if (kind === 'ok')    { pill.classList.add('ok');    pill.textContent = '✓ 已配置'; }
    if (kind === 'no')    { pill.classList.add('no');    pill.textContent = '! 未配置'; }
    if (kind === 'dirty') { pill.classList.add('dirty'); pill.textContent = '● 未保存'; }
  }

  function refreshRowStatus(row) {
    var input = row.querySelector('input[data-key]');
    if (!input) return;
    var initial = input.getAttribute('data-initial') || '';
    var current = input.value.trim();
    if (current !== initial) {
      setRowStatus(row, 'dirty');
      return;
    }
    setRowStatus(row, current ? 'ok' : 'no');
  }

  function initProvidersPanel() {
    var form = document.getElementById('providersForm');
    if (!form) return;
    document.querySelectorAll('.prov-row').forEach(function (row) {
      var input = row.querySelector('input[data-key]');
      if (!input) return;
      input.setAttribute('data-initial', input.value);
      refreshRowStatus(row);
      input.addEventListener('input', function () { refreshRowStatus(row); });
    });

    form.addEventListener('submit', function (evt) {
      evt.preventDefault();
      saveAllProviders(form);
    });
  }

  function saveAllProviders(form) {
    var csrfInput = form.querySelector('input[name="_csrf_token"]');
    var docIdInput = form.querySelector('input[name="doc_id"]');
    var csrf = csrfInput ? csrfInput.value : '';
    var docId = docIdInput ? docIdInput.value : '';
    var statusEl = document.getElementById('providersStatus');
    if (statusEl) { statusEl.textContent = '保存中…'; statusEl.style.color = 'var(--txS)'; }

    var jobs = [];
    PROVIDER_SECTIONS.forEach(function (spec) {
      var row = form.querySelector('[data-section="' + spec.section + '"]');
      if (!row) return;
      var input = row.querySelector('input[data-key]');
      if (!input) return;
      var initial = input.getAttribute('data-initial') || '';
      if (input.value === initial) return;

      var fd = new FormData();
      fd.append('_csrf_token', csrf);
      fd.append('section', spec.section);
      fd.append('doc_id', docId);
      fd.append(spec.field, input.value);

      jobs.push(fetch('/save_settings', {
        method: 'POST',
        headers: window.withCsrfHeaders ? window.withCsrfHeaders() : {},
        body: fd,
        redirect: 'manual'
      }).then(function (resp) {
        return { spec: spec, row: row, ok: resp.ok || resp.type === 'opaqueredirect' };
      }).catch(function () {
        return { spec: spec, row: row, ok: false };
      }));
    });

    if (!jobs.length) {
      if (statusEl) { statusEl.textContent = '没有变更'; statusEl.style.color = 'var(--txS)'; }
      return;
    }

    Promise.all(jobs).then(function (results) {
      var failed = results.filter(function (r) { return !r.ok; });
      failed.forEach(function (r) { setRowStatus(r.row, 'no'); });
      if (failed.length === 0) {
        window.location.reload();
      } else if (statusEl) {
        statusEl.textContent = '部分保存失败（' + failed.length + '），请检查标红行';
        statusEl.style.color = 'var(--red)';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initNav();
    initSlotCards();
    initProvidersPanel();
  });

  window.syncModelPoolSlotCard = syncModelPoolSlotCard;
})();
