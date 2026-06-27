# 脚注尾注脚本开发手册

整理日期：2026-04-02  
适用范围：当前仓库中的脚注/尾注筛选、Obsidian 导出、翻译 manifest 导出脚本

---

## 1. 目标

这一套脚本的目标不是“把 OCR 文本简单转成 markdown”，而是把一份已经完成 OCR 与 layout 解析的文档，进一步结构化成三层：

- 正文
- 脚注
- 尾注

然后再生成两类可消费产物：

- 面向阅读的 Obsidian markdown
- 面向翻译流水线的 translation manifest

这一层的职责是“结构抽取与稳定编码”，不负责：

- PDF OCR
- 大模型翻译本身
- 翻译结果回填
- 阅读器 UI 渲染

---

## 2. 文件结构

当前相关文件如下：

| 文件 | 职责 | 备注 |
|------|------|------|
| `scripts/footnote_endnote_filter_prototype.py` | 核心识别状态机 | 输入 JSON，输出 section/footnote/endnote manifest |
| `scripts/footnote_endnote_products.py` | 共享导出层 | 在 manifest 上继续生成 Obsidian 文本和 translation manifest |
| `scripts/export_obsidian_markdown.py` | Obsidian CLI | 调用共享层生成 `.obsidian.md` |
| `scripts/export_translation_manifest.py` | Translation CLI | 调用共享层生成 `.translation_manifest.json` |
| `docs/footnote-endnote-filter-design.md` | 设计说明 | 解释为什么要这样区分脚注/尾注 |
| `docs/footnote-endnote-output-formats.md` | 输出概览 | 快速了解两个产物 |
| `output/obsidian/*.obsidian.md` | 样例导出 | 开发调试用 |
| `output/translation/*.translation_manifest.json` | 样例导出 | 开发调试用 |

推荐把真正的“服务入口”视为：

- `build_manifest()`
- `build_rendered_sections()`
- `build_obsidian_markdown()`
- `build_translation_manifest()`

CLI 只是薄包装。

---

## 3. 输入约定

### 3.1 输入文件类型

当前脚本只接受 PaddleOCR-VL 输出的 JSON 文件。

需要的最低字段是：

```json
[
  {
    "prunedResult": {
      "parsing_res_list": [
        {
          "block_label": "text|footnote|doc_title|paragraph_title|...",
          "block_content": "...",
          "block_bbox": [x1, y1, x2, y2],
          "block_order": 1
        }
      ]
    },
    "markdown": {
      "text": "..."
    }
  }
]
```

### 3.2 当前脚本依赖的字段

核心识别依赖：

- `prunedResult.parsing_res_list`
- `block_label`
- `block_content`
- `block_bbox`
- `block_order`
- `markdown.text`

如果这些字段缺失，脚本不会稳定工作。

### 3.3 隐含假设

当前版本默认以下前提成立：

1. JSON 的页面顺序与 PDF 页序一致。
2. `parsing_res_list` 至少能保留正文块与注释块。
3. 文档中的尾注区通常有显式标题，例如 `NOTES`。
4. `markdown.text` 可以用于抽取正文引用标记。
5. section 的开始通常可以由 `doc_title` 识别。

当前版本不保证正确处理：

- 完全没有 section 标题的整本文档
- 尾注区没有显式标题且全靠排版区分
- 双栏复杂学术版式
- 同页既有尾注区又重新回到正文
- OCR 把大段尾注误混入正文且没有 heading 边界

---

## 4. 总体流程

从输入 JSON 到两个产物，整体流程如下：

```text
PaddleOCR-VL JSON
    ↓
build_manifest()
    ↓
section + footnotes + endnotes
    ↓
build_rendered_sections()
    ↓
obsidian refs / frozen refs / note content
    ├─ build_obsidian_markdown()
    └─ build_translation_manifest()
```

可以把它理解为三层：

### 第一层：识别层

由 `footnote_endnote_filter_prototype.py` 提供。

职责：

- section 切分
- 正文 marker 抽取
- 页脚脚注合并
- 尾注区识别
- 跨页脚注合并

产物：

- 中间 manifest

### 第二层：重写层

