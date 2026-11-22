@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 一键打包：PyInstaller onedir + Inno Setup 免 UAC 安装包
rem 用法：build.bat

echo [1/3] 清空 dist\ ...
if exist dist rmdir /s /q dist

echo [2/3] PyInstaller 打包 ...
"venv\Scripts\python.exe" -m PyInstaller "Lumen音乐.spec" --noconfirm
if errorlevel 1 goto :error

echo [3/3] Inno Setup 制作安装包 ...
"C:\Users\fengcong\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "Lumen音乐.iss"
if errorlevel 1 goto :error

echo.
echo 完成：installer_output\Lumen音乐-Setup-*.exe（版本号见 Lumen音乐.iss）
exit /b 0

:error
echo.
echo 打包失败，请检查上方报错。
pause
exit /b 1
