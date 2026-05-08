# FNM Pipeline 信号判断薄弱点分析（修正版）

## 核心论点

FNM Pipeline 在 6 个 phase 中有 **9 个信号判断点**：代码根据统计特征（数字密度、markdown 结构、正则匹配次数）做非确定性分类。信号强时正确，信号弱时出错。当前仅 Phase 1 的 visual TOC（S2）和 Phase 3.5 的 llm_repair 使用了 LLM，其余 7 个点靠规则硬扛。

**LLM 恰好擅长这类任务**，但并非所有信号点都适合引入 LLM。下面按 phase 逐一分析。

---

## Pipeline Phase 与信号判断点映射

```
Phase 1              Phase 2              Phase 3                  Phase 3.5      Phase 4-6

S1: page_role        S3: note_kind        S5: anchor_kind         LLM repair     S9: contract 阻塞
    body/note/noise?     footnote/endnote?    endnote/footnote/     (已有)           硬阻塞/零容忍
    规则级联              region 继承          unknown?
                                                                S10: cross_page
S2: chapter_boundary  S4: book_type        S7: bare_digit            跨页同段?
    ✅ LLM已覆盖          endnote_only/         真尾注/碰巧数字?         consumed_by_prev
                       footnote_only/mixed?  4条件白名单
                    S6: chapter_mode       S8: link gap-fill
                        per-chapter mode      假 anchor 验证
                        3层推断

                    SX: fnBlocks→endnote  ← 原报告遗漏
                        5-Gate 重分类
                        G0-G4
```

**LLM 已覆盖**: S2 (visual TOC), Phase 3.5 (llm_repair + visual_anchor_recovery)
**LLM 未覆盖**: S1, S3, S4, S5, S6, S7, S8, S9, S10, SX

---

## Phase 1：页面角色与章节骨架

**Phase 职责**: 每页 page_role + 章节边界。不关心注释内容，不判断 footnote/endnote 类型。

### S1: page_role 判别

| 项目 | 详情 |
|------|------|
| 文件 | `toc_structure.py:161-236`, `chapter_skeleton/builder.py:55-66` |
| 当前算法 | 4 级优先级级联：`source_role=="note"` → note; 在 chapter 映射内 → chapter/post_body; 在 back_matter 之后 → back_matter; 其余 → front_matter |
| 信号强度 | **弱**。noise 页（空白/图片页）和 note 页在 OCR 输出中特征模糊 |
| 误判后果 | noise→body: 垃圾文本进入翻译单元; note→noise: 尾注定义丢失 |
| **LLM 适用性** | **低。不建议批量使用。** 每页 1 次 vision call 成本过高（300 页书 ≈ 135K tokens），且空白页+水印的边缘情况 vision model 同样可能误判。规则级联在 95%+ 的页面上已经正确 |
| **建议** | 保持规则，按需在极端情况（整页丢失）手动介入 |

### S2: chapter_boundary 判别

| 项目 | 详情 |
|------|------|
| 文件 | `chapter_skeleton/builder.py` |
| 当前算法 | visual TOC (LLM 已用) + heading_candidates 启发式 |
| **LLM 适用性** | ✅ 已覆盖，不需追加 |

---

## Phase 2：注释捕获与分类 ← LLM 最该介入的 Phase

**Phase 职责**: 每个 note item 的 `note_kind`（全书唯一来源）+ 每章 `note_mode`（聚合属性）+ `book_type`（全书信号）。**书型问题必须在 Phase 2 内解决，不能推给下游。**

### S4: book_type 判别 ← 最该做

| 项目 | 详情 |
|------|------|
| 文件 | `book_note_type.py:138-145` |
| 当前算法 | **不是**"各章投票"（原报告描述有误）。是页面级 boolean flags：`has_footnote = bool(footnote_pages)` + `has_endnote = bool(endnote_pages)` → 4-way switch（mixed / endnote_only / footnote_only / no_notes）。`chapter_mode_counts` 只用于一致性门检，不参与 book_type 决策 |
| 信号强度 | **中弱**。页面级 boolean 比投票稳健，但依赖 footnote/endnote page 检测的准确性。真正的弱点是 `footnote_only` 分支的 `toc_has_endnotes_entry` 守卫（`book_note_type.py:231-238`）——如果 TOC 暗示有尾注但页面检测未发现，当前规则可能误判 |
| 误判后果 | 尾注书→mixed: bare_digit gate 不生效; mixed→endnote_only: sparse_note_capture 假阳性 |
| **LLM 适用性** | **高。** 抽样 3-5 页正文 + 章末尾注页，一次 LLM 调用判断 "这书用什么注释体系？" LLM 不需要看所有页面，看几页代表性页面就能判断。**和 S6 合并为同一请求**，一次调用同时输出 `book_type` + 逐章 `chapter_mode` |
| 成本 | 3-5 页图片 + prompt ≈ 3,000-6,000 tokens/书 |
| 树状约束 | ✅ 无违规。book_type 是 Phase 2 的聚合判断，LLM 在 Phase 2 内做此判断不违反任何原则 |

