# LLM / VLM 接入架构文档

## 写作目的

这份文档面向**将要接手改造 LLM 相关代码的工程师**。它记录：
- 当前仓库里**每一处真实的 LLM/VLM 调用点**（文件、函数、行号）。
- 每处调用的**输入契约、Prompt、输出契约、校验逻辑、失败路径**。
- 所有接入点共享的**防幻觉原则**与**基建函数**。
- 当前未接 LLM 的模块（比如章内语义切分）的**边界约束**，避免后续随意扩张。

读完这份文档，你应该可以：
1. 在不读其他源码的前提下，定位任意一处 LLM 调用的上下游。
2. 知道每一个 Prompt 的修改边界（哪些字段是契约、哪些只是文案）。
3. 判断一次模型失败该走哪条降级路径。
4. 在新增调用点时知道应该复用哪些基建。

---

## 一、总览

### 1.1 实际存在的 LLM / VLM 调用点

当前代码中**只有三个文件**会真正打到模型：

| 角色 | 文件 | 统一调用入口 | 模型类型 |
|---|---|---|---|
| 视觉目录解析 | [pipeline/visual_toc/vision.py](../pipeline/visual_toc/vision.py) | `_call_vision_json` | VLM（qwen-vl 系列） |
| 翻译（含流式 / qwen-mt 专用路径） | [translation/translator.py](../translation/translator.py) | `_call_openai_chat`（`translation/translator.py:534`）、`_call_openai_mt`（`translation/translator.py:612`）、`_stream_openai_chat`（`translation/translator.py:742`）、`_stream_openai_mt`（`translation/translator.py:805`） | Text-LLM（DeepSeek / Qwen / Qwen-MT） |
| 尾注孤儿修补 | [FNM_RE/llm_repair.py](../FNM_RE/llm_repair.py) | `request_llm_repair_actions`（`FNM_RE/llm_repair.py:454`） | 多模态（qwen3.5-plus，文本 + 页面截图） |

除此之外：
- `FNM_RE/modules/chapter_split.py`（章内正文 / 脚注 / 尾注切分）**目前是纯规则**，不走 LLM。
- `FNM_RE/modules/note_linking.py` 里的 `_repair_endnote_links_for_contract`（`FNM_RE/modules/note_linking.py:303`）是**确定性的 OCR 字符修复**，不走 LLM。
- `translation/translate_worker_*.py` 系列是翻译任务的调度框架，所有真实模型请求都是通过调用 `translation/translator.py` 的函数完成的。

> **一条硬性约束：**不要在这三个文件之外直接调用任何 LLM/VLM API。新增需求必须复用或扩展这里的入口，以保证异常分类、token 预算、占位符保护、JSON 解析等基建只维护一处。

### 1.2 三条防幻觉原则

所有调用点共享同一套工程约束，写任何新调用前请对照确认：

1. **极简上下文（Micro-Contexting）**
   - 视觉目录按 4 页一批（`_classify_toc_candidates` 的 `batch_size = 4`，`pipeline/visual_toc/vision.py`）。
   - 翻译按**段落**一次，不合批（`translate_paragraph` / `stream_translate_paragraph`，`translation/translator.py:1241` / `1353`）。
   - 尾注修补一次只看**一个 cluster**、最多 3 个嫌疑页（`LLM_REPAIR_MAX_*` 常量，`FNM_RE/llm_repair.py:33-36`；`_cluster_focus_pages` 限 3 页，`FNM_RE/llm_repair.py:385`）。

2. **控制面剥离（Control Plane Separation）**
   - 模型只输出**决策 JSON**（"是不是目录页"、"该动作是 match / ignore_ref / needs_review"），不输出要写回源数据的长文本。
   - 翻译是例外——但通过"占位符冻结 + 校验还原"把控制面从正文里显式剥离出来（见 §5）。

3. **闭环校验（Closed-loop Validation）**
   - VLM 输出 → `_parse_json_payload`（`pipeline/visual_toc/vision.py`）+ 结构过滤 `filter_visual_toc_items`（`pipeline/visual_toc/organization.py`）。
   - LLM 修补输出 → `parse_llm_repair_actions`（`FNM_RE/llm_repair.py:298`）+ `select_auto_applicable_actions`（`FNM_RE/llm_repair.py:339`，0.9 置信度门槛 + 互斥集合）。
   - 翻译输出 → `_restore_fnm_refs`（`translation/translator.py:600`，标签一致性断言）+ `_missing_glossary_defs`（`translation/translator.py:331`，术语缺失检查 + `_enforce_glossary_rewrite` 改写）。

> **禁止**在任何 LLM 调用后直接采纳原始输出写入 DB / 源文件。**每一次**模型响应都必须穿过上面表格里的校验函数。

### 1.3 统一的异常分类

