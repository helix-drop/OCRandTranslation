# 仓库工作规则

这份文档只约束当前 `OCRandTranslation` 仓库。已剥离的脚注/尾注结构化项目在 `/Users/hao/FEnoteTransToMD`，不要在本仓库重新加入相关模式、接口、测试资产或文档。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
6. 写完后列出边缘情况，并先自行验证再交付。
7. 对用户汇报时，只说做了什么、结果怎样、能不能用，不堆术语。
8. 没确认完成前，不要提前收工。
9. 不要机械追求最小改动；实现功能必须做较大改动或重构时，要明确提出并推进相关决策。

## 当前仓库边界

`OCRandTranslation` 只保留标准 OCR、阅读、翻译、术语词典、目录导航、视觉目录识别和 Markdown 导出。

禁止事项：

- 不新增或恢复已剥离模式的 Web/API/导出入口。
- 不新增或恢复已剥离模式的 SQLite 表、任务类型、前端视图、测试书或批测脚本。
- 不把 `/Users/hao/FEnoteTransToMD` 的测试资产复制回本仓库。

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
4. 视觉目录和翻译能力是当前主链的一部分；结构化脚注/尾注整书管线不属于当前主链。
