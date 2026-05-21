"""FNM_RE/dev/gates.py 的单元测试（Phase 1/2 Gate 判据）。

为避免依赖完整 pipeline，测试用简单 SimpleNamespace/属性 stub 喂给判据函数。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from FNM_RE.dev.gates import (
    FIX_HINTS,
    judge_phase,
    judge_phase1,
    judge_phase2,
    judge_phase3,
    judge_phase4,
    judge_phase5,
    judge_phase6,
)


# ---------- fixture 构造 ----------


def _summary(chapter_title_ok: bool = True, chapter_section_ok: bool = True) -> NS:
    return NS(
        chapter_title_alignment_ok=chapter_title_ok,
        chapter_section_alignment_ok=chapter_section_ok,
    )


def _chapter(chapter_id: str, page_start: int = 1, page_end: int = 2) -> NS:
    return NS(chapter_id=chapter_id, page_start=page_start, page_end=page_end, pages=None)


def _section_head(chapter_id: str) -> NS:
    return NS(chapter_id=chapter_id)


def _region(region_id: str, *, kind: str = "footnote", aligned: bool = True) -> NS:
    return NS(region_id=region_id, note_kind=kind, region_marker_alignment_ok=aligned)


def _mode(chapter_id: str, note_mode: str) -> NS:
    return NS(chapter_id=chapter_id, note_mode=note_mode)


def _phase1_happy() -> NS:
    return NS(
        pages=[NS(page_no=1), NS(page_no=2)],
        chapters=[_chapter("c1"), _chapter("c2", 3, 4)],
        section_heads=[_section_head("c1"), _section_head("c2")],
        summary=_summary(),
    )


def _phase2_happy() -> NS:
    p1 = _phase1_happy()
    return NS(
        pages=p1.pages,
        chapters=p1.chapters,
        section_heads=p1.section_heads,
        summary=p1.summary,
        note_regions=[_region("r1"), _region("r2", kind="endnote")],
        chapter_note_modes=[_mode("c1", "footnote"), _mode("c2", "chapter_endnotes")],
    )


# ---------- Gate 1 ----------


class Phase1GateTests(unittest.TestCase):
    def test_happy_path_passes(self):
        report = judge_phase1(_phase1_happy())
        self.assertTrue(report.pass_)
        self.assertEqual(report.phase, 1)
        self.assertEqual(report.failures, [])

    def test_no_pages_fails(self):
        stub = _phase1_happy()
        stub.pages = []
        report = judge_phase1(stub)
        self.assertFalse(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertIn("phase1.no_pages", codes)

    def test_no_chapters_fails(self):
        stub = _phase1_happy()
        stub.chapters = []
        stub.section_heads = []
        report = judge_phase1(stub)
        self.assertFalse(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertIn("phase1.no_chapters", codes)

    def test_chapter_missing_pages_fails(self):
        stub = _phase1_happy()
        stub.chapters = [_chapter("c1"), NS(chapter_id="c2", page_start=0, page_end=0, pages=None)]
        stub.section_heads = [_section_head("c1"), _section_head("c2")]
        report = judge_phase1(stub)
        self.assertFalse(report.pass_)
        orphan = next(f for f in report.failures if f.code == "phase1.chapter_missing_pages")
        self.assertEqual(len(orphan.evidence["chapters"]), 1)
        self.assertEqual(orphan.evidence["chapters"][0]["chapter_id"], "c2")

    def test_chapter_with_explicit_pages_passes(self):
        # 没 page_start/page_end 但有 pages 列表，也应通过
        stub = _phase1_happy()
        stub.chapters = [NS(chapter_id="c1", page_start=0, page_end=0, pages=[1, 2])]
        stub.section_heads = [_section_head("c1")]
        report = judge_phase1(stub)
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])

    def test_toc_alignment_failure(self):
        stub = _phase1_happy()
        stub.summary = _summary(chapter_title_ok=False)
        report = judge_phase1(stub)
        self.assertFalse(report.pass_)
        self.assertIn("phase1.toc_alignment_review_required", [f.code for f in report.failures])

    def test_chapter_without_sections_is_warning_not_failure(self):
        stub = _phase1_happy()
        stub.section_heads = [_section_head("c1")]  # c2 没 section
        report = judge_phase1(stub)
        self.assertTrue(report.pass_)
        warn_codes = [w.code for w in report.warnings]
        self.assertIn("phase1.chapter_without_section_heads", warn_codes)
        warn = next(w for w in report.warnings if w.code == "phase1.chapter_without_section_heads")
        self.assertEqual(warn.evidence["chapter_ids"], ["c2"])

    def test_failures_carry_hint_from_fix_hints(self):
        stub = _phase1_happy()
        stub.pages = []
        report = judge_phase1(stub)
        failure = next(f for f in report.failures if f.code == "phase1.no_pages")
        self.assertEqual(failure.hint, FIX_HINTS["phase1.no_pages"])
        self.assertTrue(failure.hint)

    def test_to_dict_is_json_friendly(self):
        report = judge_phase1(_phase1_happy())
        data = report.to_dict()
        self.assertEqual(data["phase"], 1)
        self.assertTrue(data["pass"])
        self.assertIsInstance(data["failures"], list)
        self.assertIsInstance(data["warnings"], list)


# ---------- Gate 2 ----------


class Phase2GateTests(unittest.TestCase):
    def test_happy_path_passes(self):
        report = judge_phase2(_phase2_happy())
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])
        self.assertEqual(report.phase, 2)

    def test_inherits_phase1_failures(self):
        stub = _phase2_happy()
        stub.pages = []
        report = judge_phase2(stub)
        self.assertFalse(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertIn("phase1.no_pages", codes)

    def test_note_region_missing_kind_fails(self):
        stub = _phase2_happy()
        stub.note_regions = [_region("r1", kind=""), _region("r2")]
        report = judge_phase2(stub)
        self.assertFalse(report.pass_)
        fail = next(f for f in report.failures if f.code == "phase2.note_region_missing_kind")
        self.assertEqual(fail.evidence["region_ids"], ["r1"])

    def test_region_marker_misaligned_fails(self):
        stub = _phase2_happy()
        stub.note_regions = [_region("r1", aligned=False), _region("r2")]
        report = judge_phase2(stub)
        self.assertFalse(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertIn("phase2.region_marker_misaligned", codes)

    def test_review_required_mode_fails(self):
        stub = _phase2_happy()
        stub.chapter_note_modes = [_mode("c1", "footnote"), _mode("c2", "review_required")]
        report = judge_phase2(stub)
        self.assertFalse(report.pass_)
        fail = next(f for f in report.failures if f.code == "phase2.chapter_note_mode_review_required")
        self.assertEqual(fail.evidence["chapter_ids"], ["c2"])

    def test_no_notes_mode_is_warning(self):
        stub = _phase2_happy()
        stub.chapter_note_modes = [_mode("c1", "footnote"), _mode("c2", "no_notes")]
        report = judge_phase2(stub)
        self.assertTrue(report.pass_)
        warn_codes = [w.code for w in report.warnings]
        self.assertIn("phase2.chapter_no_notes", warn_codes)

    def test_empty_regions_pass(self):
        # 没 note_regions、没 chapter_note_modes 也可通过（等同于无注释书）
        stub = _phase2_happy()
        stub.note_regions = []
        stub.chapter_note_modes = []
        report = judge_phase2(stub)
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])

    def test_multiple_failures_accumulate(self):
        stub = _phase2_happy()
        stub.note_regions = [_region("r1", kind=""), _region("r2", aligned=False)]
        stub.chapter_note_modes = [_mode("c1", "review_required")]
        report = judge_phase2(stub)
        self.assertFalse(report.pass_)
        codes = {f.code for f in report.failures}
        self.assertIn("phase2.note_region_missing_kind", codes)
        self.assertIn("phase2.region_marker_misaligned", codes)
        self.assertIn("phase2.chapter_note_mode_review_required", codes)


# ---------- Gate 3 ----------


def _phase3_summary(
    *,
    footnote_orphan_anchor: int = 0,
    footnote_orphan_note: int = 0,
    endnote_orphan_anchor: int = 0,
    endnote_orphan_note: int = 0,
    ambiguous: int = 0,
    synthetic_anchor_count: int = 0,
) -> NS:
    base = _summary()
    base.note_link_summary = {
        "footnote_orphan_anchor": footnote_orphan_anchor,
        "footnote_orphan_note": footnote_orphan_note,
        "endnote_orphan_anchor": endnote_orphan_anchor,
        "endnote_orphan_note": endnote_orphan_note,
        "ambiguous": ambiguous,
    }
    base.body_anchor_summary = {"synthetic_anchor_count": synthetic_anchor_count}
    return base


def _phase3_happy() -> NS:
    p2 = _phase2_happy()
    return NS(
        pages=p2.pages,
        chapters=p2.chapters,
        section_heads=p2.section_heads,
        note_regions=p2.note_regions,
        chapter_note_modes=p2.chapter_note_modes,
        body_anchors=[],
        note_links=[],
        summary=_phase3_summary(),
    )


class Phase3GateTests(unittest.TestCase):
    def test_happy_path_passes(self):
        report = judge_phase3(_phase3_happy())
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])
        self.assertEqual(report.phase, 3)

    def test_inherits_phase2_failures(self):
        stub = _phase3_happy()
        stub.note_regions = [_region("r1", kind="")]
        report = judge_phase3(stub)
        self.assertFalse(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertIn("phase2.note_region_missing_kind", codes)

    def test_orphan_counts_fail(self):
        stub = _phase3_happy()
        stub.summary = _phase3_summary(
            footnote_orphan_anchor=2,
            endnote_orphan_note=1,
            ambiguous=1,
        )
        report = judge_phase3(stub)
        self.assertFalse(report.pass_)
        codes = {f.code for f in report.failures}
        self.assertIn("phase3.footnote_orphan_anchor", codes)
        self.assertIn("phase3.endnote_orphan_note", codes)
        self.assertIn("phase3.ambiguous_note_link", codes)

    def test_freeze_only_matched_false_fails(self):
        report = judge_phase3(
            _phase3_happy(),
            freeze_summary={"only_matched_frozen": False, "no_duplicate_injection": True},
        )
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase3.freeze_unmatched_frozen",
            [f.code for f in report.failures],
        )

    def test_freeze_duplicate_injection_false_fails(self):
        report = judge_phase3(
            _phase3_happy(),
            freeze_summary={"only_matched_frozen": True, "no_duplicate_injection": False},
        )
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase3.freeze_duplicate_injection",
            [f.code for f in report.failures],
        )

    def test_freeze_summary_on_structure_attribute(self):
        stub = _phase3_happy()
        stub.freeze_summary = {"only_matched_frozen": False}
        report = judge_phase3(stub)
        self.assertIn(
            "phase3.freeze_unmatched_frozen",
            [f.code for f in report.failures],
        )

    def test_synthetic_anchor_is_warning(self):
        stub = _phase3_happy()
        stub.summary = _phase3_summary(synthetic_anchor_count=3)
        report = judge_phase3(stub)
        self.assertTrue(report.pass_)
        warn_codes = [w.code for w in report.warnings]
        self.assertIn("phase3.synthetic_anchor_warn", warn_codes)

    def test_judge_phase_dispatcher(self):
        r1 = judge_phase(1, _phase1_happy())
        self.assertEqual(r1.phase, 1)
        r3 = judge_phase(3, _phase3_happy())
        self.assertEqual(r3.phase, 3)
        r_unknown = judge_phase(9, NS())
        self.assertTrue(r_unknown.pass_)


# ---------- Gate 4 ----------


def _phase4_happy() -> NS:
    p3 = _phase3_happy()
    return NS(
        pages=p3.pages,
        chapters=p3.chapters,
        section_heads=p3.section_heads,
        note_regions=p3.note_regions,
        chapter_note_modes=p3.chapter_note_modes,
        body_anchors=[],
        note_links=[],
        summary=p3.summary,
        status=NS(structure_state="ready", blocking_reasons=[]),
        structure_reviews=[],
    )


class Phase4GateTests(unittest.TestCase):
    def test_happy_path_passes(self):
        report = judge_phase4(_phase4_happy())
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])
        self.assertEqual(report.phase, 4)

    def test_not_ready_state_fails(self):
        stub = _phase4_happy()
        stub.status = NS(structure_state="review_required", blocking_reasons=[])
        report = judge_phase4(stub)
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase4.structure_state_not_ready", [f.code for f in report.failures]
        )

    def test_blocking_reasons_fail(self):
        stub = _phase4_happy()
        stub.status = NS(structure_state="ready", blocking_reasons=["toc.offset"])
        report = judge_phase4(stub)
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase4.blocking_reasons_present", [f.code for f in report.failures]
        )

    def test_review_required_structure_fail(self):
        stub = _phase4_happy()
        stub.structure_reviews = [
            NS(target_id="rev_1", state="review_required"),
            NS(target_id="rev_2", state="resolved"),
        ]
        report = judge_phase4(stub)
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase4.review_required_structure", [f.code for f in report.failures]
        )


# ---------- Gate 5 ----------


def _phase5_happy(mode: str = "test") -> NS:
    p4 = _phase4_happy()
    status_suffix = "pseudo_done" if mode == "test" else "done"
    units = [
        NS(unit_id="u1", source_text="hello", status=status_suffix),
        NS(unit_id="u2", source_text="world", status=status_suffix),
    ]
    return NS(
        pages=p4.pages,
        chapters=p4.chapters,
        section_heads=p4.section_heads,
        note_regions=p4.note_regions,
        chapter_note_modes=p4.chapter_note_modes,
        body_anchors=[],
        note_links=[],
        structure_reviews=[],
        translation_units=units,
        status=p4.status,
        summary=p4.summary,
    )


class Phase5GateTests(unittest.TestCase):
    def test_happy_path_test_mode(self):
        report = judge_phase5(_phase5_happy("test"), execution_mode="test")
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])
        self.assertEqual(report.phase, 5)

    def test_happy_path_real_mode(self):
        report = judge_phase5(_phase5_happy("real"), execution_mode="real")
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])

    def test_missing_source_text_fails(self):
        stub = _phase5_happy("test")
        stub.translation_units[0].source_text = ""
        report = judge_phase5(stub, execution_mode="test")
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase5.unit_missing_source_text", [f.code for f in report.failures]
        )

    def test_test_mode_pending_status_fails(self):
        stub = _phase5_happy("test")
        stub.translation_units[0].status = "pending"
        report = judge_phase5(stub, execution_mode="test")
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase5.test_mode_mark_pending", [f.code for f in report.failures]
        )

    def test_real_mode_incomplete_fails(self):
        stub = _phase5_happy("real")
        stub.translation_units[1].status = "pending"
        report = judge_phase5(stub, execution_mode="real")
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase5.real_mode_unit_incomplete", [f.code for f in report.failures]
        )

    def test_empty_units_fails(self):
        stub = _phase5_happy("test")
        stub.translation_units = []
        report = judge_phase5(stub, execution_mode="test")
        self.assertFalse(report.pass_)
        self.assertIn("phase5.no_translation_units", [f.code for f in report.failures])


# ---------- Gate 6 ----------


def _phase6_happy() -> NS:
    p5 = _phase5_happy("test")
    summary = _phase3_summary()
    summary.export_bundle_summary = {
        "note_ref_residual": 0,
        "chapters_exported": 2,
        "chapters_total": 2,
        "raw_marker_residual": 0,
    }
    return NS(
        pages=p5.pages,
        chapters=p5.chapters,
        section_heads=p5.section_heads,
        note_regions=p5.note_regions,
        chapter_note_modes=p5.chapter_note_modes,
        body_anchors=[],
        note_links=[],
        structure_reviews=[],
        translation_units=p5.translation_units,
        status=NS(structure_state="ready", blocking_reasons=[], can_ship=True),
        summary=summary,
    )


class Phase6GateTests(unittest.TestCase):
    def test_happy_path_passes(self):
        report = judge_phase6(_phase6_happy(), execution_mode="test")
        self.assertTrue(report.pass_, msg=[f.code for f in report.failures])
        self.assertEqual(report.phase, 6)

    def test_cannot_ship_fails(self):
        stub = _phase6_happy()
        stub.status = NS(
            structure_state="ready", blocking_reasons=[], can_ship=False
        )
        report = judge_phase6(stub, execution_mode="test")
        self.assertFalse(report.pass_)
        self.assertIn("phase6.cannot_ship", [f.code for f in report.failures])

    def test_note_ref_residual_fails(self):
        stub = _phase6_happy()
        stub.summary.export_bundle_summary["note_ref_residual"] = 2
        report = judge_phase6(stub, execution_mode="test")
        self.assertFalse(report.pass_)
        self.assertIn("phase6.note_ref_residual", [f.code for f in report.failures])

    def test_chapter_coverage_mismatch_fails(self):
        stub = _phase6_happy()
        stub.summary.export_bundle_summary["chapters_exported"] = 1
        report = judge_phase6(stub, execution_mode="test")
        self.assertFalse(report.pass_)
        self.assertIn(
            "phase6.chapter_coverage_mismatch", [f.code for f in report.failures]
        )

    def test_raw_marker_residual_is_warning(self):
        stub = _phase6_happy()
        stub.summary.export_bundle_summary["raw_marker_residual"] = 3
        report = judge_phase6(stub, execution_mode="test")
        self.assertTrue(report.pass_)
        self.assertIn(
            "phase6.raw_marker_residual_warn", [w.code for w in report.warnings]
        )


# ---------- dispatcher ----------


class JudgePhaseDispatcherTests(unittest.TestCase):
    def test_phase4_dispatch(self):
        self.assertEqual(judge_phase(4, _phase4_happy()).phase, 4)

    def test_phase5_dispatch_test_mode(self):
        report = judge_phase(5, _phase5_happy("test"), execution_mode="test")
        self.assertTrue(report.pass_)

    def test_phase6_dispatch(self):
        report = judge_phase(6, _phase6_happy(), execution_mode="test")
        self.assertTrue(report.pass_)


class FixHintsTests(unittest.TestCase):
    def test_every_code_in_hints_is_non_empty(self):
        self.assertTrue(FIX_HINTS)
        for code, hint in FIX_HINTS.items():
            self.assertTrue(hint.strip(), msg=f"hint for {code} is empty")


if __name__ == "__main__":
    unittest.main()