所有模型异常必须走 `_classify_provider_exception`（`translation/translator.py:99`，也被 `llm_repair` 复用）：

| 异常类 | 触发条件 | 上层应对 |
|---|---|---|
| `RateLimitedError` | HTTP 429 / "rate limit" / "too many requests" | 读 `retry_after_s` 后重试 |
| `QuotaExceededError` | HTTP 402 / "insufficient_quota" / "额度不足" 等 | **不重试**，上报用户更换 key |
| `NonRetryableProviderError` | 4xx 参数 / 鉴权错误 | **不重试**，暴露 `status_code` + `detail` |
| `TransientProviderError` | 5xx / 连接异常 | 短退避重试 |
| `VisionModelRequestError` | VLM 专用，带 `stage / retryable` | `retryable=False` 直接失败，否则回退到 local scan |

新增 LLM 调用时**必须**在 `except Exception as exc:` 里调用 `_classify_provider_exception(exc)` 或抛 `VisionModelRequestError`，不要裸 `raise`。

---

## 二、模块一：视觉目录解析（VLM）

### 2.1 职责

从 PDF 的视觉页中找到目录页、并按层级抽取章节条目（含 Part / Book / Chapter / Section / Appendix 等 role_hint）。产出 `visual_toc` items，供下游章节骨架 (`FNM_RE/modules/toc_structure.py`) 使用。

### 2.2 调用链

入口：`generate_auto_visual_toc_for_doc`（`pipeline/visual_toc/runtime.py`）。完整调用链：

```
generate_auto_visual_toc_for_doc
├─ confirm_model_supports_vision        # preflight 探针，见 2.5
├─ _extract_local_toc_page_features     # 本地 PDF 文本层扫描，选候选页，不走 LLM
├─ _classify_toc_candidates             # 第一次 VLM：判断是否是目录页（batch=4）
├─ _collect_toc_clusters                # 规则聚类
├─ _extract_visual_toc_page_items_*     # 第二次 VLM：逐页抽条目
├─ _extract_visual_toc_organization_nodes_from_images  # 第三次 VLM：整体层级重建
├─ filter_visual_toc_items              # 代码校验（过滤摘要 / 容器去重 / role 归一）
└─ _annotate_visual_toc_organization    # 视觉顺序 + 容器 override
```

所有 VLM 请求都走 `pipeline.visual_toc.vision._call_vision_json`；失败由 `pipeline.visual_toc.runtime._vision_failure_result` 统一封装。

### 2.3 三个 Prompt 的契约

**不要动文案，除非你同步改 `filter_visual_toc_items` 的过滤规则。**以下所有字段都是后续模块依赖的硬契约。

#### (a) `_classify_toc_candidates`（`pipeline/visual_toc/vision.py`）

- **输入**：`page_indices`（PDF file_idx 列表），每页渲染 scale=0.9。
- **batch size**：4 页 / 次。
- **`max_tokens`**：900。
- **输出 JSON**：
  ```json
  [{"file_idx":12,"label":"not_toc|toc_start|toc_continue","score":0.0,"header_hint":"..."}]
  ```
- **关键业务约束**（写在 Prompt 里）：
  - 必须识别法语 `Sommaire`（书前）/ `Table des matières`（书后）。
  - 西语 / 葡语 / 意语的 `Índice` 是目录；英 / 法语的 `Index / Notes / Bibliography` **不是**目录。
  - 页顶只有大写 `Table` 也要视为强提示。

#### (b) `_extract_visual_toc_page_items_from_pdf` / `_extract_visual_toc_page_items_from_image`（`pipeline/visual_toc/vision.py`）

- **输入**：单页目录截图，scale=2.0。
- **`max_tokens`**：2200。
- **输出 JSON 数组**：
  ```json
  [{"title":"...","depth":0,"printed_page":12,"visual_order":1,"role_hint":"chapter"}]
  ```
- **`role_hint` 枚举（硬契约）**：`container / chapter / section / post_body / back_matter / front_matter`。下游 `_normalize_visual_toc_role_hint`（`pipeline/visual_toc/organization.py`）以此为白名单。
- **排除项**：目录页总标题（Contents / Sommaire / Table des matières）、下方摘要 / 说明文字。

#### (c) `_extract_visual_toc_organization_nodes_from_images`（`pipeline/visual_toc/vision.py`）

- **输入**：整份目录页截图列表 + 已抽取的 `seed_titles`（最多 80 条）作为锚点。
- **`max_tokens`**：3200。
- **输出 JSON**：在 (b) 基础上多一个 `parent_title` 字段。
- **作用**：补回 (b) 中漏掉的容器层（如 Part / Book / COURS）。

### 2.4 代码侧校验（硬拦截点）

