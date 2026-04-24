# 设置页重新设计 · 左侧导航 + 行内 Provider

**状态**：待实施
**日期**：2026-04-24
**范围**：仅重构 `templates/settings.html` + 新增设置页 CSS/JS，不改后端路由与数据模型

---

## 背景

当前 `templates/settings.html` 是一条单列长页，依次堆叠 6 张 API Key card（PaddleOCR / DeepSeek / DashScope / GLM / Kimi / MiMo）、2 张模型池 card（翻译 / FNM，每张 3 个大槽位）、并发、术语词典、目录文件、目录偏移、数据管理——共 12 张 card、9 个独立 `<form>`，页面冗长、视觉嘈杂，没有分组导航。

经过 4 版 mockup 对比，确定采用 **D 方案**：左侧分组导航 + 右侧单面板，Providers 采用行内紧凑输入，状态 pill 一眼可见；配色沿用现有主题 (`--bg #f5f0e8` 系列，深色 / 羊皮纸主题随 CSS 变量继承)。

## 目标

1. 页面进入后，**首屏即可看到全局状态**：哪些 Provider 已配置、两个模型池主模型是谁、词典多少条、数据管理是否危险。
2. **消除重复表单结构**：6 张 API Key card 合并成一个 Providers 面板里的 6 行；模型池槽位卡片布局更紧凑。
3. **保留所有现有功能与后端契约**：`/save_settings` 的 section 协议、`/save_glossary`、`/api/toc/*`、`/reset_text_action`、`/reset_all` 全部不变。
4. **适配已有 CSS 变量**：使用 `--bg / --bg2 / --card / --cardA / --bdr / --bdrL / --acc / --grn / --red / --blu / --txt / --txS / --txL`，三套主题（默认米色、深色、羊皮纸）自动兼容。

非目标：

- 不调整后端路由或数据结构
- 不修改模型池的字段定义（`mode / provider_type / builtin_key / display_name / model_id / base_url / custom_api_key / qwen_region / thinking_enabled`）
- 不做响应式窄屏侧边栏抽屉（留到后续，如果有需求）

## 总体布局

```
┌──────────────────────────────────────────────────────────┐
│  设置                                             ← 返回  │
├─────────────┬────────────────────────────────────────────┤
│ 接入         │                                            │
│ ● Providers │   (右侧面板：当前选中的项)                   │
│ ● 翻译池    │                                            │
│ ● FNM 池    │                                            │
│ 运行         │                                            │
│ · 并发       │                                            │
│ 文档         │                                            │
│ · 术语 (12) │                                            │
│ · 目录       │                                            │
│ 其他         │                                            │
│ ● 数据       │                                            │
└─────────────┴────────────────────────────────────────────┘
```

- **左侧 sidebar**：固定宽度 200px，背景 `--bg2`，分 4 组（接入 / 运行 / 文档 / 其他）。每项含小圆点（状态色）+ 标题 + 可选计数 pill。
- **右侧 main panel**：背景 `--card`，padding 20-24px，面板切换用客户端 JS（无 URL 跳转，仅改 hash 以便书签）。
- **顶部条**：保留 `<h1>设置</h1>` + 返回按钮 + "当前主模型"简述。

面板对应关系：

| 导航项 | 面板内容 | 对应原 card |
| --- | --- | --- |
| Providers | 6 行 Provider × (logo / 名称 / 说明 / 密钥输入 / 状态 pill) | 原 PaddleOCR / DeepSeek / DashScope / GLM / Kimi / MiMo 6 张 card |
| 翻译模型池 | 3 个槽位卡片 | 原"翻译模型"card |
| FNM 模型池 | 3 个槽位卡片 | 原"FNM 视觉与修补模型"card |
| 并发 | 段内并发开关 + 上限 | 原"翻译性能"card |
| 术语词典 | 现有术语表 + 增删 + 保存 | 原"术语词典"card |
| 目录 | 目录文件信息 + 上传 + 偏移 | 原"当前目录索引文件"+"书籍目录页码偏移"两张 card |
| 数据管理 | 清除翻译 / 清除全部 | 原"数据管理"card |

## 核心面板：Providers

### 结构

