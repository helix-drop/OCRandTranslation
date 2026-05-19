# FNM Pipeline 性能优化任务

## 已完成

| # | 优化 | 文件 | 效果 |
|---|------|------|------|
| 1 | executemany 批量 INSERT | `persistence/sqlite_repo_fnm.py` | 7 函数 × 数千次 → 7 次批量 |
| 2 | batch_save_fnm_review_overrides | `persistence/sqlite_repo_fnm.py` | llm_repair 批量写 DB |
| 3 | OpenAI client 单例（sup_recovery） | `FNM_RE/modules/sup_recovery.py` | 49K 连接 → 1 |
| 4 | 流式 markdown 加载 | `FNM_RE/modules/sup_recovery.py` | 90MB → 8MB |
| 5 | 内存守卫 + 章间 GC + L3 缓存清理 | `FNM_RE/modules/sup_recovery.py` | 90% 阈值主动退出 |
| 6 | 章节持久化回调 | `FNM_RE/modules/sup_recovery.py` + `pipeline.py` | 写临时文件 + 释放 |
| 7 | OpenAI client 单例（llm_repair） | `FNM_RE/llm_repair.py` | 连接泄漏修复 |
| 8 | fitz doc 单例 | `FNM_RE/llm_repair.py` | 复用 PDF 文档对象 |
| 9 | page_role + page_map 预缓存 | `FNM_RE/llm_repair.py` | 跨 cluster 复用 |
| 10 | cluster 间 GC + 批量 DB 写入 | `FNM_RE/llm_repair.py` | 单事务提交 |
| 11 | del file_bytes | `heading_candidates.py` + `notes.py` | PDF 二进制即时释放 |
| 12 | raw_page_by_no.clear() | `chapter_split.py` | 释放 pages 副本 |
| 13 | pages.markdown 清除 | `pipeline.py` | ChapterLayers 构建后释放 |
| 14 | 8 处 dict() 复制消除 | `heading_candidates.py` + `toc_semantics.py` | 直接引用替代全量复制 |
| 15 | 分章持久化（body_pages → DB） | `chapter_split.py` + `sqlite_repo_fnm.py` | Phase 3+ RSS -32% |
| 16 | Phase 1 后 persist + 重载 pages | `pipeline.py` | Phase 2+ RSS -140 MB |
| 17 | load_pages_light（轻量加载） | `sqlite_repo_documents.py` | 跳过 payload_json 解析 |
| 18 | 子进程 pipeline 隔离 | `FNM_RE/subprocess_pipeline.py` | 主进程 RSS 94 MB |
| 19 | fnm_chapter_body_pages 表 | `sqlite_schema.py` | 分章缓存 |

## 待完成：DB 表驱动重构

### 目标
让每个 Pipeline Phase 独立从 DB 读取输入、写入输出，实现真正的逐 Phase 子进程隔离。

### Step 1: Phase 1 → DB 的完整持久化

当前 `replace_fnm_phase1_products` 已存在但需验证覆盖全部字段。Phase 1 产物：
- fnm_pages（page_role, has_note_heading 等）
- fnm_chapters（chapter_id, title, start/end_page, pages_json）
- fnm_section_heads
- fnm_heading_candidates

### Step 2: DB → TocStructure 重建

`FNM_RE/db_reconstruct.py` 已创建骨架，需完善：
- `reconstruct_toc_structure(repo, doc_id)` → TocStructure
- `reconstruct_book_note_profile(repo, doc_id)` → BookNoteProfile

### Step 3: DB → ChapterLayers 重建

需要新函数 `reconstruct_chapter_layers(repo, doc_id)` → ChapterLayers：
- 从 fnm_chapter_body_pages 读取每章的 body_pages/body_segments
- 从 fnm_note_regions 读取 note regions
- 从 fnm_note_items 读取 note items
- 重建完整的 ChapterLayers 对象

### Step 4: Phase 3-6 改为纯 DB 驱动

修改各 Phase 函数接受 DB 对象而非内存对象：
- Phase 3 (note_linking): DB(chapters, note_items, body_pages) → fnm_note_links
- Phase 4 (ref_freeze): DB(links, anchor, chapters) → fnm_translation_units
- Phase 5 (merge): DB(units) → chapter markdown files
- Phase 6 (export): DB(markdown) → export bundle

