# 设置页重新设计 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `templates/settings.html` 从 12 张 card 的竖长页重构成"左侧分组导航 + 右侧单面板"，沿用现有暖米色主题；后端与字段协议完全不变。

**Architecture:** 单模板 + 新 CSS + 新 JS，共用模型槽位 Jinja partial。面板切换用客户端 JS（hash 可直达）；Providers 批量保存用 JS 逐 section AJAX 到现有 `/save_settings`；模型池继续走原生 form POST。

**Tech Stack:** Jinja2 模板、原生 CSS 变量（`--bg / --card / --acc / --grn / --red / --blu / --txt / --txS / --txL` 等）、vanilla JS（无框架），Flask 路由不动。

**Spec 参考:** `docs/superpowers/plans/../specs/2026-04-24-settings-page-redesign-design.md`

---

## 文件规划

| 路径 | 动作 | 职责 |
| --- | --- | --- |
| `static/settings.css` | 新建 | 设置页全部专用样式（shell / sidebar / prov-row / slot-card / segmented tabs / pill 等），使用主题变量 |
| `static/settings.js` | 新建 | 面板导航、hash 同步、slot 模式切换（迁移原 `syncModelPoolSlotCard`）、Providers 批量保存、状态 pill 刷新 |
| `templates/_settings_model_slot.html` | 新建 | 单个模型槽位的 Jinja partial，翻译池 / FNM 池共用 |
| `templates/settings.html` | 全量重写 | 顶部条 + 左导航 + 7 个面板容器 |
| `tests/integration/test_settings_page_redesign.py` | 新建 | smoke：sidebar 7 个面板、Providers 6 行、两个池各 3 槽、旧锚点兼容、关键字符串保留 |

**不改的文件**：`web/settings_routes.py`、`web/settings_support.py`、`config.py`、`model_capabilities.py`、`templates/base.html`（`extra_head` / `scripts` block 已存在）。

---

## Task 1 · 新建 settings.css 骨架 + 主题变量绑定

**Files:**
- Create: `static/settings.css`

- [ ] **Step 1: 写 CSS 骨架（shell / sidebar / panel / 通用 pill / logo 色块）**

写入 `static/settings.css`：

```css
/* Settings page — sidebar + panel layout.
   All colors go through theme vars declared in static/style.css. */

.settings-shell {
  display: flex;
  background: var(--card);
  border: 1px solid var(--bdr);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(44, 36, 22, .04);
  min-height: 560px;
}

.settings-side {
  width: 200px;
  flex-shrink: 0;
  background: var(--bg2);
  border-right: 1px solid var(--bdr);
  padding: 14px 8px;
}
.settings-side .grp {
  font-size: 10px;
  color: var(--txL);
  text-transform: uppercase;
  letter-spacing: .6px;
  padding: 10px 10px 4px;
}
.settings-side .nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--txS);
  cursor: pointer;
  margin-bottom: 1px;
  user-select: none;
  border: none;
  background: transparent;
  width: 100%;
  text-align: left;
  font-family: inherit;
}
.settings-side .nav-item:hover { background: var(--bdrL); }
.settings-side .nav-item.active {
  background: var(--card);
  color: var(--txt);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(44, 36, 22, .06);
}
.settings-side .nav-item .dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.settings-side .nav-item .count {
  margin-left: auto;
  font-size: 10px;
  color: var(--txL);
  background: var(--bdrL);
  padding: 1px 6px;
  border-radius: 8px;
}
.settings-side .nav-item.active .count { background: var(--bg2); }

.settings-main {
  flex: 1;
  min-width: 0;
  padding: 20px 24px;
  overflow: auto;
}
.settings-main .panel-h {
  font-size: 18px;
  font-weight: 700;
  color: var(--txt);
  margin: 0 0 4px;
}
.settings-main .panel-sub {
  font-size: 12px;
  color: var(--txS);
  margin-bottom: 16px;
  line-height: 1.6;
}
.settings-main .section-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.settings-main .section-hd .lbl {
  font-size: 11px;
  color: var(--txL);
  text-transform: uppercase;
  letter-spacing: .5px;
  font-weight: 600;
}

/* pills */
.pill {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
  flex-shrink: 0;
}
.pill.ok   { background: #e6f4ea; color: var(--grn); border: 1px solid #b7e0c4; }
.pill.no   { background: #fbe9e7; color: var(--red); border: 1px solid #f2c4be; }
.pill.gray { background: var(--bdrL); color: var(--txS); }
.pill.dirty { background: #fef3c7; color: #7a5a00; border: 1px solid #f5d87a; }

/* panel visibility — JS toggles .hidden */
[data-panel] { display: none; }
[data-panel].active { display: block; }

.settings-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}
.settings-topbar h1 {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
}
.settings-topbar .cur-models {
  font-size: 12px;
  color: var(--txS);
}
```

- [ ] **Step 2: 补 Providers 行 / slot 卡片 / segmented tabs / footer 样式**

追加到同一文件末尾：

