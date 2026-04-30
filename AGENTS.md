# 仓库工作规则

这份文档只写当前仓库里最需要遵守的规则，尽量短，不和 [DEV.md](/Users/hao/OCRandTranslation/DEV.md) 混写。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
7. 写完后列出边缘情况，并先自行验证再交付。
8. 对用户汇报时，只说做了什么、结果怎样、能不能用，不堆术语。
9. 没确认完成前，不要提前收工。
10. 不要机械追求最小改动；当实现功能必须做较大改动或重构时，要明确提出并敢于推进相关决策。

## 文档分工

| 文档 | 作用 |
|---|---|
| [DEV.md](/Users/hao/OCRandTranslation/DEV.md) | 稳定说明、结构、运行方式、数据位置 |
| [PROGRESS.md](/Users/hao/OCRandTranslation/PROGRESS.md) | 当前进度、最近实测、下一步工作 |
| [CLAUDE.md](/Users/hao/OCRandTranslation/CLAUDE.md) | 给 Claude/同类代理看的简版约束 |
| [verification.md](/Users/hao/OCRandTranslation/verification.md) | 验证记录 |

## 维护原则

1. 新事实优先写进对应文档，不要所有内容都堆在一个文件里。
2. 路径、端口、目录名以代码为准，改代码后同步改文档。
3. 临时结论放 `PROGRESS.md`，稳定结论放 `DEV.md`。

## 设计原则：不写逐书修补的代码

修 bug 时不能"来一本书补一本书"——不能靠枚举特例、硬编码阈值、扩充黑名单来适配当前测试书。这类修补会让代码越来越脆，下一本新书必然再次崩在同一位置。

正确做法：

1. **用 pipeline 中已有的数据驱动判断，不引入外部假设。** 例如要知道某章的 endnote marker 范围，应该读 `fnm_note_items` 的实际数据，而不是猜一个 `max_marker=200` 的常量。
2. **正向验证优于黑名单排除。** "我只信在已确认范围内的 marker"比"我不信这些词后面的数字"更稳定——前者由每本书自己的数据结构保证，后者靠穷举一种语言/排版惯例。
3. **缺口填补用已知序列推断，不做文本猜测。** OCR 丢失了一个 superscript，应该用前后已检测 marker 的位置和 note_items 的预期序列来定位，而不是在 OCR 文本里搜"可能是 47 的东西"。
4. **改完后用另一本书回归。** Goldstein 修完跑 Biopolitics，Biopolitics 修完跑 Goldstein。两本书结构差异越大，回归越有价值。
5. **模块化修补，先上游再下游。** pipeline 阶段之间有明确的数据依赖（body_anchor → note_link → export），修 bug 时必须从最上游的断层开始，验证该层输出正确后再进入下一层。跳层修补会造成下游基于错误输入做正确决策的假象。