由 `footnote_endnote_products.py` 提供。

职责：

- 把正文里的原始引用改写成稳定 ID
- 生成 Obsidian 格式引用
- 生成翻译冻结 token
- 去掉重复 section 标题
- 从正文中剔除尾注区页面

产物：

- rendered sections

### 第三层：导出层

职责：

- 导出最终 `.obsidian.md`
- 导出最终 `.translation_manifest.json`

---

## 5. 核心状态机

这一部分决定脚注和尾注能不能正确分离。

### 5.1 Section 切分

入口函数：

- `build_sections()`

规则：

- 遇到 `block_label == doc_title` 的 block，就认为进入了一个新 section。
- 当前页记为 section 起始页。
- 直到下一个 `doc_title` 或文档结束。

为什么必须先切 section：

- 数字尾注和数字脚注会重复编号
- 不同 section 的注释体系不应共享 ID

ID 设计依赖这一层：

- `fn-<section-index>-<serial>`
- `en-<section-index>-<serial>`

### 5.2 正文 marker 抽取

入口函数：

- `extract_refs()`

当前支持的正文引用形态：

- `[^note]`
- `$ ^{5} $`
- Unicode 上标 `¹²³`
- 普通贴尾数字，例如 OCR 识别出的 `dominait7`
- 星号、双星、匕首等符号型 marker

标准化函数：

- `normalize_marker()`

标准化后的 marker 形态示例：

- `¹` -> `1`
- `²` -> `2`
- `$ ^{13} $` -> `13`
- `*` -> `*`
- `**` -> `**`

### 5.3 尾注区识别

入口函数：

- `is_note_heading()`
- `collect_endnotes()`

当前用来切换到尾注区的标题正则：

- `NOTES`
- `ENDNOTES`
- `tail notes`
- `尾注`
- `注释`
- `注解`

一旦进入尾注区：

- 后续 `text` 或 `footnote` block 中
- 以 `数字 + 点/右括号` 开头的 block 会开启一条新尾注
- 没有新编号的连续 block 会并入上一条尾注

### 5.4 页脚脚注识别

入口函数：

- `collect_footnotes()`

规则不是“每个 footnote block = 一条脚注”，而是：

1. 当前 block 必须位于 `NOTES` 标题之前。
2. 当前 block 必须是 `block_label == footnote`。
3. 如果 block 的 marker 能在同页正文 marker 集合中找到，则它是新脚注起点。
4. 否则，优先视为上一条脚注的续块。

这样做是为了避免一种典型误判：

- 正文引用的是 `*`
- 脚注内部自己又包含 `1. 2. 3. 4.` 的列表
- 这些数字列表不应被当成尾注

### 5.5 跨页脚注合并

入口函数：

- `next_page_continues_footnote()`

规则：

1. 当前页末尾已经存在打开的脚注。
2. 下一页在尾注标题之前最先出现的仍然是脚注 block。
3. 下一页首个脚注 block 不是一个新的明确 marker，或者 marker 与上一条脚注相同。

满足这三条，脚本会把下一页开头脚注并入上一条脚注。

---

## 6. 关键函数说明

### 6.1 `scripts/footnote_endnote_filter_prototype.py`

#### `build_manifest(input_path: Path) -> dict`

这是识别层最重要的入口。

输入：

- PaddleOCR-VL JSON 路径

输出：

```json
{
  "source_file": "...",
  "page_count": 34,
  "sections": [
    {
      "section_id": "sec-02-lecon-du-10-janvier-1979",
      "title": "LEÇON DU 10 JANVIER 1979",
      "start_page": 9,
      "end_page": 34,
      "pages": [9, 10, 11],
      "endnotes_start_page": 31,
      "page_refs": {"9": ["1", "2", "3"]},
      "footnotes": [...],
      "endnotes": [...]
    }
  ]
}
```

#### `body_markdown(page: dict) -> str`

作用：

- 从一页 markdown 中截出“尾注标题之前的正文部分”

注意：

- 它按行匹配尾注标题，不是简单全文搜索
- 所以可以正确在 `### NOTES` 这一行截断

#### `extract_refs(text: str) -> set[str]`

