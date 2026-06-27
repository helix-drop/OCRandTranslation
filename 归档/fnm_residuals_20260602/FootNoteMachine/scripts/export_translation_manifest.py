#!/usr/bin/env python3
"""Export a PaddleOCR-VL JSON file to a translation manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.footnote_endnote_products import (
        build_translation_manifest,
        default_translation_output,
        write_json_output,
    )
except ModuleNotFoundError:
    from footnote_endnote_products import (
        build_translation_manifest,
        default_translation_output,
        write_json_output,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path, help="PaddleOCR-VL JSON file")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output manifest path. Defaults to output/translation/<name>.translation_manifest.json",
    )
    parser.add_argument(
        "--max-body-chars",
        type=int,
        default=6000,
        help="Maximum characters per body translation unit. Default: 6000",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or default_translation_output(args.input_json)
    manifest = build_translation_manifest(
        args.input_json,
        max_body_chars=args.max_body_chars,
    )
    write_json_output(output_path, manifest)
    print(output_path)


if __name__ == "__main__":
    main()