```css
/* Providers rows */
.prov-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--bdr);
  border-radius: 10px;
  background: var(--cardA);
  margin-bottom: 6px;
}
.prov-logo {
  width: 26px; height: 26px;
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: #fff;
  flex-shrink: 0;
}
.prov-logo.lg-ps { background: #0071e3; }
.prov-logo.lg-ds { background: #4d6bfe; }
.prov-logo.lg-qw { background: #615ced; }
.prov-logo.lg-gl { background: #0084ff; }
.prov-logo.lg-km { background: #111; }
.prov-logo.lg-mm { background: #ff6b35; }

.prov-row .prov-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--txt);
  min-width: 120px;
}
.prov-row .prov-hint {
  font-size: 11px;
  color: var(--txL);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prov-row .prov-key {
  width: 200px;
  font-family: ui-monospace, Menlo, monospace;
}
.prov-row .prov-link {
  color: var(--acc);
  text-decoration: none;
  font-size: 14px;
}

.providers-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--bdrL);
}
.providers-foot .hint { font-size: 11px; color: var(--txL); }

/* Model slot cards */
.slot-card {
  border: 1px solid var(--bdr);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 8px;
  background: var(--cardA);
}
.slot-card[data-mode="empty"] { opacity: .6; }
.slot-hd {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.slot-no {
  font-size: 11px;
  font-weight: 700;
  color: var(--acc);
  background: #faf3e2;
  padding: 3px 8px;
  border-radius: 10px;
  border: 1px solid #e6d9b2;
}
.slot-thinking {
  margin-left: auto;
  font-size: 11px;
  color: var(--txS);
  display: flex;
  align-items: center;
  gap: 6px;
}

.seg-tabs {
  display: inline-flex;
  gap: 2px;
  background: var(--bg2);
  padding: 2px;
  border-radius: 7px;
}
.seg-tabs .seg {
  padding: 4px 12px;
  font-size: 11px;
  color: var(--txS);
  cursor: pointer;
  border-radius: 5px;
  border: none;
  background: transparent;
  font-family: inherit;
}
.seg-tabs .seg.active {
  background: var(--card);
  color: var(--txt);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(44, 36, 22, .06);
}

.slot-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 12px;
}
.slot-grid .full { grid-column: span 2; }
.slot-label {
  font-size: 11px;
  color: var(--txS);
  font-weight: 600;
  margin-bottom: 4px;
  display: block;
}
```

- [ ] **Step 3: 提交**

```bash
git add static/settings.css
git commit -m "feat(settings): add sidebar+panel stylesheet scaffolding"
```

---

## Task 2 · 新建 settings.js：导航 + 槽位模式切换 + Providers 批量保存

**Files:**
- Create: `static/settings.js`

- [ ] **Step 1: 写文件头 + 面板导航**

写入 `static/settings.js`：

```javascript
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
```

- [ ] **Step 2: 添加槽位模式切换（取代旧 syncModelPoolSlotCard）**

在上一段之后、IIFE 尾部之前追加：

```javascript
  function syncSlotCard(card) {
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
          syncSlotCard(card);
        });
      });
      var providerSel = card.querySelector('[data-slot-provider]');
      if (providerSel) {
        providerSel.addEventListener('change', function () { syncSlotCard(card); });
      }
      syncSlotCard(card);
    });
  }
```

- [ ] **Step 3: 添加 Providers 批量保存 + pill 状态刷新**

继续追加：

```javascript
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
})();
```

- [ ] **Step 4: 提交**

```bash
git add static/settings.js
git commit -m "feat(settings): add panel nav + slot sync + providers bulk save"
```

---

## Task 3 · 新建模型槽位 Jinja partial

**Files:**
- Create: `templates/_settings_model_slot.html`

- [ ] **Step 1: 写 partial**

写入 `templates/_settings_model_slot.html`：