### S6: chapter_mode 判别

| 项目 | 详情 |
|------|------|
| 文件 | `book_note_type.py:263-312`（provisional）, `chapter_split.py:400-414`（region override）, `pipeline.py:227-298`（pipeline 确认） |
| 当前算法 | 3 层推断：provisional（endnote pages > footnote pages > book_endnote > no_notes）→ region-based override（`chapter_split.py` 有 footnote 安全守卫：fn item 多于 en item 且无 heading → 不覆盖）→ pipeline 最终确认 |
| 信号强度 | **中**。3 层推断已经比较稳健，但 `book_endnote_bound` vs `chapter_endnote_primary` 的区分仅靠 region.scope（也是推断的），存在歧义 |
| 误判后果 | chapter_endnote→book_endnote: 尾注编号跨章连续（Biopolitics 的 bug） |
| **LLM 适用性** | **中。合并到 S4 的 LLM 请求。** 同一个 LLM 调用同时输出 book_type + per-chapter mode。LLM 看了样本页后能判断每章的注释模式 |
| 成本 | 0（共享 S4 请求） |
| 注意 | `chapter_split.py:408-412` 的 footnote 安全守卫不应被 LLM 绕过——当 fn item 数量明显占优且无 heading 时，LLM 的 "chapter_endnote_primary" 判断应降级 |

### S3: note_kind 判别

| 项目 | 详情 |
|------|------|
| 文件 | `note_regions.py:50-88, 184-374`, `note_items.py:439-444` |
| 当前算法 | note item 的 kind 继承自所属 region 的 kind。region 构建：footnote_band → footnote; endnote candidate pages（page_role=="note" 或有 endnote items 或有 NOTES heading）→ endnote |
| 信号强度 | **中**。region 边界准确时正确，region 边界错误时才错 |
| 误判后果 | endnote→footnote: 尾注链断; 反之亦然 |
| **LLM 适用性** | **低。当前不建议。** 已知误判仅出现在 star-marker 和 borderline 章，频率极低。且这是树状约束最敏感的点——note_kind 是 Phase 2 的唯一分类源，下游不可覆盖。LLM 介入必须在 Phase 2 的 note_regions 构建阶段完成，集成复杂度高 |
| 树状约束 | ⚠️ 如果未来要引入 LLM，必须在 `note_regions.py` 的 region 构建时做，不能放到 Phase 3 |
| 建议 | 暂缓，除非出现新的系统性误判案例 |

### SX: fnBlocks→endnote 重分类（原报告遗漏）

| 项目 | 详情 |
|------|------|
| 文件 | `note_regions.py:582-682` `_reclassify_post_body_fnblocks_as_endnote` |
| 当前算法 | 5 道门检（G0-G4）：G0=全为 note 页, G1=≥3 个 numeric items, G2=连续序列, G3=跨页连续性, G4=有 heading 锚定 |
| 信号强度 | **中**。5 道门检已经比较严格 |
| 误判后果 | fnBlocks 来源的 endnote 被当 footnote → 尾注链断 |
| **LLM 适用性** | **低。** 5 道门检已足够严格。LLM 的边际收益小 |
| 建议 | 保持规则，观察误判率 |

---

## Phase 3：锚点检测与链接匹配

**Phase 职责**: body anchor 检测 + anchor 与 note_item 一对一匹配 + unmatched link 修复。**不能重分类 note_kind，不能用 chapter_mode 跳过修复。**

### S7: bare_digit 判别 ← 最脆弱的点

