#!/usr/bin/env python3
"""逐章对比 FNM 导出与 golden template。"""
from __future__ import annotations

import json, re, sys, zipfile
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "test_example" / "post-revolutionary"
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
        # 从 golden 文件名匹配章节编号
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
    """按章节标题相似度匹配。"""
    pairs: list[tuple[str, str]] = []
    golden_keys = list(golden.keys())

    def _first_words(text: str, n: int = 8) -> str:
        # 取 ## 标题后的前 n 个词
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


def count_endnote_refs(text: str) -> tuple[list[int], list[int]]:
    """统计 [^n] refs 和 defs。"""
    refs = [int(m.group(1)) for m in re.finditer(r"\[\^(\d{1,4})\](?!\s*[:;])", text)]
    defs = [int(m.group(1)) for m in re.finditer(r"^\[\^(\d{1,4})\]:", text, re.MULTILINE)]
    return sorted(refs), sorted(defs)


def count_superscripts(text: str) -> list[str]:
    """统计残留 ^{n} 上标。"""
    return re.findall(r"\^{\d+}", text)


def count_html_tags(text: str) -> list[str]:
    return re.findall(r"<[^>]+>", text)


def count_note_ref_leaks(text: str) -> dict[str, int]:
    return {
        "NOTE_REF": len(re.findall(r"\{\{NOTE_REF:", text)),
        "FN_REF": len(re.findall(r"\{\{FN_REF:", text)),
        "EN_REF": len(re.findall(r"\{\{EN_REF:", text)),
    }


def check_heading_structure(text: str) -> dict:
    headings = [(len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)]
    levels = Counter(h[0] for h in headings)
    return {
        "count": len(headings),
        "levels": dict(levels),
        "first_level": headings[0][0] if headings else None,
    }


def compare_chapter(exp_name: str, exp_text: str, gld_text: str) -> dict[str, Any]:
    exp_refs, exp_defs = count_endnote_refs(exp_text)
    gld_refs, gld_defs = count_endnote_refs(gld_text)

    exp_sups = count_superscripts(exp_text)
    gld_sups = count_superscripts(gld_text)

    exp_html = count_html_tags(exp_text)
    exp_leaks = count_note_ref_leaks(exp_text)

    exp_headings = check_heading_structure(exp_text)
    gld_headings = check_heading_structure(gld_text)

    # 正文相似度（去掉 NOTES 节，剥掉 [^n] 行内引用和尾注定义）
    exp_body = exp_text.split("### NOTES")[0] if "### NOTES" in exp_text else exp_text
    gld_body = gld_text.split("### NOTES")[0] if "### NOTES" in gld_text else gld_text
    exp_body_clean = re.sub(r"\[\^\d+\]", "", exp_body)
    gld_body_clean = re.sub(r"\[\^\d+\]", "", gld_body)
    exp_body_clean = re.sub(r"\{\{NOTE_REF:[^}]+\}\}", "", exp_body_clean)
    gld_body_clean = re.sub(r"\{\{NOTE_REF:[^}]+\}\}", "", gld_body_clean)
    body_similarity = SequenceMatcher(None, exp_body_clean, gld_body_clean).ratio()

    issues: list[str] = []
    if set(exp_refs) != set(gld_refs):
        missing_refs = sorted(set(gld_refs) - set(exp_refs))
        extra_refs = sorted(set(exp_refs) - set(gld_refs))
        if missing_refs:
            issues.append(f"缺失正文引用 [^n]: {missing_refs[:15]}")
        if extra_refs:
            issues.append(f"多余正文引用 [^n]: {extra_refs[:15]}")

    if set(exp_defs) != set(gld_defs):
        missing_defs = sorted(set(gld_defs) - set(exp_defs))
        extra_defs = sorted(set(exp_defs) - set(gld_defs))
        if missing_defs:
            issues.append(f"缺失尾注定义 [^n]: {missing_defs[:15]}")
        if extra_defs:
            issues.append(f"多余尾注定义 [^n]: {extra_defs[:15]}")

    if exp_sups:
        issues.append(f"^{{n}} 上标残留: {len(exp_sups)} 处")

    if exp_html:
        issues.append(f"HTML 标签残留: {len(exp_html)} 处")

    leaks_found = {k: v for k, v in exp_leaks.items() if v > 0}
    if leaks_found:
        issues.append(f"Marker 泄漏: {leaks_found}")

    if exp_headings["count"] != gld_headings["count"]:
        issues.append(f"标题数量: 导出 {exp_headings['count']} vs golden {gld_headings['count']}")

    refs_ok = set(exp_refs) == set(gld_refs)
    defs_ok = set(exp_defs) == set(gld_defs)
    clean = not exp_sups and not exp_html and not any(exp_leaks.values())

    return {
        "export_name": exp_name,
        "body_similarity": round(body_similarity, 4),
        "export_refs": len(exp_refs),
        "golden_refs": len(gld_refs),
        "export_defs": len(exp_defs),
        "golden_defs": len(gld_defs),
        "refs_ok": refs_ok,
        "defs_ok": defs_ok,
        "clean": clean,
        "issues": issues,
    }


def main():
    zip_path = EXAMPLE_DIR / "latest.fnm.obsidian.Goldstein.blocked.test.zip"
    if not zip_path.is_file():
        print(f"ZIP 不存在: {zip_path}")
        sys.exit(1)

    exported = load_export_chapters(zip_path)
    golden = load_golden_chapters()
    pairs = match_export_to_golden(exported, golden)

    print("# Goldstein FNM 导出 vs Golden Template 逐章对比\n")

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
        print(f"## {status} {short_name}")
        print(f"- 相似度: {result['body_similarity']:.1%}")
        print(f"- 正文引用: 导出 {result['export_refs']} vs golden {result['golden_refs']} {'✓' if result['refs_ok'] else '✗'}")
        print(f"- 尾注定义: 导出 {result['export_defs']} vs golden {result['golden_defs']} {'✓' if result['defs_ok'] else '✗'}")
        print(f"- 清洁度: {'✓' if result['clean'] else '✗'}")

        for issue in result["issues"]:
            print(f"- **问题**: {issue}")
        print()

    # 汇总
    total_export_refs = sum(r["export_refs"] for r in results)
    total_golden_refs = sum(r["golden_refs"] for r in results)
    total_export_defs = sum(r["export_defs"] for r in results)
    total_golden_defs = sum(r["golden_defs"] for r in results)

    print(f"## 汇总")
    print(f"- {all_ok}/9 章通过")
    print(f"- {total_issues} 个问题")
    print(f"- 正文引用: 导出 {total_export_refs} vs golden {total_golden_refs} ({total_export_refs - total_golden_refs:+d})")
    print(f"- 尾注定义: 导出 {total_export_defs} vs golden {total_golden_defs} ({total_export_defs - total_golden_defs:+d})")

    # 保存 JSON
    out_path = EXAMPLE_DIR / "golden_comparison.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n详细 JSON: {out_path}")


if __name__ == "__main__":
    main()
