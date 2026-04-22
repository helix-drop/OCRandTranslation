# FNM_RE

这个目录用于承载 FNM 的新实现。

原则只有三条：

1. 新代码写在 `FNM_RE/`，不继续把核心逻辑塞回旧 `fnm/`。
2. 旧 `fnm/` 在新实现完成前保持现状，只作为行为参考和回归对照。
3. 不做长期双实现并存，不做兼容层堆叠；等 `FNM_RE/` 主链验证通过后，再做一次明确切换。

当前状态：

- 旧实现梳理文档在 [FNM/REWRITE.md](/Users/hao/OCRandTranslation/FNM/REWRITE.md)
- 新实现详细计划在 [FNM_RE/PLAN.md](/Users/hao/OCRandTranslation/FNM_RE/PLAN.md)
- 第一阶段已落地独立入口：
  `FNM_RE.app.pipeline.build_phase1_structure(...)`
- 第二阶段已落地独立入口：
  `FNM_RE.app.pipeline.build_phase2_structure(...)`
- 第三阶段已落地独立入口：
  `FNM_RE.app.pipeline.build_phase3_structure(...)`
- 第四阶段已落地独立入口：
  `FNM_RE.app.pipeline.build_phase4_structure(...)`
- 第五阶段已落地独立入口：
  `FNM_RE.app.pipeline.build_phase5_structure(...)`
- 第六阶段已落地独立入口：
  `FNM_RE.app.pipeline.build_phase6_structure(...)`
- 第七阶段已落地接线入口：
  `FNM_RE.app.mainline.run_phase6_pipeline_for_doc(...)`
- 第一阶段代码骨架已包含：
  `models.py`、`constants.py`、`shared/`、`stages/`、`app/`
- 第二阶段已补齐：
  `shared/notes.py`、`stages/note_regions.py`、`stages/note_items.py`
- 第三阶段已补齐：
  `shared/anchors.py`、`stages/body_anchors.py`、`stages/note_links.py`
- 第四阶段已补齐：
  `stages/reviews.py`、`status.py`
- 第五阶段已补齐：
  `shared/refs.py`、`shared/segments.py`、`stages/units.py`、`stages/diagnostics.py`
- 第六阶段已补齐：
  `stages/export.py`、`stages/export_audit.py`
- 第七阶段已补齐：
  `app/mainline.py`

这个目录后续应该优先放入：

- 新领域模型
- 新结构构建链
- 新翻译单元规划器
- 新诊断投影层
- 新导出层

不应该继续放入：

- 旧实现的搬运副本
- 为旧模块打补丁的临时 helper
- 只为维持双轨运行而存在的适配层
