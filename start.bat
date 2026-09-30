@echo off
setlocal
cd /d "%~dp0"
if not defined PORT set PORT=8767
if not defined PYTHON set PYTHON=python
echo OpenAvatar Studio 正在启动...
echo 项目目录: %cd%
echo 数据目录: %OPENAVATAR_DATA_DIR%
if not exist .venv\Scripts\python.exe (
  echo 首次启动：正在创建本地 Python 环境...
  %PYTHON% -m venv .venv
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -c "import sys; sys.exit('OpenAvatar requires Python 3.11+') if sys.version_info < (3, 11) else None"
if errorlevel 1 exit /b 1
echo 正在检查并安装项目依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
start "" "http://127.0.0.1:%PORT%"
.venv\Scripts\python.exe -m uvicorn openavatar.main:app --host 127.0.0.1 --port %PORT%
