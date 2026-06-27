# Obsidian 脚注社区插件综合研究报告

整理日期：2026-04-02

---

## 功能对比矩阵

| 插件 | 插入/导航 | 重新编号 | 悬停预览 | 侧边栏面板 | Live Preview 支持 | 高亮注释 | 自动排序定义 |
|------|----------|---------|---------|-----------|-----------------|---------|------------|
| MichaBrugger/obsidian-footnotes | 是（双向） | 否 | 否 | 否 | 否 | 否 | 否 |
| charliecm/tidy-footnotes | 否 | 是 | 否 | 否 | 否 | 否 | 是 |
| aidenlx/better-fn | 否 | 否 | 是（Tippy.js） | 否 | 否（仅 post-processor） | 否 | 否 |
| BigGHS/footnotes-manager | 是 | 是（增强） | 否 | 是 | 否 | 否 | 否 |
| zweek/commentesque-footnotes | 是 | 否 | 否 | 否 | 否 | 是 | 否 |
| Oudwins/betterfotnotes | 是（弹窗输入） | 是（自动） | 否 | 否 | 否 | 否 | 是 |
| hermeneuticlens/inline-footnotes | 计划中 | 计划中 | 计划中 | 计划中 | **目标功能** | 否 | 否 |

---

## 插件详情

### Plugin 1: obsidian-footnotes（MichaBrugger）— 社区主流插件

**GitHub：** https://github.com/MichaBrugger/obsidian-footnotes  
**原始版本：** https://github.com/akaalias/obsidian-footnotes  
**状态：** 活跃维护中，已收录在官方社区插件库

#### 核心功能
- 通过快捷键自动插入编号脚注标记（`[^1]`、`[^2]`...，自动递增）
- 支持通过快捷键插入命名脚注
- **双向导航：** 快捷键可在标记 → 定义 / 定义 → 标记之间跳转
- **Footnote Autosuggest：** 输入 `[^...` 时自动建议已有脚注名（显示内容预览）
- 可配置是否在脚注区域上方插入分节标题（默认关闭）
- 不自动重新编号（推荐配合 Obsidian Linter 插件使用）

#### 源码结构
- `src/main.ts`
- `src/insert-or-navigate-footnotes.ts`
- `src/autosuggest.ts`
- `src/settings.ts`

#### 核心正则（来自 `insert-or-navigate-footnotes.ts`）
```typescript
export var AllMarkers = /\[\^([^\[\]]+)\](?!:)/dg;       // 匹配标记（非定义行）
var AllNumberedMarkers = /\[\^(\d+)\]/gi;                  // 匹配数字标记
var AllDetailsNameOnly = /\[\^([^\[\]]+)\]:/g;             // 匹配定义行
var DetailInLine = /\[\^([^\[\]]+)\]:/;
export var ExtractNameFromFootnote = /(\[\^)([^\[\]]+)(?=\])/;
```

#### 插入逻辑
- 扫描所有 `[^N]` 标记，找最大 N，在光标处插入 `[^N+1]`
- 在文档末尾（去除尾部空行后）追加 `[^N+1]: `
- 若是第一个脚注且开启了分节标题，前置插入 `# Footnotes`

#### 导航逻辑
- `shouldJumpFromDetailToMarker`：光标在 `[^X]: ` 行 → 跳转到正文中 `[^X]` 的第一处
- `shouldJumpFromMarkerToDetail`：光标在 `[^X]` 处 → 跳转到 `[^X]: ` 所在行

#### 设置项
```typescript
enableAutoSuggest: boolean      // 默认 true
enableFootnoteSectionHeading: boolean  // 默认 false
FootnoteSectionHeading: string  // 默认 "Footnotes"
```

---

### Plugin 2: obsidian-tidy-footnotes（charliecm）

**GitHub：** https://github.com/charliecm/obsidian-tidy-footnotes  
**状态：** 已收录社区插件库

#### 核心功能
- **整理归位：** 将所有脚注定义汇聚到第一个定义出现的位置，按正文出现顺序排列
- **重新编号：** 将数字脚注按顺序重新编为 1、2、3...（命名脚注保持不变）
- 通过命令面板或快捷键手动触发（非自动）
- 处理多行脚注定义（通过缩进续行）

#### 注意事项
- 代码块内的脚注也会被解析（未做排除）
- 所有定义始终移动到第一个定义所在位置