作用：

- 从正文中提取本页所有可疑 marker

用途：

- 帮助判断某条脚注是不是“新脚注起点”

#### `collect_footnotes(section, pages)`

作用：

- 遍历一个 section 里的页面
- 收集页脚脚注
- 合并跨页脚注

#### `collect_endnotes(section, pages)`

作用：

- 从尾注标题开始收集尾注

### 6.2 `scripts/footnote_endnote_products.py`

#### `build_rendered_sections(input_json: Path) -> list[dict]`

这是导出层的核心中间接口。

它在 `build_manifest()` 的结果上再加一层渲染信息：

- `obsidian_body_pages`
- `frozen_body_pages`
- `obsidian_body_markdown`
- `frozen_body_markdown`
- `footnotes[].content_text`
- `endnotes[].content_text`
- 每条注对应的 `obsidian_ref`
- 每条注对应的 `frozen_ref`

如果要接阅读器，这通常是最适合直接复用的入口。

#### `rewrite_body_refs(text, resolver)`

作用：

- 把正文中的原始脚注/尾注标记重写成目标表示法

它并不直接写死输出形式，而是依赖 `resolver()`：

- Obsidian 模式返回 `[^fn-...]` 或 `[E13](#en-...)`
- Frozen 模式返回 `{{FN_REF:...}}` 或 `{{EN_REF:...}}`

#### `build_obsidian_markdown(input_json)`

作用：

- 生成最终阅读稿

输出结构：

1. 文档级标题
2. 每个 section 一个 `##`
3. section 正文
4. `### Endnotes`
5. Obsidian footnote definitions

#### `build_translation_manifest(input_json, max_body_chars=6000)`

作用：

- 生成翻译任务分发文件

正文会先按段落切 chunk，再按 `max_body_chars` 合并。

当前 manifest 里的 `translation_units` 分三类：

- `kind = body`
- `kind = footnote`
- `kind = endnote`

### 6.3 CLI 薄封装

#### `export_obsidian_markdown.py`

命令：

```bash
python3 scripts/export_obsidian_markdown.py INPUT.json
```

可选参数：

- `--output`

#### `export_translation_manifest.py`

命令：

```bash
python3 scripts/export_translation_manifest.py INPUT.json --max-body-chars 6000
```

可选参数：

- `--output`
- `--max-body-chars`

---

## 7. 输出格式详解

### 7.1 Obsidian markdown

当前导出的约定如下：

#### 脚注

正文引用：

```markdown
... texte[^fn-02-0003]
```

定义：

```markdown
[^fn-02-0003]: 第一行
  第二行
  第三行
```

说明：

- 使用命名 footnote ID，而不是原始数字
- 多行脚注定义采用 Obsidian 要求的两空格缩进续行

#### 尾注

正文引用：

```markdown
... texte[E13](#en-02-0013)
```

尾注正文：

```markdown
### Endnotes

#### EN-02-0013

这里是尾注内容
```

说明：

- 尾注不使用 `[^...]`
- 尾注会保留在独立 section 下
- 正文中的 `[E13](#en-...)` 可以在 Obsidian 里直接跳转

### 7.2 Translation manifest

当前结构顶层字段：

- `document_id`
- `source_json`
- `max_body_chars`
- `section_count`
- `sections`
- `translation_units`

#### `sections[]`

用于描述 section 边界和 unit 归属。

字段：

- `section_id`
- `title`
- `start_page`
- `end_page`
- `endnotes_start_page`
- `body_chunk_ids`
- `footnote_ids`
- `endnote_ids`

#### `translation_units[]`

当前三种类型：

##### `kind = body`

字段：

- `unit_id`
- `kind`
- `section_id`
- `title`
- `page_start`
- `page_end`
- `char_count`
- `source_text`

##### `kind = footnote`

字段：

- `unit_id`
- `kind`
- `section_id`
- `note_id`
- `original_marker`
- `page_start`
- `page_end`
- `char_count`
- `source_text`
- `target_ref`

##### `kind = endnote`

字段与 `footnote` 基本相同。

#### Frozen token

正文在 translation manifest 中不会保留最终渲染形式，而是冻结成：

