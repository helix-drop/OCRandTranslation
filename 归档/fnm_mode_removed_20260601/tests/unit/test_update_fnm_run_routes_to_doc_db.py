"""回归：`update_fnm_run` 在拆库场景下必须能按 doc_id 路由到对应文档库。

历史实现依赖 `_DOC_CONTEXT_METHODS` 从 app_state 的 `current_doc_id` 取上下文；
批处理脚本不会写这个 app_state，结果 UPDATE 落到 catalog 库、命中 0 行，
`fnm_runs.status` 永远停在 'running'。根治做法：把 `doc_id` 变成正式参数，
让 dispatcher 通过方法签名自动路由。
"""

from __future__ import annotations

import unittest

from persistence.sqlite_store import SQLiteRepository


class UpdateFnmRunDocRoutingTest(unittest.TestCase):
    def test_update_persists_without_setting_current_doc_id(self):
        doc_id = "test-doc-update-fnm-run-routing"
        repo = SQLiteRepository()
        repo.upsert_document(doc_id, "UpdateFnmRunRoutingTest")
        # 确认 app_state 里没有设置该 doc（批处理脚本的真实场景）
        repo.set_app_state("current_doc_id", "")
        rid = repo.create_fnm_run(doc_id, status="running")
        self.addCleanup(repo.delete_document, doc_id)

        repo.update_fnm_run(doc_id, rid, status="done", error_msg="")

        latest = repo.get_latest_fnm_run(doc_id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.get("id"), rid)
        self.assertEqual(
            latest.get("status"),
            "done",
            "UPDATE 未落到正确的 doc 库；app_state 未设置 current_doc_id 时必须也能成功",
        )


class UpdateFnmTranslationUnitDocRoutingTest(unittest.TestCase):
    def test_update_persists_without_setting_current_doc_id(self):
        doc_id = "test-doc-update-fnm-unit-routing"
        unit_id = "unit-routing-001"
        repo = SQLiteRepository()
        repo.upsert_document(doc_id, "UpdateFnmTranslationUnitRoutingTest")
        repo.set_app_state("current_doc_id", "")
        self.addCleanup(repo.delete_document, doc_id)
        repo.replace_fnm_data(
            doc_id,
            notes=[],
            units=[
                {
                    "unit_id": unit_id,
                    "kind": "body",
                    "owner_kind": "chapter",
                    "owner_id": "ch-1",
                    "section_id": "ch-1",
                    "section_title": "Chapter",
                    "section_start_page": 1,
                    "section_end_page": 1,
                    "page_start": 1,
                    "page_end": 1,
                    "char_count": 10,
                    "source_text": "hello",
                    "translated_text": "",
                    "status": "pending",
                    "page_segments": [],
                },
            ],
        )

        repo.update_fnm_translation_unit(
            doc_id, unit_id, status="done", translated_text="bye"
        )

        units = repo.list_fnm_translation_units(doc_id)
        self.assertTrue(units)
        self.assertEqual(units[0].get("status"), "done")
        self.assertEqual(units[0].get("translated_text"), "bye")


if __name__ == "__main__":
    unittest.main()