### Step 5: 逐 Phase 子进程

每个 Phase 对应一个 `phase_N.py`，调用 `FNM_RE/subprocess_phases.py` 串联。

## 未完成的优化（优先级排序）

### 高优先

| # | 问题 | 文件 | 方案 |
|---|------|------|------|
| A | Phase 1 峰值 651 MB | `pipeline.py` | DB 表驱动后 pages 仅加载一次 |
| B | llm_book_type_verify 加载全量 pages | `llm_book_type_verify.py` | 仅传章节摘要而非全量 pages |
| C | Phase 3 note_linking 全量扫描 | `note_linking.py` | 分章索引（已确认 n² 不瓶颈，但内存可优化） |

### 中优先

| # | 问题 | 文件 | 方案 |
|---|------|------|------|
| D | raw_pages.json 在 reingest 和 sup_recovery 重复加载 | `reingest_fnm.py`, `sup_recovery.py` | 合并为一次加载 |
| E | 视觉 API 调用未批量 | `sup_recovery.py`, `visual_anchor_recovery.py`, `llm_bare_digit_verify.py` | 同页多 marker 打包为一次 API 调用 |
| F | PagePartition 和 ChapterLayer 文本重复存储 | `page_partition.py`, `chapter_split.py` | 统一 text 来源 |

### 低优先

| # | 问题 | 方案 |
|---|------|------|
| G | llm_repair 每 cluster 重建 page_map | 已部分修复，进一步预计算 |
| H | 导出 zip 在内存中构建 | 流式写入磁盘 |
| I | 对比脚本重复的正则通道 | 合并为一次扫描 |

## 关键文件索引

| 文件 | 作用 |
|------|------|
| `FNM_RE/app/pipeline.py` | 主 pipeline 编排 |
| `FNM_RE/app/mainline.py` | pipeline 入口 |
| `FNM_RE/modules/chapter_split.py` | Phase 2 章节构建 |
| `FNM_RE/modules/note_linking.py` | Phase 3 注释链接 |
| `FNM_RE/modules/ref_freeze.py` | Phase 4 翻译单元 |
| `FNM_RE/modules/chapter_merge.py` | Phase 5 markdown 合并 |
| `FNM_RE/modules/book_assemble.py` | Phase 6 导出 |
| `FNM_RE/modules/sup_recovery.py` | 上标恢复 |
| `FNM_RE/llm_repair.py` | LLM 修补 |
| `FNM_RE/modules/types.py` | 所有数据类定义 |
| `persistence/sqlite_repo_fnm.py` | FNM 数据库方法 |
| `persistence/sqlite_schema.py` | 数据库表定义 |
| `FNM_RE/db_reconstruct.py` | DB→对象重建（新） |
| `FNM_RE/subprocess_pipeline.py` | 子进程入口 |
| `FNM_RE/subprocess_phases.py` | 逐 Phase 调度器（骨架） |
| `FNM_RE/phase12.py` | Phase 1-2 子进程 |
| `FNM_RE/phase36.py` | Phase 3-6 子进程 |

## 运行方式

```bash
# 普通模式
.venv/bin/python scripts/test_fnm_real_batch.py --slug Heidegger_en_France

# 子进程模式（主进程 ~94 MB）
FNM_USE_SUBPROCESS=1 .venv/bin/python scripts/test_fnm_real_batch.py --slug Heidegger_en_France

# 增量测试（无 LLM repair 和 reingest）
.venv/bin/python scripts/test_fnm_incremental.py --slug Heidegger_en_France --verbose

# 本地内存监控
python3 -c "
import subprocess, re
proc = subprocess.Popen(['.venv/bin/python', 'scripts/test_fnm_incremental.py', '--slug', 'Heidegger_en_France', '--verbose'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
for line in proc.stdout:
    m = re.match(r'\s*\[\s*[\d.]+\%\]\s+(\S+)', line)
    if m and 'done' in line:
        rss = int(subprocess.check_output(['ps','-o','rss=','-p',str(proc.pid)]).strip()) / 1024
        print(f'{m.group(1):30s} {rss:.0f} MB')
"
```
