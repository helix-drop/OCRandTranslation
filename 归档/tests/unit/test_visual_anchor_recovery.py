from __future__ import annotations

import unittest
from unittest.mock import patch

from FNM_RE.models import (
    BodyAnchorRecord,
    ChapterRecord,
    NoteItemRecord,
    NoteRegionRecord,
    Phase2Structure,
)
from FNM_RE.modules.visual_anchor_recovery import (
    ChapterAnchorGap,
    compute_chapter_anchor_gaps,
    _materialize_visual_findings,
    _resolve_gap_page_range,
    run_visual_anchor_recovery,
)


def _anchor(marker: int, page_no: int, *, kind: str = "endnote") -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=f"a-{marker}-{page_no}",
        chapter_id="ch-1",
        page_no=page_no,
        paragraph_index=0,
        char_start=0,
        char_end=1,
        source_marker=str(marker),
        normalized_marker=str(marker),
        anchor_kind=kind,  # type: ignore[arg-type]
        certainty=1.0,
        source_text="body",
        source="test",
        synthetic=False,
        ocr_repaired_from_marker="",
    )


class VisualAnchorRecoveryMaterializeTest(unittest.TestCase):
    def test_gap_range_uses_nearest_marker_numbers_not_extreme_pages(self):
        gap = ChapterAnchorGap(
            chapter_id="ch-1",
            expected_markers=set(range(1, 54)),
            detected_markers=set(range(1, 54)) - {22, 23},
            missing_markers=[22, 23],
            gap_count=2,
            gap_rate=2 / 53,
            body_page_range=(91, 118),
        )
        anchors = [
            _anchor(18, 110),
            _anchor(21, 96),
            _anchor(24, 97),
            _anchor(44, 95),
        ]

        resolved = _resolve_gap_page_range(gap, anchors)

        self.assertEqual(resolved, (95, 98))

    def test_gap_detection_uses_endnote_items_and_ignores_footnote_anchors(self):
        phase2 = Phase2Structure(
            chapters=[
                ChapterRecord(
                    chapter_id="ch-1",
                    title="Chapter",
                    start_page=1,
                    end_page=5,
                    pages=[1, 2, 3, 4, 5],
                    source="test",  # type: ignore[arg-type]
                    boundary_state="ready",  # type: ignore[arg-type]
                )
            ],
            note_regions=[
                NoteRegionRecord(
                    region_id="en-r",
                    chapter_id="ch-1",
                    page_start=5,
                    page_end=5,
                    pages=[5],
                    note_kind="endnote",  # type: ignore[arg-type]
                    scope="chapter",  # type: ignore[arg-type]
                    source="test",  # type: ignore[arg-type]
                    heading_text="Notes",
                    start_reason="test",
                    end_reason="test",
                    region_marker_alignment_ok=True,
                    region_start_first_source_marker="1",
                    region_first_note_item_marker="1",
                    review_required=False,
                ),
                NoteRegionRecord(
                    region_id="fn-r",
                    chapter_id="ch-1",
                    page_start=2,
                    page_end=2,
                    pages=[2],
                    note_kind="footnote",  # type: ignore[arg-type]
                    scope="page",  # type: ignore[arg-type]
                    source="test",  # type: ignore[arg-type]
                    heading_text="",
                    start_reason="test",
                    end_reason="test",
                    region_marker_alignment_ok=True,
                    region_start_first_source_marker="1",
                    region_first_note_item_marker="1",
                    review_required=False,
                ),
            ],
            note_items=[
                NoteItemRecord(
                    note_item_id="en-1",
                    region_id="en-r",
                    chapter_id="ch-1",
                    page_no=5,
                    marker="1",
                    marker_type="numeric",
                    text="endnote one",
                    source="test",
                    source_page_label="5",
                    is_reconstructed=False,
                    review_required=False,
                    note_kind="endnote",
                ),
                NoteItemRecord(
                    note_item_id="en-2",
                    region_id="en-r",
                    chapter_id="ch-1",
                    page_no=5,
                    marker="2",
                    marker_type="numeric",
                    text="endnote two",
                    source="test",
                    source_page_label="5",
                    is_reconstructed=False,
                    review_required=False,
                    note_kind="endnote",
                ),
                NoteItemRecord(
                    note_item_id="fn-99",
                    region_id="fn-r",
                    chapter_id="ch-1",
                    page_no=2,
                    marker="99",
                    marker_type="numeric",
                    text="footnote only",
                    source="test",
                    source_page_label="2",
                    is_reconstructed=False,
                    review_required=False,
                    note_kind="footnote",
                ),
            ],
        )
        anchors = [_anchor(1, 2, kind="footnote"), _anchor(2, 3, kind="endnote")]

        gaps = compute_chapter_anchor_gaps(phase2, anchors)

        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].missing_markers, [1])
        self.assertEqual(gaps[0].expected_markers, {1, 2})

    def test_visual_recovery_retries_unmapped_markers_individually(self):
        gap = ChapterAnchorGap(
            chapter_id="ch-1",
            expected_markers={22, 23},
            detected_markers=set(),
            missing_markers=[22, 23],
            gap_count=2,
            gap_rate=1.0,
            body_page_range=(95, 97),
        )
        pages = [
            {
                "bookPage": 96,
                "markdown": (
                    "libération de l'économie des contraintes étatiques. "
                    "Freiheit et Bindung deviennent une loi."
                ),
            }
        ]

        with patch(
            "FNM_RE.modules.visual_anchor_recovery._resolve_model_args",
            return_value={"provider": "test", "model_id": "m", "api_key": "k"},
        ), patch(
            "FNM_RE.modules.visual_anchor_recovery._render_page_image",
            return_value=(b"image", "image/jpeg"),
        ), patch(
            "FNM_RE.modules.visual_anchor_recovery._request_visual_findings",
            side_effect=[
                [
                    {
                        "marker": 22,
                        "page_no": 96,
                        "anchor_phrase": "contraintes étatiques",
                        "source_marker": "²²",
                    }
                ],
                [
                    {
                        "marker": 23,
                        "page_no": 96,
                        "anchor_phrase": "Freiheit et Bindung",
                        "source_marker": "²³",
                    }
                ],
            ],
        ) as request_findings:
            anchors = run_visual_anchor_recovery(
                gap=gap,
                phase2=Phase2Structure(),
                pages=pages,
                pdf_path="/tmp/source.pdf",
                body_anchors=[],
            )

        self.assertEqual(request_findings.call_count, 2)
        self.assertEqual(
            sorted(int(anchor.normalized_marker) for anchor in anchors),
            [22, 23],
        )

    def test_printed_page_number_is_remapped_to_rendered_candidate_page(self):
        gap = ChapterAnchorGap(
            chapter_id="ch-1",
            expected_markers={20},
            detected_markers=set(),
            missing_markers=[20],
            gap_count=1,
            gap_rate=1.0,
            body_page_range=(91, 118),
        )
        pages = {
            91: {"bookPage": 91, "markdown": "Le corps du texte reste fermé avant la note."},
        }
        findings = [
            {
                "marker": 20,
                "page_no": 82,
                "anchor_phrase": "fermé",
                "source_marker": "²⁰",
            }
        ]

        anchors, summary = _materialize_visual_findings(
            findings,
            gap,
            pages,
            candidate_pages=[91],
        )

        self.assertEqual(summary["mapped"], 1)
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].page_no, 91)
        self.assertEqual(anchors[0].normalized_marker, "20")

    def test_unmapped_finding_outside_candidate_pages_is_not_materialized(self):
        gap = ChapterAnchorGap(
            chapter_id="ch-1",
            expected_markers={22},
            detected_markers=set(),
            missing_markers=[22],
            gap_count=1,
            gap_rate=1.0,
            body_page_range=(91, 118),
        )
        pages = {
            91: {"bookPage": 91, "markdown": "Le corps du texte ne contient pas la phrase."},
        }
        findings = [
            {
                "marker": 22,
                "page_no": 82,
                "anchor_phrase": "introuvable",
                "source_marker": "²²",
            }
        ]

        anchors, summary = _materialize_visual_findings(
            findings,
            gap,
            pages,
            candidate_pages=[91],
        )

        self.assertEqual(summary["mapped"], 0)
        self.assertEqual(summary["match_failed"], 1)
        self.assertEqual(anchors, [])


if __name__ == "__main__":
    unittest.main()
