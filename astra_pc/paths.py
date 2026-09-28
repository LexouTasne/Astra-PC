from __future__ import annotations

import os
import platform
from pathlib import Path


def data_dir() -> Path:
    override = os.getenv("ASTRA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home()))
        return base / "Astra-PC" / "data"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Astra-PC"
    return Path.home() / ".local" / "share" / "astra-pc"


def cache_dir() -> Path:
    override = os.getenv("ASTRA_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()

    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home()))
        return base / "Astra-PC" / "cache"
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / "Astra-PC"
    return Path.home() / ".cache" / "astra-pc"


def install_dir() -> Path:
    override = os.getenv("ASTRA_INSTALL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def ensure_storage() -> tuple[Path, Path]:
    data = data_dir()
    cache = cache_dir()
    data.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    return data, cache
