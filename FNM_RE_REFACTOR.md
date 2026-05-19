# FNM_RE 代码结构重构清单

## 第一轮：结构重构（P0–P2）

| # | 优先级 | 问题 | 状态 |
|---|--------|------|------|
| 1 | P0 | `_apply_link_overrides` 在 pipeline.py 和 note_linking.py 中重复定义 | ✅ 已修 |
| 2 | P1 | 9 个子进程脚本功能重叠，省内存改动遗留 | ✅ 已修 |
| 3 | P1 | 根级大文件错位：llm_repair / status / page_translate 应下沉到子包 | ✅ 已修 |
| 4 | P2 | stages/ → modules/ 反向依赖（2 处 lazy import） | ✅ 已修 |
| 5 | P2 | 死文件：shared/export_audit.py | ✅ 已删 |
| 6 | P3 | modules/note_linking.py 过大（1730 行） | ⏸️ 搁置 |
| 7 | P3 | 两套 pipeline API 并行 | ⏸️ 搁置 |

## 第二轮：深度审计（口径一致性 / 反向依赖）

| # | 优先级 | 问题 | 状态 |
|---|--------|------|------|
| 8 | P1 | `chapter_id` 类型不稳，70+ 处防御性 `str(x or "")` | 🔴 待修 |
| 9 | P1 | `NoteItemRecord.note_kind` 是 `str=""` 而非 `NoteKind` Literal | ✅ 已修 |
| 10 | P2 | `note_mode` 别名映射散落在多处，反序列化用启发式 | ✅ 已修 |
| 11 | P2 | `dev/phase_runner.py` 反向导入 `app.pipeline` / `app.persist_helpers` | ✅ 已修 |
| 12 | P3 | `stages/diagnostics.py:269` 启发式 fallback 推断 note_kind | ✅ 已修 |

---

## 问题详情

### 1. `_apply_link_overrides` 重复定义 (P0) ✅

- ~~`FNM_RE/app/pipeline.py:604` — 120 行版本，返回 `(links, summary)`~~
- `FNM_RE/modules/note_linking.py:567` — 190 行版本，返回 `(links, summary, logs)`（唯一权威实现）
- **已修复**：pipeline.py 的 120 行实现替换为 thin wrapper，委托 note_linking 的版本并丢弃 logs

### 2. 子进程脚本扇出过多 (P1) ✅

原 9 个文件，已整理为 4 个：
- ✅ `subprocess_runner.py` — 三段式调度器（唯一入口）
- ✅ `subprocess_phase1.py` — Phase 1 worker
- ✅ `subprocess_phase2.py` — Phase 2 worker
- ✅ `subprocess_phase3_6.py` — Phase 3-6 worker

已删除 5 个冗余文件：`phase12.py`、`phase36.py`、`phase_phase1.py`、`subprocess_phases.py`、`subprocess_pipeline.py`
`__init__.py` 的 `run_doc_pipeline_subprocess` / `run_doc_pipeline_phased_subprocess` 均指向 `subprocess_runner`

### 3. 根级大文件错位 (P1) ✅

全部 5 个文件已移至正确子包，所有 import 已更新：
- `llm_repair.py` → `modules/llm_repair.py`（7 处导入已更新）
- `status.py` → `app/status.py`（5 处导入已更新）
- `page_translate.py` → `app/page_translate.py`（9 处导入已更新）
- `review.py` → `shared/review.py`（2 处导入已更新）
- `db_reconstruct.py` → `app/db_reconstruct.py`（2 处导入已更新）

### 4. stages/ → modules/ 反向依赖 (P2) ✅

- `_cleanup_nested_note_refs` 及 3 个正则常量从 `modules/ref_freeze.py` 下沉到 `shared/refs.py`（公共名 `cleanup_nested_note_refs`）
- `stages/units.py` 和 `modules/ref_freeze.py` 均改为从 `shared/refs` 导入
- `stages/body_anchors.py` 的 LLM verify 改为 `bare_digit_verifier` 回调参数注入，modules 层调用时注入实际函数
- stages/ 现在零 `from FNM_RE.modules` 导入

### 5. 死文件 (P2) ✅

- `shared/export_audit.py` — 0 处 import → **已删除**
- ~~`shared/segment_codec.py`~~ — 经确认被 persistence 层使用（`FNM_RE/app/persistence.py` 导入），非死文件，从清单移除

### 6. modules/note_linking.py 过大 (P3) ⏸️ 评估后搁置

1730 行，22 个函数。评估结论：**不拆**。
- 函数边界已经清晰，12 个 <30 行工具函数 + 6 个大型业务逻辑函数
- 大函数是业务密集型（`_chapter_contracts` 274 行、`_repair_explicit_footnote_anchor_ocr_variants` 219 行），拆到别的文件不减少复杂度
- 19 个外部消费者（10 测试 + 4 生产）需同步改路径
- 当前无 bug 或开发瓶颈源于文件大小

### 7. 两套 pipeline API 并行 (P3) ⏸️ 评估后搁置