```html
{# ---------------------------------------------------------------
   Model pool slot.
   Expected context:
     slot            (dict)   current slot config
     slot_no         (int)    1..3
     prefix          (str)    form name prefix e.g. "translation_model_pool_slot1"
     builtin_models  (dict)   key -> {label, ...}
     providers       (list of (value, label)) custom provider options
--------------------------------------------------------------- #}
<div class="slot-card" data-slot-card data-mode="{{ slot.mode }}">
  <div class="slot-hd">
    <span class="slot-no">#{{ slot_no }}{% if slot_no == 1 %} 主{% else %} 备{% endif %}</span>
    <div class="seg-tabs" role="tablist">
      <button type="button" class="seg{% if slot.mode == 'builtin' %} active{% endif %}" data-mode="builtin">内置</button>
      <button type="button" class="seg{% if slot.mode == 'custom' %} active{% endif %}" data-mode="custom">自定义</button>
      <button type="button" class="seg{% if slot.mode == 'empty' %} active{% endif %}" data-mode="empty">留空</button>
    </div>
    <input type="hidden" name="{{ prefix }}_mode" value="{{ slot.mode }}" data-slot-mode-input>
    <label class="slot-thinking" data-slot-thinking-row>
      <input type="checkbox" name="{{ prefix }}_thinking_enabled" value="on"{% if slot.thinking_enabled %} checked{% endif %}>
      <span>思考模式</span>
    </label>
  </div>

  <div data-slot-mode-panel="builtin">
    <label class="slot-label">内置模型</label>
    <select name="{{ prefix }}_builtin_key" class="inp" style="width:100%;">
      {% for key, model in builtin_models.items() %}
      <option value="{{ key }}"{% if slot.builtin_key == key %} selected{% endif %}>{{ model.label }}</option>
      {% endfor %}
    </select>
    <div class="hint" style="margin-top:6px;">内置模型会自动使用对应全局 API Key，不需要填写 Base URL 或专用 Key。</div>
  </div>

  <div data-slot-mode-panel="custom">
    <div class="slot-grid">
      <div>
        <label class="slot-label">Provider</label>
        <select name="{{ prefix }}_provider_type" class="inp" style="width:100%;" data-slot-provider>
          {% for value, label in providers %}
          <option value="{{ value }}"{% if slot.provider_type == value %} selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label class="slot-label">展示名</label>
        <input name="{{ prefix }}_display_name" class="inp" type="text" value="{{ slot.display_name }}" placeholder="例如：MiMo Flash" style="width:100%;">
      </div>
      <div>
        <label class="slot-label">模型 ID</label>
        <input name="{{ prefix }}_model_id" class="inp" type="text" value="{{ slot.model_id }}" placeholder="例如：mimo-v2-flash" style="width:100%;">
      </div>
      <div data-provider-field="qwen_region">
        <label class="slot-label">Qwen 地域</label>
        <select name="{{ prefix }}_qwen_region" class="inp" style="width:100%;">
          <option value="cn"{% if slot.qwen_region == 'cn' %} selected{% endif %}>中国内地</option>
          <option value="sg"{% if slot.qwen_region == 'sg' %} selected{% endif %}>新加坡</option>
          <option value="us"{% if slot.qwen_region == 'us' %} selected{% endif %}>美国</option>
        </select>
      </div>
      <div class="full" data-provider-field="endpoint">
        <label class="slot-label">Base URL</label>
        <input name="{{ prefix }}_base_url" class="inp" type="text" value="{{ slot.base_url }}" placeholder="例如：https://token-plan-cn.xiaomimimo.com/v1" style="width:100%;">
      </div>
      <div class="full" data-provider-field="endpoint">
        <label class="slot-label">专用 API Key</label>
        <input name="{{ prefix }}_custom_api_key" class="inp" type="password" value="{{ slot.custom_api_key }}" placeholder="如需专属 Key，请填写" style="width:100%;">
      </div>
    </div>
  </div>

  <div data-slot-mode-panel="empty">
    <div class="hint">留空：失败时不再尝试此槽位。</div>
  </div>
</div>
```

- [ ] **Step 2: 提交**

```bash
git add templates/_settings_model_slot.html
git commit -m "feat(settings): extract shared model slot partial"
```

---

## Task 4 · 重写 settings.html：shell + topbar + sidebar

**Files:**
- Modify: `templates/settings.html` (full rewrite from line 1)

- [ ] **Step 1: 替换整个文件，初版只含 shell + sidebar + 7 个空面板占位**

先备份（工作区已经 tracked，不需要额外备份），整体覆盖写入。文件开头到 `{% endblock %}` 结束之间的全部内容用下面替换：

