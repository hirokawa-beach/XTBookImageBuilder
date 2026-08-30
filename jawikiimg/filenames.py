from __future__ import annotations

from pathlib import Path


def file_title(title: str) -> str:
    return title[5:] if title.lower().startswith("file:") else title


def safe_xtbook_filename(title: str) -> str:
    """Return the title plus .jpg; retain its original extension for XTBook lookup."""
    name = file_title(title).replace("\0", "").replace("/", "∕").replace("\\", "⧵")
    if name in {"", ".", ".."}:
        raise ValueError(f"unsafe file title: {title!r}")
    return name + ".jpg"


def raw_download_path(directory: Path, image_id: int) -> Path:
    return directory / f"{image_id:09d}.media"

