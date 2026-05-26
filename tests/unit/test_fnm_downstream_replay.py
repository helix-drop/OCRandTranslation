#!/usr/bin/env python3
"""FNM 下游回放的阶段 5 证据口径测试。"""

from __future__ import annotations

import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test_fnm_downstream_replay.py"
SCRIPT_NS = runpy.run_path(str(SCRIPT_PATH))


class FnmDownstreamReplayTest(unittest.TestCase):
    def test_phase4_contract_can_pass_when_later_export_fails(self):
        phase4_evidence = SCRIPT_NS.get("_phase4_contract_evidence")
        build_summary = SCRIPT_NS.get("_build_summary")
        self.assertIsNotNone(phase4_evidence)
        self.assertIsNotNone(build_summary)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "doc.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE fnm_translation_units (doc_id TEXT NOT NULL);
                    CREATE TABLE fnm_structure_reviews (
                        doc_id TEXT NOT NULL,
                        review_type TEXT NOT NULL,
                        chapter_id TEXT,
                        page_start INTEGER,
                        page_end INTEGER,
                        payload_json TEXT,
                        severity TEXT NOT NULL
                    );
                    INSERT INTO fnm_translation_units(doc_id) VALUES ('doc-1');
                    """
                )

            evidence = phase4_evidence(
                db_path,
                "doc-1",
                {"ok": True, "blocking_reasons": ["export_audit_blocking"]},
                True,
            )
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["freeze_blocker_count"], 0)
            self.assertEqual(evidence["translation_unit_count"], 1)

            summary = build_summary(
                [
                    {
                        "passed": False,
                        "phase4_contract_passed": evidence["passed"],
                    }
                ],
                phase4_contract_only=True,
            )
            self.assertFalse(summary["passed"])
            self.assertTrue(summary["phase4_contract_passed"])
            self.assertTrue(summary["exit_passed"])

    def test_freeze_review_blocks_phase4_contract(self):
        phase4_evidence = SCRIPT_NS.get("_phase4_contract_evidence")
        self.assertIsNotNone(phase4_evidence)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "doc.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE fnm_translation_units (doc_id TEXT NOT NULL);
                    CREATE TABLE fnm_structure_reviews (
                        doc_id TEXT NOT NULL,
                        review_type TEXT NOT NULL,
                        chapter_id TEXT,
                        page_start INTEGER,
                        page_end INTEGER,
                        payload_json TEXT,
                        severity TEXT NOT NULL
                    );
                    INSERT INTO fnm_structure_reviews(
                        doc_id, review_type, chapter_id, page_start, page_end,
                        payload_json, severity
                    ) VALUES (
                        'doc-1', 'freeze_matched_ref_not_injected',
                        'ch-1', 7, 7, '{"reason":"token_not_found"}', 'error'
                    );
                    """
                )

            evidence = phase4_evidence(db_path, "doc-1", {"ok": True}, True)
            self.assertFalse(evidence["passed"])
            self.assertEqual(evidence["freeze_blocker_count"], 1)
            self.assertEqual(
                evidence["freeze_blockers"][0]["payload"]["reason"],
                "token_not_found",
            )

    def test_sqlite_snapshot_includes_committed_wal_rows(self):
        copy_snapshot = SCRIPT_NS.get("_copy_sqlite_snapshot")
        self.assertIsNotNone(copy_snapshot)

        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "source.db"
            copy_path = Path(tmp) / "copy.db"
            with sqlite3.connect(str(source_path)) as source:
                source.execute("PRAGMA journal_mode=WAL")
                source.execute("PRAGMA wal_autocheckpoint=0")
                source.execute("CREATE TABLE marker(value TEXT NOT NULL)")
                source.commit()
                source.execute("INSERT INTO marker(value) VALUES ('committed-in-wal')")
                source.commit()
                self.assertTrue(Path(f"{source_path}-wal").exists())

                copy_snapshot(source_path, copy_path)

            with sqlite3.connect(str(copy_path)) as copied:
                rows = copied.execute("SELECT value FROM marker").fetchall()
            self.assertEqual(rows, [("committed-in-wal",)])

    def test_batch_replay_runs_each_book_in_an_isolated_worker(self):
        replay_isolated = SCRIPT_NS.get("_replay_book_isolated")
        self.assertIsNotNone(replay_isolated)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "batch-tag"
            calls: list[list[str]] = []

            def fake_run(command, **kwargs):
                calls.append(command)
                book_dir = output_dir / "Biopolitics"
                book_dir.mkdir(parents=True, exist_ok=True)
                (book_dir / "result.json").write_text(
                    '{"slug":"Biopolitics","phase4_contract_passed":true,"passed":false}',
                    encoding="utf-8",
                )

            globals_dict = replay_isolated.__globals__
            with patch.object(globals_dict["subprocess"], "run", side_effect=fake_run):
                report = replay_isolated("Biopolitics", output_dir)

        self.assertTrue(report["phase4_contract_passed"])
        self.assertIn("--isolated-worker", calls[0])
        self.assertIn("Biopolitics", calls[0])


if __name__ == "__main__":
    unittest.main()
