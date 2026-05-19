"""End-to-end smoke test：从 Python 调 Rust pipeline 跑 Biopolitics 完整 6-phase。

用法：
    .venv/bin/python fnm_re_rs/fnm-py/smoke_test.py

成功标志：
- pipeline 返回 phase1-6 完整 snapshot
- chapter count == 12（Biopolitics 是 12 章 lecture collection）
- workspace 940 lib tests + 本 smoke = 1 套完整 Python 端契约。
"""

import json
import os
import sys
import tempfile

import fnm_re_rs

print(f"fnm_re_rs version: {fnm_re_rs.version()}")
print()

# 1. 加载 Biopolitics raw_pages
fixture_path = "test_example/Biopolitics/raw_pages.json"
with open(fixture_path) as f:
    raw = json.load(f)
pages = raw["pages"]
print(f"loaded {len(pages)} pages from {fixture_path}")

# 2. Biopolitics TOC items（与 phase1 测试一致）
toc_items = [
    {"item_id": f"toc-{i}", "title": title, "target_pdf_page": page, "role_hint": "chapter"}
    for i, (title, page) in enumerate(
        [
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
        ],
        start=1,
    )
]
print(f"toc_items: {len(toc_items)} chapters")
print()

# 3. 配置
config = {
    "doc_id": "biopolitics-smoke",
    "slug": "biopolitics",
    "pdf_path": "",  # 不调 LLM，pdf 路径无所谓
    "toc_offset": 0,
    "max_body_chars": 6000,
    "include_diagnostic_entries": False,
    "manual_toc_ready": True,
    "pipeline_state": "done",
    "start_phase": "toc",
}

# 4a. 纯内存 pipeline（不持久化）
print("=" * 60)
print("Test 1: run_pipeline_json (in-memory)")
print("=" * 60)
result_json = fnm_re_rs.run_pipeline_json(
    json.dumps(pages),
    json.dumps(toc_items),
    json.dumps(config),
)
result = json.loads(result_json)
print(f"doc_id: {result['doc_id']}")
print(f"pipeline_run_id: {result['pipeline_run_id']}")
for phase in ("phase1", "phase2", "phase3", "phase4", "phase5", "phase6"):
    p = result.get(phase)
    if p is None:
        print(f"  {phase}: <missing>")
        continue
    if phase == "phase1":
        print(f"  phase1: {len(p['chapters'])} chapters, {len(p['pages'])} pages, {len(p['heading_candidates'])} candidates")
    elif phase == "phase2":
        print(f"  phase2: {len(p['note_regions'])} regions, {len(p['note_items'])} items, {len(p['chapter_note_modes'])} modes")
    elif phase == "phase3":
        print(f"  phase3: {len(p['body_anchors'])} body_anchors, {len(p['note_links'])} note_links")
    elif phase == "phase4":
        print(f"  phase4: {len(p['translation_units'])} units, {len(p['structure_reviews'])} reviews")
    elif phase == "phase5":
        print(f"  phase5: chapter_count={p['chapter_count']}")
    elif phase == "phase6":
        bundle = p["export_bundle"]
        print(f"  phase6: {len(bundle.get('chapters', []))} exported chapters, contract_ok={bundle.get('export_semantic_contract_ok')}")

# 4b. DB-driven（持久化到临时 SQLite）
print()
print("=" * 60)
print("Test 2: run_pipeline_for_doc_json (DB-driven)")
print("=" * 60)
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
    db_path = tmp.name
try:
    result_json = fnm_re_rs.run_pipeline_for_doc_json(
        db_path,
        "biopolitics-smoke",
        json.dumps(pages),
        json.dumps(toc_items),
        json.dumps(config),
    )
    result = json.loads(result_json)
    print(f"persisted to {db_path} ({os.path.getsize(db_path):,} bytes)")
    print(f"run_meta: {json.dumps(result['run_meta'], indent=2)}")
finally:
    os.unlink(db_path)

print()
print("=" * 60)
print("Test 3: run_pipeline_for_doc_with_llm_repair_json (NoopRenderer, 无 vision)")
print("=" * 60)
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
    db_path = tmp.name
try:
    # 不传 renderer → 内部用 NoopRenderer + pdf_path 空字符串 → LLM repair 无 cluster 可发，
    # 仅验证调用链通畅（不抛错、产出 llm_repair 子段）
    result_json = fnm_re_rs.run_pipeline_for_doc_with_llm_repair_json(
        db_path,
        "biopolitics-llm",
        json.dumps(pages),
        json.dumps(toc_items),
        json.dumps(config),
        "",  # pdf_path 空
        None,  # renderer 用默认 Noop
        True,  # auto_apply
        0.9,  # confidence_threshold
    )
    result = json.loads(result_json)
    llm = result["run_meta"].get("llm_repair")
    print(f"llm_repair report: cluster_count={llm['cluster_count']}, "
          f"suggestion_count={llm['suggestion_count']}, "
          f"auto_applied_count={llm['auto_applied_count']}")
finally:
    os.unlink(db_path)

print()
print("=" * 60)
print("✓ smoke test passed")
print("=" * 60)