```html
{% extends "base.html" %}
{% block extra_head %}
  <link rel="stylesheet" href="{{ url_for('static', filename='settings.css') }}">
{% endblock %}
{% block content %}
<div class="container" style="max-width:1080px;">
  <div class="settings-topbar">
    <h1>设置</h1>
    <div style="display:flex;gap:12px;align-items:center;">
      <div class="cur-models">
        翻译：<code>{{ current_model_label or current_model_id }}</code>
        · FNM：<code>{{ current_visual_model_label or current_visual_model_id }}</code>
      </div>
      <a href="{{ url_for('home', doc_id=current_doc_id) }}" class="btn btn-sec">← 返回</a>
    </div>
  </div>

  <div class="settings-shell">
    <nav class="settings-side" aria-label="设置分组">
      <div class="grp">接入</div>
      <button class="nav-item" data-nav="providers" type="button">
        <span class="dot" data-status-dot="providers"></span>
        <span>Providers</span>
        <span class="count" data-count="providers"></span>
      </button>
      <button class="nav-item" data-nav="translation-pool" type="button">
        <span class="dot" style="background:var(--blu);"></span>
        <span>翻译模型池</span>
      </button>
      <button class="nav-item" data-nav="fnm-pool" type="button">
        <span class="dot" style="background:var(--blu);"></span>
        <span>FNM 模型池</span>
      </button>

      <div class="grp">运行</div>
      <button class="nav-item" data-nav="concurrency" type="button">
        <span class="dot" style="background:var(--txL);"></span>
        <span>并发设置</span>
      </button>

      <div class="grp">文档</div>
      <button class="nav-item" data-nav="glossary" type="button">
        <span class="dot" style="background:var(--txL);"></span>
        <span>术语词典</span>
        <span class="count">{{ glossary|length }}</span>
      </button>
      <button class="nav-item" data-nav="toc" type="button">
        <span class="dot" style="background:var(--txL);"></span>
        <span>目录文件</span>
      </button>

      <div class="grp">其他</div>
      <button class="nav-item" data-nav="data" type="button">
        <span class="dot" style="background:{% if has_pages or has_entries %}var(--red){% else %}var(--txL){% endif %};"></span>
        <span>数据管理</span>
      </button>
    </nav>

    <section class="settings-main">
      <div data-panel="providers"></div>
      <div data-panel="translation-pool"></div>
      <div data-panel="fnm-pool"></div>
      <div data-panel="concurrency"></div>
      <div data-panel="glossary"></div>
      <div data-panel="toc"></div>
      <div data-panel="data"></div>
    </section>
  </div>
</div>

<script src="{{ url_for('static', filename='settings.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: 手工验证页面能打开、sidebar 可见、点击切换会改 hash**

```bash
python -m pytest tests/integration/test_translate_stop_flow_real_docs.py::MultiSlotModelUXRegressionTests -x -q 2>&1 | tail -20
```

此时现有测试必然失败（面板内容还没写），这一步只验证模板能渲染、无 Jinja 错误。如果是模板语法错误需要立刻修复再继续。先不 commit，留到 Task 5-8 全部完成再一次合并提交，避免中间状态挂测试。

---

## Task 5 · 填充 Providers 面板

**Files:**
- Modify: `templates/settings.html` (替换 `data-panel="providers"` 占位)

- [ ] **Step 1: 替换 Providers 面板占位内容**

把 `<div data-panel="providers"></div>` 整行替换为：

```html
<div data-panel="providers">
  <h2 class="panel-h">Providers · 全局 API Key</h2>
  <div class="panel-sub">
    所有内置模型共享这些 Key；内置模型会自动选择对应 Provider 的全局 Key，无需在槽位重复填写。
  </div>

  <div class="section-hd">
    <div class="lbl">6 Providers</div>
    <span id="providersStatus" style="font-size:11px;color:var(--txS);"></span>
  </div>

  <form id="providersForm" method="POST" action="{{ url_for('save_settings') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="doc_id" value="{{ current_doc_id }}">

    <div class="prov-row" data-section="paddle">
      <div class="prov-logo lg-ps">P</div>
      <div class="prov-name">PaddleOCR</div>
      <div class="prov-hint">Token · 版面 OCR</div>
      <input class="inp prov-key" type="password" data-key
             name="paddle_token" value="{{ paddle_token }}"
             placeholder="输入 PaddleOCR Token">
      <span class="pill" data-status></span>
      <a class="prov-link" href="https://aistudio.baidu.com/paddleocr/task" target="_blank" rel="noreferrer" title="获取 Token">↗</a>
    </div>

    <div class="prov-row" data-section="deepseek">
      <div class="prov-logo lg-ds">DS</div>
      <div class="prov-name">DeepSeek</div>
      <div class="prov-hint">OpenAI 兼容 · DeepSeek V3 / R1</div>
      <input class="inp prov-key" type="password" data-key
             name="deepseek_key" value="{{ deepseek_key }}"
             placeholder="sk-...">
      <span class="pill" data-status></span>
      <a class="prov-link" href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer" title="获取 Key">↗</a>
    </div>

    <div class="prov-row" data-section="dashscope">
      <div class="prov-logo lg-qw">Q</div>
      <div class="prov-name">DashScope</div>
      <div class="prov-hint">Qwen 系列 · 阿里云百炼</div>
      <input class="inp prov-key" type="password" data-key
             name="dashscope_key" value="{{ dashscope_key }}"
             placeholder="sk-...">
      <span class="pill" data-status></span>
      <a class="prov-link" href="https://bailian.console.aliyun.com/?tab=model#/api-key" target="_blank" rel="noreferrer" title="获取 Key">↗</a>
    </div>

    <div class="prov-row" data-section="glm">
      <div class="prov-logo lg-gl">GL</div>
      <div class="prov-name">智谱 GLM</div>
      <div class="prov-hint">GLM-4.6 / GLM-4.5V</div>
      <input class="inp prov-key" type="password" data-key
             name="glm_api_key" value="{{ glm_api_key }}"
             placeholder="输入智谱 GLM API Key">
      <span class="pill" data-status></span>
      <a class="prov-link" href="https://open.bigmodel.cn/" target="_blank" rel="noreferrer" title="获取 Key">↗</a>
    </div>

    <div class="prov-row" data-section="kimi">
      <div class="prov-logo lg-km">K</div>
      <div class="prov-name">Kimi</div>
      <div class="prov-hint">Moonshot · K2</div>
      <input class="inp prov-key" type="password" data-key
             name="kimi_api_key" value="{{ kimi_api_key }}"
             placeholder="输入 Kimi / Moonshot API Key">
      <span class="pill" data-status></span>
      <a class="prov-link" href="https://platform.moonshot.ai/console/api-keys" target="_blank" rel="noreferrer" title="获取 Key">↗</a>
    </div>

    <div class="prov-row" data-section="mimo">
      <div class="prov-logo lg-mm">M</div>
      <div class="prov-name">MiMo</div>
      <div class="prov-hint">按量 · 小米</div>
      <input class="inp prov-key" type="password" data-key
             name="mimo_api_key" value="{{ mimo_api_key }}"
             placeholder="输入 MiMo 按量 API Key">
      <span class="pill" data-status></span>
      <a class="prov-link" href="https://api.xiaomimimo.com/" target="_blank" rel="noreferrer" title="获取 Key">↗</a>
    </div>

    <div class="providers-foot">
      <span class="hint">只保存到本机 SQLite，不对外上传。Token Plan 的自定义 Base URL 请在"翻译模型池 / FNM 模型池"槽位里单独填写。</span>
      <button type="submit" class="btn btn-pri">保存所有变更</button>
    </div>
  </form>