评估结论：**不统一**。
- Phase-by-Phase（测试用切面工具，130+ 引用）和 Module Pipeline（生产入口，带 DB/subprocess/LLM repair）职责本就不同
- 唯一的真实代码重复（`_apply_link_overrides`）已在 P0 中消除
- 统一会让测试变慢变脆弱或让生产代码暴露不必要的旁路

---

## 第二轮问题详情

### 8. `chapter_id` 类型不稳 (P1)

**现状**：
- 全 dataclass 中 `chapter_id: str`，无格式约束
- 全包 70+ 处 `str(chapter_id or "")` / `str(row.get("chapter_id") or "")` 防御性转换
- 多种格式来源：TOC 来源（`"toc-ch-X"`）、fallback 来源（`"ch-fallback-X"`）、LLM override 来源等

**上下文（为什么这么写）**：
- 历史上 chapter_id 可能为 None / 空串 / int（从 DB 不同 schema 演化），所以加防御
- 多种前缀格式（toc-ch / ch-fallback）反映 chapter 来源的多通道（visual TOC / 自动 fallback / 手工 override）
- `stages/_link_utils.py:_is_fallback_chapter_id` 等函数依赖前缀判定章节来源

**风险点**：
- chapter_id 在 DB 里以 TEXT 存储，但反序列化时 row.get 可能拿到 None
- 改成 NewType 后必须确保所有创建点都用 NewType 包装

**修复方案**：
- 在 `shared/` 添加 `chapter_id.py`：`ChapterId = NewType("ChapterId", str)` + `make_chapter_id()` 工厂函数（拒绝空串、强制 str）
- 工厂函数集中校验前缀格式，把 `_is_fallback_chapter_id` 等也移过去
- 逐步替换 dataclass 类型注解（保留运行时 str 兼容性，因为 NewType 在 runtime 就是 str）

### 9. `NoteItemRecord.note_kind` 类型降级 (P1) ✅

**调查发现**：
- 所有 6 个生产创建点都显式传 `note_kind`，默认空串实际几乎不触发
- 上游 `LayerNoteItem.note_kind: NoteKind`（Literal）—— 派生关系成立
- DB schema `note_kind TEXT NOT NULL` —— 反序列化路径有保障

**修复**：
- `NoteItemRecord.note_kind: NoteKind`（去掉默认值，强制必传）
- 创建点简化：`str(row.note_kind or "")` → `row.note_kind`（上游已是 Literal）
- `_repo_note_item_record` 增加 DB 反序列化兜底（保留向后兼容旧数据，缺失时按 note_item_id 前缀推断）
- 11 处测试创建点补齐 `note_kind=` 参数
- 测试结果：1127 passed（净 +1），0 新增失败

### 10. `note_mode` 别名映射散落 (P2) ✅

**修复**：
- 新建 `shared/note_modes.py`：`MODE_TO_DB_ALIAS` / `DB_ALIAS_TO_MODE` 双向 dict + `to_db_alias`/`from_db_alias`/`increment_chapter_mode_summary` helpers
- `app/persist_helpers.py:189` 的 inline `mode_alias` → 调用 `to_db_alias`
- `app/status.py` 两处手写 5-bucket 映射（`_chapter_mode_summary`、`_chapter_mode_summary_from_snapshot`）→ 调用 helper
- `app/db_reconstruct.py` 两处启发式 `"footnote" in mode.lower()` → 改用 `from_db_alias` 还原 canonical 后精确判断；修正 `ChapterNoteMode.note_mode` 字段契约（原先直接塞 DB alias 字面量，违反 Literal 类型）
- 测试结果：1127 passed，0 新增失败

### 11. `dev/phase_runner.py` 反向依赖 (P2) ✅

**调查发现**：
- dev/ **不被** FNM_RE 任何内部层（shared/stages/modules/app）import —— 已审计，零反向依赖
- dev/ 的真实角色是 **app 层的调试客户端**，与 `web/dev_routes.py` 同级
- 它依赖 app 是客户端语义（不是层内反向），不破坏单向依赖

**修复**：
- 在 `dev/__init__.py` 明确分层定位文档：dev/ 不属于核心分层，是 app 的外部客户端
- 标明允许的依赖方向（dev → shared/stages/modules/app）和禁止的依赖方向（任何核心层 ↛ dev）
- 留下迁移指引：未来若需严格分层，把 dev/ 移到根级 `dev/` 即可，仅影响 web/dev_routes.py 与测试 import 路径

不做代码移动：移包路径影响 web、测试、CLI 多处 import，收益不抵成本；文档化设计意图已足够约束

### 12. `stages/diagnostics.py` fallback 启发式 (P3) ✅

**修复**：
- 删除从 unit_kind 和 note_id 前缀启发式推断的 fallback
- 改为：region.note_kind 优先 → item.note_kind 次之（NoteItemRecord 升级为 Literal 后保证有值）
- 借力 Issue 9 的类型升级，启发式不再需要