```html
<form id="providersForm" onsubmit="return saveAllProviders(event)">
  <input type="hidden" name="_csrf_token" value="...">
  <input type="hidden" name="doc_id" value="...">

  <div class="prov-row" data-section="paddle">
    <div class="prov-logo lg-ps">P</div>
    <div class="prov-name">PaddleOCR</div>
    <div class="prov-hint">Token · 版面 OCR</div>
    <input class="inp" type="password" name="paddle_token" value="{{ paddle_token }}" placeholder="...">
    <span class="pill" data-status></span>
    <a class="prov-link" href="https://aistudio.baidu.com/paddleocr/task">↗</a>
  </div>

  <!-- 重复 deepseek / dashscope / glm / kimi / mimo 5 行 -->

  <div class="providers-foot">
    <span class="hint">只保存到本机 SQLite，不对外上传。</span>
    <button type="submit" class="btn btn-pri">保存所有变更</button>
  </div>
</form>
```

- 6 行共享一张 `<form>`，前端 JS 在提交时**逐个 AJAX POST 到 `/save_settings`**（对有变更的行），保留现有后端 per-section 契约。
- 每行的 `data-section` 对应当前 `save_settings` 已识别的 section 名（`paddle / deepseek / dashscope / glm / kimi / mimo`）。
- 文档链接（百炼 / 智谱 / Moonshot / DeepSeek / MiMo / PaddleOCR）从"每张 card 一段话"压缩成一个 ↗ 小图标，hover 显示完整说明。
- 状态 pill：
  - 初始基于模板变量渲染（`{{ paddle_token }}` 非空 → ✓ 已配置）
  - 输入框 `input` 事件后若内容变化则显示灰色 "● 未保存"
  - 保存成功后回到 ✓ 已配置

### 保存流程

1. 用户点"保存所有变更"
2. JS 遍历所有行，比较 `input.value` 与 `data-initial`，只对变更行构造 `FormData`（含 `_csrf_token / doc_id / section=<name> / <key_name>=<value>`）
3. 并发 `fetch('/save_settings', { method:'POST', body: fd })`
4. 全部完成后 `location.reload()`（保留 Flask flash 提示），或显示内联成功条并更新 `data-initial`

> 备选：新增一个 `section=providers_bulk` 后端分支，一次性保存全部。本次暂不做，避免改后端；只动前端。

### 状态计算（sidebar 圆点）

- **绿色** (`--grn`)：所有 6 个 Key 均非空
- **琥珀** (`--acc`) + "4/6" 计数：部分配置
- **红色** (`--red`) + "0/6"：全部未配置

## 核心面板：模型池（翻译 / FNM）

两个池子结构一致，复用同一个槽位组件（Jinja include）。

### 单槽位卡片

```
┌─ #1 主 ──────────────────────────────────┐
│ [内置] [自定义] [留空]      □ 思考模式     │
├───────────────────────────────────────────┤
│ 内置模式：                                 │
│   内置模型 ▼ [DeepSeek V3 ...]            │
│                                           │
│ 自定义模式（grid 2列）：                    │
│   Provider ▼     展示名                   │
│   模型 ID        Base URL (按需)          │
│   Qwen 地域 (按需)                         │
│   专用 API Key (full width, 可选)          │
└───────────────────────────────────────────┘
```

- 模式选择从 `<select>` 改为三段式 segmented tab（`内置 / 自定义 / 留空`），视觉更轻。
- 切换模式由 JS 控制显示哪一块，同步隐藏不相关字段（与现有 `syncModelPoolSlotCard` 逻辑等价，迁移并微调）。
- Thinking checkbox 只在非"留空"时显示；文字 hint 改成 tooltip 或折叠，不再占两行。
- "留空"模式下整张卡片变灰（opacity 0.6），只保留一句"失败时不再尝试此槽位"。

### 面板底部

- `当前主模型：<strong>...</strong>`（原有）
- 保存按钮 `保存模型池`

后端 POST 字段**完全保持**现状（`translation_model_pool_slot1_mode` 等），`save_settings` 不改。

## 其他面板

