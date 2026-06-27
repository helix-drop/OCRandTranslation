#!/usr/bin/env python3
"""运行 FNM unresolved cluster 的 Qwen 修补。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from FNM_RE import run_doc_pipeline as run_fnm_pipeline  # noqa: E402
from FNM_RE import run_llm_repair  # noqa: E402
from persistence.sqlite_store import SQLiteRepository  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 FNM LLM 修补。")
    parser.add_argument("doc_id", help="文档 id")
    parser.add_argument(
        "--cluster-limit",
        type=int,
        default=0,
        help="最多处理多少个 unresolved cluster；<=0 表示全部（默认全部）。",
    )
    parser.add_argument("--no-auto-apply", action="store_true", help="只生成建议，不自动应用高置信结果")
    parser.add_argument("--skip-rebuild", action="store_true", help="自动应用后不重建 FNM")
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.9,
        help="auto-apply 的置信度阈值，默认 0.9。",
    )
    parser.add_argument(
        "--max-matched-examples",
        type=int,
        default=0,
        help="每簇送入 LLM 的已匹配示例上限；<=0 使用模块默认。",
    )
    parser.add_argument(
        "--max-unmatched-notes",
        type=int,
        default=0,
        help="每簇送入 LLM 的孤儿 note_item 上限；<=0 使用模块默认。",
    )
    parser.add_argument(
        "--max-unmatched-anchors",
        type=int,
        default=0,
        help="每簇送入 LLM 的孤儿 anchor 上限；<=0 使用模块默认。",
    )
    return parser.parse_args()


def _positive_or_none(value: int) -> int | None:
    return int(value) if int(value or 0) > 0 else None


def main() -> int:
    args = parse_args()
    repo = SQLiteRepository()
    cluster_limit = int(args.cluster_limit or 0)
    result = run_llm_repair(
        args.doc_id,
        repo=repo,
        cluster_limit=cluster_limit if cluster_limit > 0 else None,
        auto_apply=not args.no_auto_apply,
        confidence_threshold=float(args.confidence_threshold),
        max_matched_examples=_positive_or_none(args.max_matched_examples),
        max_unmatched_note_items=_positive_or_none(args.max_unmatched_notes),
        max_unmatched_anchors=_positive_or_none(args.max_unmatched_anchors),
    )
    if not args.skip_rebuild and int(result.get("auto_applied_count") or 0) > 0:
        rebuild = run_fnm_pipeline(args.doc_id)
        result["rebuild"] = rebuild
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