| 校验位置 | 作用 |
|---|---|
| `_parse_json_payload`（`pipeline/visual_toc/vision.py`） | 去除 ```json``` 包裹、容错解析最外层 `{}` / `[]` |
| `filter_visual_toc_items`（`pipeline/visual_toc/organization.py`） | 丢弃无页码又无 role 的容器行；用 `_looks_like_summary_text` 拦摘要 |
| `_normalize_visual_toc_role_hint`（`pipeline/visual_toc/organization.py`） | 把非白名单的 `role_hint` 回退成空字符串 |
| `_filter_resolved_visual_toc_anomalies`（`pipeline/visual_toc/organization.py`） | 过滤 frontmatter 假目录、Notes 区段假目录 |
| `_annotate_visual_toc_organization`（`pipeline/visual_toc/organization.py`） | 重建 `visual_order` 与容器 override |

**重要：**页码不要求严格递增——真实书有罗马卷首、跨卷重置、附录交叉。相关校验只在 `_filter_resolved_visual_toc_anomalies` 做宽松过滤，**不要加"页码必须递增否则重试"这种硬逻辑**。

### 2.5 失败降级

`VisionModelRequestError`（`pipeline/visual_toc/shared.py`）定义三级可重试性：

```python
retryable = status_code in {429, 500, 502, 503, 504}
```

`generate_auto_visual_toc_for_doc` 内部已处理：
- `confirm_model_supports_vision`（`pipeline/visual_toc/vision.py`）失败 → 返回 `status="unsupported"`，走 `local_scan` 退化。
- 第一次 classify 失败且 `retryable=True` → 进入 `visual_retry` 阶段用 `retry_indices` 扩搜。
- classify 成功但未形成 cluster → 返回 `reason_code="*_text_layer/no_toc_cluster_after_retry"`。
- 抽 items 失败且 `retryable=False` → 直接 `_vision_failure_result` 终止，**不要偷偷回退到本地扫描**。

### 2.6 如何修改 / 扩展

- 改 Prompt：只改文案描述，**不要改 JSON 字段名与枚举值**。改字段需同步改 §2.4 表中所有校验函数。
- 新增一种 VLM 任务：**必须**复用 `_call_vision_json`，不要新建 client。新的 `stage` 字符串写成 `动作名[粒度]` 格式（例：`classify_toc_candidates[3-6]`），便于日志追踪。
- 换模型：只需改 `config.get_visual_custom_model_config()` 返回的 `model_id / base_url / api_key`；Prompt 不需要动。

---

## 三、模块二：章内语义切分（**当前未接 LLM**）

### 3.1 状态

[FNM_RE/modules/chapter_split.py](../FNM_RE/modules/chapter_split.py)（458 行）**是纯规则切分**：
- 按 OCR 文本块的位置 / 字号 / footnote band 几何位置分正文 vs 脚注。
- 按 `toc_structure` 的章节边界切章内单元。
- 输出真相对象 `ChapterLayers`，字段见 `FNM_RE/modules/contracts.py`。

**目前没有任何 LLM 调用经过这里。**

### 3.2 如果未来要接 LLM（设计约束）

这是当前最容易被误用 LLM 的地方。如果将来要接，必须遵守以下边界（对应"控制面剥离"原则）：

1. **模型只输出决策 JSON，不回吐文本。**
   输入传一个带稳定块 id 的 OCR 片段列表：
   ```json
   [
     {"block_id":"p42_b3","text":"..."},
     {"block_id":"p42_b4","text":"..."}
   ]
   ```
   输出只允许这两种形态之一：
   ```json
   {"classify":[{"block_id":"p42_b3","kind":"body|title|footnote"}, ...]}
   ```
   或
   ```json
   {"merge":[{"block_ids":["p42_b4","p43_b1"],"reason":"cross_page_sentence"}, ...]}
   ```
   由 Python 侧按 block_id 执行实际合并/标注。

2. **禁止**让 LLM 原样回吐合并后的文本再用字数差校验——这会浪费 token、触发幻觉、把控制面混进内容面。字数差校验只能作为已经违反本条约束时的**补丁**，不能当设计。

3. **输入上下文上限**：不超过 2 页文本块（约 1200 字符 * 2）。跨页拼接只允许相邻页。

4. **校验**：Python 侧比对 `block_id` 白名单（输出中出现的 id 必须全部在输入里），越界 id 直接丢弃。

5. **复用**：必须通过在 `translation/translator.py` 或 `FNM_RE/llm_repair.py` 新增函数接入，**不要**在 `chapter_split.py` 里直接 `from openai import OpenAI`。

### 3.3 当前的替代路径

如果规则切分出问题，现有兜底是：
- 低质量 OCR 页 → `pipeline/visual_toc/runtime.py` 的 degraded-text-layer 分支会用 VLM 重新扫候选页。
- 跨页脚注 / 正文 → `FNM_RE/modules/chapter_split.py` 内部的 `note_region_binding` 规则已经可以处理。
- 不要在这里新加 LLM 补丁，除非上面两条规则穷举之后仍有无法覆盖的长尾。

