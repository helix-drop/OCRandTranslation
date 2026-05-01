# Claude 协作约束

这份文件只保留给 Claude 或同类代理看的最短约束，避免和 [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md) 重复太多。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
6. 写完后列出边缘情况，并先自行验证再交付。
7. 不写逐书修补的代码：用 pipeline 已有数据驱动（如 note_items 的实际范围），做正向验证而非黑名单排除，缺口用已知序列推断而非 OCR 猜测。修完一本要用另一本回归。
8. 模块化修补，先上游再下游：pipeline 共 6 个 phase（TOC 结构 → 章节拆分/注释捕获 → 锚点检测/链接 → LLM 修补 → 引用冻结 → 章节合并 → 导出审计），必须从最上游断层开始修，验证该层输出正确后再进入下一层。各 phase 的核心函数、blocker reason 归属、上下游依赖关系见 [AGENTS.md § FNM Pipeline 数据流与 blocker 归因](/Users/hao/OCRandTranslation/AGENTS.md)。
9. 修 bug 必须追溯到具体页面：查 PDF 原页（`scripts/inspect_page.py`）、raw_pages.json（markdown/blocks/fnBlocks）、fnm_real_test_modules.json（各 module 中间输出）、SQLite DB（note_items/anchors/links）。不能凭 blocker 名字猜测根因。
10. 区分强信号和弱信号：强信号（显式 `## NOTES` 标题、LaTeX/HTML/Unicode 上标标记）优先信任；弱信号（bare_digit、无标题的 `endnote_collection`）需要额外守卫（TOC 交叉验证、右侧上下文检查）。修复时优先加新识别模式（如 OCR 乱码 `'N`→`apostrophe_sup`），再考虑收紧弱信号守卫。
11. 假阳性有两种：(a) 数据统计 bug——如 `captured_pages` 只收 footnote 没收 endnote，导致 `dense_anchor_zero_capture` 全假阳性；(b) 模式匹配过于宽松——如 bare_digit 把日期/列表/文档编号误判为 note marker。先排除 (a) 再处理 (b)。

更完整的工作规则见 [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md)。
