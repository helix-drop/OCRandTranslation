/* FNM 开发者模式前端逻辑。
 *
 * 无构建步骤：纯 ES module，手动 import。
 * 两种入口：
 *   - fnmDevHome.init()  → 书列表页（home）
 *   - fnmDevBook.init(doc_id) → 单本详情页
 */

const POLL_INTERVAL_MS = 2000;
const PHASE_NUMBERS = [1, 2, 3, 4, 5, 6];
const SUPPORTED_RUN_PHASES = new Set([1, 2, 3, 4, 5, 6]); // 与后端 SUPPORTED_PHASES 对齐

function csrfHeaders(extra = {}) {
  const token = (window && window.getCsrfToken) ? window.getCsrfToken() : "";
  const headers = Object.assign({ "Content-Type": "application/json" }, extra);
  if (token) headers["X-CSRF-Token"] = token;
  return headers;
}

async function postJSON(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: csrfHeaders(),
    body: JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { ok: false, error: text }; }
  return { ok: res.ok, status: res.status, data };
}

async function getJSON(url) {
  const res = await fetch(url);
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

function phaseRunByNum(phaseRuns, n) {
  return (phaseRuns || []).find((r) => Number(r.phase) === Number(n)) || null;
}

function statusOf(run) {
  return (run && run.status) || "idle";
}

function renderPhaseCell(doc_id, n, run, { onRun, onReset, onForceSkip }) {
  const status = statusOf(run);
  const cell = document.createElement("div");
  cell.className = `fnm-phase-cell ${status}`;
  if (!SUPPORTED_RUN_PHASES.has(n)) cell.classList.add("locked");

  const title = document.createElement("div");
  title.className = "title";
  title.innerHTML = `<span>Phase ${n}</span><span class="status-tag">${status}</span>`;
  cell.appendChild(title);

  const meta = document.createElement("div");
  meta.style.fontSize = "11px";
  meta.style.color = "#666";
  const gate = run && run.gate_pass ? "gate ✓" : (run && run.status === "failed" ? "gate ✗" : "—");
  const forced = run && run.forced_skip ? " (forced)" : "";
  meta.textContent = `${gate}${forced}`;
  cell.appendChild(meta);

  const actions = document.createElement("div");
  actions.className = "actions";
  const runBtn = document.createElement("button");
  runBtn.className = "primary";
  runBtn.textContent = "跑";
  runBtn.disabled = !SUPPORTED_RUN_PHASES.has(n) || status === "running";
  runBtn.addEventListener("click", () => onRun(n));
  actions.appendChild(runBtn);

  const resetBtn = document.createElement("button");
  resetBtn.className = "danger";
  resetBtn.textContent = `重置${n}+`;
  resetBtn.disabled = status === "running";
  resetBtn.addEventListener("click", () => onReset(n));
  actions.appendChild(resetBtn);

  const skipBtn = document.createElement("button");
  skipBtn.textContent = "强制跳过";
  skipBtn.disabled = !SUPPORTED_RUN_PHASES.has(n) || status === "running";
  skipBtn.addEventListener("click", () => onForceSkip(n));
  actions.appendChild(skipBtn);

  cell.appendChild(actions);
  return cell;
}

function confirmForceSkip(n) {
  return window.confirm(
    `确认对 Phase ${n} 强制跳过？\n\n` +
      `这会绕过 Gate 硬约束，产物将被标记为 forced_skip。\n` +
      `仅在你已经了解失败原因、需要继续下游阶段调试时使用。`
  );
}

// ---------- Home 页 ----------

const fnmDevHome = {
  _pollTimer: null,
  _container: null,

  init() {
    this._container = document.getElementById("books");
    document.getElementById("refresh-btn").addEventListener("click", () => this.refresh());
    document.getElementById("import-form").addEventListener("submit", (ev) => this._onImport(ev));
    this.refresh();
    this._startPolling();
  },

  _startPolling() {
    if (this._pollTimer) return;
    this._pollTimer = setInterval(() => this.refresh(), POLL_INTERVAL_MS);
  },

  async _onImport(ev) {
    ev.preventDefault();
    const docId = document.getElementById("doc-id").value.trim();
    if (!docId) return;
    const { data } = await postJSON("/api/dev/fnm/import", { doc_id: docId });
    document.getElementById("import-result").textContent = JSON.stringify(data, null, 2);
    if (data.ok) this.refresh();
  },

  async refresh() {
    const { data } = await getJSON("/api/dev/fnm/books");
    if (!data.ok) {
      this._container.textContent = data.error || "加载失败";
      return;
    }
    this._render(data.books || []);
  },

  _render(books) {
    this._container.innerHTML = "";
    if (!books.length) {
      this._container.textContent = "（还没有任何书。先在首页上传一本，或使用上方表单按 doc_id 导入。）";
      return;
    }
    for (const book of books) {
      this._container.appendChild(this._renderCard(book));
    }
  },

  _renderCard(book) {
    const card = document.createElement("div");
    card.className = "fnm-book-card";

    const titleRow = document.createElement("div");
    titleRow.className = "title-row";
    const title = document.createElement("h3");
    title.textContent = book.name || book.doc_id;
    const link = document.createElement("a");
    link.textContent = "详情 →";
    link.href = `/dev/fnm/book/${encodeURIComponent(book.doc_id)}`;
    titleRow.appendChild(title);
    titleRow.appendChild(link);
    card.appendChild(titleRow);

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `doc_id: <code>${book.doc_id}</code>`;
    card.appendChild(meta);

    const grid = document.createElement("div");
    grid.className = "fnm-phase-grid";
    for (const n of PHASE_NUMBERS) {
      const run = phaseRunByNum(book.phase_runs, n);
      grid.appendChild(
        renderPhaseCell(book.doc_id, n, run, {
          onRun: (p) => this._runPhase(book.doc_id, p, false),
          onReset: (p) => this._resetPhase(book.doc_id, p),
          onForceSkip: (p) => {
            if (confirmForceSkip(p)) this._runPhase(book.doc_id, p, true);
          },
        })
      );
    }
    card.appendChild(grid);
    return card;
  },

  async _runPhase(doc_id, phase, force_skip) {
    const { status, data } = await postJSON(
      `/api/dev/fnm/book/${encodeURIComponent(doc_id)}/phase/${phase}/run`,
      { force_skip }
    );
    if (status === 409) window.alert("该 doc 已有任务在跑，请等结束后再试");
    else if (!data.ok) window.alert(data.error || `运行失败（HTTP ${status}）`);
    this.refresh();
  },

  async _resetPhase(doc_id, phase) {
    if (!window.confirm(`确认重置 Phase ${phase}+？\n将级联清空 Phase ${phase} 及以下所有产物。`)) return;
    const { status, data } = await postJSON(
      `/api/dev/fnm/book/${encodeURIComponent(doc_id)}/phase/${phase}/reset`,
      {}
    );
    if (!data.ok) window.alert(data.error || `重置失败（HTTP ${status}）`);
    this.refresh();
  },
};

// ---------- Book 详情页 ----------

const fnmDevBook = {
  _doc_id: null,
  _pollTimer: null,

  init(doc_id) {
    this._doc_id = doc_id;
    document.getElementById("refresh-btn").addEventListener("click", () => this.refresh());
    this.refresh();
    if (!this._pollTimer) {
      this._pollTimer = setInterval(() => this.refresh(), POLL_INTERVAL_MS);
    }
  },

  async refresh() {
    const { data } = await getJSON(`/api/dev/fnm/book/${encodeURIComponent(this._doc_id)}/status`);
    const container = document.getElementById("phases");
    if (!data.ok) {
      container.innerHTML = `<div class="fnm-flash error">${data.error || "加载失败"}</div>`;
      return;
    }
    container.innerHTML = "";
    for (const n of PHASE_NUMBERS) {
      const run = phaseRunByNum(data.phase_runs, n);
      container.appendChild(this._renderPhaseDetail(n, run));
    }
  },

  _renderPhaseDetail(n, run) {
    const status = statusOf(run);
    const el = document.createElement("div");
    el.className = "fnm-phase-detail";

    const header = document.createElement("h3");
    const statusTag = `<span class="status-tag" style="font-size:11px;padding:2px 6px;border-radius:3px;background:#eee;color:#555;">${status}</span>`;
    header.innerHTML = `<span>Phase ${n}</span> ${statusTag}`;
    el.appendChild(header);

    const meta = document.createElement("div");
    meta.className = "meta";
    const parts = [];
    if (run && run.execution_mode) parts.push(`mode=${run.execution_mode}`);
    if (run && run.started_at) parts.push(`started=${run.started_at}`);
    if (run && run.ended_at) parts.push(`ended=${run.ended_at}`);
    if (run && run.forced_skip) parts.push("forced_skip=1");
    meta.textContent = parts.join(" · ") || "（未运行）";
    el.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "toolbar";
    const runBtn = document.createElement("button");
    runBtn.className = "primary";
    runBtn.textContent = "跑本阶段";
    runBtn.disabled = !SUPPORTED_RUN_PHASES.has(n) || status === "running";

    // Phase 5 专属：test / real 切换（默认 test）
    const modeSelect = n === 5 ? this._buildPhaseModeSelect(n, run) : null;
    if (modeSelect) actions.appendChild(modeSelect);

    runBtn.addEventListener("click", () =>
      this._runPhase(n, false, modeSelect ? modeSelect.value : undefined)
    );
    actions.appendChild(runBtn);

    const resetBtn = document.createElement("button");
    resetBtn.className = "danger";
    resetBtn.textContent = `重置 ${n}+`;
    resetBtn.disabled = status === "running";
    resetBtn.addEventListener("click", () => this._resetPhase(n));
    actions.appendChild(resetBtn);

    const skipBtn = document.createElement("button");
    skipBtn.textContent = "强制跳过";
    skipBtn.disabled = !SUPPORTED_RUN_PHASES.has(n) || status === "running";
    skipBtn.addEventListener("click", () => {
      if (confirmForceSkip(n)) this._runPhase(n, true, modeSelect ? modeSelect.value : undefined);
    });
    actions.appendChild(skipBtn);
    el.appendChild(actions);

    // 错误 / warning 列表
    const errorsWrap = this._renderFailures(run);
    if (errorsWrap) el.appendChild(errorsWrap);
    return el;
  },

  _renderFailures(run) {
    if (!run) return null;
    const report = run.gate_report_json || run.gate_report || {};
    const failures = (run.errors_json || run.errors || []).concat(report.failures || []);
    const uniqueByCode = new Map();
    for (const f of failures) {
      const code = f.code || "(no-code)";
      if (!uniqueByCode.has(code)) uniqueByCode.set(code, f);
    }
    const warnings = report.warnings || [];
    if (!uniqueByCode.size && !warnings.length) return null;

    const wrap = document.createElement("div");
    wrap.className = "errors";
    for (const f of uniqueByCode.values()) {
      wrap.appendChild(this._renderFailureItem(f, false));
    }
    if (warnings.length) {
      const warnWrap = document.createElement("div");
      warnWrap.className = "warnings";
      for (const w of warnings) warnWrap.appendChild(this._renderFailureItem(w, true));
      wrap.appendChild(warnWrap);
    }
    return wrap;
  },

  _renderFailureItem(f, isWarning) {
    const item = document.createElement("div");
    item.className = "error-item";
    const code = f.code || "(no-code)";
    const message = f.message || "";
    item.innerHTML = `<span class="code">${code}</span>${message}`;
    if (f.hint) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = f.hint;
      item.appendChild(hint);
    }
    if (f.evidence && Object.keys(f.evidence).length) {
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(f.evidence, null, 2);
      item.appendChild(pre);
    }
    const refs = Array.isArray(f.evidence_refs) ? f.evidence_refs : [];
    if (refs.length) {
      const row = document.createElement("div");
      row.className = "fnm-evidence-row";
      for (const ref of refs) {
        const btn = document.createElement("button");
        btn.className = "locate-btn";
        btn.textContent = ref.label || `${ref.kind}`;
        btn.addEventListener("click", () => fnmDrawer.open(this._doc_id, code, ref));
        row.appendChild(btn);
      }
      item.appendChild(row);
    }
    return item;
  },

  _buildPhaseModeSelect(phase, run) {
    const modes = phase === 5 ? ["test", "real"] : [];
    if (!modes.length) return null;
    const select = document.createElement("select");
    select.className = `phase${phase}-mode`;
    select.title = `Phase ${phase} 执行模式`;
    for (const m of modes) {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      select.appendChild(opt);
    }
    select.value = (run && run.execution_mode) || "test";
    return select;
  },

  async _runPhase(phase, force_skip, execution_mode) {
    const body = { force_skip };
    if (execution_mode) body.execution_mode = execution_mode;
    const { status, data } = await postJSON(
      `/api/dev/fnm/book/${encodeURIComponent(this._doc_id)}/phase/${phase}/run`,
      body
    );
    if (status === 409) window.alert("该 doc 已有任务在跑，请等结束后再试");
    else if (!data.ok) window.alert(data.error || `运行失败（HTTP ${status}）`);
    this.refresh();
  },

  async _resetPhase(phase) {
    if (!window.confirm(`确认重置 Phase ${phase}+？`)) return;
    const { status, data } = await postJSON(
      `/api/dev/fnm/book/${encodeURIComponent(this._doc_id)}/phase/${phase}/reset`,
      {}
    );
    if (!data.ok) window.alert(data.error || `重置失败（HTTP ${status}）`);
    this.refresh();
  },
};

