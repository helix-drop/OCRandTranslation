#!/usr/bin/env python3
"""M2.C5 — CLI e2e smoke 脚本，验证 M2 切换后所有 caller path 可用。

用法:
    .venv/bin/python scripts/smoke_post_m2.py --doc-id biopolitics-seed
    .venv/bin/python scripts/smoke_post_m2.py --db-path /tmp/test.db --no-skip-translate

退出码 0 = 所有 step 通过；其它 = 失败 step 名 + 详情
"""

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURE_PATH = REPO_ROOT / "test_example/Biopolitics/raw_pages.json"


def _make_toc_items():
    entries = [
        ("Leçon du 10 janvier 1979", 17),
        ("Leçon du 17 janvier 1979", 43),
        ("Leçon du 24 janvier 1979", 67),
        ("Leçon du 31 janvier 1979", 90),
        ("Leçon du 7 février 1979", 107),
        ("Leçon du 14 février 1979", 130),
        ("Leçon du 21 février 1979", 149),
        ("Leçon du 28 février 1979", 165),
        ("Leçon du 7 mars 1979", 192),
        ("Leçon du 14 mars 1979", 219),
        ("Leçon du 21 mars 1979", 252),
        ("Leçon du 4 avril 1979", 290),
    ]
    return [
        {"item_id": f"toc-{i}", "title": title, "target_pdf_page": page, "role_hint": "chapter"}
        for i, (title, page) in enumerate(entries, start=1)
    ]


