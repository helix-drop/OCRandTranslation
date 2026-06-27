#!/usr/bin/env python3
"""Export a PaddleOCR-VL JSON file to Obsidian-oriented Markdown."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.footnote_endnote_products import (
        build_obsidian_markdown,
        default_obsidian_output,
        write_text_output,
    )
except ModuleNotFoundError:
    from footnote_endnote_products import (
        build_obsidian_markdown,
        default_obsidian_output,
        write_text_output,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path, help="PaddleOCR-VL JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output markdown path. Defaults to output/obsidian/<name>.obsidian.md",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or default_obsidian_output(args.input_json)
    markdown = build_obsidian_markdown(args.input_json)
    write_text_output(output_path, markdown)
    print(output_path)


if __name__ == "__main__":
    main()
