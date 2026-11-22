# -*- mode: python ; coding: utf-8 -*-
"""Lumen 音乐 PyInstaller 打包配置（onedir + noconsole，公司规范）。

构建命令（打包前先清空 dist\）：
    venv\Scripts\python.exe -m PyInstaller "Lumen音乐.spec" --noconfirm
"""
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),      # 窗口/任务栏图标 icon.ico、封面用 icon.png
        ('图标.png', '.'),          # 公司规范图标（关于对话框读取）
        ('vendor/vlc', 'vendor/vlc'),  # 内置 libVLC 运行库（均衡器依赖它）
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Lumen音乐',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Lumen音乐',
)