---

## 四、模块三：尾注孤儿修补（多模态 LLM）

### 4.1 漏斗总览

对齐尾注（endnote）→ 正文引用（anchor）是四级漏斗（2026-04 扩展）：

```
Tier 0  _repair_endnote_links_for_contract    确定性 OCR 字符修复（非 LLM）
        FNM_RE/modules/note_linking.py:303

Tier 1a 纯文本 LLM + rapidfuzz synthesize_anchor   正文短语模糊定位（本模块）
        FNM_RE/llm_repair.py（locate_anchor_phrase_in_body）

Tier 1b 多模态 LLM match / ignore_ref         多模态 LLM 修补（本模块）
        FNM_RE/llm_repair.py:run_llm_repair

Tier 2  fnm_review_overrides 表                人工 override
        scope ∈ {link, anchor, llm_suggestion}
```

Tier 1a：针对「有孤儿 note_item、没有结构化 anchor」的 cluster，让 LLM 从正文摘录里回填一个 3–12 词的短语，然后用 rapidfuzz `partial_ratio_alignment` 在正文里模糊定位，产出一个 `source="llm", synthetic=False` 的真实坐标 anchor 并写回 `scope="anchor"` + `scope="link"` 双 override。

Tier 1b：沿用原来的多模态输入（文本嫌疑段 + 嫌疑页截图），模型只输出动作（match / ignore_ref / synthesize_anchor / needs_review），不碰源文本。

### 4.2 入口与 HTTP 路由

- 公开函数：`run_llm_repair`（`FNM_RE/llm_repair.py:547`），对外通过 `from FNM_RE import run_llm_repair`（`FNM_RE/__init__.py:24`）导出。
- HTTP 入口：`POST /api/doc/<doc_id>/fnm/review/llm-repair`，实现在 `web/translation_routes.py:1210`。
- 命令行：`python scripts/run_fnm_llm_repair.py`。

三个入口最终都调 `run_llm_repair(doc_id, *, repo=None, cluster_limit=1, auto_apply=True, confidence_threshold=0.9, model_args=None)`。

### 4.3 Cluster 构造（`build_unresolved_clusters`，`FNM_RE/llm_repair.py:94`）

按 `(chapter_id, region_id, note_system)` 聚合所有 `note_links` 中 `status ∈ {matched, orphan_note, orphan_anchor, ambiguous}` 的 endnote link，产出：

```python
{
  "cluster_id": "<chapter_id>:<region_id>:endnote",
  "chapter_id", "chapter_title",
  "note_system": "endnote",
  "matched_examples": [...],        # 作为 few-shot 范例，取 3 个
  "unmatched_note_items": [...],    # 孤儿尾注条目
  "unmatched_anchors": [...],       # 孤儿正文引用
  "page_start", "page_end"
}
```

按"未匹配数量倒序 + 起始页正序"排序，`cluster_limit` 控制本轮处理多少个。

### 4.4 请求截取（`_slice_cluster_for_request`，`FNM_RE/llm_repair.py:212`）

**硬上限常量（`FNM_RE/llm_repair.py:33-36`）：**
```python
LLM_REPAIR_SOFT_INPUT_TOKEN_BUDGET    = 2_048
LLM_REPAIR_MAX_OUTPUT_TOKENS          = 768
LLM_REPAIR_MAX_MATCHED_EXAMPLES       = 2
LLM_REPAIR_MAX_UNMATCHED_DEFINITIONS  = 8
LLM_REPAIR_MAX_UNMATCHED_REFS         = 8
```

即使模型上下文是 100 万 token，这里也故意压到 2K——**修补任务的延迟和错误率都和输入规模强相关**。

**`request_mode` 四档**（决定 `allowed_actions`）：

| request_mode | 触发条件 | allowed_actions |
|---|---|---|
| `paired` | 有孤儿 note + 有孤儿 anchor + 无章节正文 | `match / ignore_ref / needs_review` |
| `paired`（带正文） | 有孤儿 note + 有孤儿 anchor + 章节正文可用 | `match / ignore_ref / synthesize_anchor / needs_review` |
| `ref_only` | 只有孤儿 anchor | `ignore_ref / needs_review` |
| `note_only` | 只有孤儿 note，无正文 | `needs_review` |
| `note_only_with_body` | 只有孤儿 note，有章节正文 | `synthesize_anchor / needs_review` |
| `review_only` | 两边都空 | `needs_review` |

`chapter_body_text` 由 `_build_chapter_body_text` 按 `(start_page, end_page)` 拼接 markdown 正文产出，同时维护 `(page_no, char_start, char_end)` 分段映射，用于把命中的字符偏移还原成页码。Prompt 里注入 `chapter_body_excerpt`（`_trim_excerpt` 压到 1800 字符）并提示 `anchor_phrase` 必须从摘录里**逐字抄写** 3–12 词。

