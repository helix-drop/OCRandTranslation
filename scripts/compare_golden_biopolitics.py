#!/usr/bin/env python3
"""Biopolitics 金版对比脚本。"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from fnm_golden_freshness import assert_export_is_fresh
from golden_paragraph_diff import compare_chapter_paragraphs, format_paragraph_diff_report

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "test_example" / "Biopolitics"
GOLDEN_DIR = EXAMPLE_DIR / "golden_exports" / "real_golden_template"


def load_export_chapters(zip_path: Path) -> dict[str, str]:
    chapters: dict[str, str] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith("chapters/") and name.endswith(".md"):
                key = Path(name).stem
                chapters[key] = zf.read(name).decode("utf-8")
    return chapters


def load_golden_chapters() -> dict[str, str]:
    chapters: dict[str, str] = {}
    for path in sorted(GOLDEN_DIR.glob("*.md")):
        if path.name == "PROCESSING_NOTES.md":
            continue
        text = path.read_text(encoding="utf-8")
        match = re.match(r"(\d{3})-(.+)", path.stem)
        if match:
            key = f"{match.group(1)}-{match.group(2)}"
        else:
            key = path.stem
        chapters[key] = text
    return chapters


def match_export_to_golden(
    exported: dict[str, str], golden: dict[str, str]
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    golden_keys = list(golden.keys())

    def _first_words(text: str, n: int = 8) -> str:
        m = re.search(r"^##\s+(.+)$", text, re.MULTILINE)
        if not m:
            return ""
        return " ".join(m.group(1).split()[:n]).lower()

    for exp_key, exp_text in sorted(exported.items()):
        exp_title = _first_words(exp_text)
        best_score = 0.0
        best_gk = ""
        for gk in golden_keys:
            g_text = golden[gk]
            g_title = _first_words(g_text)
            score = SequenceMatcher(None, exp_title, g_title).ratio()
            if score > best_score:
                best_score = score
                best_gk = gk
        if best_score >= 0.6:
            pairs.append((exp_key, best_gk))
            golden_keys.remove(best_gk)
        else:
            pairs.append((exp_key, ""))
    return pairs


def split_body_and_notes(text: str) -> tuple[str, str]:
    match = re.search(r"^#{2,6}\s+NOTES\s*$", text, re.MULTILINE)
    if not match:
        return text, ""
    return text[: match.start()], text[match.start():]


def count_endnote_refs(text: str) -> tuple[list[int], list[int]]:
    body, _notes = split_body_and_notes(text)
    refs = [int(m.group(1)) for m in re.finditer(r"\[\^(\d{1,4})\](?!\s*[:;])", body)]
    defs = [int(m.group(1)) for m in re.finditer(r"^\[\^(\d{1,4})\]:", text, re.MULTILINE)]
    return sorted(refs), sorted(defs)


def count_note_section_refs(text: str) -> list[int]:
    _body, notes = split_body_and_notes(text)
    return [int(m.group(1)) for m in re.finditer(r"\[\^(\d{1,4})\](?!\s*[:;])", notes)]


def count_superscripts(text: str) -> list[str]:
    return re.findall(r"\^{\d+}", text)


def count_html_tags(text: str) -> list[str]:
    return re.findall(r"<[^>]+>", text)


def count_note_ref_leaks(text: str) -> dict[str, int]:
    return {
        "NOTE_REF": len(re.findall(r"\{\{NOTE_REF:", text)),
        "FN_REF": len(re.findall(r"\{\{FN_REF:", text)),
        "EN_REF": len(re.findall(r"\{\{EN_REF:", text)),
    }


def normalize_body_for_similarity(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[\^\d+\]", " ", text)
    text = re.sub(r"\{\{NOTE_REF:[^}]+\}\}", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    trans_map = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
    }
    text = text.translate(str.maketrans(trans_map))
    text = re.sub(r"[^\w\s#'-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


def compare_chapter(exp_name: str, exp_text: str, gld_text: str) -> dict:
    exp_refs, exp_defs = count_endnote_refs(exp_text)
    gld_refs, gld_defs = count_endnote_refs(gld_text)
    exp_note_refs = count_note_section_refs(exp_text)
    exp_sups = count_superscripts(exp_text)
    gld_sups = count_superscripts(gld_text)
    exp_html = count_html_tags(exp_text)
    exp_leaks = count_note_ref_leaks(exp_text)
    exp_body, _ = split_body_and_notes(exp_text)
    gld_body, _ = split_body_and_notes(gld_text)
    exp_body_clean = normalize_body_for_similarity(exp_body)
    gld_body_clean = normalize_body_for_similarity(gld_body)
    body_similarity = SequenceMatcher(None, exp_body_clean, gld_body_clean).ratio()
    issues = []
    exp_ref_counts = Counter(exp_refs)
    gld_ref_counts = Counter(gld_refs)
    if exp_ref_counts != gld_ref_counts:
        missing_refs = sorted((gld_ref_counts - exp_ref_counts).elements())
        extra_refs = sorted((exp_ref_counts - gld_ref_counts).elements())
        if missing_refs:
            issues.append("缺失正文引用 [^n]: {}".format(missing_refs[:15]))
        if extra_refs:
            issues.append("多余正文引用 [^n]: {}".format(extra_refs[:15]))
        issues.append("正文引用计数不一致: 导出 {} vs golden {}".format(len(exp_refs), len(gld_refs)))
    exp_def_counts = Counter(exp_defs)
    gld_def_counts = Counter(gld_defs)
    if exp_def_counts != gld_def_counts:
        missing_defs = sorted((gld_def_counts - exp_def_counts).elements())
        extra_defs = sorted((exp_def_counts - gld_def_counts).elements())
        if missing_defs:
            issues.append("缺失尾注定义 [^n]: {}".format(missing_defs[:15]))
        if extra_defs:
            issues.append("多余尾注定义 [^n]: {}".format(extra_defs[:15]))
    if exp_sups:
        issues.append("上标残留: {} 处".format(len(exp_sups)))
    if exp_html:
        issues.append("HTML 标签残留: {} 处".format(len(exp_html)))
    leaks_found = {k: v for k, v in exp_leaks.items() if v > 0}
    if leaks_found:
        issues.append("Marker 泄漏: {}".format(leaks_found))
    refs_ok = exp_ref_counts == gld_ref_counts
    defs_ok = exp_def_counts == gld_def_counts
    clean = not exp_sups and not exp_html and not any(exp_leaks.values())
    return {
        "export_name": exp_name,
        "body_similarity": round(body_similarity, 4),
        "export_refs": len(exp_refs),
        "golden_refs": len(gld_refs),
        "export_defs": len(exp_defs),
        "golden_defs": len(gld_defs),
        "ignored_note_section_refs": len(exp_note_refs),
        "refs_ok": refs_ok,
        "defs_ok": defs_ok,
        "clean": clean,
        "issues": issues,
    }


def main() -> int:
    zip_path = EXAMPLE_DIR / "latest.fnm.obsidian.Biopolitics.blocked.test.zip"
    if not zip_path.is_file():
        print("ZIP 不存在: {}".format(zip_path))
        return 1
    if not assert_export_is_fresh(EXAMPLE_DIR, zip_path):
        return 1

    exported = load_export_chapters(zip_path)
    golden = load_golden_chapters()
    pairs = match_export_to_golden(exported, golden)

    print("# Biopolitics FNM 导出 vs Golden Template 逐章对比")
    print()

    total_issues = 0
    all_ok = 0
    results = []

    for exp_key, gld_key in pairs:
        exp_text = exported[exp_key]
        gld_text = golden.get(gld_key, "") if gld_key else ""
        result = compare_chapter(exp_key, exp_text, gld_text)
        results.append(result)
        status = "✓" if not result["issues"] else "✗"
        if not result["issues"]:
            all_ok += 1
        total_issues += len(result["issues"])
        short_name = exp_key[:60]
        print("## {} {}".format(status, short_name))
        print("- 相似度: {:.1%}".format(result["body_similarity"]))
        print("- 正文引用: 导出 {} vs golden {} {}".format(
            result["export_refs"], result["golden_refs"],
            "✓" if result["refs_ok"] else "✗"))
        print("- 尾注定义: 导出 {} vs golden {} {}".format(
            result["export_defs"], result["golden_defs"],
            "✓" if result["defs_ok"] else "✗"))
        print("- 清洁度: {}".format("✓" if result["clean"] else "✗"))
        for issue in result["issues"]:
            print("- **问题**: {}".format(issue))
        print()

    # ── 段对段对比 ──────────────────────────────────────────
    para_results: list[dict[str, Any]] = []
    total_missing_paras = 0
    total_added_paras = 0
    total_low_sim_paras = 0
    para_report_lines: list[str] = [
        "# Biopolitics 段对段金版对比报告",
        "",
    ]

    for exp_key, gld_key in pairs:
        exp_text = exported[exp_key]
        gld_text = golden.get(gld_key, "") if gld_key else ""
        if not gld_text:
            continue
        para_diff = compare_chapter_paragraphs(exp_text, gld_text)
        para_diff["export_name"] = exp_key
        para_diff["golden_name"] = gld_key
        para_results.append(para_diff)
        total_missing_paras += para_diff["missing_count"]
        total_added_paras += para_diff["added_count"]
        total_low_sim_paras += para_diff["low_similarity_count"]
        para_report_lines.append(
            format_paragraph_diff_report(exp_key[:60], para_diff)
        )

    para_report_lines.append("## 段对比汇总")
    para_report_lines.append("")
    para_report_lines.append("- 总缺失段落: {}".format(total_missing_paras))
    para_report_lines.append("- 总新增段落: {}".format(total_added_paras))
    para_report_lines.append("- 总低相似度段落: {}".format(total_low_sim_paras))
    para_report_lines.append("")

    total_export_refs = sum(r["export_refs"] for r in results)
    total_golden_refs = sum(r["golden_refs"] for r in results)
    total_export_defs = sum(r["export_defs"] for r in results)
    total_golden_defs = sum(r["golden_defs"] for r in results)

    print("## 汇总")
    print("- {}/{} 章通过".format(all_ok, len(results)))
    print("- {} 个问题".format(total_issues))
    print("- 正文引用: 导出 {} vs golden {} ({:+d})".format(
        total_export_refs, total_golden_refs,
        total_export_refs - total_golden_refs))
    print("- 尾注定义: 导出 {} vs golden {} ({:+d})".format(
        total_export_defs, total_golden_defs,
        total_export_defs - total_golden_defs))
    print("- 段对比: {} 缺失, {} 新增, {} 低相似度".format(
        total_missing_paras, total_added_paras, total_low_sim_paras))

    out_path = EXAMPLE_DIR / "golden_comparison.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("\n详细 JSON: {}".format(out_path))

    para_out_path = EXAMPLE_DIR / "golden_paragraph_diff.json"
    para_out_path.write_text(json.dumps(para_results, ensure_ascii=False, indent=2))
    print("段对比 JSON: {}".format(para_out_path))

    para_report_path = EXAMPLE_DIR / "golden_paragraph_diff.md"
    para_report_path.write_text("\n".join(para_report_lines), encoding="utf-8")
    print("段对比报告: {}".format(para_report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
