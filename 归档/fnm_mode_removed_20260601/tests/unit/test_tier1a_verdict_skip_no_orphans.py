"""Tier1a 判定回归：没有孤儿 note 的书不该被判 FAIL。

Neuropsychoanalysis_Introduction / _in_Practice 的基线 orphan_note=0，LLM
没有可合成的输入，注定不会产出 llm-synth anchor。沿用原先严格判定
（PASS iff llm_synth_anchor_count>0）会把这类"已经干净"的书标成 FAIL，
让批次结果失真。改为 SKIP：orphan_note 全部为 0 → 没有待修的任务。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_script_module():
    # 脚本文件名不是合法 Python 标识符，用 importlib 直接加载。
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_fnm_llm_tier1a.py"
    spec = importlib.util.spec_from_file_location("run_fnm_llm_tier1a", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_fnm_llm_tier1a"] = module
    spec.loader.exec_module(module)
    return module


class DecideVerdictTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_script_module()

    def _baseline(self, *, fn_note=0, fn_anchor=0, en_note=0, en_anchor=0):
        return {
            "orphans": {
                "footnote_orphan_note": fn_note,
                "footnote_orphan_anchor": fn_anchor,
                "endnote_orphan_note": en_note,
                "endnote_orphan_anchor": en_anchor,
                "ambiguous": 0,
            },
            "override_scope_counts": {},
        }

    def _after(self, *, synth=0, anchor_scope=0):
        return {
            "llm_synth_anchor_count": synth,
            "override_scope_counts": {"anchor": anchor_scope},
            "orphans": {},
        }

    def test_skip_when_no_orphan_notes_in_baseline(self):
        # Neuropsychoanalysis_Introduction 场景：没有任何孤儿。
        verdict = self.module._decide_verdict(
            baseline=self._baseline(),
            after=self._after(),
            blocking_reasons=[],
        )
        self.assertEqual(verdict, "SKIP")

    def test_skip_when_only_orphan_anchors_no_orphan_notes(self):
        # Neuropsychoanalysis_in_Practice 场景：有孤儿 anchor，但没孤儿 note。
        verdict = self.module._decide_verdict(
            baseline=self._baseline(en_anchor=45),
            after=self._after(),
            blocking_reasons=[],
        )
        self.assertEqual(verdict, "SKIP")

    def test_pass_when_synth_anchor_written(self):
        verdict = self.module._decide_verdict(
            baseline=self._baseline(en_note=10),
            after=self._after(synth=3, anchor_scope=3),
            blocking_reasons=[],
        )
        self.assertEqual(verdict, "PASS")

    def test_fail_when_orphan_notes_but_no_synth(self):
        # Goldstein/Biopolitics 场景：有待修孤儿 note，但本次 synth=0。
        verdict = self.module._decide_verdict(
            baseline=self._baseline(en_note=466, en_anchor=873),
            after=self._after(),
            blocking_reasons=["link_orphan_note_remaining"],
        )
        self.assertEqual(verdict, "FAIL")

    def test_fail_when_footnote_orphan_notes_but_no_synth(self):
        verdict = self.module._decide_verdict(
            baseline=self._baseline(fn_note=5),
            after=self._after(),
            blocking_reasons=[],
        )
        self.assertEqual(verdict, "FAIL")


if __name__ == "__main__":
    unittest.main()
