# 仓库工作规则

这份文档只写当前仓库里最需要遵守的规则，尽量短，不和 [DEV.md](/Users/hao/OCRandTranslation/DEV.md) 混写。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
6. 修改超过 3 个文件时，先拆成小任务。
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