Prompt 里会写明 `本次只允许动作：xxx`（`FNM_RE/llm_repair.py:288-293`），超出白名单的动作会在解析阶段被 `parse_llm_repair_actions` 丢弃。

### 4.5 Prompt

#### System（`_repair_system_prompt`，`FNM_RE/llm_repair.py:184`）

```
你是 FNM 尾注修补助手。
只处理已经确认的 unresolved cluster，不要改 section、note zone、标题或原文。
你只能输出 JSON 数组；每项 action 只能是 match、ignore_ref 或 needs_review。
match 需要 note_item_id、anchor_id、confidence、reason；
ignore_ref 需要 anchor_id、confidence、reason；
needs_review 需要 reason。
```

#### User（`_repair_user_prompt`，`FNM_RE/llm_repair.py:241`）

- `/no_think` 前缀强制非思考模式（qwen3.5-plus 的开关，同时在 `extra_body={"enable_thinking": False}` 里兜底，`FNM_RE/llm_repair.py:483`）。
- 载荷是 JSON：`cluster_id` / `chapter_title` / `page_range` / `allowed_actions` / `page_contexts` / `matched_examples`（few-shot）/ `unmatched_note_items` / `unmatched_anchors`。
- 每条正文 / 尾注摘录经 `_trim_excerpt`（`FNM_RE/llm_repair.py:195`）压到 240 字符。
- 每页 OCR 摘录经 `_trim_page_text`（`FNM_RE/llm_repair.py:411`）压到 900 字符。

#### 多模态图片（`_build_cluster_page_contexts`，`FNM_RE/llm_repair.py:418`）

- 从 `raw_pages.json` 拿 `bookPage → markdown` 映射。
- 用 `render_pdf_page(pdf_path, file_idx, scale=1.3)` 渲染嫌疑页，base64 编码成 `data:image/png;base64,...` URL。
- 每个 cluster 最多带 3 张图（`_cluster_focus_pages`）。
- 图片通过 `user_content.append({"type":"image_url","image_url":{"url":...}})` 拼到消息里（`FNM_RE/llm_repair.py:460`）。

### 4.6 输出校验

两层：

**第一层：`parse_llm_repair_actions`**
- 去掉 ```json``` 包裹，容错切出 `[...]`。
- 允许外层是 `{"actions":[...]}`。
- **只保留 `action ∈ {match, ignore_ref, synthesize_anchor, needs_review}` 的条目**（硬白名单）。
- 归一化字段：`note_item_id / anchor_id / anchor_phrase / confidence / reason`；`synthesize_anchor` 缺 `anchor_phrase` 的一律丢弃。

**第二层：`select_auto_applicable_actions`**
- `confidence < confidence_threshold`（默认 0.9）直接丢。
- **互斥使用集合**：每个 `note_item_id` 和 `anchor_id` 最多被消费一次，并且 `synthesize_anchor` 共用 `note_item_id` 集合，避免同一条尾注既 `match` 又 `synthesize`。
- `synthesize_anchor` 额外门槛：
  - `fuzzy_score ≥ FUZZY_SCORE_THRESHOLD`（默认 88）。
  - `ambiguous == False`（正文里不能存在多处分数接近的命中，差值由 `FUZZY_AMBIGUITY_MARGIN = 5.0` 控制）。
  - `chapter_unmatched_count ≥ MIN_CHAPTER_UNMATCHED_FOR_AUTO`（默认 3）——单条孤儿章节不许自动合成，强制人工复核。
- 只有 `match / ignore_ref / synthesize_anchor` 会进入自动执行，`needs_review` 永不自动应用。

### 4.7 持久化：`fnm_review_overrides` 表

`run_llm_repair` 的写入合同（`FNM_RE/llm_repair.py:570-629`）：

1. 先 `repo.clear_fnm_review_overrides(doc_id, scope="llm_suggestion")` 和 `scope="anchor"`——**每轮全量重建**。
2. 每个模型动作写一条 `scope="llm_suggestion"`，`suggestion_id = llm-<cluster>-<action>`，payload 里除通用字段外还会带上 `anchor_phrase / fuzzy_score / fuzzy_hit / ambiguous / matched_text`，便于人工审查。
3. 通过第二层校验的动作：
   - `match`：写 `scope="link"`，`key=link_id`，payload `{"action":"match", "note_item_id":..., "anchor_id":...}`。
   - `ignore_ref`：写 `scope="link"`，`{"action":"ignore"}`。
   - `synthesize_anchor`：先写 `scope="anchor"`，`key=llm-synth-<link_id>`，payload 包含 `{action:"create", anchor_id, chapter_id, page_no, paragraph_index, char_start, char_end, source_text, normalized_marker, anchor_kind:"endnote", certainty, source:"llm", synthetic:False, anchor_phrase, fuzzy_score}`；再写 `scope="link"`，`{"action":"match", note_item_id, anchor_id=<new_anchor_id>}`。
