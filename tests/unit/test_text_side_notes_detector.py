"""文本侧 NOTES 容器页识别（工单 #5，覆盖 docs/fnm-notes-coverage-plan.md §6.5）。

针对：
1. `build_page_partitions` 已支持把 `endnote_collection` 页打成 `note` role；
   验证 Biopolitics 真实数据上至少 60 页被识别。
2. `_build_page_roles`（toc_structure）必须**保留** partition 的 `note` 信号，
   不被 chapter_by_page 映射覆盖。
3. `_is_endnote_page`（book_note_type）作为补充检测：在 partition 没识别到 note
   但 markdown 显然是 NOTES 页时仍能命中。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BIOPOLITICS_RAW = REPO_ROOT / "test_example" / "Biopolitics" / "raw_pages.json"

# 金板 manifest 的 note_pages 全集（72 页）
GOLD_NOTE_PAGES: frozenset[int] = frozenset(
    [39, 40, 41, 42]
    + [63, 64, 65, 66]
    + [86, 87, 88, 89, 90]
    + [111, 112, 113, 114, 115, 116, 117, 118]
    + [139, 140, 141, 142, 143, 144, 145, 146, 147, 148]
    + [170, 171, 172, 173, 174, 175, 176, 177, 178]
    + [197, 198, 199, 200, 201, 202]
    + [225, 226, 227, 228, 229, 230, 231, 232]
    + [252, 253, 254, 255, 256]
    + [279, 280, 281, 282]
    + [302, 303, 304, 305, 306]
    + [329, 330, 331, 332]
)
# 反例：明显的正文页
BODY_PAGES_SAMPLE: tuple[int, ...] = (17, 18, 100, 250)


def _load_biopolitics_pages() -> list[dict]:
    if not BIOPOLITICS_RAW.exists():
        raise FileNotFoundError(f"测试 fixture 缺失: {BIOPOLITICS_RAW}")
    raw = json.loads(BIOPOLITICS_RAW.read_text(encoding="utf-8"))
    return list(raw.get("pages") or [])


class IsEndnotePageHeuristicTest(unittest.TestCase):
    """`book_note_type._is_endnote_page` 命中真实 NOTES 页且不误识正文。"""

    @classmethod
    def setUpClass(cls):
        from FNM_RE.shared.text import page_markdown_text
        cls.pages = _load_biopolitics_pages()
        cls.page_md_by_no = {
            int(p.get("bookPage") or 0): page_markdown_text(p) for p in cls.pages
        }

    def test_recognizes_majority_of_gold_notes_pages(self):
        from FNM_RE.modules.book_note_type import _is_endnote_page

        hits = sum(
            1
            for pn in GOLD_NOTE_PAGES
            if _is_endnote_page(self.page_md_by_no.get(pn, ""))
        )
        self.assertGreaterEqual(
            hits,
            55,
            f"_is_endnote_page 命中过低 ({hits}/72)，无法支撑工单 #5 验收。",
        )

    def test_does_not_misidentify_body_page(self):
        from FNM_RE.modules.book_note_type import _is_endnote_page

        for pn in BODY_PAGES_SAMPLE:
            md = self.page_md_by_no.get(pn, "")
            self.assertFalse(
                _is_endnote_page(md),
                f"正文页 p{pn} 被误识为 NOTES 容器：{md[:120]!r}",
            )


class BuildPagePartitionsNoteRoleTest(unittest.TestCase):
    """`build_page_partitions` 在 Biopolitics 真实数据上识别 note role 页 ≥ 60。"""

    @classmethod
    def setUpClass(cls):
        from FNM_RE.stages.page_partition import build_page_partitions
        cls.pages = _load_biopolitics_pages()
        cls.partitions = build_page_partitions(list(cls.pages))

    def test_note_role_count_on_biopolitics(self):
        note_pages = sorted(
            int(p.page_no) for p in self.partitions if str(p.page_role or "") == "note"
        )
        self.assertGreaterEqual(
            len(note_pages),
            60,
            f"build_page_partitions 应识别 ≥ 60 个 note 页, 实际 {len(note_pages)}: {note_pages}",
        )

    def test_note_pages_overlap_with_gold(self):
        note_pages = {
            int(p.page_no) for p in self.partitions if str(p.page_role or "") == "note"
        }
        overlap = note_pages & GOLD_NOTE_PAGES
        self.assertGreaterEqual(
            len(overlap),
            55,
            f"build_page_partitions 与金板 NOTES 页交集过低: {len(overlap)}/72",
        )


class BuildPageRolesPreservesNoteRoleTest(unittest.TestCase):
    """`_build_page_roles` 必须保留 partition 的 note 信号，不被 chapter mapping 覆盖。

    工单 #5 的核心：当前 chapter.pages 包含章末 NOTES 页，会让 role 被覆盖为
    chapter / post_body，使下游识别不到 NOTES 容器。本测试钉死"note 优先"。
    """

    def test_note_role_preserved_when_chapter_covers_page(self):
        from FNM_RE.models import PagePartitionRecord
        from FNM_RE.modules.toc_structure import _build_page_roles
        from FNM_RE.modules.types import TocChapter

        partitions = [
            PagePartitionRecord(
                page_no=10,
                target_pdf_page=10,
                page_role="body",
                confidence=1.0,
                reason="default_body",
                section_hint="",
                has_note_heading=False,
                note_scan_summary={},
            ),
            PagePartitionRecord(
                page_no=11,
                target_pdf_page=11,
                page_role="note",  # 上游 note_scan 识别为 NOTES 容器
                confidence=0.95,
                reason="note_scan_collection",
                section_hint="",
                has_note_heading=True,
                note_scan_summary={"page_kind": "endnote_collection"},
            ),
            PagePartitionRecord(
                page_no=12,
                target_pdf_page=12,
                page_role="note",
                confidence=0.95,
                reason="note_continuation",
                section_hint="",
                has_note_heading=False,
                note_scan_summary={"page_kind": "endnote_collection"},
            ),
        ]
        # chapter 覆盖了 p10-12（含 NOTES 容器页）
        chapters = [
            TocChapter(
                chapter_id="ch-1",
                title="Lesson 1",
                start_page=10,
                end_page=12,
                pages=[10, 11, 12],
                role="chapter",
                source="visual_toc",
                boundary_state="ready",
            )
        ]
        roles = _build_page_roles(partitions, chapters=chapters)
        roles_by_no = {row.page_no: row.role for row in roles}

        # p10 是正文 → chapter
        self.assertEqual(roles_by_no[10], "chapter")
        # p11/p12 上游标 note → 必须保留为 note，不被 chapter 覆盖
        self.assertEqual(
            roles_by_no[11], "note",
            f"NOTES 容器页 p11 应保留 note role，实际为 {roles_by_no[11]}",
        )
        self.assertEqual(
            roles_by_no[12], "note",
            f"NOTES 续页 p12 应保留 note role，实际为 {roles_by_no[12]}",
        )

    def test_note_role_clears_chapter_id(self):
        """note 页不应绑定到原 chapter_id（避免下游 region 把 NOTES 当章节正文）。"""
        from FNM_RE.models import PagePartitionRecord
        from FNM_RE.modules.toc_structure import _build_page_roles
        from FNM_RE.modules.types import TocChapter

        partitions = [
            PagePartitionRecord(
                page_no=20,
                target_pdf_page=20,
                page_role="note",
                confidence=0.95,
                reason="note_scan_collection",
                section_hint="",
                has_note_heading=True,
                note_scan_summary={"page_kind": "endnote_collection"},
            )
        ]
        chapters = [
            TocChapter(
                chapter_id="ch-X",
                title="Lesson X",
                start_page=20,
                end_page=20,
                pages=[20],
                role="chapter",
                source="visual_toc",
                boundary_state="ready",
            )
        ]
        roles = _build_page_roles(partitions, chapters=chapters)
        self.assertEqual(roles[0].role, "note")
        # chapter_id 仍可保留（用于绑定 NOTES 区到 chapter）
        # 但 reason 必须留下追溯线索
        self.assertIn(
            "note",
            str(roles[0].reason or "").lower(),
            f"note role 的 reason 应含 'note' 标记: {roles[0].reason}",
        )


class FullToCStructureNoteCountTest(unittest.TestCase):
    """跑完整 build_toc_structure，验证 page_role_counts.note ≥ 30（工单 #5 验收）。"""

    def test_biopolitics_page_role_counts_note(self):
        from FNM_RE.modules.toc_structure import build_toc_structure
        from tests.unit.fnm_re_module_fixtures import load_auto_visual_toc

        pages = _load_biopolitics_pages()
        toc_bundle = load_auto_visual_toc("Biopolitics")
        toc_items = toc_bundle.get("toc_items") if isinstance(toc_bundle, dict) else toc_bundle
        result = build_toc_structure(pages, toc_items)
        note_role_count = sum(
            1 for row in result.data.pages if str(row.role or "") == "note"
        )
        self.assertGreaterEqual(
            note_role_count,
            30,
            f"page_role_counts.note 应 ≥ 30, 实际 {note_role_count}",
        )


if __name__ == "__main__":
    unittest.main()