def main():
    parser = argparse.ArgumentParser(description="M2 end-to-end smoke test")
    parser.add_argument("--doc-id", default="biopolitics-seed")
    parser.add_argument("--db-path", default=None,
                        help="SQLite DB 路径（默认：临时文件）")
    parser.add_argument("--skip-translate", dest="skip_translate",
                        default=True, action="store_true",
                        help="跳过 run_post_translate_export_checks (default: true)")
    parser.add_argument("--no-skip-translate", dest="skip_translate",
                        action="store_false")
    args = parser.parse_args()

    doc_id = args.doc_id

    # Step 0 — 准备 DB
    if args.db_path:
        db_path = args.db_path
        print(f"  DB: {db_path}")
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        print(f"  DB (temp): {db_path}")

    # Step 1 — 读 fixture + 运行 pipeline
    print(f"\n[1/9] run_pipeline_for_doc …")
    try:
        with open(FIXTURE_PATH) as fh:
            raw = json.load(fh)
        pages = raw["pages"]
        toc_items = _make_toc_items()
        config = {
            "doc_id": doc_id,
            "slug": "biopolitics",
            "pdf_path": "",
            "toc_offset": 0,
            "max_body_chars": 6000,
            "include_diagnostic_entries": False,
            "manual_toc_ready": False,
            "pipeline_state": "done",
            "start_phase": "toc",
        }

        import fnm_re_rs
        result_json = fnm_re_rs.run_pipeline_for_doc_json(
            db_path, doc_id,
            json.dumps(pages), json.dumps(toc_items), json.dumps(config),
        )
        snapshot = json.loads(result_json)
        assert "phase6" in snapshot, f"pipeline snapshot missing phase6, keys={list(snapshot.keys())}"
        print("  ✓ pipeline 完成，phase6 存在")
    except Exception as exc:
        print(f"  ✗ pipeline 失败: {exc}")
        traceback.print_exc()
        sys.exit(1)

    # Step 2 — load_doc_structure → 验证 12 章
    print(f"\n[2/9] load_doc_structure …")
    try:
        from FNM_RE import load_doc_structure
        loaded = load_doc_structure(doc_id=doc_id, db_path=db_path)
        chapters = loaded.get("chapters", [])
        assert len(chapters) == 12, f"expected 12 chapters, got {len(chapters)}"
        for ch in chapters:
            assert "chapter_id" in ch
            assert "title" in ch
            assert "start_page" in ch
            assert "end_page" in ch
        for key in ("pages", "note_regions", "note_items", "body_anchors", "note_links"):
            assert key in loaded, f"missing key: {key}"
        print("  ✓ 12 章存在，字段齐全")
    except Exception as exc:
        print(f"  ✗ load_doc_structure 失败: {exc}")
        traceback.print_exc()
        sys.exit(2)

    # Step 3 — build_export_zip_for_doc
    print(f"\n[3/9] build_export_zip_for_doc …")
    zip_path = None
    try:
        from FNM_RE import build_export_zip_for_doc
        zip_bytes = build_export_zip_for_doc(doc_id=doc_id, db_path=db_path)
        assert isinstance(zip_bytes, bytes), f"expected bytes, got {type(zip_bytes)}"
        assert len(zip_bytes) > 100, f"zip too small: {len(zip_bytes)} bytes"
        zip_path = db_path + ".zip"
        Path(zip_path).write_bytes(zip_bytes)
        print(f"  ✓ ZIP 生成 ({len(zip_bytes)} bytes)")
    except Exception as exc:
        print(f"  ✗ build_export_zip_for_doc 失败: {exc}")
        traceback.print_exc()
        sys.exit(3)

    # Step 4 — audit_export_for_doc
    print(f"\n[4/9] audit_export_for_doc …")
    try:
        from FNM_RE import audit_export_for_doc
        audit = audit_export_for_doc(doc_id=doc_id, db_path=db_path,
                                     slug="biopolitics", zip_path=zip_path)
        can_ship = audit.get("can_ship")
        if can_ship is None:
            can_ship = audit.get("contract_ok") or audit.get("export_audit", {}).get("contract_ok", False)
        assert can_ship, f"can_ship is False: {json.dumps(audit, ensure_ascii=False)[:500]}"
        assert audit.get("applicable", False), "audit not applicable"
        print("  ✓ can_ship=True, applicable=True")
    except Exception as exc:
        print(f"  ✗ audit_export_for_doc 失败: {exc}")
        traceback.print_exc()
        sys.exit(4)

    # Step 5 — build_unit_progress + build_retry_summary
    print(f"\n[5/9] build_unit_progress + build_retry_summary …")
    try:
        from FNM_RE import build_unit_progress, build_retry_summary
        progress = build_unit_progress(doc_id=doc_id, db_path=db_path)
        assert isinstance(progress, dict), f"expected dict, got {type(progress)}"
        assert len(progress.keys()) > 0, "empty progress dict"

        retry = build_retry_summary(doc_id=doc_id, db_path=db_path)
        assert isinstance(retry, dict), f"expected dict, got {type(retry)}"
        print(f"  ✓ progress keys={sorted(progress.keys())[:4]}…, "
              f"retry keys={sorted(retry.keys())[:4]}…")
    except Exception as exc:
        print(f"  ✗ build_unit_progress/retry_summary 失败: {exc}")
        traceback.print_exc()
        sys.exit(5)

    # Step 6 — build_doc_status
    print(f"\n[6/9] build_doc_status …")
    try:
        from FNM_RE import build_doc_status
        status = build_doc_status(doc_id=doc_id, db_path=db_path)
        assert isinstance(status, dict), f"expected dict, got {type(status)}"
        structure_state = status.get("structure_state")
        assert structure_state is not None, "missing structure_state"
        # structure_state 可能的值："" (seed 初始) / "done" / "in_progress" 等
        assert isinstance(structure_state, str), f"expected str, got {type(structure_state)}"
        print(f"  ✓ structure_state={structure_state!r}")
    except Exception as exc:
        print(f"  ✗ build_doc_status 失败: {exc}")
        traceback.print_exc()
        sys.exit(6)

    # Step 7 — (可选) run_post_translate_export_checks_for_doc
    if not args.skip_translate:
        print(f"\n[7/9] run_post_translate_export_checks_for_doc …")
        try:
            from FNM_RE import run_post_translate_export_checks_for_doc
            result = run_post_translate_export_checks_for_doc(
                doc_id=doc_id, db_path=db_path, max_repair_rounds=0,
            )
            ok = result.get("ok", result.get("can_ship", False))
            assert ok, f"post_translate checks failed: {json.dumps(result, ensure_ascii=False)[:500]}"
            print("  ✓ post_translate_export_checks ok=True")
        except Exception as exc:
            print(f"  ✗ run_post_translate_export_checks_for_doc 失败: {exc}")
            traceback.print_exc()
            sys.exit(7)
    else:
        print(f"\n[7/9] 已跳过 (--skip-translate)")

    # Step 8 — run_doc_pipeline_json（DB-driven，含 fnm_run 生命周期）
    print(f"\n[8/9] run_doc_pipeline_json (DB-driven) …")
    try:
        import sqlite3
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        pipe_db = tmp.name
        tmp.close()

        conn = sqlite3.connect(pipe_db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                slug TEXT,
                state TEXT NOT NULL DEFAULT 'idle'
            );
            CREATE TABLE IF NOT EXISTS pages (
                doc_id TEXT NOT NULL,
                book_page INTEGER NOT NULL,
                payload_json TEXT
            );
            CREATE TABLE IF NOT EXISTS fnm_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                status TEXT,
                page_count INTEGER,
                section_count INTEGER,
                note_count INTEGER,
                unit_count INTEGER,
                structure_state TEXT,
                blocking_reasons_json TEXT,
                created_at INTEGER,
                updated_at INTEGER
            );
        """)
        # 加 TOC 列
        for col in ("toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"):
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT '[]'")

        now = 1700000000
        # seed TOC
        conn.execute(
            "INSERT INTO documents (id, slug, toc_user_json) VALUES (?, ?, ?)",
            ("smoke-pipe", "biopolitics", json.dumps(_make_toc_items())),
        )
        # seed pages（前 5 页）
        with open(FIXTURE_PATH) as fh:
            raw = json.load(fh)
        for p in raw["pages"][:5]:
            conn.execute(
                "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, ?, ?)",
                ("smoke-pipe", p.get("bookPage", 0), json.dumps(p)),
            )
        conn.commit()
        conn.close()

        result_json = fnm_re_rs.run_doc_pipeline_json(str(pipe_db), "smoke-pipe", 6000, "toc")
        result = json.loads(result_json)
        assert result.get("ok"), f"run_doc_pipeline_json failed: {result}"
        assert result.get("run_id", 0) > 0, f"no run_id: {result}"
        assert result.get("page_count", 0) >= 5, f"expected >=5 pages: {result}"
        print(f"  ✓ run_doc_pipeline_json OK, run_id={result['run_id']}, "
              f"sections={result['section_count']}, pages={result['page_count']}")
        Path(pipe_db).unlink(missing_ok=True)
    except Exception as exc:
        print(f"  ✗ run_doc_pipeline_json (DB-driven) 失败: {exc}")
        traceback.print_exc()
        sys.exit(8)

    # Step 9 — load_toc_items_for_doc_json（TOC 优先级验证）
    print(f"\n[9/9] load_toc_items_for_doc_json (TOC 优先级) …")
    try:
        import sqlite3
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        toc_db = tmp.name
        tmp.close()

        conn = sqlite3.connect(toc_db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                slug TEXT,
                state TEXT NOT NULL DEFAULT 'idle'
            );
            CREATE TABLE IF NOT EXISTS pages (
                doc_id TEXT NOT NULL,
                book_page INTEGER NOT NULL,
                payload_json TEXT
            );
        """)
        for col in ("toc_user_json", "toc_auto_visual_json", "toc_auto_pdf_json"):
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT DEFAULT '[]'")
        conn.execute(
            "INSERT INTO documents (id, slug, toc_user_json, toc_auto_visual_json, toc_auto_pdf_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("toc-prio", "test",
             json.dumps([{"item_id": "user-1", "title": "User Ch", "level": 1, "depth": 0}]),
             json.dumps([{"item_id": "vis-1", "title": "Vis Ch", "level": 1, "depth": 0}]),
             json.dumps([{"item_id": "pdf-1", "title": "Pdf Ch", "level": 1, "depth": 0}])),
        )
        conn.execute(
            "INSERT INTO pages (doc_id, book_page, payload_json) VALUES (?, 1, '{}')",
            ("toc-prio",),
        )
        conn.commit()
        conn.close()

        toc_json = fnm_re_rs.load_toc_items_for_doc_json(str(toc_db), "toc-prio")
        items = json.loads(toc_json)
        assert len(items) == 1, f"expected 1 item, got {len(items)}"
        assert items[0]["item_id"] == "user-1", f"expected user-1 priority, got {items[0]}"
        print(f"  ✓ TOC priority correct: user over visual/pdf, item={items[0]['item_id']}")
        Path(toc_db).unlink(missing_ok=True)
    except Exception as exc:
        print(f"  ✗ load_toc_items_for_doc_json (TOC 优先级) 失败: {exc}")
        traceback.print_exc()
        sys.exit(9)

    # 清理
    if not args.db_path:
        Path(db_path).unlink(missing_ok=True)
    if zip_path:
        Path(zip_path).unlink(missing_ok=True)

    print("\n✓ 所有 step 通过。退出码 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
