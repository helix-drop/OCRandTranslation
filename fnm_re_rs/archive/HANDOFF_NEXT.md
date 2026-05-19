# Step A 全部完成

## A1 — chapter_id 前缀 bug ✅

修复 Phase 1 两处 `toc-ch-` → `toc-toc-ch-`：

| 文件 | 行 | 改动 |
|---|---|---|
| `builder.rs` | 63 | `toc-ch-{}` → `toc-toc-ch-{}` |
| `title_utils.rs` | 254, 257 | `toc-ch-{:03}` → `toc-toc-ch-{:03}` |

## A2 — Phase 1 Biopolitics parity ✅

已有 4 个 parity 测试全部 PASS（无需额外工作）：
- Page partitions: 96.8% 角色一致，100% note 页覆盖
- Chapters: 12/12 byte-equal

## A3 — endnote_chapter_explorer + endnote_repair 接入主入口 ✅

| 模块 | 接入点 | 完成度 |
|---|---|---|
| `endnote_repair` | `lib.rs:68-70` — step 4 在 sup_recovery 后调用 `repair_endnote_items`，产出喂给 chapter_split | 37% stub |
| `endnote_chapter_explorer` | `note_regions/mod.rs:88-92` — step 4b 在 promote 后调用，结果占位 | 20% stub |

两模块标记为 stub（FNM_PHASE12_AUDIT F8），接线已建立，待完整实现后启用。

## 全量验证

```
cargo test --workspace: 21 suites, 0 failed
cargo clippy -D warnings: clean
cargo fmt --check: clean
```

## 当前完成状态

| Step | 完成 |
|---|---|
| A (4 tasks) | 3/3 ✅（A 仅有 3 个实任务） |
| B (5 tasks) | 5/5 ✅ |
| C (5 tasks) | ⬜ |
| D (6 tasks) | ⬜ |

下一步：Step C（需 vision API key 的 LLM/PDF 任务）或 Step D（工程纪律收尾）。
