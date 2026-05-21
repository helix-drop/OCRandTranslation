#!/usr/bin/env python3
"""生成 Rust parity 测试用的 fixture JSON 文件。

用法:
    python tools/gen_parity_fixtures.py

对每个公开函数，用 Python 端输出生成 (input, expected) 对，
写入 fnm_re_rs/fnm-core/tests/fixtures/ 目录。
"""

import json
from pathlib import Path

FIXTURES_DIR = Path("fnm_re_rs/fnm-core/tests/fixtures")


def ensure_dir() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


# ── T2: types 验证 ──────────────────────────────────────────────


def gen_types_validity_cases() -> None:
    """生成所有 is_valid_* 函数的测试 case。"""
    from FNM_RE.constants import (
        is_valid_page_role,
        is_valid_chapter_source,
        is_valid_boundary_state,
        is_valid_note_kind,
        is_valid_region_scope,
        is_valid_region_source,
        is_valid_note_mode,
        is_valid_anchor_kind,
        is_valid_link_status,
        is_valid_link_resolver,
        is_valid_pipeline_state,
    )

    funcs = [
        ("is_valid_page_role", is_valid_page_role),
        ("is_valid_chapter_source", is_valid_chapter_source),
        ("is_valid_boundary_state", is_valid_boundary_state),
        ("is_valid_note_kind", is_valid_note_kind),
        ("is_valid_region_scope", is_valid_region_scope),
        ("is_valid_region_source", is_valid_region_source),
        ("is_valid_note_mode", is_valid_note_mode),
        ("is_valid_anchor_kind", is_valid_anchor_kind),
        ("is_valid_link_status", is_valid_link_status),
        ("is_valid_link_resolver", is_valid_link_resolver),
        ("is_valid_pipeline_state", is_valid_pipeline_state),
    ]

    all_cases: dict[str, list[dict]] = {}
    for name, fn in funcs:
        cases: list[dict] = []
        for raw in [
            "", " ", "noise", "  body  ", "unknown_blah", "footnote", "endnote",
            "matched", "orphan_note", "visual_toc", "fallback", "ready",
            "review_required", "heading_scan", "chapter", "book",
            "footnote_band", "continuation_merge", "manual_rebind",
            "explorer_toc_match", "explorer_signal_match", "fallback_nearest_prior",
            "footnote_primary", "chapter_endnote_primary", "book_endnote_bound",
            "no_notes", "idle", "running", "error", "done",
            "rule", "fallback", "repair", "note", "other",
        ]:
            cases.append({"input": raw, "expected": fn(raw)})
        all_cases[name] = cases

    ensure_dir()
    (FIXTURES_DIR / "types_validity_cases.json").write_text(
        json.dumps(all_cases, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ types_validity_cases.json ({sum(len(v) for v in all_cases.values())} cases)")


# ── T4: note_marker ─────────────────────────────────────────────


def gen_normalize_note_marker_cases() -> None:
    from FNM_RE.shared.notes import normalize_note_marker

    cases: list[dict] = []
    for raw in [
        "12", " 1 2 ", "12a", "<sup>5</sup>", "", "abc", "1.", "[3]",
        " ⁵ ", "¹²", "²³⁴⁵", "*", "**", "†", "‡‡", "§", "¶",
        "1.2", "100", "0", "01", "a", "Z", "12345",
        "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹", "⁰",
        " 1 ", "\t2\n", "[12]", "12;", "12:", "12,", "12)", "12.",
    ]:
        cases.append({"input": raw, "expected": normalize_note_marker(raw)})

    ensure_dir()
    (FIXTURES_DIR / "normalize_note_marker_cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2)
    )
    print(f"  ✓ normalize_note_marker_cases.json ({len(cases)} cases)")


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("生成 parity fixtures …")
    gen_types_validity_cases()
    gen_normalize_note_marker_cases()
    print("完成。")
