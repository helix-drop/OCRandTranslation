"""FNM 开发模式 Gate 判据（Phase 1 / Phase 2）。

每个 Gate 接收对应 `PhaseNStructure`，返回 `GateReport`。

- failures：阻塞项（`pass_=False`）。
- warnings：软告警，不影响 `pass_`。

每个 `code` 都在 `FIX_HINTS` 中配一个中文修复建议。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ---------- 结果对象 ----------


@dataclass
class GateFailure:
    code: str
    message: str
    hint: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateReport:
    phase: int
    pass_: bool
    failures: list[GateFailure] = field(default_factory=list)
    warnings: list[GateFailure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "pass": self.pass_,
            "failures": [f.to_dict() for f in self.failures],
            "warnings": [w.to_dict() for w in self.warnings],
        }


# ---------- 修复建议文案 ----------

FIX_HINTS: dict[str, str] = {
    # Phase 1
    "phase1.no_pages": (
        "Phase 1 产物中 page_partitions 为空。通常意味着 raw_pages.json 未被正确加载，"
        "或上游 OCR 结果异常。检查 /api/dev/fnm/import 的 raw_pages 路径与页数。"
    ),
    "phase1.no_chapters": (
        "未识别到任何章节。可能原因：TOC 为空、visual_toc 未对齐、标题层级解析失败。"
        "修复入口：检查 auto_visual_toc.json 是否存在；或手动提供 toc_items。"
    ),
    "phase1.chapter_missing_pages": (
        "存在章节没有绑定任何页面。通常是 chapter_skeleton 切分时页范围越界。"
        "修复入口：打开诊断抽屉查看该章节的 page_start/page_end 与 partitions 的对照。"
    ),
    "phase1.toc_alignment_review_required": (
        "TOC 对齐未通过（chapter_title_alignment_ok 或 chapter_section_alignment_ok 为 False）。"
        "表示 visual_toc 中的章节标题/层级与正文解析结果不一致。"
        "修复入口：回到 Phase 1 诊断，比对 TOC 与首页标题，必要时调整 TOC 的 offset。"
    ),
    "phase1.chapter_without_section_heads": (
        "（warning）该章节未识别到任何 section_head。不阻塞 Phase 2，但后续翻译切段可能过粗。"
    ),
    # Phase 2
    "phase2.note_region_missing_kind": (
        "存在 note_region 的 note_kind 为空。通常是 region_scope 识别失败。"
        "修复入口：手动 override note_kind（footnote/endnote）。"
    ),
    "phase2.region_marker_misaligned": (
        "note_region 的起始 marker 与首条 note_item 对不齐（region_marker_alignment_ok=False）。"
        "表示该区域的第一条注释从编号层面未对上。"
        "修复入口：检查该 region 的 start_page / pages，必要时缩小范围或调整 heading 启发式。"
    ),
    "phase2.chapter_note_mode_review_required": (
        "某章节的 note_mode 仍为 review_required，说明该章注释归属尚未确定（footnote / chapter_endnotes / book_endnotes）。"
        "修复入口：在诊断抽屉里检查 chapter_note_modes 的 primary_region_scope 证据。"
    ),
    "phase2.chapter_no_notes": (
        "（warning）该章节没有任何 note_regions。若原书该章确实无注释，可忽略；"
        "否则检查 Phase 1 的 note heading 识别是否漏判。"
    ),
    # Phase 3
    "phase3.footnote_orphan_anchor": (
        "正文中出现了编号但找不到对应脚注条目（orphan_anchor）。常见原因："
        "注释页未被纳入 note_region（检查 Phase 2 的 region_marker_alignment_ok）、"
        "或编号格式不在识别白名单。修复入口：Phase 2 诊断抽屉 / 编辑 note_regions override。"
    ),
    "phase3.footnote_orphan_note": (
        "脚注条目没有对应的正文编号（orphan_note）。可能是正文 OCR 漏字，或编号被拆到相邻段。"
        "修复入口：打开诊断抽屉定位该 note_item 的 owner_chapter，核对原文。"
    ),
    "phase3.endnote_orphan_anchor": (
        "正文编号在 endnote 区找不到匹配条目。通常是尾注收集页边界没对齐。"
        "修复入口：检查 Phase 2 的 chapter_endnote_region_alignment_ok 与相关 region 的 pages。"
    ),
    "phase3.endnote_orphan_note": (
        "尾注条目没有对应的正文编号。检查该 endnote region 是否被错划到相邻章节。"
    ),
    "phase3.ambiguous_note_link": (
        "某条 note_link 状态为 ambiguous：同一个正文编号匹配到了多条注释候选。"
        "修复入口：在诊断抽屉里给该 link 做 override，选定正确的 note_id。"
    ),
    "phase3.freeze_unmatched_frozen": (
        "ref_freeze 冻结阶段发现有未 matched 的 link 被写入了 frozen_text（only_matched_frozen=False）。"
        "这违反了注入契约，必须修复才能进入 Phase 4。检查 freeze_summary 的计数。"
    ),
    "phase3.freeze_duplicate_injection": (
        "同一锚点被注入了多次占位符（no_duplicate_injection=False）。"
        "通常是 body_anchors 去重失败。修复入口：回滚 Phase 3 的 frozen_text 后重跑。"
    ),
    "phase3.synthetic_anchor_warn": (
        "（warning）存在 synthetic_anchor：系统根据启发式补了一个原文没有显式编号的锚点。"
        "偶发可以接受；密集出现说明编号识别规则需要加强。"
    ),
    # Phase 4
    "phase4.structure_state_not_ready": (
        "Phase 4 status.structure_state != 'ready'。表示综合审核没有放行。"
        "修复入口：查看 status.blocking_reasons 中列出的具体条目。"
    ),
    "phase4.blocking_reasons_present": (
        "Phase 4 status.blocking_reasons 非空。每项代表一个阻塞原因（alignment / override / review）。"
        "修复入口：逐条定位到对应 Phase 1~3 的诊断。"
    ),
    "phase4.review_required_structure": (
        "存在 structure_reviews.state=='review_required'。需要人工 override 或修正 Phase 2/3 输出。"
    ),
    # Phase 5
    "phase5.no_translation_units": (
        "Phase 5 产物 translation_units 为空。通常意味着上游章节切分失败或无内容。"
        "检查 Phase 4 的 chapter_source_summary。"
    ),
    "phase5.unit_missing_source_text": (
        "有 translation_unit 的 source_text 为空。检查对应 chapter 的 frozen_text 是否产出。"
    ),
    "phase5.real_mode_unit_incomplete": (
        "real 模式下存在 translation_unit.status != 'done'。开发模式不接入真 FNM Worker；"
        "要验收 real 模式请回生产路径跑。"
    ),
    "phase5.test_mode_mark_pending": (
        "test 模式下仍有 translation_unit 未被标记为 pseudo_done。"
        "通常是 dev 执行器的标记步骤被跳过，重跑 Phase 5 即可。"
    ),
    # Phase 6
    "phase6.cannot_ship": (
        "Phase 6 status.can_ship != True。export_bundle 未通过最终校验。"
        "修复入口：查看 export_audit_summary 中的具体失败项。"
    ),
    "phase6.note_ref_residual": (
        "导出 markdown 中残留 `{{NOTE_REF:...}}` 占位符。表示 Phase 3 注入后没有在 "
        "chapter_merge 阶段替换。检查 ref_materialization_summary.accounting_closed。"
    ),
    "phase6.chapter_coverage_mismatch": (
        "导出覆盖章节数 != TOC 章节数。export_bundle_summary.chapters_exported 不等于 "
        "chapters_total。修复入口：查看哪些 chapter_id 缺失。"
    ),
    "phase6.raw_marker_residual_warn": (
        "（warning）导出文件里仍有原始编号标记残留（非 NOTE_REF）。不阻塞，但建议排查。"
    ),
}


def _fail(code: str, message: str, *, evidence: dict[str, Any] | None = None) -> GateFailure:
    return GateFailure(
        code=code,
        message=message,
        hint=FIX_HINTS.get(code, ""),
        evidence=dict(evidence or {}),
    )


# ---------- Gate 1 ----------


def judge_phase1(structure: Any) -> GateReport:
    """Phase 1 Gate.

    pass 条件：
      1. `pages` 非空
      2. `chapters` 非空，且每章至少有 1 页（page_start/page_end 任一可推出）
      3. summary.chapter_title_alignment_ok == True 且 summary.chapter_section_alignment_ok == True
         （等价于计划文案里 "toc_alignment_review_required==0"）

    warnings：
      - 个别章节无对应 section_heads
    """
    failures: list[GateFailure] = []
    warnings: list[GateFailure] = []

    pages = list(getattr(structure, "pages", []) or [])
    chapters = list(getattr(structure, "chapters", []) or [])
    section_heads = list(getattr(structure, "section_heads", []) or [])
    summary = getattr(structure, "summary", None)

    if not pages:
        failures.append(_fail("phase1.no_pages", "page_partitions 为空"))

    if not chapters:
        failures.append(_fail("phase1.no_chapters", "未识别到任何章节"))

    # 每章至少一页
    orphan_chapters: list[dict[str, Any]] = []
    for ch in chapters:
        chapter_id = str(getattr(ch, "chapter_id", "") or "")
        page_start = int(getattr(ch, "page_start", 0) or 0)
        page_end = int(getattr(ch, "page_end", 0) or 0)
        pages_attr = getattr(ch, "pages", None)
        has_explicit_pages = bool(pages_attr) if pages_attr is not None else False
        has_page_range = page_start > 0 and page_end >= page_start
        if not has_explicit_pages and not has_page_range:
            orphan_chapters.append(
                {"chapter_id": chapter_id, "page_start": page_start, "page_end": page_end}
            )
    if orphan_chapters:
        failures.append(
            _fail(
                "phase1.chapter_missing_pages",
                f"{len(orphan_chapters)} 个章节未绑定页面",
                evidence={"chapters": orphan_chapters},
            )
        )

    # TOC alignment
    chapter_title_ok = bool(getattr(summary, "chapter_title_alignment_ok", True))
    chapter_section_ok = bool(getattr(summary, "chapter_section_alignment_ok", True))
    if not (chapter_title_ok and chapter_section_ok):
        failures.append(
            _fail(
                "phase1.toc_alignment_review_required",
                "TOC 与正文章节/小节对不齐",
                evidence={
                    "chapter_title_alignment_ok": chapter_title_ok,
                    "chapter_section_alignment_ok": chapter_section_ok,
                },
            )
        )

    # Warning：章节缺 section_heads
    chapter_ids_with_sections = {
        str(getattr(sh, "chapter_id", "") or "")
        for sh in section_heads
        if str(getattr(sh, "chapter_id", "") or "")
    }
    chapters_without_sections = [
        str(getattr(ch, "chapter_id", "") or "")
        for ch in chapters
        if str(getattr(ch, "chapter_id", "") or "")
        and str(getattr(ch, "chapter_id", "") or "") not in chapter_ids_with_sections
    ]
    if chapters_without_sections:
        warnings.append(
            _fail(
                "phase1.chapter_without_section_heads",
                f"{len(chapters_without_sections)} 个章节没有 section_head",
                evidence={"chapter_ids": chapters_without_sections},
            )
        )

    return GateReport(phase=1, pass_=not failures, failures=failures, warnings=warnings)


# ---------- Gate 2 ----------


def judge_phase2(structure: Any) -> GateReport:
    """Phase 2 Gate.

    pass 条件：
      1. Phase 1 Gate 通过（Phase 2 结构里包含 Phase 1 的所有字段）
      2. 所有 `note_regions.note_kind` 非空
      3. 所有 `note_regions.region_marker_alignment_ok == True`
      4. 没有 `chapter_note_modes.note_mode == "review_required"`

    warnings：
      - 有章节 `note_mode == "no_notes"`（可能是漏判）
    """
    failures: list[GateFailure] = []
    warnings: list[GateFailure] = []

    # Phase 1 部分复用
    phase1_report = judge_phase1(structure)
    failures.extend(phase1_report.failures)
    warnings.extend(phase1_report.warnings)

    note_regions = list(getattr(structure, "note_regions", []) or [])
    chapter_note_modes = list(getattr(structure, "chapter_note_modes", []) or [])

    # 2. note_kind 非空
    missing_kind = [
        str(getattr(r, "region_id", "") or "")
        for r in note_regions
        if not str(getattr(r, "note_kind", "") or "").strip()
    ]
    if missing_kind:
        failures.append(
            _fail(
                "phase2.note_region_missing_kind",
                f"{len(missing_kind)} 个 note_region 的 note_kind 为空",
                evidence={"region_ids": missing_kind},
            )
        )

    # 3. region_marker_alignment_ok
    misaligned = [
        str(getattr(r, "region_id", "") or "")
        for r in note_regions
        if not bool(getattr(r, "region_marker_alignment_ok", True))
    ]
    if misaligned:
        failures.append(
            _fail(
                "phase2.region_marker_misaligned",
                f"{len(misaligned)} 个 note_region marker 未对齐",
                evidence={"region_ids": misaligned},
            )
        )

    # 4. chapter_note_modes 没 review_required
    review_required_chapters = [
        str(getattr(m, "chapter_id", "") or "")
        for m in chapter_note_modes
        if str(getattr(m, "note_mode", "") or "") == "review_required"
    ]
    if review_required_chapters:
        failures.append(
            _fail(
                "phase2.chapter_note_mode_review_required",
                f"{len(review_required_chapters)} 个章节 note_mode=review_required",
                evidence={"chapter_ids": review_required_chapters},
            )
        )

    # Warning：no_notes 章节
    no_notes_chapters = [
        str(getattr(m, "chapter_id", "") or "")
        for m in chapter_note_modes
        if str(getattr(m, "note_mode", "") or "") == "no_notes"
    ]
    if no_notes_chapters:
        warnings.append(
            _fail(
                "phase2.chapter_no_notes",
                f"{len(no_notes_chapters)} 个章节无任何注释",
                evidence={"chapter_ids": no_notes_chapters},
            )
        )

    return GateReport(phase=2, pass_=not failures, failures=failures, warnings=warnings)


# ---------- Gate 3 ----------


def judge_phase3(structure: Any, *, freeze_summary: Any = None) -> GateReport:
    """Phase 3 Gate.

    pass 条件：
      1. Phase 2 Gate 通过（Phase 3 结构包含 Phase 2 所有字段）
      2. `summary.note_link_summary` 中 footnote_orphan_note / footnote_orphan_anchor /
         endnote_orphan_note / endnote_orphan_anchor / ambiguous 全为 0
      3. 若提供 `freeze_summary`（dev runner 跑完 ref_freeze 后附加）：
         - `only_matched_frozen` is True
         - `no_duplicate_injection` is True

    warnings：
      - `body_anchor_summary.synthetic_anchor_count > 0`
    """
    failures: list[GateFailure] = []
    warnings: list[GateFailure] = []

    phase2_report = judge_phase2(structure)
    failures.extend(phase2_report.failures)
    warnings.extend(phase2_report.warnings)

    summary = getattr(structure, "summary", None)
    note_link_summary = dict(getattr(summary, "note_link_summary", {}) or {})
    body_anchor_summary = dict(getattr(summary, "body_anchor_summary", {}) or {})

    def _count(key: str) -> int:
        try:
            return int(note_link_summary.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    code_to_key = [
        ("phase3.footnote_orphan_anchor", "footnote_orphan_anchor"),
        ("phase3.footnote_orphan_note", "footnote_orphan_note"),
        ("phase3.endnote_orphan_anchor", "endnote_orphan_anchor"),
        ("phase3.endnote_orphan_note", "endnote_orphan_note"),
        ("phase3.ambiguous_note_link", "ambiguous"),
    ]
    for code, key in code_to_key:
        n = _count(key)
        if n > 0:
            failures.append(
                _fail(
                    code,
                    f"note_link_summary.{key} = {n}（应为 0）",
                    evidence={key: n},
                )
            )

    # ref_freeze（可选）
    freeze = freeze_summary
    if freeze is None:
        freeze = getattr(structure, "freeze_summary", None)
    if freeze is not None:
        freeze_dict = dict(freeze) if not isinstance(freeze, dict) else freeze
        if not bool(freeze_dict.get("only_matched_frozen", True)):
            failures.append(
                _fail(
                    "phase3.freeze_unmatched_frozen",
                    "freeze_summary.only_matched_frozen = False",
                    evidence={"freeze_summary": freeze_dict},
                )
            )
        if not bool(freeze_dict.get("no_duplicate_injection", True)):
            failures.append(
                _fail(
                    "phase3.freeze_duplicate_injection",
                    "freeze_summary.no_duplicate_injection = False",
                    evidence={"freeze_summary": freeze_dict},
                )
            )

    # Warning：synthetic_anchor
    try:
        synth = int(body_anchor_summary.get("synthetic_anchor_count", 0) or 0)
    except (TypeError, ValueError):
        synth = 0
    if synth > 0:
        warnings.append(
            _fail(
                "phase3.synthetic_anchor_warn",
                f"存在 {synth} 个 synthetic_anchor",
                evidence={"synthetic_anchor_count": synth},
            )
        )

    return GateReport(phase=3, pass_=not failures, failures=failures, warnings=warnings)


# ---------- Gate 4 ----------


def judge_phase4(structure: Any) -> GateReport:
    """Phase 4 Gate.

    pass 条件：
      1. Phase 3 Gate 通过（Phase 4 结构里包含 Phase 3 所有字段，freeze 可选）
      2. `status.structure_state == "ready"`
      3. `status.blocking_reasons == []`
      4. 没有 `structure_reviews.state == "review_required"`
    """
    failures: list[GateFailure] = []
    warnings: list[GateFailure] = []

    phase3_report = judge_phase3(structure)
    failures.extend(phase3_report.failures)
    warnings.extend(phase3_report.warnings)

    status = getattr(structure, "status", None)
    state = str(getattr(status, "structure_state", "") or "").lower()
    blocking = list(getattr(status, "blocking_reasons", []) or [])
    if state != "ready":
        failures.append(
            _fail(
                "phase4.structure_state_not_ready",
                f"structure_state={state or '(empty)'}",
                evidence={"structure_state": state},
            )
        )
    if blocking:
        failures.append(
            _fail(
                "phase4.blocking_reasons_present",
                f"{len(blocking)} 个 blocking_reason",
                evidence={"blocking_reasons": blocking},
            )
        )

    reviews = list(getattr(structure, "structure_reviews", []) or [])
    review_required = [
        str(getattr(r, "target_id", "") or "")
        for r in reviews
        if str(getattr(r, "state", "") or "") == "review_required"
    ]
    if review_required:
        failures.append(
            _fail(
                "phase4.review_required_structure",
                f"{len(review_required)} 项 structure_review 待审核",
                evidence={"target_ids": review_required},
            )
        )

    return GateReport(phase=4, pass_=not failures, failures=failures, warnings=warnings)


# ---------- Gate 5 ----------


def judge_phase5(structure: Any, *, execution_mode: str = "real") -> GateReport:
    """Phase 5 Gate.

    pass 条件：
      1. Phase 4 Gate 通过
      2. `translation_units` 非空，所有 `source_text` 非空
      3. test 模式：所有 unit `status == "pseudo_done"`
         real 模式：所有 unit `status == "done"`
    """
    failures: list[GateFailure] = []
    warnings: list[GateFailure] = []

    phase4_report = judge_phase4(structure)
    failures.extend(phase4_report.failures)
    warnings.extend(phase4_report.warnings)

    units = list(getattr(structure, "translation_units", []) or [])
    if not units:
        failures.append(_fail("phase5.no_translation_units", "translation_units 为空"))
        return GateReport(phase=5, pass_=not failures, failures=failures, warnings=warnings)

    missing_source = [
        str(getattr(u, "unit_id", "") or "")
        for u in units
        if not str(getattr(u, "source_text", "") or "").strip()
    ]
    if missing_source:
        failures.append(
            _fail(
                "phase5.unit_missing_source_text",
                f"{len(missing_source)} 个 unit 的 source_text 为空",
                evidence={"unit_ids": missing_source[:20]},
            )
        )

    mode = str(execution_mode or "real").lower()
    if mode == "test":
        pending = [
            str(getattr(u, "unit_id", "") or "")
            for u in units
            if str(getattr(u, "status", "") or "") != "pseudo_done"
        ]
        if pending:
            failures.append(
                _fail(
                    "phase5.test_mode_mark_pending",
                    f"test 模式下 {len(pending)} 个 unit 未标记 pseudo_done",
                    evidence={"unit_ids": pending[:20]},
                )
            )
    else:
        incomplete = [
            str(getattr(u, "unit_id", "") or "")
            for u in units
            if str(getattr(u, "status", "") or "") != "done"
        ]
        if incomplete:
            failures.append(
                _fail(
                    "phase5.real_mode_unit_incomplete",
                    f"real 模式下 {len(incomplete)} 个 unit 未完成",
                    evidence={"unit_ids": incomplete[:20]},
                )
            )

    return GateReport(phase=5, pass_=not failures, failures=failures, warnings=warnings)


# ---------- Gate 6 ----------


def judge_phase6(structure: Any, *, execution_mode: str = "real") -> GateReport:
    """Phase 6 Gate.

    pass 条件：
      1. Phase 5 Gate 通过
      2. `status.can_ship == True`
      3. `export_bundle_summary.note_ref_residual == 0`
      4. `chapters_exported == chapters_total`

    warnings：
      - `raw_marker_residual > 0`
    """
    failures: list[GateFailure] = []
    warnings: list[GateFailure] = []

    phase5_report = judge_phase5(structure, execution_mode=execution_mode)
    failures.extend(phase5_report.failures)
    warnings.extend(phase5_report.warnings)

    status = getattr(structure, "status", None)
    can_ship = bool(getattr(status, "can_ship", False))
    if not can_ship:
        failures.append(
            _fail(
                "phase6.cannot_ship",
                "status.can_ship = False",
                evidence={"can_ship": can_ship},
            )
        )

    summary = getattr(structure, "summary", None)
    export_bundle_summary = dict(getattr(summary, "export_bundle_summary", {}) or {})

    def _as_int(key: str) -> int:
        try:
            return int(export_bundle_summary.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    note_ref_residual = _as_int("note_ref_residual")
    if note_ref_residual > 0:
        failures.append(
            _fail(
                "phase6.note_ref_residual",
                f"导出残留 {note_ref_residual} 个 NOTE_REF 占位",
                evidence={"note_ref_residual": note_ref_residual},
            )
        )

    chapters_exported = _as_int("chapters_exported")
    chapters_total = _as_int("chapters_total")
    if chapters_total and chapters_exported != chapters_total:
        failures.append(
            _fail(
                "phase6.chapter_coverage_mismatch",
                f"导出 {chapters_exported} / 总 {chapters_total} 章",
                evidence={
                    "chapters_exported": chapters_exported,
                    "chapters_total": chapters_total,
                },
            )
        )

    raw_marker_residual = _as_int("raw_marker_residual")
    if raw_marker_residual > 0:
        warnings.append(
            _fail(
                "phase6.raw_marker_residual_warn",
                f"{raw_marker_residual} 处原始编号残留",
                evidence={"raw_marker_residual": raw_marker_residual},
            )
        )

    return GateReport(phase=6, pass_=not failures, failures=failures, warnings=warnings)


# ---------- 统一入口 ----------


def judge_phase(phase: int, structure: Any, **kwargs: Any) -> GateReport:
    """按 phase 号分派到对应 judge 函数。未实现的 phase 返回空通过报告。"""
    p = int(phase)
    if p == 1:
        return judge_phase1(structure)
    if p == 2:
        return judge_phase2(structure)
    if p == 3:
        return judge_phase3(structure, **kwargs)
    if p == 4:
        return judge_phase4(structure)
    if p == 5:
        return judge_phase5(structure, **kwargs)
    if p == 6:
        return judge_phase6(structure, **kwargs)
    return GateReport(phase=p, pass_=True)


__all__ = [
    "FIX_HINTS",
    "GateFailure",
    "GateReport",
    "judge_phase",
    "judge_phase1",
    "judge_phase2",
    "judge_phase3",
    "judge_phase4",
    "judge_phase5",
    "judge_phase6",
]
