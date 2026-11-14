"""日志：落盘到 %LOCALAPPDATA%\\OppoEncoController\\logs，便于排障。

- 默认 INFO；开启「详细协议日志」后 RFCOMM 层会记录每条收发的原始帧。
- 每次启动一个文件，只保留最近 10 个。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

APP_DIR_NAME = "OppoEncoController"
KEEP_FILES = 10

_configured = False
_log_path: Path | None = None


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    return Path(base) / APP_DIR_NAME / "logs"


def _prune(folder: Path):
    try:
        files = sorted(folder.glob("app-*.log"), key=lambda p: p.stat().st_mtime)
        for old in files[:-KEEP_FILES]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def setup(verbose: bool = False) -> Path:
    """初始化日志（幂等），返回日志文件路径。"""
    global _configured, _log_path
    if _configured and _log_path:
        set_verbose(verbose)
        return _log_path

    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    _prune(folder)
    _log_path = folder / f"app-{time.strftime('%Y%m%d-%H%M%S')}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler(_log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"))
    root.addHandler(fh)

    # 源码运行时才往控制台打；打包成 exe 后没有控制台
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setLevel(logging.DEBUG if verbose else logging.WARNING)
        sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(sh)

    _configured = True
    logging.getLogger("app").info("=" * 52)
    logging.getLogger("app").info("启动 OPPO Enco Controller，日志：%s", _log_path)
    return _log_path


def set_verbose(on: bool):
    """切换协议层详细日志（运行时生效）。"""
    lvl = logging.DEBUG if on else logging.WARNING
    logging.getLogger("rfcomm").setLevel(lvl)
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            h.setLevel(logging.DEBUG if on else logging.INFO)


def current_path() -> Path | None:
    return _log_path


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