// ---------- 诊断抽屉 ----------

const fnmDrawer = {
  _bound: false,

  _ensureBound() {
    if (this._bound) return;
    const backdrop = document.getElementById("drawer-backdrop");
    const closeBtn = document.getElementById("drawer-close");
    if (backdrop) backdrop.addEventListener("click", () => this.close());
    if (closeBtn) closeBtn.addEventListener("click", () => this.close());
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") this.close();
    });
    this._bound = true;
  },

  async open(doc_id, code, ref) {
    this._ensureBound();
    const drawer = document.getElementById("drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (!drawer || !backdrop) return;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    backdrop.classList.add("open");

    const title = document.getElementById("drawer-title");
    if (title) title.textContent = `诊断 · ${code || ""}`;

    this._resetPanes();
    if (!ref) return;
    if (ref.kind === "page") {
      this._loadPdf(doc_id, ref.page_no);
    } else if (ref.kind === "artifact" && ref.artifact) {
      this._loadArtifact(doc_id, ref.artifact);
    } else if (ref.kind === "export" && ref.export) {
      this._loadExport(doc_id, ref.export.chapter_id);
    }
  },

  close() {
    const drawer = document.getElementById("drawer");
    const backdrop = document.getElementById("drawer-backdrop");
    if (drawer) {
      drawer.classList.remove("open");
      drawer.setAttribute("aria-hidden", "true");
    }
    if (backdrop) backdrop.classList.remove("open");
  },

  _resetPanes() {
    const paneBody = (id) => document.querySelector(`#${id} .pane-body`);
    const pdf = paneBody("pane-pdf");
    if (pdf) pdf.innerHTML = `<div class="empty">（选择页面证据后加载 PDF）</div>`;
    const art = paneBody("pane-artifact");
    if (art) art.innerHTML = `<div class="empty">（选择产物证据后加载）</div>`;
    const exp = paneBody("pane-export");
    if (exp) exp.innerHTML = `<div class="empty">（Phase 6 未接入）</div>`;
    const pdfMeta = document.getElementById("pane-pdf-meta");
    if (pdfMeta) pdfMeta.textContent = "";
    const artMeta = document.getElementById("pane-artifact-meta");
    if (artMeta) artMeta.textContent = "";
  },

  _loadPdf(doc_id, page_no) {
    const body = document.querySelector("#pane-pdf .pane-body");
    if (!body) return;
    const meta = document.getElementById("pane-pdf-meta");
    if (meta) meta.textContent = page_no ? `p.${page_no}` : "";
    const src = `/api/dev/fnm/book/${encodeURIComponent(doc_id)}/pdf${
      page_no ? `#page=${page_no}` : ""
    }`;
    const iframe = document.createElement("iframe");
    iframe.src = src;
    iframe.title = "PDF 原文";
    body.innerHTML = "";
    body.appendChild(iframe);
  },

  async _loadArtifact(doc_id, art) {
    const body = document.querySelector("#pane-artifact .pane-body");
    const meta = document.getElementById("pane-artifact-meta");
    if (!body) return;
    body.innerHTML = `<div class="empty">加载中…</div>`;
    const qs = new URLSearchParams({
      row_key: art.row_key,
      row_value: art.row_value,
    });
    const url = `/api/dev/fnm/book/${encodeURIComponent(doc_id)}/artifact/${art.phase}/${art.table}?${qs.toString()}`;
    const { data, ok } = await getJSON(url);
    if (!ok || !data.ok) {
      body.innerHTML = `<div class="empty">加载失败：${(data && data.error) || "未知错误"}</div>`;
      return;
    }
    if (meta) {
      const truncated = data.truncated ? "（截断）" : "";
      meta.textContent = `${data.table} · ${data.total} 行${truncated}`;
    }
    if (!data.rows || !data.rows.length) {
      body.innerHTML = `<div class="empty">无匹配行</div>`;
      return;
    }
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data.rows, null, 2);
    body.innerHTML = "";
    body.appendChild(pre);
  },

  async _loadExport(doc_id, chapter_id) {
    const body = document.querySelector("#pane-export .pane-body");
    if (!body) return;
    body.innerHTML = `<div class="empty">加载中…</div>`;
    const url = `/api/dev/fnm/book/${encodeURIComponent(doc_id)}/export-fragment/${encodeURIComponent(chapter_id)}`;
    const { data } = await getJSON(url);
    if (data && data.available && data.markdown) {
      const pre = document.createElement("pre");
      pre.textContent = data.markdown;
      body.innerHTML = "";
      body.appendChild(pre);
    } else {
      const reason = (data && data.reason) || "Phase 6 未接入";
      body.innerHTML = `<div class="empty">${reason}</div>`;
    }
  },
};

window.fnmDevHome = fnmDevHome;
window.fnmDevBook = fnmDevBook;
window.fnmDrawer = fnmDrawer;
