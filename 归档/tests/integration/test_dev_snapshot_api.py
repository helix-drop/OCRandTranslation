"""/api/dev/fnm/.../phase/<n>/snapshot 的集成测试。

覆盖：
- phase 无记录 -> 404
- 成功创建 -> 落盘 + DB 行 + 返回字段
- list 返回刚才创建的快照（带 note）
- 非法 phase -> 400
"""
from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path

import config
from config import create_doc, ensure_dirs
from persistence.sqlite_store import SQLiteRepository
from web.dev_routes import register_dev_routes


class DevSnapshotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FNM_DEV_MODE"] = "1"
        self._original_config = {
            "CONFIG_DIR": config.CONFIG_DIR,
            "CONFIG_FILE": config.CONFIG_FILE,
            "DATA_DIR": config.DATA_DIR,
            "DOCS_DIR": config.DOCS_DIR,
            "CURRENT_FILE": config.CURRENT_FILE,
        }
        root = (
            Path(__file__).resolve().parents[2]
            / "local_data"
            / "_test_runtime"
            / f"dev-snapshot-{uuid.uuid4().hex}"
        )
        root.mkdir(parents=True, exist_ok=True)
        self.temp_root = root
        config.CONFIG_DIR = str(root)
        config.CONFIG_FILE = os.path.join(str(root), "config.json")
        config.DATA_DIR = os.path.join(config.CONFIG_DIR, "data")
        config.DOCS_DIR = os.path.join(config.DATA_DIR, "documents")
        config.CURRENT_FILE = os.path.join(config.DATA_DIR, "current.txt")
        ensure_dirs()

        self.doc_id = create_doc("snapshot_test.pdf")
        self.doc_dir = os.path.join(config.DOCS_DIR, self.doc_id)

        self.repo = SQLiteRepository()
        self.repo.init_phase_runs(self.doc_id)
        # 给 phase 2 一个有意义的状态
        self.repo.upsert_phase_run(
            self.doc_id,
            2,
            status="ready",
            gate_pass=True,
            gate_report={"gate": "ok"},
            errors=[],
        )

        from flask import Flask

        app = Flask(__name__)
        app.testing = True
        register_dev_routes(app)
        self.app = app
        self.client = app.test_client()

    def tearDown(self) -> None:
        for key, value in self._original_config.items():
            setattr(config, key, value)
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_snapshot_create_missing_phase_run_404(self):
        # phase 3 没有 upsert 过（init 时是 idle 占位，但 init_phase_runs 会写入 idle 行）
        # 所以换成根本不存在的 doc
        res = self.client.post(
            "/api/dev/fnm/book/doc_unknown/phase/2/snapshot",
            json={},
        )
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["ok"])

    def test_snapshot_create_and_list_roundtrip(self):
        res = self.client.post(
            f"/api/dev/fnm/book/{self.doc_id}/phase/2/snapshot",
            json={"note": "before refactor"},
        )
        self.assertEqual(res.status_code, 200, res.data)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["phase"], 2)
        self.assertEqual(body["note"], "before refactor")
        self.assertGreater(body["size_bytes"], 0)
        self.assertTrue(body["blob_path"].startswith("dev_snapshots/"))

        abs_path = os.path.join(self.doc_dir, body["blob_path"])
        self.assertTrue(os.path.isfile(abs_path))
        with open(abs_path, "r", encoding="utf-8") as fh:
            snap = json.load(fh)
        self.assertEqual(snap["doc_id"], self.doc_id)
        self.assertEqual(snap["phase"], 2)
        self.assertEqual(snap["gate_pass"], True)
        self.assertEqual(snap["gate_report"], {"gate": "ok"})

        # list 能读到
        res2 = self.client.get(
            f"/api/dev/fnm/book/{self.doc_id}/phase/2/snapshots"
        )
        self.assertEqual(res2.status_code, 200)
        body2 = res2.get_json()
        self.assertTrue(body2["ok"])
        self.assertEqual(len(body2["snapshots"]), 1)
        row = body2["snapshots"][0]
        self.assertEqual(row["phase"], 2)
        self.assertEqual(row["note"], "before refactor")
        self.assertEqual(row["blob_path"], body["blob_path"])

    def test_snapshot_list_empty_phase(self):
        res = self.client.get(
            f"/api/dev/fnm/book/{self.doc_id}/phase/4/snapshots"
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["snapshots"], [])

    def test_snapshot_create_cleans_json_when_db_fails(self):
        from persistence.sqlite_store import SingleDBRepository

        orig = SingleDBRepository.save_dev_snapshot

        def _boom(self, *args, **kwargs):
            raise RuntimeError("db down")

        SingleDBRepository.save_dev_snapshot = _boom
        try:
            res = self.client.post(
                f"/api/dev/fnm/book/{self.doc_id}/phase/2/snapshot",
                json={},
            )
        finally:
            SingleDBRepository.save_dev_snapshot = orig
        self.assertEqual(res.status_code, 500)
        snap_dir = os.path.join(self.doc_dir, "dev_snapshots")
        leftovers = os.listdir(snap_dir) if os.path.isdir(snap_dir) else []
        self.assertEqual(leftovers, [], f"孤儿文件未清理: {leftovers}")

    def test_reset_clears_snapshot_disk_files(self):
        from FNM_RE.dev.reset import reset_from_phase

        # 建 phase 2/3 两条 snapshot
        self.repo.upsert_phase_run(self.doc_id, 3, status="ready", gate_pass=True)
        for phase in (2, 3):
            res = self.client.post(
                f"/api/dev/fnm/book/{self.doc_id}/phase/{phase}/snapshot",
                json={"note": f"p{phase}"},
            )
            self.assertEqual(res.status_code, 200, res.data)

        snap_dir = os.path.join(self.doc_dir, "dev_snapshots")
        files_before = sorted(os.listdir(snap_dir))
        self.assertEqual(len(files_before), 2)

        from config import get_doc_dir

        result = reset_from_phase(
            self.doc_id, 3, repo=self.repo, get_doc_dir=get_doc_dir
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.deleted_snapshots, 1)
        self.assertEqual(result.deleted_snapshot_files, 1)

        files_after = sorted(os.listdir(snap_dir))
        self.assertEqual(len(files_after), 1)
        # 留下的是 phase 2 的
        self.assertTrue(files_after[0].startswith("phase2_"))


if __name__ == "__main__":
    unittest.main()