</div>
```

- [ ] **Step 2: 手工烟测 Providers 面板**

```bash
python -m pytest tests/integration/test_backend_backlog.py -x -q -k settings 2>&1 | tail -10
```

预期：不红掉 `/settings` GET。关键字符串保留要到 Task 6 之后测试才会绿。

---

## Task 6 · 填充翻译模型池面板

**Files:**
- Modify: `templates/settings.html` (替换 `data-panel="translation-pool"` 占位)

- [ ] **Step 1: 替换翻译池面板占位**

把 `<div data-panel="translation-pool"></div>` 整行替换为：

```html
<div data-panel="translation-pool">
  <h2 class="panel-h">翻译模型池</h2>
  <div class="panel-sub">
    用于标准连续翻译和 FNM 文本翻译。槽位 1 是主模型；某页或某个 FNM unit 失败后，按 2 → 3 顺序切换重试。
  </div>

  <form method="POST" action="{{ url_for('save_settings') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="section" value="translation_model_pool">
    <input type="hidden" name="doc_id" value="{{ current_doc_id }}">

    {% set translation_providers = [
      ('deepseek', 'DeepSeek'),
      ('qwen', 'Qwen (DashScope)'),
      ('qwen_mt', 'Qwen-MT (DashScope)'),
      ('glm', 'GLM (智谱)'),
      ('kimi', 'Kimi (Moonshot)'),
      ('mimo', 'MiMo 按量'),
      ('mimo_token_plan', 'MiMo Token Plan'),
      ('openai_compatible', 'OpenAI Compatible')
    ] %}

    {% for slot in translation_model_pool %}
      {% set slot_no = loop.index %}
      {% set prefix = 'translation_model_pool_slot' ~ slot_no %}
      {% with slot=slot, slot_no=slot_no, prefix=prefix, builtin_models=translation_models, providers=translation_providers %}
        {% include "_settings_model_slot.html" %}
      {% endwith %}
    {% endfor %}

    <div class="providers-foot">
      <span class="hint">当前主翻译模型：<code>{{ current_model_label or current_model_id }}</code></span>
      <button type="submit" class="btn btn-pri">保存翻译模型池</button>
    </div>
  </form>
</div>
```

- [ ] **Step 2: 运行现有快照类测试确认老字符串保留**

```bash
python -m pytest tests/integration/test_translate_stop_flow_real_docs.py -x -q -k "MultiSlotModel or set_model" 2>&1 | tail -20
```

预期：断言 `当前主翻译模型` 的 case 绿。如果仍红，说明文案被意外改掉，立刻修回。

---

## Task 7 · 填充 FNM 模型池面板

**Files:**
- Modify: `templates/settings.html`

- [ ] **Step 1: 替换 FNM 池面板占位**

把 `<div data-panel="fnm-pool"></div>` 整行替换为：

```html
<div data-panel="fnm-pool">
  <h2 class="panel-h">FNM 视觉与修补模型</h2>
  <div class="panel-sub">
    用于自动视觉目录、FNM 视觉判断和 LLM 修补。槽位 1 是主模型；视觉/修补失败后，按 2 → 3 顺序切换重试。
  </div>

  <form method="POST" action="{{ url_for('save_settings') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="section" value="fnm_model_pool">
    <input type="hidden" name="doc_id" value="{{ current_doc_id }}">

    {% set fnm_providers = [
      ('qwen', 'Qwen (DashScope)'),
      ('glm', 'GLM (智谱)'),
      ('kimi', 'Kimi (Moonshot)'),
      ('mimo', 'MiMo 按量'),
      ('mimo_token_plan', 'MiMo Token Plan'),
      ('openai_compatible', 'OpenAI Compatible')
    ] %}

    {% for slot in fnm_model_pool %}
      {% set slot_no = loop.index %}
      {% set prefix = 'fnm_model_pool_slot' ~ slot_no %}
      {% with slot=slot, slot_no=slot_no, prefix=prefix, builtin_models=fnm_models, providers=fnm_providers %}
        {% include "_settings_model_slot.html" %}
      {% endwith %}
    {% endfor %}

    <div class="providers-foot">
      <span class="hint">当前主 FNM 模型：<code>{{ current_visual_model_label or current_visual_model_id }}</code></span>
      <button type="submit" class="btn btn-pri">保存 FNM 模型池</button>
    </div>
  </form>
</div>
```

---

## Task 8 · 填充并发 / 词典 / 目录 / 数据管理面板

**Files:**
- Modify: `templates/settings.html`

- [ ] **Step 1: 替换并发面板占位**

把 `<div data-panel="concurrency"></div>` 整行替换为：

```html
<div data-panel="concurrency">
  <h2 class="panel-h">段内并发翻译</h2>
  <div class="panel-sub">
    默认关闭。开启后，单页会同时请求多个段落，通常更快，但也更容易触发模型限流、超时或单页失败。
  </div>
  <form method="POST" action="{{ url_for('save_settings') }}">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="section" value="translate_parallel">
    <input type="hidden" name="doc_id" value="{{ current_doc_id }}">
    <input type="hidden" name="translate_parallel_enabled" value="off">
    <label class="flex items-center gap-8" style="font-weight:600;margin-bottom:10px;">
      <input type="checkbox" name="translate_parallel_enabled" value="on"{% if translate_parallel_enabled %} checked{% endif %}
             onchange="document.getElementById('translateParallelLimit').disabled = !this.checked;">
      <span>开启段内并发翻译</span>
    </label>
    <div class="flex items-center gap-8" style="flex-wrap:wrap;">
      <label for="translateParallelLimit" style="font-size:13px;color:var(--txt);">并发上限</label>
      <input id="translateParallelLimit" name="translate_parallel_limit" class="inp" type="number" min="1" max="10"
             value="{{ translate_parallel_limit }}" style="width:96px;"
             {% if not translate_parallel_enabled %}disabled{% endif %}>
      <span class="hint" style="margin:0;">范围 1-10；数值越高，请求越密集，也越容易遇到限流或超时。</span>
    </div>
    <div class="providers-foot">
      <span></span>
      <button type="submit" class="btn btn-pri">保存并发设置</button>
    </div>
  </form>
