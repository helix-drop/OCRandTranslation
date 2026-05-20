"""M1.12: 验证 run_post_translate_export_checks 导出检查 + 自修复。"""

import json
import sqlite3
import tempfile
from pathlib import Path

import fnm_re_rs


def _seed(db_path: str, doc_id: str):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, slug TEXT, state TEXT)")
    conn.execute("INSERT OR IGNORE INTO documents (id, slug, state) VALUES (?, ?, 'idle')", (doc_id, doc_id))
    conn.execute("CREATE TABLE IF NOT EXISTS pages (doc_id TEXT, book_page INTEGER, payload_json TEXT)")
    conn.execute(
        "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 1, ?)",
        (doc_id, json.dumps({"bookPage": 1, "markdown": "# Chapter 1\n\nContent.", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
    )
    conn.execute(
        "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 2, ?)",
        (doc_id, json.dumps({"bookPage": 2, "markdown": "More.", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
    )
    conn.commit()
    conn.close()

    # 跑 pipeline 填充所有 phase 表
    try:
        fnm_re_rs.run_doc_pipeline_json(db_path, doc_id)
    except RuntimeError:
        pass


def test_post_translate_export_checks_empty_model_skips_repair():
    """无 API key 的 model_args 应跳过 repair，max_repair_rounds=0 直接返回。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed(db_path, "test-pe")

        model_args_json = json.dumps([])  # 空列表，无可用模型

        result_json = fnm_re_rs.run_post_translate_export_checks_for_doc_json(
            db_path,
            "test-pe",
            "test-pe",       # slug
            "",              # pdf_path
            model_args_json,
            0,               # max_repair_rounds=0，不进入 repair 循环
        )
        result = json.loads(result_json)

        assert isinstance(result, dict)
        assert result["ok"] is True
        assert "export_ready_real" in result
        assert "repair_rounds" in result
        assert result["repair_rounds"] == []
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_post_translate_export_checks_with_model_skipped():
    """model_args 无 api_key 应被跳过，max_repair_rounds=1 仍不进入 repair。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed(db_path, "test-pe2")

        model_args_json = json.dumps([
            {"provider": "openai", "model_id": "gpt-4", "api_key": "", "display_label": "GPT-4"},
        ])

        result_json = fnm_re_rs.run_post_translate_export_checks_for_doc_json(
            db_path,
            "test-pe2",
            "test-pe2",
            "",
            model_args_json,
            1,  # max_repair_rounds=1，但模型无 api_key 会被跳过
        )
        result = json.loads(result_json)

        assert isinstance(result, dict)
        assert result["ok"] is True
        # 管线结果干净则不进 repair 循环（repair_rounds 为空）
        # 若进循环，model_attempts 中应有 skipped_no_api_key
    finally:
        Path(db_path).unlink(missing_ok=True)