| 项目 | 详情 |
|------|------|
| 文件 | `body_anchors.py:258-359`, `anchors.py:222-246` |
| 当前算法 | 两阶段：扫描时廉价预过滤（`_is_bare_digit_marker_context`：左词≥3字符、非结构前缀、右侧非数字）→ 收集后 4 条件正向门检（①在 note_items 精确集合中 ②非冗余 ③≤2次 ④句末白名单 `. , ; : ! ? — – -`） |
| 信号强度 | **最弱**。纯语法，零语义。"nationale 7»" 和 "Beccaria 17." 在语法层面无法区分——都是 "词+空格+数字+句末标点" |
| 误判后果 | 假阳性：噪声数字当尾注; 假阴性：合法 bare_digit 被白名单拒绝 |
| **LLM 适用性** | **高。** 这是 LLM 最适合的场景：看一页图，判断 "这个位置的数字 7 是不是尾注标记？" 语义理解天然区分专有名词中的数字和引用标记 |
| 方案 | 视觉模型看候选 bare_digit 所在页面，给出 yes/no + 置信度。低置信度回退到规则白名单 |
| 成本 | 每个候选 1 次 vision call。Biopolitics ~8 个候选，但需先在 3 本书上统计候选量确认成本 |
| 注意 | 必须在 Phase 3 的 `_positive_gate_bare_digit` 阶段做，不能放到 Phase 3.5（那太晚了，bare_digit 必须在 anchor 扫描时就决定） |

### S5: anchor_kind 判别

| 项目 | 详情 |
|------|------|
| 文件 | `anchors.py:113-132` `resolve_anchor_kind` |
| 当前算法 | 4 分支优先级：pattern==bracket → footnote/unknown; normalized_marker 在 chapter_endnote_markers 中 → endnote; has_page_footnote_band → footnote; else → unknown |
| 信号强度 | **中**。bracket 修复后大幅改善，但 bare_digit / plain pattern 仍有歧义 |
| 误判后果 | unknown → 不参与 endnote 链接; 错误分类 → 多余/缺失链接 |
| **LLM 适用性** | **中低。text-only LLM 可辅助，vision 过重。** bare_digit 的歧义问题已被 S7 覆盖。这里只需对 `resolve_anchor_kind` 返回 "unknown" 的 anchor 做 text-only 二次判断——看 anchor 的文本上下文（前后 50 字符），不需要页面图片 |
| 方案 | 对 unknown anchor，提交文本上下文给 LLM："这段文字中的数字 X 是注释标记还是正文内容？" |
| 成本 | ~500 tokens/候选，text-only |
| 建议 | P2，和 S7 联动——S7 修好后 unknown 的 bare_digit 会大幅减少 |

### S8: link 配对 gap-fill 验证

| 项目 | 详情 |
|------|------|
| 文件 | `endnote_links.py:138-303`（初始匹配）, `endnote_repair.py:28-287`（修复） |
| 当前算法 | 多阶段：primary match → orphan repair → body-text recovery（5 种正则） → OCR repair → fallback 配对 → dedup → endnote-only 配对 |
| 信号强度 | **中**。primary match 靠数字精确匹配，正确率高。gap-fill 的 body-text recovery 盲信数字匹配（ch002 标题 "17" → en-00035） |
| 误判后果 | gap-fill 假 anchor 创建无效链接 |
| **LLM 适用性** | **中低。** gap-fill 验证需要页面图片（验证 "正文中是否真的有个上标数字在这里"），集成复杂度高，每候选一次 vision call。不如先收紧 gap-fill 的匹配合并逻辑（如要求匹配文本必须在段落末/行末） |
| 建议 | P3。规则收紧优先于 LLM 验证 |

---

## Phase 3.5：LLM 修补（已覆盖）

当前已有的 LLM 调用：

| 调用点 | 文件 | 类型 | 用途 |
|--------|------|------|------|
| `llm_repair` | `llm_repair.py:1475` | 文本+可选视觉 | 修复未解决的 orphan cluster |
| `visual_anchor_recovery` | `visual_anchor_recovery.py:711` | 视觉 | 定位 OCR 遗漏的上标 anchor |
| `sup_recovery L3` | `sup_recovery.py:534` | 视觉 | 定位 OCR 遗漏的上标标记 |

这些保留，不需要调整。

---

## Phase 4-6：引用注入到导出审计

**Phase 职责**: 引用注入 + 翻译单元 + 章合并 + 导出审计。不修改任何上游数据。

### S9: contract 阻塞判断

