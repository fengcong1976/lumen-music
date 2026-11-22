@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo [Lumen] 首次运行，正在创建虚拟环境...
    python -m venv venv
    if errorlevel 1 goto :error
    echo [Lumen] 正在安装依赖 PySide6 / mutagen ...
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

start "" "venv\Scripts\pythonw.exe" "main.py"
exit /b 0

:error
echo.
echo 初始化失败：请确认已安装 Python 3.10+ 并加入 PATH。
pause
exit /b 1
