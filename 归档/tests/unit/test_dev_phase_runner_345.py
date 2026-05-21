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
        self.footnotes: dict[str, dict] = {}
        self.endnotes: dict[str, dict] = {}
        self.alignments: dict[str, dict] = {}

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

    def replace_fnm_paragraph_footnotes(self, doc_id, chapter_id, *, footnotes):
        key = (doc_id, chapter_id)
        if key not in self.footnotes:
            self.footnotes[key] = []
        self.footnotes[key].extend(dict(fn) for fn in (footnotes or []))

    def replace_fnm_chapter_endnotes(self, doc_id, chapter_id, *, endnotes):
        key = (doc_id, chapter_id)
        if key not in self.endnotes:
            self.endnotes[key] = []
        self.endnotes[key].extend(dict(en) for en in (endnotes or []))

    def upsert_fnm_chapter_anchor_alignment(
        self,
        doc_id,
        chapter_id,
        *,
        alignment_status="misaligned",
        body_anchor_count=0,
        endnote_count=0,
        mismatch=None,
    ):
        self.alignments[(doc_id, chapter_id)] = {
            "alignment_status": alignment_status,
            "body_anchor_count": body_anchor_count,
            "endnote_count": endnote_count,
            "mismatch": mismatch,
        }


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
        chapter_anchor_alignment_summary={
            "total_chapters": 1,
            "clean": 1,
            "mismatches": 0,
            "misaligned": 0,
            "chapter_status": {
                "c1": {"alignment_status": "clean", "body_anchor_count": 0, "endnote_count": 0},
            },
        },
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
        paragraph_footnotes=[],
        paragraph_endnotes=[],
        chapter_anchor_alignments=[],
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




class Phase3PersistenceTests(unittest.TestCase):
    """直接测试 _persist_phase3 的写入逻辑。"""

    def test_persist_phase3_empty_lists(self):
        """空列表不报错、不写入。"""
        repo = FakeRepo()
        p3 = NS(
            paragraph_footnotes=[],
            paragraph_endnotes=[],
            chapter_anchor_alignments=[],
        )
        phase_runner._persist_phase3(repo, "doc-x", p3)
        self.assertEqual(len(repo.footnotes), 0)
        self.assertEqual(len(repo.endnotes), 0)
        self.assertEqual(len(repo.alignments), 0)

    def test_persist_phase3_footnotes(self):
        """footnotes 按 chapter_id 分组写入。"""
        repo = FakeRepo()
        fn1 = NS(chapter_id="c1", page_no=5, paragraph_index=0, attachment_kind="anchor_matched", source_marker="1", text="fn1")
        fn2 = NS(chapter_id="c1", page_no=5, paragraph_index=1, attachment_kind="page_tail", source_marker="2", text="fn2")
        fn3 = NS(chapter_id="c2", page_no=9, paragraph_index=0, attachment_kind="anchor_matched", source_marker="1", text="fn3")
        p3 = NS(
            paragraph_footnotes=[fn1, fn2, fn3],
            paragraph_endnotes=[],
            chapter_anchor_alignments=[],
        )
        phase_runner._persist_phase3(repo, "doc-x", p3)
        c1_fns = repo.footnotes.get(("doc-x", "c1"), [])
        c2_fns = repo.footnotes.get(("doc-x", "c2"), [])
        self.assertEqual(len(c1_fns), 2)
        self.assertEqual(len(c2_fns), 1)
        self.assertEqual(c1_fns[0]["source_marker"], "1")
        self.assertEqual(c1_fns[1]["text"], "fn2")

    def test_persist_phase3_endnotes(self):
        """endnotes 按 chapter_id 分组写入。"""
        repo = FakeRepo()
        en1 = NS(chapter_id="c1", ordinal=1, marker="1", text="First note")
        en2 = NS(chapter_id="c1", ordinal=2, marker="2", text="Second note")
        p3 = NS(
            paragraph_footnotes=[],
            paragraph_endnotes=[en1, en2],
            chapter_anchor_alignments=[],
        )
        phase_runner._persist_phase3(repo, "doc-x", p3)
        c1_ens = repo.endnotes.get(("doc-x", "c1"), [])
        self.assertEqual(len(c1_ens), 2)
        self.assertEqual(c1_ens[0]["marker"], "1")
        self.assertEqual(c1_ens[0]["text"], "First note")

    def test_persist_phase3_alignments(self):
        """anchor alignment 逐章节 upsert。"""
        repo = FakeRepo()
        al1 = NS(chapter_id="c1", alignment_status="clean", body_anchor_count=3, endnote_count=3, mismatch=None)
        al2 = NS(chapter_id="c2", alignment_status="misaligned", body_anchor_count=2, endnote_count=5, mismatch={"body_extra_markers": ["1"]})
        p3 = NS(
            paragraph_footnotes=[],
            paragraph_endnotes=[],
            chapter_anchor_alignments=[al1, al2],
        )
        phase_runner._persist_phase3(repo, "doc-x", p3)
        self.assertEqual(len(repo.alignments), 2)
        self.assertEqual(repo.alignments[("doc-x", "c1")]["alignment_status"], "clean")
        self.assertEqual(repo.alignments[("doc-x", "c2")]["alignment_status"], "misaligned")
        self.assertIsNotNone(repo.alignments[("doc-x", "c2")]["mismatch"])

    def test_persist_phase3_round_trip(self):
        """完整写入和通过 gate 验证（使用 PipelineStub）。"""
        repo = FakeRepo()
        patchers = [
            patch.dict(sys.modules, {"FNM_RE.app.pipeline": _PipelineStub()}),
            patch(
                "FNM_RE.dev.phase_runner.load_fnm_toc_items",
                side_effect=_fake_load_toc_items,
            ),
        ]
        for p in patchers:
            p.start()
        try:
            result = phase_runner.execute_phase(
                "doc-x",
                3,
                repo=repo,
                load_pages_from_disk=_fake_load_pages,
            )
            self.assertTrue(result.ok, msg=result.error)
            self.assertEqual(result.status, "ready")
            self.assertTrue(repo.phase_runs[("doc-x", 3)]["gate_pass"])
        finally:
            for p in patchers:
                p.stop()


