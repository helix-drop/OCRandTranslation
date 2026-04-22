"""Tier 1b: scope="anchor" override materialization in note_linking."""

from __future__ import annotations

import unittest

from FNM_RE.models import BodyAnchorRecord
from FNM_RE.modules.note_linking import (
    _group_review_overrides,
    _materialize_anchor_overrides,
)


def _base_anchor(anchor_id: str = "a-1") -> BodyAnchorRecord:
    return BodyAnchorRecord(
        anchor_id=anchor_id,
        chapter_id="c-1",
        page_no=10,
        paragraph_index=0,
        char_start=5,
        char_end=12,
        source_marker="1",
        normalized_marker="1",
        anchor_kind="endnote",  # type: ignore[arg-type]
        certainty=1.0,
        source_text="foo",
        source="rule",
        synthetic=False,
        ocr_repaired_from_marker="",
    )


class GroupReviewOverridesAnchorScopeTest(unittest.TestCase):
    def test_anchor_scope_in_list_form(self):
        overrides = [
            {
                "scope": "anchor",
                "target_id": "llm-synth-L1",
                "payload": {"action": "create", "anchor_id": "llm-synth-L1"},
            }
        ]
        grouped = _group_review_overrides(overrides)
        self.assertIn("anchor", grouped)
        self.assertIn("llm-synth-L1", grouped["anchor"])

    def test_anchor_scope_in_mapping_form(self):
        overrides = {"anchor": {"llm-synth-L1": {"action": "create"}}}
        grouped = _group_review_overrides(overrides)
        self.assertEqual(grouped["anchor"]["llm-synth-L1"], {"action": "create"})


class MaterializeAnchorOverridesTest(unittest.TestCase):
    def _valid_payload(self, **overrides):
        base = {
            "action": "create",
            "anchor_id": "llm-synth-L1",
            "chapter_id": "c-1",
            "page_no": 11,
            "paragraph_index": 0,
            "char_start": 100,
            "char_end": 130,
            "source_text": "verbatim phrase from body",
            "normalized_marker": "n-99",
            "anchor_kind": "endnote",
            "certainty": 0.91,
            "source": "llm",
            "synthetic": False,
        }
        base.update(overrides)
        return base

    def test_create_appends_new_anchor(self):
        existing = [_base_anchor("a-1")]
        new_anchors, summary, logs = _materialize_anchor_overrides(
            existing, anchor_overrides={"llm-synth-L1": self._valid_payload()}
        )
        self.assertEqual(len(new_anchors), 2)
        synth = new_anchors[-1]
        self.assertEqual(synth.anchor_id, "llm-synth-L1")
        self.assertEqual(synth.source, "llm")
        self.assertFalse(synth.synthetic)
        self.assertEqual(synth.char_start, 100)
        self.assertEqual(summary["created_count"], 1)
        self.assertEqual(summary["rejected_count"], 0)
        self.assertEqual(logs[0]["anchor_id"], "llm-synth-L1")

    def test_conflicting_anchor_id_rejected(self):
        existing = [_base_anchor("dup-id")]
        overrides = {"dup-id": self._valid_payload(anchor_id="dup-id")}
        new_anchors, summary, _ = _materialize_anchor_overrides(
            existing, anchor_overrides=overrides
        )
        self.assertEqual(len(new_anchors), 1)
        self.assertEqual(summary["rejected_count"], 1)

    def test_invalid_coords_rejected(self):
        overrides = {
            "bad-1": self._valid_payload(char_start=50, char_end=50),
            "bad-2": self._valid_payload(anchor_id="ok", page_no=0),
        }
        new_anchors, summary, _ = _materialize_anchor_overrides(
            [], anchor_overrides=overrides
        )
        self.assertEqual(len(new_anchors), 0)
        self.assertEqual(summary["rejected_count"], 2)

    def test_non_create_action_rejected(self):
        overrides = {"x": self._valid_payload(action="delete")}
        _, summary, _ = _materialize_anchor_overrides([], anchor_overrides=overrides)
        self.assertEqual(summary["created_count"], 0)
        self.assertEqual(summary["rejected_count"], 1)

    def test_empty_override_returns_input_unchanged(self):
        existing = [_base_anchor("a-1")]
        new_anchors, summary, logs = _materialize_anchor_overrides(
            existing, anchor_overrides=None
        )
        self.assertEqual(new_anchors, existing)
        self.assertEqual(summary["created_count"], 0)
        self.assertEqual(logs, [])

    def test_synthesized_anchor_is_not_synthetic_flag(self):
        """Regression: LLM-discovered anchors must pass through ref_freeze,
        which skips synthetic=True. So source="llm" BUT synthetic=False."""
        _, _, _ = _materialize_anchor_overrides(
            [], anchor_overrides={"x": self._valid_payload()}
        )
        new_anchors, _, _ = _materialize_anchor_overrides(
            [], anchor_overrides={"x": self._valid_payload()}
        )
        self.assertEqual(new_anchors[0].source, "llm")
        self.assertFalse(new_anchors[0].synthetic)


if __name__ == "__main__":
    unittest.main()