</div>
```

- [ ] **Step 2: 替换术语词典面板占位**

把 `<div data-panel="glossary"></div>` 整行替换为：

```html
<div data-panel="glossary">
  <h2 class="panel-h">术语词典 ({{ glossary|length }} 条)</h2>
  <div class="panel-sub">法语术语 → 中文译文；翻译阶段会优先参考这里的定义。</div>
  <form method="POST" action="{{ url_for('save_glossary') }}" id="glossaryForm">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="doc_id" value="{{ current_doc_id }}">
    <div class="glossary-scroll" id="glossaryList">
      {% for term, defn in glossary %}
      <div class="glossary-row" data-idx="{{ loop.index0 }}">
        <input name="term_{{ loop.index0 }}" class="inp" style="flex:1;padding:3px 8px;font-size:12px;color:var(--fr);" value="{{ term }}" placeholder="法语术语">
        <span class="arrow">→</span>
        <input name="defn_{{ loop.index0 }}" class="inp" style="flex:1;padding:3px 8px;font-size:12px;color:var(--cn);" value="{{ defn }}" placeholder="中文译文">
        <button type="button" class="remove-btn" onclick="this.parentElement.remove();">×</button>
      </div>
      {% endfor %}
    </div>
    <input type="hidden" name="count" id="glossaryCount" value="{{ glossary|length }}">
    <div class="providers-foot">
      <button type="button" class="btn btn-grn btn-sm" onclick="addGlossaryRow();">+ 添加术语</button>
      <button type="submit" class="btn btn-pri btn-sm">保存词典</button>
    </div>
  </form>
</div>

<script>
  (function () {
    var nextIdx = {{ glossary|length }};
    window.addGlossaryRow = function () {
      var list = document.getElementById('glossaryList');
      if (!list) return;
      var row = document.createElement('div');
      row.className = 'glossary-row';
      row.innerHTML =
        '<input name="term_' + nextIdx + '" class="inp" style="flex:1;padding:3px 8px;font-size:12px;color:var(--fr);" placeholder="法语术语">' +
        '<span class="arrow">→</span>' +
        '<input name="defn_' + nextIdx + '" class="inp" style="flex:1;padding:3px 8px;font-size:12px;color:var(--cn);" placeholder="中文译文">' +
        '<button type="button" class="remove-btn" onclick="this.parentElement.remove();">×</button>';
      list.appendChild(row);
      nextIdx++;
      var counter = document.getElementById('glossaryCount');
      if (counter) counter.value = nextIdx;
    };
  })();
</script>
```

- [ ] **Step 3: 替换目录面板占位**

把 `<div data-panel="toc"></div>` 整行替换为：

```html
<div data-panel="toc">
  <h2 class="panel-h">当前目录索引文件</h2>
  <div class="panel-sub">上传后持续保留，直到被新上传的目录文件替换。</div>

  {% if toc_file.exists %}
  <div style="display:grid;grid-template-columns:max-content 1fr;gap:8px 12px;align-items:start;font-size:13px;margin-bottom:12px;">
    <div style="color:var(--txL);">原始文件名</div>
    <div style="color:var(--txt);word-break:break-word;">{{ toc_file.display_name }}</div>
    <div style="color:var(--txL);">导入时间</div>
    <div style="color:var(--txt);">{{ toc_file.uploaded_at_display or '未知' }}</div>
    <div style="color:var(--txL);">目录条数</div>
    <div style="color:var(--txt);">{{ toc_item_count }} 条</div>
    <div style="color:var(--txL);">目录对齐</div>
    <div style="color:var(--txt);">原书第 1 页 = PDF 第{{ toc_offset + 1 }}页</div>
  </div>
  {% if toc_file.is_legacy_name %}
  <div class="hint" style="margin-bottom:10px;">旧记录，原始文件名不可恢复；当前仅能显示保存后的固定文件名。</div>
  {% endif %}
  {% else %}
  <div class="hint" style="margin-bottom:10px;">当前未选择目录索引文件</div>
  {% endif %}

  <div style="margin-top:12px;">
    <input type="file" id="settingsTocFileInput" accept=".csv,.xlsx" style="font-size:12px;color:var(--txt);">
  </div>
  <div class="flex gap-8 mt-10" style="align-items:center;flex-wrap:wrap;">
    <button type="button" class="btn btn-pri btn-sm" id="settingsTocImportBtn" onclick="replaceTocFileFromSettings();">重新上传替换目录文件</button>
  </div>
  <div id="settingsTocImportMsg" style="display:none;font-size:12px;margin-top:10px;"></div>

  {% if toc_source == 'user' %}
  <hr style="border:none;border-top:1px solid var(--bdrL);margin:20px 0;">
  <h3 style="font-size:15px;font-weight:700;color:var(--txt);margin:0 0 6px;">书籍目录页码偏移</h3>
  <p class="hint" style="margin-bottom:14px;">
    已导入目录 {{ toc_item_count }} 条。若目录跳转落页不准，调整偏移后刷新阅读页即可生效。<br>
    <strong>偏移含义：</strong>原书第 1 印刷页对应 PDF 的第几页（1-based）。例如封面占 3 页，则填 4。
  </p>
  <div class="flex items-center gap-8" style="flex-wrap:wrap;">
    <label style="font-size:13px;color:var(--txS);">原书第 1 页 = PDF 第</label>
    <input id="tocOffsetSettingsInput" type="number" min="1" class="inp"
           style="width:80px;" value="{{ toc_offset + 1 }}">
    <label style="font-size:13px;color:var(--txS);">页</label>
    <button type="button" class="btn btn-pri btn-sm" onclick="saveTocOffset();">保存偏移</button>
  </div>
  <div id="tocOffsetSettingsMsg" style="display:none;font-size:12px;margin-top:8px;"></div>
  {% endif %}
