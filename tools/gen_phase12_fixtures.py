#!/usr/bin/env python3
"""生成 fnm-phase1 / fnm-phase2 parity fixture 的 expected output。

从 test_example/Biopolitics 的 raw_pages.json 和 module snapshots 提取
Phase1 / Phase2 的期望输出，写入 fnm_re_rs/fnm-phase1/tests/fixtures/ 和
fnm_re_rs/fnm-phase2/tests/fixtures/。

用法:
    PYTHONPATH=. python tools/gen_phase12_fixtures.py
"""

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BIOPOLITICS_DIR = REPO_ROOT / "test_example" / "Biopolitics"
P1_FIXTURES = REPO_ROOT / "fnm_re_rs" / "fnm-phase1" / "tests" / "fixtures"
P2_FIXTURES = REPO_ROOT / "fnm_re_rs" / "fnm-phase2" / "tests" / "fixtures"


def ensure_dirs() -> None:
    P1_FIXTURES.mkdir(parents=True, exist_ok=True)
    P2_FIXTURES.mkdir(parents=True, exist_ok=True)


def load_raw_pages() -> list[dict]:
    path = BIOPOLITICS_DIR / "raw_pages.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — Biopolitics fixture missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("pages", [])
    return data


def load_module_snapshot() -> dict:
    path = BIOPOLITICS_DIR / "fnm_real_test_modules.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def gen_basic_fixtures() -> None:
    """生成基础的 Biopolitics pages fixture（用于 deserialization 测试）。"""
    pages = load_raw_pages()
    # 写前 5 页作为轻量 fixture
    light_pages = pages[:5]
    for p in light_pages:
        p.pop("prunedResult", None)
        p.pop("fnBlocks", None)
    (P1_FIXTURES / "biopolitics_pages_sample.json").write_text(
        json.dumps(light_pages, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ biopolitics_pages_sample.json ({len(light_pages)} pages)")


def gen_phase1_expected_from_snapshot() -> None:
    """从 module snapshot 提取 Phase1 期望数据。"""
    snapshot = load_module_snapshot()
    if not snapshot:
        print("  ⚠️  No module snapshot — skipping Phase 1 expected")
        return

    # 提取 page_partition 结果（从 boundary_detection 中）
    boundary = snapshot.get("boundary_detection", {})
    page_role_samples = boundary.get("page_role_samples", [])

    # 提取 note region summary（Phase 1 产出给 Phase 2 的接口数据）
    note_region = snapshot.get("note_region_detection", {})
    region_rows = note_region.get("region_rows", [])

    expected_p1 = {
        "description": "Phase 1 expected output extracted from module snapshot (boundary_detection)",
        "total_pages": len(load_raw_pages()),
        "page_role_samples": page_role_samples[:20],
        "first_body_page": boundary.get("first_body_page"),
        "first_note_page": boundary.get("first_note_page"),
        "region_count": len(region_rows),
    }
    (P1_FIXTURES / "biopolitics_phase1_expected.json").write_text(
        json.dumps(expected_p1, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ biopolitics_phase1_expected.json")
    print(f"    - page_role_samples: {len(page_role_samples[:20])}")
    print(f"    - region_count: {len(region_rows)}")


def gen_phase2_expected_from_snapshot() -> None:
    """从 module snapshot 提取 Phase 2 期望数据。"""
    snapshot = load_module_snapshot()
    if not snapshot:
        print("  ⚠️  No module snapshot — skipping Phase 2 expected")
        return

    endnote_array = snapshot.get("endnote_array_building", {})
    array_rows = endnote_array.get("array_rows", [])
    note_capture = endnote_array.get("note_capture_summary", {})

    anchor_res = snapshot.get("anchor_resolution", {})
    link_summary = anchor_res.get("link_summary", {})
    anchor_kind_counts = anchor_res.get("anchor_kind_counts", {})

    expected_p2 = {
        "description": "Phase 2 expected output extracted from module snapshot",
        "endnote_array_rows_count": len(array_rows),
        "endnote_array_sample": array_rows[:5] if array_rows else [],
        "note_capture_summary": note_capture,
        "link_summary": link_summary,
        "anchor_kind_counts": anchor_kind_counts,
    }
    (P2_FIXTURES / "biopolitics_phase2_expected.json").write_text(
        json.dumps(expected_p2, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ biopolitics_phase2_expected.json")
    print(f"    - endnote_array_rows: {len(array_rows)}")
    print(f"    - link_summary: {link_summary}")


def gen_marker_fixtures() -> None:
    """生成 marker 相关的测试 fixture。"""
    # OCR split marker 测试用例
    ocr_split_cases = [
        {"input": "1 2", "expected": {"marker": "12", "is_reconstructed": True}},
        {"input": " 1 , 2 ", "expected": {"marker": "12", "is_reconstructed": True}},
        {"input": "1.2", "expected": {"marker": "12", "is_reconstructed": True}},
    ]
    (P2_FIXTURES / "ocr_split_marker_cases.json").write_text(
        json.dumps(ocr_split_cases, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ ocr_split_marker_cases.json ({len(ocr_split_cases)} cases)")

    # 引文缩写截断测试用例
    citation_cases = [
        {"note": "See vol.", "truncated": True},
        {"note": "Complete sentence.", "truncated": False},
        {"note": "Reference, cf.", "truncated": True},
    ]
    (P2_FIXTURES / "citation_truncation_cases.json").write_text(
        json.dumps(citation_cases, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ citation_truncation_cases.json ({len(citation_cases)} cases)")

    # sup_recovery layer2 测试用例
    layer2_cases = [
        {"text": "1927-30 * ou", "expected_marker": "30", "reason": "symbol_after_year"},
        {"text": "text ; 11 ; more", "expected_marker": "11", "reason": "punctuation_surrogate"},
        {"text": "7. some note", "expected_marker": "37", "reason": "ocr_suffix"},
    ]
    (P2_FIXTURES / "sup_recovery_layer2_cases.json").write_text(
        json.dumps(layer2_cases, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ sup_recovery_layer2_cases.json ({len(layer2_cases)} cases)")


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("生成 Biopolitics parity fixtures …")
    ensure_dirs()

    gen_basic_fixtures()
    gen_phase1_expected_from_snapshot()
    gen_phase2_expected_from_snapshot()
    gen_marker_fixtures()

    print("\n完成。Rust 端 cargo test 将读取这些 fixture JSON 进行 parity 比对。")
