#!/bin/bash
# 外文文献阅读器 - 一键启动脚本
# 自动创建虚拟环境、安装依赖、启动应用

cd "$(dirname "$0")"

VENV_DIR=".venv"

# 创建虚拟环境（仅首次）
if [ ! -d "$VENV_DIR" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    echo "虚拟环境创建完成。"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 安装/更新依赖（仅首次或 requirements.txt 变化时）
MARKER="$VENV_DIR/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    echo "正在安装依赖..."
    pip install -q -r requirements.txt
    touch "$MARKER"
    echo "依赖安装完成。"
fi

echo ""
echo "========================================="
echo "  外文文献阅读器"
echo "  浏览器打开: http://localhost:8080"
echo "========================================="
echo ""

# 自动打开浏览器（延迟1秒等服务启动）
open_browser() {
    local url="$1"
    if command -v open >/dev/null 2>&1; then
        open "$url" >/dev/null 2>&1
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1
    else
        echo "未检测到浏览器打开命令，请手动访问: $url"
    fi
}

(sleep 1 && open_browser "http://localhost:8080") &

# 启动 Flask
python3 app.py
