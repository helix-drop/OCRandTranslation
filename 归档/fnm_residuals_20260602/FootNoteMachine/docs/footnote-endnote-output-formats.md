# 脚注尾注实际产物

当前已经提供两个可直接调用的脚本产物：

- [`scripts/export_obsidian_markdown.py`](../scripts/export_obsidian_markdown.py)
- [`scripts/export_translation_manifest.py`](../scripts/export_translation_manifest.py)

共享逻辑在：

- [`scripts/footnote_endnote_products.py`](../scripts/footnote_endnote_products.py)

## 1. Obsidian 导出器

命令：

```bash
python3 scripts/export_obsidian_markdown.py INPUT.json
```

默认输出：

```text
output/obsidian/<源文件名>.obsidian.md
```

导出规则：

- 脚注引用重写为 Obsidian 原生 `[^fn-...]`
- 脚注定义写成标准 footnote definition
- 尾注引用重写为可点击内部链接，例如 `[E13](#en-02-0013)`
- 尾注正文保留在 `### Endnotes` 区域下
- 尾注标题使用稳定 ID，例如 `#### EN-02-0013`

这样在 Obsidian 中：

- 脚注仍然是原生脚注体验
- 尾注不会被错误并入脚注区
- 尾注可以从正文点击跳转

## 2. Translation Manifest 生成器

命令：

```bash
python3 scripts/export_translation_manifest.py INPUT.json --max-body-chars 6000
```

默认输出：

```text
output/translation/<源文件名>.translation_manifest.json
```

manifest 结构包含：

- `sections[]`
- `translation_units[]`

其中 `translation_units[]` 分三类：

- `kind = body`
- `kind = footnote`
- `kind = endnote`

正文中的引用先被冻结：

- `[^fn-02-0003]` -> `{{FN_REF:fn-02-0003}}`
- `[E13](#en-02-0013)` -> `{{EN_REF:en-02-0013}}`

这样后续翻译时：

- 正文 chunk 可以独立翻
- 脚注和尾注可以一条一条翻
- 回填时不会把脚注和尾注混在一起

## 接入建议

如果后面要接入阅读器软件，推荐把这两个产物当成两个独立接口：

1. `obsidian export`
   用于落地最终阅读稿
2. `translation manifest export`
   用于翻译任务分发、回填和重组

这样筛选器只负责结构抽取，不和具体翻译模型或阅读器 UI 耦合。
