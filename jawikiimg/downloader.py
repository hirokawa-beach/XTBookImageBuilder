from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
import os
import time

from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .db import Database
from .filenames import raw_download_path
from .http import BandwidthLimiter, HttpClient, check_free_space
from .license import ALLOW_STATES


class MediaDownloader:
    def __init__(self, settings: Settings, db: Database, control: Control):
        self.settings, self.db, self.control = settings, db, control
        self.bandwidth = BandwidthLimiter(settings.media_mbps)
        self.bytes_total = 0
        self.bytes_lock = Lock()

    def run(self, progress: ProgressCallback = null_progress) -> int:
        self.settings.validate(network=True)
        self.settings.ensure_dirs()
        placeholders = ",".join("?" for _ in ALLOW_STATES)
        params = tuple(sorted(ALLOW_STATES))
        with self.db.connect() as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM images WHERE classification IN ({placeholders})", params,
            ).fetchone()[0])
            completed_before = int(conn.execute(
                f"SELECT COUNT(*) FROM images WHERE classification IN ({placeholders}) "
                "AND download_status='done'", params,
            ).fetchone()[0])
        started = time.monotonic()
        done = 0
        last_id = 0
        progress({
            "stage": "download", "phase": "media", "current": "画像取得を開始",
            "done": completed_before, "total": total, "unit": "items",
            "status": "reused" if completed_before == total else "running",
            "message": f"完了済み{completed_before}件を再利用" if completed_before else None,
        })
        while True:
            with self.db.connect() as conn:
                rows = conn.execute(
                    f"SELECT id,dump_title,thumb_url FROM images WHERE classification IN ({placeholders}) "
                    "AND download_status!='done' AND id>? ORDER BY id LIMIT 100",
                    params + (last_id,),
                ).fetchall()
            if not rows:
                break
            last_id = int(rows[-1]["id"])
            with ThreadPoolExecutor(max_workers=self.settings.media_workers) as pool:
                futures = {pool.submit(self._one, dict(row)): row for row in rows}
                for future in as_completed(futures):
                    self.control.checkpoint()
                    future.result()
                    done += 1
                    elapsed = max(0.001, time.monotonic() - started)
                    progress({
                        "stage": "download", "phase": "media",
                        "done": completed_before + done, "total": total, "unit": "items",
                        "processed": done,
                        "dl_mbps": self.bytes_total * 8 / elapsed / 1_000_000,
                        "rate": done / elapsed, "rate_unit": "items/s", "elapsed": elapsed,
                        "current": futures[future]["dump_title"],
                    })
        progress({
            "stage": "download", "phase": "media", "current": "画像取得完了",
            "done": completed_before + done, "total": total, "unit": "items",
            "processed": done,
            "dl_mbps": self.bytes_total * 8 / max(0.001, time.monotonic() - started) / 1_000_000,
            "elapsed": max(0.001, time.monotonic() - started),
            "status": "done" if done else "reused",
        })
        return done

    def _one(self, row: dict) -> None:
        self.control.checkpoint()
        if not row.get("thumb_url"):
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE images SET download_status='error',error=? WHERE id=?",
                    ("ALLOW image has no API thumburl", row["id"]),
                )
            raise RuntimeError(f"no thumburl for {row['dump_title']}")
        check_free_space(self.settings.downloads_dir, self.settings.minimum_free_gib)
        destination = raw_download_path(self.settings.downloads_dir, int(row["id"]))
        part = destination.with_name(destination.name + ".part")
        client = HttpClient(self.settings.user_agent, self.control)
        try:
            response = client.get(row["thumb_url"], stream=True, timeout=(15, 180))
            received = 0
            with part.open("wb") as fh:
                for chunk in response.iter_content(64 * 1024):
                    self.control.checkpoint()
                    if not chunk:
                        continue
                    self.bandwidth.consume(len(chunk), self.control)
                    fh.write(chunk)
                    received += len(chunk)
                    with self.bytes_lock:
                        self.bytes_total += len(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            response.close()
            part.replace(destination)
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE images SET download_status='done',download_path=?,download_bytes=?,"
                    "error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(destination), received, row["id"]),
                )
        except Exception as exc:
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE images SET download_status='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(exc), row["id"]),
                )
            raise
