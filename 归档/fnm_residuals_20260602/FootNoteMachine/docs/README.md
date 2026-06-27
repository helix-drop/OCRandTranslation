# FootNoteMachine 参考文档索引

整理日期：2026-04-02  
用途：Obsidian 脚注相关功能开发参考资料

---

## 文档目录

### 官方文档
- [`obsidian-footnote-official-docs.md`](./obsidian-footnote-official-docs.md)  
  Obsidian 官方脚注语法文档，包含四种脚注类型、渲染行为对比、已知限制

### 当前项目设计与脚本
- [`footnote-endnote-filter-design.md`](./footnote-endnote-filter-design.md)  
  当前脚注/尾注筛选逻辑设计，解释 JSON、markdown、脚注、尾注之间的关系
- [`footnote-endnote-output-formats.md`](./footnote-endnote-output-formats.md)  
  当前两个导出产物的快速说明：Obsidian 导出与 translation manifest
- [`footnote-endnote-developer-guide.md`](./footnote-endnote-developer-guide.md)  
  面向后续开发的详细文档，覆盖模块职责、状态机、输入输出格式、CLI 与接入建议

### 社区插件综合研究
- [`plugins/community-plugins-overview.md`](./plugins/community-plugins-overview.md)  
  8 个脚注相关社区插件的完整研究报告，含功能对比矩阵、技术实现分析

### 源码参考（TypeScript）

| 文件 | 来源插件 | 内容 |
|------|---------|------|
| [`plugins/obsidian-footnotes-main.ts`](./plugins/obsidian-footnotes-main.ts) | MichaBrugger/obsidian-footnotes | 插件入口，命令注册 |
| [`plugins/obsidian-footnotes-insert-navigate.ts`](./plugins/obsidian-footnotes-insert-navigate.ts) | MichaBrugger/obsidian-footnotes | 核心逻辑：插入自动编号脚注、命名脚注、双向导航 |
| [`plugins/obsidian-footnotes-autosuggest.ts`](./plugins/obsidian-footnotes-autosuggest.ts) | MichaBrugger/obsidian-footnotes | EditorSuggest 自动补全实现 |
| [`plugins/tidy-footnotes-core.ts`](./plugins/tidy-footnotes-core.ts) | charliecm/tidy-footnotes | 脚注整理归位与重新编号算法 |

---

## 关键技术要点速查

### 核心正则

```typescript
// 标记（正文引用）：(?!:) 排除定义行
/\[\^([^\[\]]+)\](?!:)/g

// 定义行：行首锚定
/^\[\^([^\[\]]+)\]:/

// 数字标记
/\[\^(\d+)\]/gi

// 脚注定义名称+完整内容（含多行）
/\[\^([^\[\]]+)\]:(.+(?:\n(?:(?!\[\^[^\[\]]+\]:).)+)*)/g
```

### 最大技术空白
**Live Preview 模式下脚注不渲染** — 目前没有任何插件通过 CodeMirror 6 `ViewPlugin` / `StateField` 实现 Live Preview 交互式脚注渲染。这是 FootNoteMachine 可能的核心突破方向。

### 相关 GitHub 仓库

| 插件 | GitHub | 状态 |
|------|--------|------|
| obsidian-footnotes | https://github.com/MichaBrugger/obsidian-footnotes | 活跃，已收录 |
| tidy-footnotes | https://github.com/charliecm/obsidian-tidy-footnotes | 活跃，已收录 |
| better-fn | https://github.com/aidenlx/better-fn | 活跃，已收录 |
| footnotes-manager | https://github.com/BigGHS/obsidian-footnotes-manager | 仅手动安装 |
| commentesque-footnotes | https://github.com/zweek/commentesque-footnotes | 已收录 |
| betterfotnotes | https://github.com/Oudwins/obsidian-betterfotnotes | 实验阶段 |
| inline-footnotes | https://github.com/hermeneuticlens/obsidian-markdown-inline-footnotes | 早期，未实现 |