- **并发**：保留单张简表，加个 toggle 视觉更友好。
- **术语词典**：保留现有 glossary-scroll 列表、`+ 添加术语` / `保存词典`。导航项右侧显示条数计数。
- **目录**：把"当前目录索引文件"和"页码偏移"合并到一个面板。未导入 TOC 时不显示偏移区块（延续现有 `{% if toc_source == 'user' %}`）。
- **数据管理**：保留两个红色按钮 + confirm 弹窗；sidebar 圆点：有数据时红色，无数据时灰色。

## 面板切换 JS

```js
function initSettingsNav() {
  const panels = document.querySelectorAll('[data-panel]');
  const items = document.querySelectorAll('[data-nav]');
  function activate(key) {
    panels.forEach(p => p.hidden = p.dataset.panel !== key);
    items.forEach(i => i.classList.toggle('active', i.dataset.nav === key));
    if (history.replaceState) history.replaceState(null, '', '#' + key);
  }
  items.forEach(i => i.addEventListener('click', () => activate(i.dataset.nav)));
  const initial = (location.hash || '#providers').slice(1);
  activate(document.querySelector(`[data-panel="${initial}"]`) ? initial : 'providers');
}
```

- 默认打开 `#providers`
- 直接访问 `/settings#glossary` 仍可直达该面板（兼容旧锚点：`#glossary / #toc-file / #toc-offset` 统一映射到 `glossary / toc` 两个新 key）

## 文件改动

| 路径 | 改动 |
| --- | --- |
| `templates/settings.html` | 重写整页结构：外层 shell / sidebar / panels；模型池槽位抽成 `{% include %}` 分片 |
| `templates/_settings_model_slot.html` | 新增 Jinja partial，翻译池 / FNM 池共用 |
| `static/settings.css` | 新增；所有设置页专用样式集中于此（prov-row / slot-card / segmented-tabs / sidebar 等） |
| `static/settings.js` | 新增；面板导航、`syncModelPoolSlotCard` 迁移、Providers 批量保存、状态 pill 刷新 |
| `templates/base.html` | 若还没有，在设置页分支里引入新 CSS/JS（通过 block extra_head / extra_scripts） |

后端：**不改**。测试维持现状；如果有模板快照测试，更新期望 HTML。

## 测试策略

由于这是纯模板/CSS/JS 重构：

1. **手工 checklist**（以现有 `docs/superpowers/specs/...` 风格列出）：
   - 默认主题下 6 个 Provider 行对齐、pill 状态正确
   - 切换深色/羊皮纸主题，所有面板颜色跟随
   - 分别保存 6 个 Provider Key（含单个、多个、全部）
   - 翻译池 3 槽位：内置 / 自定义 (每种 provider_type) / 留空，保存后刷新 form 还原
   - FNM 池同上
   - 词典增删保存、目录上传替换、偏移保存、清除数据
   - 直达 `#providers / #translation-pool / #fnm-pool / #concurrency / #glossary / #toc / #data` 均能打开对应面板
2. **E2E 脚本**（如果项目已有 playwright / 类似框架）：补一个 smoke case，断言 sidebar 6 项可见、点击切面板、Providers 表单包含 6 个 input。若无框架则跳过。

## 边缘情况

- 首次进入 `/settings` 无 hash：默认 `#providers`
- `/settings#glossary` / `#toc-file` / `#toc-offset` 兼容映射到新 key
- Providers 批量保存中途某项失败：继续保存其他项，失败行显示红色 pill + 错误气泡，不整体 reload
- CSRF token：所有 AJAX POST 调用 `withCsrfHeaders()`（已有工具函数）
- 没有文档 (current_doc_id 为空)：只有 Providers + 全局设置面板有意义；模型池 / 词典 / 目录 / 数据等仍按现有逻辑渲染，不特殊处理
- 窄屏：暂不做自适应；sidebar 固定 200px，内容最小宽度 640px，窄于该宽度时水平滚动（后续可优化为折叠抽屉）
- Preview 截图到的 pill / logo 色值：在默认米色主题下与 `--acc / --grn / --red` 协调，在深色主题需针对 `.pill.ok` / `.pill.no` 背景色做单独覆盖

## 不包含的东西（YAGNI）

- 移动端响应式抽屉
- Provider 连通性测试按钮（"测试 Key"功能）
- Key 导入/导出
- 主题切换开关（仍依赖现有全局主题）
- 新增后端批量保存端点

如果用户后续需要，这些都是独立增量。
