# Obsidian 脚注官方文档

来源：https://help.obsidian.md/syntax  
整理日期：2026-04-02

---

## 支持的脚注类型

### 1. 数字编号脚注（标准）

```markdown
这是一个简单的脚注[^1]。

[^1]: 这是引用文本。
```

### 2. 命名脚注（标签脚注）

标签可以用单词，Obsidian 渲染时自动分配连续数字编号：

```markdown
这里使用命名脚注[^note]。

[^note]: 命名脚注的内容。
```

### 3. 多行脚注

续行需要两个空格缩进：

```markdown
[^1]: 脚注第一行内容。
  第二行内容（两空格缩进）。
```

### 4. 行内脚注（Inline Footnote）

注意 `^` 符号在方括号外面：

```markdown
这里有行内脚注^[这是脚注内容]。
```

> **重要限制：** 行内脚注仅在阅读视图（Reading View）中正确渲染，在实时预览（Live Preview）中显示为原始文本。

---

## 渲染行为对比

| 功能 | 实时预览 (Live Preview) | 阅读视图 (Reading View) |
|------|------------------------|------------------------|
| 标准脚注 `[^1]` | 显示原始标记，不移至底部 | 完整渲染到页面底部 |
| 行内脚注 `^[...]` | 仅显示原始文本 | 完整渲染 |
| 表格内脚注 | 不支持 | 不支持 |
| Callout 内脚注 | 不支持 | 不支持 |
| Ctrl/Cmd + 悬停 | 显示预览弹窗 | N/A |

---

## 已知限制与设计背景

- **Live Preview 不渲染脚注定义**：这是 Obsidian 实时预览模式逐行解析的架构决定，官方确认为设计限制而非 Bug。
- **所有脚注定义在阅读视图中自动收集到页面底部**，无论其在源码中的位置。
- 命名脚注在渲染输出中显示为连续数字，标签名仅在源码中保留。
- Obsidian v1.8.9 内置了"插入脚注"命令，使用连续数字 ID。

---

## 参考链接

- 官方帮助文档（基础格式）：https://help.obsidian.md/syntax
- 官方帮助文档（高级格式）：https://help.obsidian.md/advanced-syntax
- GitHub 源码：https://github.com/obsidianmd/obsidian-help/blob/master/en/Editing%20and%20formatting/Basic%20formatting%20syntax.md
- 论坛讨论（Live Preview 脚注渲染问题）：https://forum.obsidian.md/t/footnotes-are-not-rendered-in-live-preview-mode/75904
- 论坛讨论（行内脚注 Live Preview 支持请求）：https://forum.obsidian.md/t/live-preview-add-support-for-inline-footnotes/28416
