from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os

from PIL import Image, ImageOps

from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .db import Database
from .filenames import safe_xtbook_filename
from .http import check_free_space


def output_size(size: tuple[int, int], maximum: tuple[int, int] = (800, 480)) -> tuple[int, int]:
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    ratio = min(maximum[0] / width, maximum[1] / height, 1.0)
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def convert_image(
    source: Path,
    destination: Path,
    maximum: tuple[int, int] = (800, 480),
    quality: int = 85,
) -> tuple[int, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        size = output_size(image.size, maximum)
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        if image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        image.save(part, "JPEG", quality=quality, optimize=True, progressive=False)
    with part.open("r+b") as fh:
        os.fsync(fh.fileno())
    part.replace(destination)
    return size


class Converter:
    def __init__(self, settings: Settings, db: Database, control: Control):
        self.settings, self.db, self.control = settings, db, control

    def run(self, progress: ProgressCallback = null_progress) -> int:
        self.settings.ensure_dirs()
        with self.db.connect() as conn:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM images WHERE download_status='done' AND convert_status!='done'"
            ).fetchone()[0])
        done, last_id = 0, 0
        while True:
            with self.db.connect() as conn:
                rows = conn.execute(
                    "SELECT id,dump_title,download_path FROM images WHERE download_status='done' "
                    "AND convert_status!='done' AND id>? ORDER BY id LIMIT 100", (last_id,),
                ).fetchall()
            if not rows:
                break
            last_id = int(rows[-1]["id"])
            with ThreadPoolExecutor(max_workers=self.settings.convert_workers) as pool:
                futures = {pool.submit(self._one, dict(row)): row for row in rows}
                for future in as_completed(futures):
                    self.control.checkpoint()
                    future.result()
                    done += 1
                    progress({
                        "stage": "convert", "done": done, "total": total,
                        "current": futures[future]["dump_title"],
                    })
        return done

    def _one(self, row: dict) -> None:
        self.control.checkpoint()
        check_free_space(self.settings.converted_dir, self.settings.minimum_free_gib)
        filename = safe_xtbook_filename(row["dump_title"])
        destination = self.settings.converted_dir / filename
        try:
            convert_image(
                Path(row["download_path"]), destination,
                (self.settings.max_width, self.settings.max_height), self.settings.jpeg_quality,
            )
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE images SET convert_status='done',jpeg_path=?,xtbook_filename=?,"
                    "error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(destination), filename, row["id"]),
                )
        except Exception as exc:
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE images SET convert_status='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc), row["id"]),
                )
            raise
