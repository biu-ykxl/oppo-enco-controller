# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：OPPO Enco Controller 单文件 EXE
#
# 目标：拷到任何 64 位 Windows 10/11 上双击即可运行，不装 Python、不装运行库。
# 因此把 VC++ 运行库（vcruntime/msvcp）显式打进去 —— PyInstaller 在新版
# Python 下不一定自动收集，缺失时会报「找不到 VCRUNTIME140.dll」。
import os

from PyInstaller.utils.hooks import collect_submodules

VC_RUNTIME = [
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
]

_candidates = [
    os.path.join(os.path.dirname(os.path.abspath(SPEC)), ""),  # 项目目录
    r"C:\Windows\System32",
]


def _find(dll: str) -> str | None:
    for root in _candidates:
        p = os.path.join(root, dll)
        if root and os.path.exists(p):
            return p
    return None


binaries = [(p, ".") for p in (_find(d) for d in VC_RUNTIME) if p]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=[],
    hiddenimports=collect_submodules("oppo"),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OppoEncoController",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无控制台窗口
    disable_windowed_traceback=False,
)
