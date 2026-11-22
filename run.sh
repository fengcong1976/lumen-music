#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -x "venv/bin/python" ]; then
    echo "[Lumen] 创建虚拟环境并安装依赖..."
    python3 -m venv venv
    venv/bin/python -m pip install -q -r requirements.txt
fi

exec venv/bin/python main.py