</div>

<script>
  function setSettingsTocMsg(msg, type) {
    var el = document.getElementById('settingsTocImportMsg');
    if (!el) return;
    if (!msg) { el.style.display = 'none'; el.textContent = ''; return; }
    el.style.display = '';
    el.textContent = msg;
    el.style.color = type === 'error' ? 'var(--red)' : 'var(--grn)';
  }

  function replaceTocFileFromSettings() {
    var input = document.getElementById('settingsTocFileInput');
    var btn = document.getElementById('settingsTocImportBtn');
    if (!input || !input.files || !input.files.length) {
      setSettingsTocMsg('请先选择目录文件', 'error');
      return;
    }
    btn.disabled = true;
    setSettingsTocMsg('上传中…', 'ok');
    var fd = new FormData();
    fd.append('file', input.files[0]);
    fetch('/api/toc/import?doc_id={{ current_doc_id }}', {
      method: 'POST',
      headers: { 'X-CSRF-Token': getCsrfToken() },
      body: fd
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        btn.disabled = false;
        if (d.ok) {
          var name = (d.toc_file && d.toc_file.display_name) ? d.toc_file.display_name : '目录文件';
          setSettingsTocMsg('已替换目录文件：' + name + '，正在刷新页面…', 'ok');
          window.setTimeout(function () {
            window.location.href = '{{ url_for("settings", doc_id=current_doc_id) }}#toc';
          }, 180);
          return;
        }
        setSettingsTocMsg(d.error || '上传失败', 'error');
      })
      .catch(function (err) {
        btn.disabled = false;
        setSettingsTocMsg('请求失败：' + err, 'error');
      });
  }

  {% if toc_source == 'user' %}
  function saveTocOffset() {
    var raw = document.getElementById('tocOffsetSettingsInput').value;
    var pdfPage1 = parseInt(raw, 10);
    var msgEl = document.getElementById('tocOffsetSettingsMsg');
    if (isNaN(pdfPage1) || pdfPage1 < 1) {
      msgEl.style.display = '';
      msgEl.textContent = '请输入有效页码（≥ 1）';
      msgEl.style.color = 'var(--red)';
      return;
    }
    fetch('/api/toc/set_offset?doc_id={{ current_doc_id }}', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, withCsrfHeaders()),
      body: JSON.stringify({ offset: pdfPage1 - 1 })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        msgEl.style.display = '';
        if (d.ok) {
          msgEl.textContent = '偏移已保存（offset = ' + d.offset + '），前往阅读页刷新即可生效';
          msgEl.style.color = 'var(--grn)';
        } else {
          msgEl.textContent = d.error || '保存失败';
          msgEl.style.color = 'var(--red)';
        }
      })
      .catch(function (err) {
        msgEl.style.display = '';
        msgEl.textContent = '请求失败：' + err;
        msgEl.style.color = 'var(--red)';
      });
  }
  {% endif %}
</script>
```

- [ ] **Step 4: 替换数据管理面板占位**

把 `<div data-panel="data"></div>` 整行替换为：

```html
<div data-panel="data">
  <h2 class="panel-h">数据管理</h2>
  <div class="panel-sub">清除操作不可撤销，请谨慎。</div>
  <div class="flex gap-8 flex-wrap">
    {% if has_entries %}
    <form method="POST" action="{{ url_for('reset_text_action') }}" class="inline-form"
          onsubmit="return confirm('确定清除翻译数据？');">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
      <input type="hidden" name="doc_id" value="{{ current_doc_id }}">
      <button type="submit" class="btn btn-sec" style="font-size:12px;">清除翻译数据</button>
    </form>
    {% endif %}
    {% if has_pages %}
    <form method="POST" action="{{ url_for('reset_all') }}" class="inline-form"
          onsubmit="return confirm('确定清除所有数据？');">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
      <input type="hidden" name="doc_id" value="{{ current_doc_id }}">
      <button type="submit" class="btn btn-red-ghost" style="font-size:12px;border:1px solid var(--red);">清除所有数据</button>
    </form>
    {% endif %}
    {% if not has_pages and not has_entries %}
    <span style="font-size:13px;color:var(--txL);">暂无数据</span>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 5: 跑全量 settings 相关回归**

```bash
python -m pytest tests/integration/test_translate_stop_flow_real_docs.py tests/integration/test_backend_backlog.py -x -q -k settings 2>&1 | tail -30
```

