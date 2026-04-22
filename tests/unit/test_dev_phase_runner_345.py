"""phase_runner 扩展到 Phase 3~6 的单测。

不跑真 FNM pipeline —— 用 monkeypatch 替换 `build_phaseN_structure`，
让执行器走完「load → build → gate → upsert_phase_run」的全路径，
同时验证 Phase 5 test 模式会把 units 标成 pseudo_done、real 模式会被拒。
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from FNM_RE.dev import phase_runner


# ---------- 假 repo ----------


class FakeRepo:
    def __init__(self):
        self.phase_runs: dict[tuple[str, int], dict] = {}

    def upsert_phase_run(
        self,
        doc_id,
        phase,
        *,
        status=None,
        gate_pass=None,
        gate_report=None,
        errors=None,
        execution_mode=None,
        forced_skip=None,
        started_at=None,
        ended_at=None,
    ):
        key = (doc_id, phase)
        row = self.phase_runs.get(key, {"doc_id": doc_id, "phase": phase})
        if status is not None:
            row["status"] = status
        if gate_pass is not None:
            row["gate_pass"] = bool(gate_pass)
        if gate_report is not None:
            row["gate_report"] = gate_report
        if errors is not None:
            row["errors"] = errors
        if execution_mode is not None:
            row["execution_mode"] = execution_mode
        if forced_skip is not None:
            row["forced_skip"] = bool(forced_skip)
        self.phase_runs[key] = row
        return row

    def list_phase_runs(self, doc_id):
        return [v for (d, _), v in self.phase_runs.items() if d == doc_id]


# ---------- fixture ----------


def _fake_phase1():
    return NS(
        pages=[NS(page_no=1)],
        chapters=[NS(chapter_id="c1", page_start=1, page_end=1, pages=None)],
        section_heads=[NS(chapter_id="c1")],
        heading_candidates=[],
        summary=NS(chapter_title_alignment_ok=True, chapter_section_alignment_ok=True),
    )


def _fake_phase2():
    p1 = _fake_phase1()
    return NS(
        pages=p1.pages,
        chapters=p1.chapters,
        section_heads=p1.section_heads,
        heading_candidates=[],
        note_regions=[NS(region_id="r1", note_kind="footnote", region_marker_alignment_ok=True)],
        chapter_note_modes=[NS(chapter_id="c1", note_mode="footnote")],
        note_items=[],
        summary=p1.summary,
    )


def _fake_phase3():
    p2 = _fake_phase2()
    summary = NS(
        chapter_title_alignment_ok=True,
        chapter_section_alignment_ok=True,
        note_link_summary={
            "footnote_orphan_anchor": 0,
            "footnote_orphan_note": 0,
            "endnote_orphan_anchor": 0,
            "endnote_orphan_note": 0,
            "ambiguous": 0,
        },
        body_anchor_summary={"synthetic_anchor_count": 0},
    )
    return NS(
        pages=p2.pages,
        chapters=p2.chapters,
        section_heads=p2.section_heads,
        note_regions=p2.note_regions,
        chapter_note_modes=p2.chapter_note_modes,
        note_items=[],
        heading_candidates=[],
        body_anchors=[],
        note_links=[],
        summary=summary,
    )


def _fake_phase4():
    p3 = _fake_phase3()
    return NS(
        pages=p3.pages,
        chapters=p3.chapters,
        section_heads=p3.section_heads,
        note_regions=p3.note_regions,
        chapter_note_modes=p3.chapter_note_modes,
        note_items=[],
        heading_candidates=[],
        body_anchors=[],
        note_links=[],
        structure_reviews=[],
        summary=p3.summary,
        status=NS(structure_state="ready", blocking_reasons=[], can_ship=True),
    )


class _MutableUnit:
    """用普通类而非 NS —— 让 translated_text/status 可被赋值。"""

    def __init__(self, unit_id, source_text):
        self.unit_id = unit_id
        self.source_text = source_text
        self.translated_text = ""
        self.status = "pending"
        self.error_msg = ""


def _fake_phase5():
    p4 = _fake_phase4()
    return NS(
        pages=p4.pages,
        chapters=p4.chapters,
        section_heads=p4.section_heads,
        note_regions=p4.note_regions,
        chapter_note_modes=p4.chapter_note_modes,
        note_items=[],
        heading_candidates=[],
        body_anchors=[],
        note_links=[],
        structure_reviews=[],
        translation_units=[_MutableUnit("u1", "hello world")],
        summary=p4.summary,
        status=p4.status,
    )


def _fake_phase6():
    p5 = _fake_phase5()
    summary = NS(
        chapter_title_alignment_ok=True,
        chapter_section_alignment_ok=True,
        note_link_summary={
            "footnote_orphan_anchor": 0,
            "footnote_orphan_note": 0,
            "endnote_orphan_anchor": 0,
            "endnote_orphan_note": 0,
            "ambiguous": 0,
        },
        body_anchor_summary={"synthetic_anchor_count": 0},
        export_bundle_summary={
            "note_ref_residual": 0,
            "chapters_exported": 1,
            "chapters_total": 1,
            "raw_marker_residual": 0,
        },
    )
    return NS(
        pages=p5.pages,
        chapters=p5.chapters,
        section_heads=p5.section_heads,
        note_regions=p5.note_regions,
        chapter_note_modes=p5.chapter_note_modes,
        note_items=[],
        heading_candidates=[],
        body_anchors=[],
        note_links=[],
        structure_reviews=[],
        translation_units=p5.translation_units,
        export_chapters=[NS(chapter_id="c1", markdown="# hello")],
        summary=summary,
        status=p5.status,
    )


# ---------- 公共 pipeline 替身 ----------


class _PipelineStub(types.ModuleType):
    def __init__(self):
        super().__init__("FNM_RE.app.pipeline")
        self.build_phase1_structure = lambda *a, **kw: _fake_phase1()
        self.build_phase2_structure = lambda *a, **kw: _fake_phase2()
        self.build_phase3_structure = lambda *a, **kw: _fake_phase3()
        self.build_phase4_structure = lambda *a, **kw: _fake_phase4()
        self.build_phase5_structure = lambda *a, **kw: _fake_phase5()
        self.build_phase6_structure = lambda *a, **kw: _fake_phase6()


def _fake_load_pages(doc_id):
    return [{"page_no": 1, "text": "demo"}], "demo.pdf"


def _fake_load_toc_items(doc_id, repo):
    return [], 0


class PhaseRunnerPhase3to6Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FakeRepo()
        self.tmp_dir = tempfile.mkdtemp(prefix="dev-runner-345-")
        self.patchers = [
            patch.dict(sys.modules, {"FNM_RE.app.pipeline": _PipelineStub()}),
            patch(
                "FNM_RE.dev.phase_runner.load_fnm_toc_items",
                side_effect=_fake_load_toc_items,
            ),
        ]
        for p in self.patchers:
            p.start()
        # 覆盖 get_doc_dir 指向临时目录，Phase 6 导出到这里
        import config

        self._orig_get_doc_dir = config.get_doc_dir
        config.get_doc_dir = lambda doc_id="": self.tmp_dir

    def tearDown(self) -> None:
        for p in self.patchers:
            p.stop()
        import config

        config.get_doc_dir = self._orig_get_doc_dir
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _run(self, phase, *, execution_mode="real"):
        return phase_runner.execute_phase(
            "doc_x",
            phase,
            repo=self.repo,
            load_pages_from_disk=_fake_load_pages,
            execution_mode=execution_mode,
        )

    def test_supported_phases_covers_1_to_6(self):
        self.assertEqual(tuple(phase_runner.SUPPORTED_PHASES), (1, 2, 3, 4, 5, 6))

    def test_phase3_runs_and_gate_passes(self):
        res = self._run(3)
        self.assertTrue(res.ok, msg=res.error)
        self.assertEqual(res.status, "ready")
        row = self.repo.phase_runs[("doc_x", 3)]
        self.assertTrue(row["gate_pass"])

    def test_phase4_runs_and_gate_passes(self):
        res = self._run(4)
        self.assertTrue(res.ok, msg=res.error)

    def test_phase5_test_mode_marks_pseudo_done(self):
        res = self._run(5, execution_mode="test")
        self.assertTrue(res.ok, msg=res.error)
        row = self.repo.phase_runs[("doc_x", 5)]
        self.assertTrue(row["gate_pass"])

    def test_phase5_real_mode_is_rejected(self):
        res = self._run(5, execution_mode="real")
        self.assertFalse(res.ok)
        self.assertIn("real", res.error.lower())

    def test_phase6_writes_markdown(self):
        res = self._run(6, execution_mode="test")
        self.assertTrue(res.ok, msg=res.error)
        export_file = os.path.join(self.tmp_dir, "dev_exports", "c1.md")
        self.assertTrue(os.path.isfile(export_file))
        with open(export_file, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# hello")


if __name__ == "__main__":
    unittest.main()