class Phase3GateAlignmentTests(unittest.TestCase):
    """对齐数据在 judge_phase3 中的表现。"""

    def setUp(self) -> None:
        self.base = _fake_phase3()

    def _summary_with_alignment(self, chapter_status: dict) -> NS:
        return NS(
            chapter_title_alignment_ok=True,
            chapter_section_alignment_ok=True,
            note_link_summary={
                "footnote_orphan_anchor": 0, "footnote_orphan_note": 0,
                "endnote_orphan_anchor": 0, "endnote_orphan_note": 0,
                "ambiguous": 0,
            },
            body_anchor_summary={"synthetic_anchor_count": 0},
            chapter_anchor_alignment_summary={
                "total_chapters": len(chapter_status),
                "chapter_status": chapter_status,
            },
        )

    def test_clean_alignment_passes_gate(self):
        """所有章节 clean → gate pass."""
        from FNM_RE.dev.gates import judge_phase3
        p3 = NS(
            pages=self.base.pages,
            chapters=self.base.chapters,
            note_links=[],
            body_anchors=[],
            note_items=[],
            paragraph_footnotes=[],
            paragraph_endnotes=[],
            chapter_anchor_alignments=[],
            summary=self._summary_with_alignment({
                "c1": {"alignment_status": "clean"},
            }),
        )
        report = judge_phase3(p3)
        self.assertTrue(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertNotIn("phase3.chapter_anchor_misaligned", codes)

    def test_misaligned_fails_gate(self):
        """misaligned 章节 → gate failure."""
        from FNM_RE.dev.gates import judge_phase3
        p3 = NS(
            pages=self.base.pages,
            chapters=self.base.chapters,
            note_links=[],
            body_anchors=[],
            note_items=[],
            paragraph_footnotes=[],
            paragraph_endnotes=[],
            chapter_anchor_alignments=[],
            summary=self._summary_with_alignment({
                "c1": {"alignment_status": "misaligned", "body_anchor_count": 3, "endnote_count": 1},
            }),
        )
        report = judge_phase3(p3)
        self.assertFalse(report.pass_)
        codes = [f.code for f in report.failures]
        self.assertIn("phase3.chapter_anchor_misaligned", codes)

    def test_mismatches_warns_only(self):
        """mismatches 只产生 warning，不阻塞 gate."""
        from FNM_RE.dev.gates import judge_phase3
        p3 = NS(
            pages=self.base.pages,
            chapters=self.base.chapters,
            note_links=[],
            body_anchors=[],
            note_items=[],
            paragraph_footnotes=[],
            paragraph_endnotes=[],
            chapter_anchor_alignments=[],
            summary=self._summary_with_alignment({
                "c1": {"alignment_status": "mismatches"},
            }),
        )
        report = judge_phase3(p3)
        self.assertTrue(report.pass_)
        warn_codes = [f.code for f in report.warnings]
        self.assertIn("phase3.chapter_anchor_mismatches_warn", warn_codes)


if __name__ == "__main__":
    unittest.main()