4. `scope="link"` 和 `scope="anchor"` 的 override 由 `note_linking` 下一次运行消费：anchor 级 override 会被 materialize 成真实 `fnm_body_anchors` 行（保持 `synthetic=False` 以便 ref_freeze 接纳，`source="llm"` 用于审计）。

### 4.8 请求指标

返回值里的 `request_metrics`（`FNM_RE/llm_repair.py:499`）字段建议**必须记录到日志**：
- `chars` / `estimated_prompt_tokens` / `soft_input_token_budget`：预算监控。
- `truncated`：只要为 `True` 说明触发了截断上限，要评估是否调大常量或拆分 cluster。
- `request_mode` / `allowed_actions`：后续 review 时快速判断是"没见到动作"还是"动作被拒"。

### 4.9 已知的弱点（改造建议，不必立刻动）

- **第一级 repair 没走 LLM，第二级一上来就是多模态**：中间可以插一档"纯文本 LLM，返回多候选锚点句子的稀有子串"，用 `rapidfuzz` 做近似匹配。现在跳过这档会让容易的 case 也付图片编码代价。
- **"last 5 words" 风格的锚定没有**：当前 Prompt 让模型直接回 `note_item_id / anchor_id`，这是因为 Tier 0 已经把锚点 id 结构化了。如果 Tier 0 失败后发现还有未结构化的 anchor，走 fuzzy 寻址比多模态更省。
- 没有 golden set；建议按 `tests/` 目录新增固定 cluster 样本做回归。

---

## 五、模块四：翻译中的占位符冻结与标签保护（Text-LLM）

### 5.1 职责

把正文段落翻成简体中文，同时保证以下不变量：
1. 脚注 / 尾注引用占位符 `{{NOTE_REF:xxx}}`（及历史格式 `{{FN_REF:xxx}} / {{EN_REF:xxx}}`）**原样保留并落在正确语义位置**。
2. 术语词典（glossary）映射被硬使用。
3. 脚注与正文字段严格分离（`original` / `translation` / `footnotes` / `footnotes_translation`）。
4. 标题段不吸收正文，正文段不编造脚注。

### 5.2 两层占位符（关键设计）

**第一层（业务层）：`{{NOTE_REF:xxx}}`**
- 由 `FNM_RE/modules/ref_freeze.py` 在翻译前注入到段落文本。
- 作用是让每个注释引用在翻译管线里有稳定 id，便于后续 merge 阶段解冻回 `[^n]`。
- Prompt 显式硬约束"必须原样保留 `{{NOTE_REF:xxx}}`"（`translation/translator.py:218-223` 和 `286`）。

**第二层（调用层）：`__FNM_REF_n__`**
- 由 `_freeze_fnm_refs`（`translation/translator.py:587`）在**发请求前**把所有 `{{(NOTE|FN|EN)_REF:[^}]+}}` 替换为顺序编号的 `__FNM_REF_n__` 占位符。
- `_restore_fnm_refs`（`translation/translator.py:600`）在**拿到译文后**还原。
- 还原时做**断言**：任何一个原 token 在译文里找不到就抛 `RuntimeError("FNM 引用标记未保留")`。

**为什么是两层？**
- 第一层面向业务（合并 / 解冻流程要读 `NOTE_REF` 的 key）。
- 第二层面向模型（`{{...}}` 在 tokenizer 里会被拆、也容易被模型"修正"成 Markdown `[^]`）。`__FNM_REF_n__` 是一个长度稳定、字符极罕见的字符串，tokenization 稳。

> **新增占位符格式时必须同步更新 `_freeze_fnm_refs` 的正则**，否则会穿透到 Prompt 裸露，导致模型误以为可以翻译大括号内的内容。

### 5.3 调用入口

| 入口函数 | 行号 | 用途 |
|---|---|---|
| `translate_paragraph` | `translation/translator.py:1241` | 非流式翻译（默认） |
| `stream_translate_paragraph` | `translation/translator.py:1353` | 流式翻译（前端实时显示） |
| `_translate_with_mt` | 由 `translate_paragraph` 调用 | provider="qwen_mt" 分支 |
| `_call_openai_chat` | `translation/translator.py:534` | 非流式底层 |
| `_call_openai_mt` | `translation/translator.py:612` | Qwen-MT 专用底层（走 `translation_options`） |
| `_stream_openai_chat` | `translation/translator.py:742` | 流式底层 |
| `_stream_openai_mt` | `translation/translator.py:805` | Qwen-MT 流式底层 |

所有 worker（`translation/translate_worker_*.py`）最终都会收敛到这几个函数。

### 5.4 Prompt 契约

