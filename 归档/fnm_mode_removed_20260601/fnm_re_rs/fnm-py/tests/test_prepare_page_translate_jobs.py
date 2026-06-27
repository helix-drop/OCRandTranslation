"""M1.11c: 验证 prepare_page_translate_jobs 构建翻译任务。"""

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
        (doc_id, json.dumps({"bookPage": 1, "markdown": "# Chapter 1\n\nParagraph one.\n\nParagraph two.", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
    )
    conn.execute(
        "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 2, ?)",
        (doc_id, json.dumps({"bookPage": 2, "markdown": "Page two content.", "footnotes": "", "fnBlocks": [], "prunedResult": {}})),
    )
    conn.commit()
    conn.close()

    # 跑 pipeline 填充 fnm_translation_units 等表
    try:
        fnm_re_rs.run_doc_pipeline_json(db_path, doc_id)
    except RuntimeError:
        pass


def test_prepare_page_translate_jobs_empty_units():
    """无 translation units 时应报 RuntimeError '未找到有效内容'。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed(db_path, "test-pt")

        pages_json = json.dumps([
            {"bookPage": 1, "markdown": "# Test\n\nContent", "footnotes": "", "fnBlocks": [], "prunedResult": {}},
        ])
        t_args_json = json.dumps({"model": "test"})

        # 无 units → 应报错
        try:
            fnm_re_rs.prepare_page_translate_jobs_json(pages_json, 1, t_args_json, "test-pt", db_path)
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "未找到有效内容" in str(e)
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_prepare_page_translate_jobs_with_units():
    """含 translation units 时应返回 [ctx, jobs, meta] JSON 数组。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        _seed(db_path, "test-pt2")

        # 手动插入一个 body unit（含 page 1 的 frozen 文本）
        seg_json = json.dumps([{
            "page_no": 1,
            "paragraph_count": 1,
            "source_text": "Frozen paragraph one.\n\nFrozen paragraph two.",
            "display_text": "Frozen paragraph one.\n\nFrozen paragraph two.",
            "paragraphs": [],
        }])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO fnm_translation_units (unit_id, doc_id, kind, owner_kind, owner_id, section_id, section_title, section_start_page, section_end_page, note_id, page_start, page_end, char_count, source_text, translated_text, status, error_msg, target_ref, page_segments_json, source_hash, created_at, updated_at) VALUES (?, ?, 'body', '', '', 's1', 'Section 1', 1, 10, '', 1, 10, 0, '', '', 'done', '', '', ?, '', 1000000, 1000001)",
            ("u1", "test-pt2", seg_json),
        )
        conn.commit()
        conn.close()

        pages_json = json.dumps([
            {"bookPage": 1, "markdown": "# Test\n\nContent line 1.\n\nContent line 2.", "footnotes": "", "fnBlocks": [], "prunedResult": {}},
        ])
        t_args_json = json.dumps({"model": "test"})

        result_json = fnm_re_rs.prepare_page_translate_jobs_json(pages_json, 1, t_args_json, "test-pt2", db_path)
        result = json.loads(result_json)

        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) == 3, f"Expected [ctx, jobs, meta], got {len(result)} items"
        ctx, jobs, meta = result
        assert isinstance(ctx, dict)
        assert isinstance(jobs, list)
        assert isinstance(meta, dict)
        assert len(jobs) >= 1
        # 第一个 job 应是 body
        assert jobs[0]["content_role"] == "body"
    finally:
        Path(db_path).unlink(missing_ok=True)
