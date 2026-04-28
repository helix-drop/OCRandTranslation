"""阶段3：扩展章节 end_page 覆盖其绑定的 endnote region。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from FNM_RE.models import (
    ChapterRecord,
    NoteRegionRecord,
    Phase1Structure,
    PagePartitionRecord,
)


def _make_chapter(chapter_id: str, title: str, start: int, end: int, pages: list[int] | None = None) -> ChapterRecord:
    return ChapterRecord(
        chapter_id=chapter_id, title=title,
        start_page=start, end_page=end,
        pages=list(pages or []),
        source="visual_toc", boundary_state="ready",
    )


def _make_endnote_region(
    chapter_id: str, region_id: str,
    start: int, end: int, pages: list[int] | None = None,
) -> NoteRegionRecord:
    return NoteRegionRecord(
        region_id=region_id, chapter_id=chapter_id,
        page_start=start, page_end=end,
        pages=list(pages or []),
        note_kind="endnote", scope="chapter", source="scan",
        heading_text="", start_reason="", end_reason="",
        region_marker_alignment_ok=True,
        region_start_first_source_marker="",
        region_first_note_item_marker="",
        review_required=False,
    )


def _extend_chapter_boundaries_for_endnote_regions(
    chapters: list[ChapterRecord],
    regions: list[NoteRegionRecord],
) -> list[ChapterRecord]:
    """核心逻辑（与 chapter_split.py 中将写入的逻辑一致）。"""
    for region in regions:
        if str(region.note_kind or "") != "endnote" or str(region.scope or "") != "chapter":
            continue
        cid = str(region.chapter_id or "").strip()
        if not cid:
            continue
        for idx, ch in enumerate(chapters):
            if str(ch.chapter_id or "") != cid:
                continue
            new_end = max(int(ch.end_page), int(region.page_end))
            new_pages = list(ch.pages or [])
            for p in (region.pages or []):
                if int(p) not in new_pages:
                    new_pages.append(int(p))
            new_pages.sort()
            chapters[idx] = replace(ch, end_page=new_end, pages=new_pages)
            break
    return chapters


class Phase3ChapterBoundaryTest(unittest.TestCase):
    """章节边界扩展单元测试。"""

    def test_extend_chapter_end_page_to_cover_endnote_region(self):
        """章节 end_page 从 body 末页扩展到尾注区末页。"""
        chapters = [_make_chapter("ch1", "Ch1", 1, 39, list(range(1, 40)))]
        regions = [_make_endnote_region("ch1", "r1", 40, 42, [40, 41, 42])]
        result = _extend_chapter_boundaries_for_endnote_regions(chapters, regions)
        self.assertEqual(result[0].end_page, 42)

    def test_extend_merges_region_pages_into_chapter_pages(self):
        """尾注区的页号合并进 chapter.pages。"""
        chapters = [_make_chapter("ch1", "Ch1", 1, 39, [1, 2, 3, 39])]
        regions = [_make_endnote_region("ch1", "r1", 40, 42, [40, 41, 42])]
        result = _extend_chapter_boundaries_for_endnote_regions(chapters, regions)
        self.assertIn(40, result[0].pages)
        self.assertIn(41, result[0].pages)
        self.assertIn(42, result[0].pages)
        self.assertEqual(result[0].pages, sorted(result[0].pages))

    def test_no_extend_when_endnote_already_covered(self):
        """end_page 已覆盖尾注区时不改。"""
        chapters = [_make_chapter("ch1", "Ch1", 1, 45)]
        regions = [_make_endnote_region("ch1", "r1", 40, 42)]
        result = _extend_chapter_boundaries_for_endnote_regions(chapters, regions)
        self.assertEqual(result[0].end_page, 45)

    def test_skip_non_endnote_region(self):
        """只处理 kind=endnote + scope=chapter 的 region。"""
        chapters = [_make_chapter("ch1", "Ch1", 1, 39)]
        fn_region = NoteRegionRecord(
            region_id="r1", chapter_id="ch1",
            page_start=40, page_end=42, pages=[40, 41, 42],
            note_kind="footnote", scope="chapter", source="scan",
            heading_text="", start_reason="", end_reason="",
            region_marker_alignment_ok=True,
            region_start_first_source_marker="",
            region_first_note_item_marker="",
            review_required=False,
        )
        result = _extend_chapter_boundaries_for_endnote_regions(chapters, [fn_region])
        self.assertEqual(result[0].end_page, 39)

    def test_skip_book_scope_region(self):
        """scope=book 的不绑定到单章，跳过。"""
        chapters = [_make_chapter("ch1", "Ch1", 1, 39)]
        regions = [_make_endnote_region("ch1", "r1", 40, 42)]
        regions[0] = replace(regions[0], scope="book", chapter_id="")
        result = _extend_chapter_boundaries_for_endnote_regions(chapters, regions)
        self.assertEqual(result[0].end_page, 39)


class Phase3BioptimicsIntegrationTest(unittest.TestCase):
    """Biopolitics 真实 fixture 端到端验证。"""

    def test_biopolitics_all_chapters_cover_endnote_regions(self):
        """跑 build_chapter_layers 后每章 endnote_regions 都有对应 chapter_id。"""
        import json, os
        from example_manifest import load_example_manifest
        from FNM_RE.modules.toc_structure import build_toc_structure
        from FNM_RE.modules.book_note_type import build_book_note_profile
        from FNM_RE.modules.chapter_split import build_chapter_layers

        books = load_example_manifest()
        book = next(b for b in books if b.slug == "Biopolitics")
        raw_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "test_example", book.folder, "raw_pages.json",
        )
        with open(raw_path) as fh:
            payload = json.loads(fh.read())
        pages = payload.get("pages", [])

        toc = build_toc_structure(pages, {}).data
        book_note_profile = build_book_note_profile(toc, pages).data

        result = build_chapter_layers(toc, book_note_profile, pages)
        layer = result.data

        # 每章如果有 endnote region，region 的章节归属必须有 chapter_id
        chapter_ids = {ch.chapter_id for ch in layer.chapters}
        unbound = []
        for r in layer.regions:
            if str(r.note_kind or "") != "endnote":
                continue
            if str(r.chapter_id or "") not in chapter_ids:
                unbound.append(r.region_id)
        self.assertEqual(
            unbound, [],
            f"有 {len(unbound)} 个 endnote region 未绑定到有效章节: {unbound[:5]}"
        )


if __name__ == "__main__":
    unittest.main()
