# Claude 协作约束

这份文件只保留给 Claude 或同类代理看的最短约束，避免和 [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md) 重复太多。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
6. 写完后列出边缘情况，并先自行验证再交付。
7. 不写逐书修补的代码：用 pipeline 已有数据驱动（如 note_items 的实际范围），做正向验证而非黑名单排除，缺口用已知序列推断而非 OCR 猜测。修完一本要用另一本回归。
8. 模块化修补，先上游再下游。每个 phase 只做一种决策：Phase1=页面角色+章节边界，Phase2=note_kind 分类（全书唯一来源）+note_mode 聚合，Phase3=body anchor 检测+link 匹配（不能重分类 note_kind，不能用 chapter_mode 跳过修复），Phase4=引用注入+翻译单元，Phase5=章 markdown 合并，Phase6=导出审计。书型问题必须在 Phase2 内解决，不能推给下游。详见 [AGENTS.md § FNM Pipeline 数据流与 phase 职责边界](/Users/hao/OCRandTranslation/AGENTS.md)。
9. 修 bug 必须追溯到具体页面：查 PDF 原页（`scripts/inspect_page.py`）、raw_pages.json（markdown/blocks/fnBlocks）、fnm_real_test_modules.json（各 module 中间输出）、SQLite DB（note_items/anchors/links）。不能凭 blocker 名字猜测根因。
10. 区分强信号和弱信号：强信号（显式 `## NOTES` 标题、LaTeX/HTML/Unicode 上标标记）优先信任；弱信号（bare_digit、无标题的 `endnote_collection`）需要额外守卫（TOC 交叉验证、右侧上下文检查）。修复时优先加新识别模式（如 OCR 乱码 `'N`→`apostrophe_sup`），再考虑收紧弱信号守卫。
11. 假阳性有两种：(a) 数据统计 bug——如 `captured_pages` 只收 footnote 没收 endnote，导致 `dense_anchor_zero_capture` 全假阳性；(b) 模式匹配过于宽松——如 bare_digit 把日期/列表/文档编号误判为 note marker。先排除 (a) 再处理 (b)。
12. **树枝状条件处理（最高优先级）**：分类源头唯一（每个 entity 的类型只在一处决定，下游透传不可覆盖）、分支条件穷尽互斥（禁止 else 吞掉边界情况）、禁止广播（章的聚合属性不能赋值给个体 entity）、上下游隔离（下游只消费上游事实，不可重新解释）、集中 dispatch 分散处理（按类型分流后独立处理）。详见 AGENTS.md。
13. 测试分两层——增量（单书，冻结已确认成果、层层推进）和实批（多书完整回归+导出）。判断 blocker 前先确认数据来源时间戳：Module snapshot 是 Phase 3 gate 权威来源，Persisted DB 是 Phase 4-6 持久化后的数据，两者可能分叉。

更完整的工作规则见 [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md)。
