#!/usr/bin/env python3
"""为 fnm-phase1 生成 parity fixture。

每个测试函数喂入 Python 真实输出，序列化后写入
fnm_re_rs/fnm-phase1/tests/fixtures/ 目录。

用法:
    python tools/gen_phase1_fixtures.py
"""

import json
import sys
from pathlib import Path

FIXTURES_DIR = Path("fnm_re_rs/fnm-phase1/tests/fixtures")


def ensure_dir() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


# ── P1.2: page_partition ─────────────────────────────────────


def gen_page_partition_fixture() -> None:
    """用 Biopolitics 全书跑 Python build_page_partitions，序列化输出。"""
    ensure_dir()
    # TODO: 加载 Biopolitics fixture pages
    # from tests.unit.fnm_re_module_fixtures import load_pages
    # pages = load_pages("Biopolitics")
    # from FNM_RE.stages.page_partition import build_page_partitions
    # result = build_page_partitions(pages)
    # (FIXTURES_DIR / "biopolitics_partitions.json").write_text(
    #     json.dumps(result, ensure_ascii=False, indent=2, default=str)
    # )
    print("  ⏳ page_partition fixture: 待 Biopolitics pages fixture 就绪")


# ── 主入口 ──────────────────────────────────────────────────


if __name__ == "__main__":
    print("生成 fnm-phase1 parity fixtures …")
    gen_page_partition_fixture()
    print("完成。")