- `{{FN_REF:fn-02-0003}}`
- `{{EN_REF:en-02-0013}}`

这样翻译模型即使调整句序，也不会丢失注释绑定。

---

## 8. 阅读器接入建议

### 8.1 推荐接入层级

如果你要把这套逻辑接入已有阅读器软件，优先顺序建议如下：

#### 方案 A：接 `build_rendered_sections()`

适合：

- 你想自己控制 UI 渲染
- 你不想直接吃 markdown
- 你想在阅读器里做“正文 / 脚注 / 尾注”三栏或浮窗

优点：

- 数据粒度最合适
- 不用重新解析导出的 markdown
- 同时保留 Obsidian 风格引用与 frozen 风格引用

#### 方案 B：接 `build_translation_manifest()`

适合：

- 你要把翻译任务投递给另一个服务
- 你要在阅读器里维护翻译状态

优点：

- body / footnote / endnote 已经拆开
- 每个单元有稳定 ID
- 可直接记录翻译状态与回填结果

#### 方案 C：直接接 CLI

适合：

- 当前阶段先快速验证完整链路
- 不急着做进程内集成

### 8.2 不建议的接法

不建议把阅读器建立在 `.obsidian.md` 的反向解析之上。

原因：

- `.obsidian.md` 是最终阅读稿，不是结构主数据
- 反向再解析会丢掉脚本内部的 section、page、marker 关系

### 8.3 推荐服务化接口

如果后面要服务化，建议接口粒度如下：

#### `POST /notes/classify`

输入：

- OCR JSON 路径或内容

输出：

- `build_manifest()` 的结果

#### `POST /notes/export/obsidian`

输入：

- OCR JSON

输出：

- markdown 文本

#### `POST /notes/export/translation`

输入：

- OCR JSON
- `max_body_chars`

输出：

- translation manifest

---

## 9. 性能

当前脚本复杂度基本是线性的：

- 按页扫描
- 按 block 扫描
- 不做重型版面重算

在当前样例上，识别和导出都是秒级以内。

因此对 370 页、800 页这种量级：

- 处理时间不是主要风险
- 正确率和边界情况才是主要风险

---

## 10. 已知限制

当前版本明确存在这些限制：

1. 默认依赖显式尾注标题。
2. 默认 section 由 `doc_title` 触发。
3. 默认尾注区开始后，后续页面不会再回到正文。
4. 对极端复杂双栏排版尚未做专门规则。
5. 没有做 PDF 图像回查。
6. 没有做翻译回填脚本。
7. 没有为阅读器提供专门的 Python 类封装或 API server。

---

## 11. 下一步开发建议

如果接下来进入正式开发，优先级建议如下：

### P1

- 把 `build_rendered_sections()` 封装成更稳定的模块接口
- 增加翻译回填脚本
- 增加单元测试样例

### P2

- 增加“无显式 NOTES 标题”的尾注识别
- 增加多栏版式支持
- 增加异常 OCR 页的回查机制

### P3

- 把这一层服务化
- 接入阅读器的文档打开流程
- 接入翻译状态缓存和断点恢复

---

## 12. 最小调用示例

### Python 内调用

```python
from pathlib import Path
from scripts.footnote_endnote_products import (
    build_obsidian_markdown,
    build_rendered_sections,
    build_translation_manifest,
)

input_json = Path("your_doc.json")

sections = build_rendered_sections(input_json)
obsidian_md = build_obsidian_markdown(input_json)
translation_manifest = build_translation_manifest(input_json, max_body_chars=6000)
```

### CLI 调用

```bash
python3 scripts/export_obsidian_markdown.py your_doc.json
python3 scripts/export_translation_manifest.py your_doc.json --max-body-chars 6000
```

---

## 13. 你在阅读器里最可能直接用到什么

如果只给一句结论：

- 结构抽取层用 `build_manifest()`
- 阅读器渲染层用 `build_rendered_sections()`
- 翻译任务分发层用 `build_translation_manifest()`
- 最终落地阅读稿才用 `build_obsidian_markdown()`

这四层不要混用，否则后面会很难维护。