#### 核心正则（来自 `src/tidyFootnotes.ts`）
```typescript
const reKey = /\[\^(.+?(?=\]))\]/gi;        // 标记
const reDefinition = /^\[\^([^\]]+)\]\:/;    // 定义行
```

#### 算法流程
1. 单遍扫描：收集所有标记（含位置）和所有定义（key → value 映射）
2. 记录 `firstDefinitionLine`（作为合并后插入位置）
3. 重新编号：按首次出现顺序遍历，仅对数字 key 分配 `count++`
4. 构建 `definitionsStr`（按顺序排列的完整定义块）
5. 逆向迭代标记：替换定义行（仅保留第一行，用合并块替换），更新文本中的数字标记

---

### Plugin 3: better-fn / BetterFn（aidenlx）

**原版：** https://github.com/aidenlx/better-fn  
**侧边注释 fork：** https://github.com/jancbeck/obsidian-better-footnotes

#### 核心功能
- **悬停弹窗：** 悬停 `[^n]` 上标时显示 Tippy.js 弹窗，内容为脚注文本
- **点击：** 显示持久性弹窗
- **双击：** 跳转到底部定义（需在设置中开启 "Show reference"）
- 使用 `registerMarkdownPostProcessor` — 仅在阅读视图 / 已渲染 HTML 中生效
- 使用 `monkey-around` 拦截 `MarkdownView.onUnloadFile` 进行清理

#### 架构
- `src/bf-main.ts` — 插件主类，注册 `PopoverHandler` 作为 MarkdownPostProcessor
- `src/processor.ts` — 处理渲染后的 HTML，识别 `.footnote-ref` 和 `.footnote` 元素，创建 Tippy 弹窗
- `src/modules/renderChild.ts` — `createPopover()`，使用 Tippy.js 配合 Obsidian 主题样式

```typescript
// processor.ts：关键 ID 匹配逻辑
const match = keys.filter(
  (key) =>
    key.replace(/(?<=^fnref-\d+?-)\d+?-/, "") ===
    id.replace(/^fn-/, "fnref-"),
);
```

#### jancbeck fork 扩展
在悬停弹窗基础上增加了侧边栏边注（margin annotation）功能，底层方案相同。

---

### Plugin 4: obsidian-footnotes-manager（BigGHS）— 功能最丰富

**GitHub：** https://github.com/BigGHS/obsidian-footnotes-manager  
**状态：** 仅支持手动安装（尚未收录社区库）

#### 核心功能
- **专用侧边栏面板**（`ItemView`，类似 Obsidian 内置的大纲面板）
- **两种视图模式：** Outline（按文档标题分组，可折叠）和 List（顺序列表）
- **面板内联编辑：** 直接在面板中编辑脚注内容，自动保存；通过 `MarkdownRenderer` 渲染 Markdown
- **跨节脚注检测：** 同一 `[^n]` 在多个标题下出现时，在所有相关节中显示
- **未引用脚注检测：** 无对应标记的定义显示在 "Unreferenced" 区域（标红，仅支持删除）
- **增强重编号对话框：** 复选框弹窗，选择性（a）删除孤立引用 / （b）填补编号空缺
- **引用导航：** 按钮跳转到正文中每个标记的具体位置
- **搜索：** 实时按内容或编号过滤脚注

#### 数据模型（来自 `main.ts`）
```typescript
interface FootnoteData {
  number: string;
  content: string;
  definition: FootnoteDefinition;
  references: FootnoteReference[];
  referenceCount: number;
  isUnreferenced?: boolean;
  isMultiSection?: boolean;
  appearanceCount?: number;
}

interface FootnoteGroup {
  header: HeaderData | null;
  footnotes: FootnoteData[];
  children?: FootnoteGroup[];
  isCollapsed?: boolean;
  isUnreferencedGroup?: boolean;
}
```

---

### Plugin 5: commentesque-footnotes（zweek）

**GitHub：** https://github.com/zweek/commentesque-footnotes  
**状态：** 已收录社区库

#### 核心功能
- 让脚注用起来像 Google Docs / Notion 的内联批注
- 默认快捷键：`Ctrl+Shift+M`（编号）、`Ctrl+Alt+M`（命名）
- **文本选中行为：** 选中文字 → 自动加 `==高亮==` + 脚注标记（如 `==selected text==[^1]`）
- 光标在单词内时自动在词尾插入标记