预期：全绿。若任一断言依赖的中文字符串（如 `当前主翻译模型` / `当前主 FNM 模型` / `Qwen 3.5 Plus`）被意外删除或改名，需要立即修正模板。

- [ ] **Step 6: 提交第 4-8 阶段（整页重写一起提交，避免中间不可用状态）**

```bash
git add templates/settings.html templates/_settings_model_slot.html
git commit -m "feat(settings): rewrite settings page into sidebar+panel layout"
```

---

## Task 9 · 写新 smoke test

**Files:**
- Create: `tests/integration/test_settings_page_redesign.py`

- [ ] **Step 1: 写 failing test**

```python
"""Smoke tests for the redesigned settings page layout."""

from __future__ import annotations

import unittest

from web.app_factory import create_app


class SettingsPageRedesignSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True)

    def setUp(self):
        self.client = self.app.test_client()

    def _get_html(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    def test_sidebar_shows_all_seven_panels(self):
        html = self._get_html()
        for nav_key in (
            'data-nav="providers"',
            'data-nav="translation-pool"',
            'data-nav="fnm-pool"',
            'data-nav="concurrency"',
            'data-nav="glossary"',
            'data-nav="toc"',
            'data-nav="data"',
        ):
            self.assertIn(nav_key, html, f"missing sidebar entry: {nav_key}")

    def test_providers_panel_has_six_rows(self):
        html = self._get_html()
        for section in ("paddle", "deepseek", "dashscope", "glm", "kimi", "mimo"):
            self.assertIn(f'data-section="{section}"', html)
        self.assertIn('id="providersForm"', html)

    def test_model_pools_render_three_slots_each(self):
        html = self._get_html()
        for prefix in (
            "translation_model_pool_slot1_mode",
            "translation_model_pool_slot2_mode",
            "translation_model_pool_slot3_mode",
            "fnm_model_pool_slot1_mode",
            "fnm_model_pool_slot2_mode",
            "fnm_model_pool_slot3_mode",
        ):
            self.assertIn(prefix, html)

    def test_preserves_current_model_labels(self):
        html = self._get_html()
        self.assertIn("当前主翻译模型", html)
        self.assertIn("当前主 FNM 模型", html)

    def test_loads_new_css_and_js(self):
        html = self._get_html()
        self.assertIn("static/settings.css", html)
        self.assertIn("static/settings.js", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行并确认全部通过**

```bash
python -m pytest tests/integration/test_settings_page_redesign.py -v 2>&1 | tail -20
```

预期：5 个 case 全绿。入口已确认：`from web.app_factory import create_app`。

- [ ] **Step 3: 提交**

```bash
git add tests/integration/test_settings_page_redesign.py
git commit -m "test(settings): add smoke coverage for redesigned layout"
```

---

## Task 10 · 手工验证 checklist

**Files:**（无代码改动，纯手工检查）

- [ ] **Step 1: 启动应用并依次验证**

```bash
python app.py
```

浏览器打开 `/settings`，按序确认：

1. 默认打开 Providers 面板，左侧"Providers"高亮
2. 点击 sidebar 每项，面板切换、URL hash 同步（`#translation-pool` 等）
3. 直接访问 `/settings#glossary` → 词典面板打开；`/settings#toc-file` 或 `#toc-offset` → 目录面板
4. Providers 面板：
   - 随便改一个 Key，pill 变成"● 未保存"
   - 点"保存所有变更"，页面刷新、pill 变回"✓ 已配置"
   - 清空某个已配置的 Key 并保存，pill 变成"! 未配置"
5. 翻译池槽位：
   - Tab 切换"内置 / 自定义 / 留空"可见字段随之切换
   - 自定义 + `openai_compatible` → Base URL / 专用 Key 出现
   - 自定义 + `qwen` → Qwen 地域出现
   - 点保存，回到相同面板且选择保留
6. FNM 池同上
7. 并发开关 toggle + 保存；词典增删 + 保存；目录上传 + 偏移保存；清除翻译数据 / 清除所有数据
8. 切换系统主题为深色（如果 app 支持）：所有 pill / 卡片颜色仍协调

- [ ] **Step 2: 整理收尾**

```bash
git status
git log --oneline -10
```

确认工作区干净、最近 6 个提交分别覆盖 CSS / JS / partial / 模板重写 / 新 smoke test。

---

## Self-Review Notes

- Spec → Task 映射：
  - "Providers 6 行 + 批量保存" → Task 1 样式 + Task 2 JS + Task 5 模板
  - "模型池槽位卡片 segmented tabs" → Task 1 样式 + Task 2 syncSlotCard + Task 3 partial + Task 6/7 模板
  - "旧 hash 兼容 `#glossary / #toc-file / #toc-offset`" → Task 2 `HASH_ALIAS`
  - "主题变量全覆盖" → Task 1 全部用 `var(--...)`
  - "保留 `当前主翻译模型` / `当前主 FNM 模型` 字符串" → Task 6/7 显式写入 + Task 9 断言
- Placeholder 扫描：无 TBD，所有代码块完整。
- 类型一致性：`data-mode / data-slot-mode-input / data-slot-provider / data-provider-field / data-status / data-key / data-section / data-nav / data-panel` 在 CSS、JS、模板中名字一致。
- 未包含：连通性测试、Key 导入导出、窄屏自适应（spec 已明确 YAGNI）。
