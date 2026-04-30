# Claude 协作约束

这份文件只保留给 Claude 或同类代理看的最短约束，避免和 [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md) 重复太多。

1. 全部用中文回复。
2. 写代码或改文档前，先说明方案。
3. 需求不清楚时，先澄清再动手。
4. 不写兼容性代码，除非用户主动要求。
5. 出 bug 先写能重现的测试，再修复。
6. 写完后列出边缘情况，并先自行验证再交付。
7. 不写逐书修补的代码：用 pipeline 已有数据驱动（如 note_items 的实际范围），做正向验证而非黑名单排除，缺口用已知序列推断而非 OCR 猜测。修完一本要用另一本回归。
8. 模块化修补，先上游再下游：pipeline 阶段间有明确数据依赖，必须从最上游断层开始修，验证该层输出正确后再进入下一层。

更完整的工作规则见 [AGENTS.md](/Users/hao/OCRandTranslation/AGENTS.md)。
