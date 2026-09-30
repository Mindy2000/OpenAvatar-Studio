#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8767}"
URL="http://127.0.0.1:${PORT}"

echo "OpenAvatar Studio 正在启动..."
echo "项目目录: $(pwd)"
echo "数据目录: ${OPENAVATAR_DATA_DIR:-$(pwd)/data}"

if [[ ! -x .venv/bin/python ]]; then
  echo "首次启动：正在创建本地 Python 环境..."
  "$PYTHON" -m venv .venv
fi
echo "正在检查并安装项目依赖..."
.venv/bin/python -c 'import sys; sys.exit("OpenAvatar requires Python 3.11+") if sys.version_info < (3, 11) else None'
.venv/bin/python -m pip install -r requirements.txt

(
  sleep 2
  .venv/bin/python - <<PY
import platform, subprocess, webbrowser
url = "${URL}"
try:
    webbrowser.open(url)
except Exception:
    if platform.system() == "Darwin":
        subprocess.run(["open", url], check=False)
print("请在浏览器打开:", url)
PY
) &

echo "本机访问地址: ${URL}"
exec .venv/bin/python -m uvicorn openavatar.main:app --host 127.0.0.1 --port "${PORT}"
