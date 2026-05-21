"""/api/dev/fnm/.../pdf 与 /export-fragment 的集成测试。

只验证路由行为（文件存在/不存在、Range、占位返回）。不跑 FNM pipeline。
"""
from __future__ import annotations

import os
import tempfile
import unittest

from flask import Flask

from web.dev_routes import register_dev_routes


class DevPdfAndExportRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FNM_DEV_MODE"] = "1"
        self.tmp = tempfile.mkdtemp(prefix="dev-pdf-test-")
        self.doc_dir = os.path.join(self.tmp, "docs", "doc_x")
        os.makedirs(self.doc_dir, exist_ok=True)

        app = Flask(__name__)
        app.testing = True

        # 猴补丁：让 register_dev_routes 用我们 tmp doc_dir
        import web.dev_routes as dev_routes_mod

        self._orig_register = dev_routes_mod.register_dev_routes

        # 这里直接 call register，它内部 from config import get_doc_dir
        # 所以打补丁更简单的方式：替换 config.get_doc_dir
        import config

        self._orig_get_doc_dir = config.get_doc_dir
        config.get_doc_dir = lambda doc_id="": self.doc_dir if doc_id == "doc_x" else ""

        register_dev_routes(app)
        self.app = app
        self.client = app.test_client()

    def tearDown(self) -> None:
        import config

        config.get_doc_dir = self._orig_get_doc_dir
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pdf_missing_returns_404(self):
        res = self.client.get("/api/dev/fnm/book/doc_x/pdf")
        self.assertEqual(res.status_code, 404)

    def test_pdf_serves_full_and_range(self):
        pdf_path = os.path.join(self.doc_dir, "source.pdf")
        payload = b"%PDF-1.4\n" + b"abcdefghij" * 200  # ~2KB
        with open(pdf_path, "wb") as f:
            f.write(payload)

        # 全量
        res = self.client.get("/api/dev/fnm/book/doc_x/pdf")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, payload)
        self.assertEqual(res.headers.get("Content-Type"), "application/pdf")

        # Range
        res = self.client.get(
            "/api/dev/fnm/book/doc_x/pdf", headers={"Range": "bytes=0-9"}
        )
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res.data, payload[:10])

    def test_export_fragment_placeholder(self):
        res = self.client.get(
            "/api/dev/fnm/book/doc_x/export-fragment/ch01"
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["available"])
        self.assertEqual(body["chapter_id"], "ch01")

    def test_export_fragment_reads_dev_export_markdown(self):
        export_dir = os.path.join(self.doc_dir, "dev_exports")
        os.makedirs(export_dir, exist_ok=True)
        with open(os.path.join(export_dir, "ch_intro.md"), "w", encoding="utf-8") as fh:
            fh.write("# hello\n【TEST】body")
        res = self.client.get(
            "/api/dev/fnm/book/doc_x/export-fragment/ch_intro"
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["available"])
        self.assertIn("【TEST】", body["markdown"])


if __name__ == "__main__":
    unittest.main()
