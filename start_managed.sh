#!/bin/bash
# 外文文献阅读器 - 受控窗口启动脚本
# 关闭专用浏览器窗口后，自动结束应用进程

cd "$(dirname "$0")"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    echo "虚拟环境创建完成。"
fi

source "$VENV_DIR/bin/activate"

MARKER="$VENV_DIR/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    echo "正在安装依赖..."
    pip install -q -r requirements.txt
    touch "$MARKER"
    echo "依赖安装完成。"
fi

echo ""
echo "========================================="
echo "  外文文献阅读器（受控窗口模式）"
echo "  关闭专用浏览器窗口后将自动结束应用"
echo "========================================="
echo ""

"$VENV_DIR/bin/python" managed_launcher.py \
  --server-python "$VENV_DIR/bin/python" \
  --url "http://localhost:8080" \
  --cwd "$(pwd)"