**System Prompt** 由 `build_prompt(gloss_str, content_role, is_fnm)`（`translation/translator.py:179`）动态拼：
- 默认：正文翻译规则 + 脚注硬契约。
- `is_fnm=True`：追加 `{{NOTE_REF:xxx}}` 保留硬约束（`translation/translator.py:218-223`）。
- `content_role="footnote"`：追加"单条脚注，禁止正文化 / 吞号"。
- `content_role="endnote"`：追加"单条尾注，禁止正文化 / 吞号"。
- 带 glossary 时追加"术语词典硬约束"。

**User Message** 由 `_build_translate_message`（`translation/translator.py:258`）拼：
- 顶部元信息：`页码 / 导出契约 / 脚注约束 / 内容角色 / 段落类型 / 段落序号 / 章节路径 / 跨页标记`。
- 正文在 `===正文===` / `===正文结束===` 之间。
- 可选前文片段（200 字，从末尾截）、后文片段（200 字，从开头截）。
- 脚注在 `===页面脚注===` 之间，**无脚注时必须显式写"本页无脚注"**（Prompt 硬要求 `footnotes` 为空字符串）。

**输出 JSON**：
```json
{
  "pages": "页码",
  "original": "校正后的正文原文",
  "footnotes": "校正后的脚注原文",
  "translation": "正文的简体中文翻译",
  "footnotes_translation": "脚注的简体中文翻译"
}
```

### 5.5 代码侧校验

`translate_paragraph` 的响应处理（`translation/translator.py:1314-1348`）执行了以下闭环：

1. **JSON 解析**：`parse_json_response`（`translation/translator.py:385`），容错修复未转义换行。
2. **`pages` 兜底**：缺 `pages` 字段就回填输入 `para_pages`。
3. **`original` 清洗**：去掉行首 `>`，避免模型把原文当 markdown 引用块。
4. **`footnotes` / `footnotes_translation` 归一**：`_normalize_optional_text` + `.strip()`。
5. **`translation` 归一**：`_normalize_translation_text`（`translation/translator.py:315`），清理多余空行并按标题/正文做尾部规则。
6. **术语强制**：
   - `_collect_required_glossary`（`translation/translator.py:327`）算出输入段落真正引用了哪些词典项。
   - `_missing_glossary_defs`（`translation/translator.py:331`）比对译文中是否缺失。
   - 缺失则调 `_enforce_glossary_rewrite`（`translation/translator.py:345`）让模型**只改术语不改语义**再跑一次。
7. **占位符还原**：由 worker 层在外层调 `_restore_fnm_refs`，如果任意 `{{NOTE_REF:xxx}}` 丢失直接抛错（见 5.2）。

> 所有 worker（streaming / continuous / fnm / glossary）必须**在调用后校验**，不能直接 `return response.text`。

### 5.6 Qwen-MT 专用路径

`_call_openai_mt`（`translation/translator.py:612`）走 DashScope 的 `translation_options`：

```python
extra_body = {
    "translation_options": {
        "source_lang": "auto",
        "target_lang": "Chinese",
        "terms": [{"source": "...", "target": "..."}, ...]  # glossary 硬约束
    }
}
```

这条路径**没有 system prompt**（由 DashScope 内置），所以：
- `is_fnm=True` 时的占位符保护**仍然生效**——因为 `_freeze_fnm_refs` 在请求前已经把 token 替换成 `__FNM_REF_n__`，MT 模型会当成不可翻译的私有符号透传。
- 词典通过 `terms` 参数硬约束，比 Prompt 提示更强。
- 输出是纯译文字符串，不是 JSON，所以 `_translate_with_mt` 会手工组装成标准字典。

### 5.7 流式输出的特殊处理

`_stream_openai_chat`（`translation/translator.py:742`）与 `_stream_openai_mt`（`translation/translator.py:805`）逐 chunk 累积文本：
- 通过 `stop_checker` 回调支持外部中止，抛 `TranslateStreamAborted`。
- 流结束后走同一套 `parse_json_response` + 占位符还原校验。
- **不要**在流式 chunk 阶段做占位符检查——`{{NOTE_REF:xxx}}` 可能跨 chunk 边界。检查必须在全部 chunk 拼完之后。

---

## 六、共享基建速查

### 6.1 Token 预算

| 场景 | `max_tokens` | 位置 |
|---|---|---|
| VLM 目录识别 batch | 900 | `pipeline/visual_toc/vision.py` |
| VLM 单页目录抽取 | 2200 | `pipeline/visual_toc/vision.py` |
| VLM 整体组织重建 | 3200 | `pipeline/visual_toc/vision.py` |
| VLM preflight 探针 | 由 `_call_vision_json` 默认 1200 | `pipeline/visual_toc/vision.py` |
| LLM 修补输出 | 768 | `FNM_RE/llm_repair.py:34` |
| 翻译非流式 | 4096 | `translation/translator.py:541`、`:626` |