| 项目 | 详情 |
|------|------|
| 文件 | `note_linking.py:1528-1540`（9 道硬门检）, `export_contract.py:53-113`（语义 contract） |
| 当前算法 | Δ>0 → 阻塞导出。零容忍。有 outlier truncation（max marker 比 second-max 差 >50% 时截断） |
| 信号强度 | **弱**。不能区分 "Δ=1 来自 LLM 不可控" 和 "Δ=10 来自程序 BUG" |
| 误判后果 | Biopolitics: 5 个 LLM 不可控 orphan → 整书阻塞 |
| **LLM 适用性** | **不需要 LLM。** 改为统计阈值即可——这是成本最低、收益最快的修改 |
| 方案 | `def_anchor_mismatch ≤ 1` 且全部来自 `orphan_note`（非 `ambiguous`、非 `gap`）→ warning 不阻塞。Δ≥2 或来自 gap/ambiguous → 保持阻塞 |
| 成本 | 0 tokens，一行条件判断 |

### S10: cross_page 段落同段判断

| 项目 | 详情 |
|------|------|
| 文件 | `units.py:293` |
| 当前算法 | OCR 标记 `consumed_by_prev` → 跳过。含 NOTE_REF 的 consumed 段做内容去重后可能重入 |
| **LLM 适用性** | **不需要 LLM。** 文本相似度比较（>95%）就能判断，用 LLM 是杀鸡用牛刀 |
| 建议 | 规则 + 文本相似度 |

---

## 总结：LLM 适合发挥作用的位置

### 按 Phase 汇总

| Phase | 信号点 | LLM？ | 理由 |
|-------|--------|-------|------|
| **Phase 1** | S1 page_role | ❌ 不建议 | 成本过高（每页 vision），规则 95%+ 正确 |
| | S2 chapter_boundary | ✅ 已覆盖 | visual TOC |
| **Phase 2** | **S4 book_type** | ✅ **最该做** | 抽样几页即可，成本极低，影响全局 |
| | **S6 chapter_mode** | ✅ 合并到 S4 | 同一 LLM 请求，零额外成本 |
| | S3 note_kind | ❌ 暂缓 | 误判率低，集成复杂度高 |
| | SX fnBlocks 重分类 | ❌ 不需要 | 5-Gate 已足够严格 |
| **Phase 3** | **S7 bare_digit** | ✅ **最该做** | 语法无法解决的问题，LLM 天然擅长 |
| | S5 anchor_kind | ⚠️ 辅助 | text-only 对 unknown 二次判断 |
| | S8 link gap-fill | ❌ 暂缓 | 规则收紧优先于 LLM |
| **Phase 3.5** | llm_repair 等 | ✅ 已覆盖 | — |
| **Phase 4-6** | **S9 contract** | ✅ 不用 LLM | 改阈值即可，零成本 |
| | S10 cross_page | ❌ 不需要 | 文本相似度足够 |

### 修正后的优先级

| 优先级 | 做什么 | LLM？ | 成本 | 说明 |
|--------|--------|-------|------|------|
| **P0** | S9 contract 阈值 | 不用 | 0 | Δ≤1 且全 orphan_note → warning |
| **P0** | S4+S6 book_type + chapter_mode | 用 | ~5,000 | 一次 LLM 请求，抽样 3-5 页 |
| **P1** | S7 bare_digit | 用 | ~10,000 | 先在 3 本书统计候选量，确认成本 |
| **P2** | S5 anchor_kind unknown | 用 | ~3,000 | text-only，不调 vision |
| **P3** | S3 note_kind | 暂缓 | — | 等出现系统性误判案例 |
| **P3** | S8 link gap-fill | 暂缓 | — | 先收紧规则 |

### 成本估算（修正后）

| 场景 | Token |
|------|-------|
| P0 全部（S9 + S4/S6） | ~5,000 |
| P0 + P1（+ S7） | ~15,000 |
| P0 + P1 + P2（全部 LLM 介入） | ~18,000 |

相对于当前 llm_repair 的 ~190K tokens（286 次请求），新增 LLM 用量约为当前的 **8-10%**，而非原报告估计的 6%。

### 与原报告的关键差异

1. **S4 算法修正**：book_type 是页面级 boolean flags，不是章模式投票。LLM 方案仍然有效但切入点需调整——聚焦 `toc_has_endnotes_entry` 守卫这个真正弱点
2. **补充 SX**：fnBlocks→endnote 5-Gate 重分类被原报告遗漏，当前规则已足够
3. **成本修正**：P0+P1 ≈ 15K tokens（原报告 12K），约占 llm_repair 的 8-10%（原报告 6%）
4. **S5 降级**：从 P1→P2，text-only 即可不需要 vision
5. **Phase 组织**：按 phase 而非 S1-S10 编号，更清晰地反映 LLM 在每个 phase 的角色
