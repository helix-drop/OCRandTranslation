#!/usr/bin/env bash
# 下载 o200k_base tokenizer JSON，嵌入为 fnm-core 静态资源。
# 本地跑一次即可，CI 将 assets/ 目录纳入缓存。
set -euo pipefail

ASSET_DIR="$(cd "$(dirname "$0")/../fnm_re_rs/fnm-core/assets" && pwd)"
OUTPUT="${ASSET_DIR}/o200k_base.json"
URL="https://huggingface.co/Xenova/gpt-4o/resolve/main/tokenizer.json"

echo "Fetching tokenizer from ${URL} ..."
curl -L -o "${OUTPUT}" "${URL}"
echo "Done: ${OUTPUT} ($(wc -c < "${OUTPUT}") bytes)"