### 6.2 JSON 解析兜底

两套等价实现（有轻微差异，**不要合并**，保持独立演化）：
- `_parse_json_payload`（`pipeline/visual_toc/vision.py`）：最外层 `{}` 或 `[]` 切片。
- `parse_json_response`（`translation/translator.py:385`）：额外做未转义换行修复。
- `_parse_json_array`（`translation/translator.py:668`）：数组专用。
- `parse_llm_repair_actions`（`FNM_RE/llm_repair.py:298`）：动作专用，带动作白名单。

### 6.3 异常分类

见 §1.3。新增模型调用时用法：
```python
try:
    response = client.chat.completions.create(...)
except Exception as exc:
    raise _classify_provider_exception(exc) from exc
```
VLM 侧等价写法：
```python
except Exception as exc:
    status_code, detail = _extract_vision_error_detail(exc)
    retryable = status_code in {429, 500, 502, 503, 504}
    raise VisionModelRequestError(
        message, stage=stage, status_code=status_code,
        retryable=retryable, detail=detail,
    ) from exc
```

### 6.4 超时 / 限流

- VLM：`_call_vision_json` 默认 `timeout=90.0`（`pipeline/visual_toc/vision.py`）。
- LLM 修补：`timeout=45.0` + 信号级 `_time_limit(60)`（`FNM_RE/llm_repair.py:472-483`）。
- 翻译：OpenAI 客户端默认超时（未显式设），依赖上层 retry。

### 6.5 置信度门槛

- LLM 修补 auto-apply：`confidence_threshold=0.9`（`run_llm_repair` 默认参数）。
- `synthesize_anchor` 的额外门槛：
  - `FUZZY_SCORE_THRESHOLD = 88`：rapidfuzz `partial_ratio` 分数下限。
  - `FUZZY_AMBIGUITY_MARGIN = 5.0`：屏蔽主命中后再扫一次，次命中分数只要还在 `score - 5` 以内就判为歧义。
  - `MIN_CHAPTER_UNMATCHED_FOR_AUTO = 3`：本章孤儿尾注少于 3 条时不自动合成，强制人工复核。
- 翻译无置信度；改为"缺词典 → 二次改写"闭环。
- 新增置信度类设计请对齐 LLM 修补的"互斥使用集合"逻辑，避免同一个 id 被多次消费。

---

## 七、执行清单（给改造者的交付项）

拿到任何一项 LLM 相关改造任务，上岗前核对以下清单：

1. **找到真调用点**：是否在 §1.1 的三个文件内？不在就先停下，考虑是否应该扩展现有入口而非新建。
2. **对照 §1.2 三原则**：你的输入上下文有没有超 2K token 预算？模型是否只输出决策 JSON？有没有闭环校验？
3. **Prompt 改动评估**：
   - 只是文案 → 改 Prompt 即可。
   - 涉及 JSON 字段、`role_hint` 枚举、`action` 白名单 → 必须同步改 §2.4 / §4.6 / §5.5 的校验函数。
4. **异常路径**：新增 try/except 是否走了 `_classify_provider_exception` 或 `VisionModelRequestError`？
5. **占位符**：翻译链路上如果引入新占位符格式，`_freeze_fnm_refs` 的正则（`translation/translator.py:588`）是否同步更新？
6. **持久化**：LLM 产物是否写了 `fnm_review_overrides`（scope="llm_suggestion" 全量重建）？直接写入业务表属于跨权限，不允许。
7. **日志**：是否记录 `request_metrics`（至少 `stage / chars / truncated / status_code`）？
8. **回归**：本次改动至少要能跑通 `python scripts/run_fnm_llm_repair.py` 和一次 `translate_paragraph` 冒烟（Biopolitics 样本）。

---

## 八、索引

- 三大调用入口：
  - [`_call_vision_json`](../pipeline/visual_toc/vision.py)
  - [`_call_openai_chat`](../translation/translator.py) — `translation/translator.py:534`
  - [`request_llm_repair_actions`](../FNM_RE/llm_repair.py) — `FNM_RE/llm_repair.py:454`
- 三大校验函数：
  - [`filter_visual_toc_items`](../pipeline/visual_toc/organization.py)
  - [`_restore_fnm_refs`](../translation/translator.py) — `translation/translator.py:600`
  - [`select_auto_applicable_actions`](../FNM_RE/llm_repair.py) — `FNM_RE/llm_repair.py:339`
- 异常分类：[`_classify_provider_exception`](../translation/translator.py) — `translation/translator.py:99`
- 持久化 override：`web/translation_routes.py:1210`（HTTP 入口）、`FNM_RE/llm_repair.py:570`（写入合同）
- 子模块设计原点：[FNM_RE/Overview.md](../FNM_RE/Overview.md)