#### 关键代码（`src/footnote.ts`）
```typescript
private CommentMarkers = /==.+==\[\^([^[\]]+)\](?!:)/dg; // 匹配 ==文字==[^id]

// AddNumberedFootnote:
if (this.MoveCursorToEndOfWord(editor))
    editor.replaceSelection(footnoteMarker);
else
    editor.replaceSelection(`==${editor.getSelection()}==${footnoteMarker}`);
```

在 MichaBrugger 插件基础上增加了高亮+批注的 UX 层。

---

### Plugin 6: obsidian-betterfotnotes（Oudwins）— 实验性

**GitHub：** https://github.com/Oudwins/obsidian-betterfotnotes  
**状态：** 未收录社区库（实验阶段）

#### 核心功能
- **替换 Obsidian 原生 `editor:insert-footnote` 命令**（保持原快捷键）
- 插入时弹出**模态对话框**，直接输入脚注文本（无需导航到文档底部）
- **每次插入后自动全文重新编号**，按首次出现顺序分配 1、2、3...
- **自动排序定义块**至文档末尾，与引用顺序一致
- **内置备份机制：** 修改前创建带时间戳的备份文件，30 天后自动清理

#### 关键正则（`src/footnote-utils.ts`）
```typescript
const footnoteRefRegex = /\[\^((?:[^\]\\]|\\.)+)\](?!:)/g;  // 仅匹配标记
```

#### 重新编号算法
1. 按首次出现顺序收集所有唯一标签 → `orderedLabels[]`
2. 将每个原始标签映射到顺序编号
3. 将定义行与正文行分离
4. 按新编号排序定义
5. 在内容中替换所有标记和定义

---

### Plugin 7: obsidian-markdown-inline-footnotes（hermeneuticlens）— 目标最激进

**GitHub：** https://github.com/hermeneuticlens/obsidian-markdown-inline-footnotes  
**状态：** 早期阶段，`main.ts` 仍为默认脚手架（尚未实现）

#### 目标功能路线图（README）
1. **在 Live Preview 中折叠/展开行内脚注**（类似 Overleaf Visual Editor 或 LyX）
2. 悬停预览折叠的行内脚注
3. 快捷键折叠/展开单个或整段所有行内脚注
4. （延伸目标）跟随光标的脚注面板（类似 Word 草稿视图的脚注面板）

这是目前所有插件中对 Live Preview 集成目标最激进的，但尚未实现。

---

### Plugin 8: obsidian-footnote-indicator（chrisgrieser）— 已归档

**GitHub：** https://github.com/chrisgrieser/obsidian-footnote-indicator  
**状态：** 已归档，功能已合并入 BetterWordCount 插件

#### 历史功能
- 统计当前文件中脚注和 Pandoc 引用数量，在状态栏显示
- 在编辑器边栏显示脚注存在标识
- 已知限制：行内脚注（`^[...]`）无法在边栏指示，因为 Obsidian 未为其分配 CSS 类

---

## 关键技术观察（开发参考）

### 1. Live Preview 是最大的未解难题
目前没有任何插件实现了基于 CodeMirror 6 `ViewPlugin` 或 `StateField` 的 Live Preview 交互式脚注渲染。所有悬停/预览方案均通过 `registerMarkdownPostProcessor` 作用于阅读视图的渲染后 HTML。

### 2. 标记 vs 定义的标准正则
```typescript
// 标记（正文引用）：(?!:) 负向前瞻排除定义行
/\[\^([^\[\]]+)\](?!:)/g

// 定义行：行首锚定
/^\[\^([^\[\]]+)\]:/
```

### 3. 重新编号策略分歧
- **tidy-footnotes**：保留命名脚注，仅对数字脚注重编号；将所有定义移至第一个定义位置
- **betterfotnotes（Oudwins）**：所有脚注统一重编号为顺序数字；定义排至文件末尾

### 4. 标准 PostProcessor 模式
`monkey-around` + `MarkdownPostProcessor`（better-fn 使用）是在渲染后 HTML 中添加弹窗/提示行为的标准方式。

### 5. 相关周边插件
- **Obsidian Linter**（https://github.com/platers/obsidian-linter）：非独立脚注插件，但包含"保存时重新编号脚注"规则，MichaBrugger 插件明确推荐配合使用。
