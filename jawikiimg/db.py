from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Iterator, Iterable, Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dumps (
    kind TEXT PRIMARY KEY,
    snapshot_date TEXT NOT NULL,
    url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    sha1 TEXT,
    size INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT
);
CREATE TABLE IF NOT EXISTS link_targets (
    target_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    dump_title TEXT NOT NULL UNIQUE,
    canonical_title TEXT,
    pageid INTEGER,
    thumb_url TEXT,
    mime TEXT,
    thumb_mime TEXT,
    sha1 TEXT,
    width INTEGER,
    height INTEGER,
    byte_size INTEGER,
    description_url TEXT,
    license_short_name TEXT,
    license_url TEXT,
    artist TEXT,
    credit TEXT,
    attribution TEXT,
    attribution_required TEXT,
    copyrighted TEXT,
    non_free TEXT,
    permission TEXT,
    restrictions_text TEXT,
    extmetadata_json TEXT,
    api_json TEXT,
    metadata_status TEXT NOT NULL DEFAULT 'pending',
    classification TEXT,
    classification_reason TEXT,
    manual_override TEXT,
    manual_note TEXT,
    manual_updated_at TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending',
    download_path TEXT,
    download_bytes INTEGER,
    convert_status TEXT NOT NULL DEFAULT 'pending',
    jpeg_path TEXT,
    xtbook_filename TEXT,
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_images_metadata ON images(metadata_status, id);
CREATE INDEX IF NOT EXISTS idx_images_classification ON images(classification, id);
CREATE INDEX IF NOT EXISTS idx_images_download ON images(download_status, id);
CREATE INDEX IF NOT EXISTS idx_images_convert ON images(convert_status, id);
"""


class ClosingConnection(sqlite3.Connection):
    """Make ``with db.connect()`` close as callers naturally expect."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add columns introduced after the first public database schema."""
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(images)")}
        for name, declaration in (
            ("manual_override", "TEXT"),
            ("manual_note", "TEXT"),
            ("manual_updated_at", "TEXT"),
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE images ADD COLUMN {name} {declaration}")

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=60, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=60000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def set_state(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False)
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO state(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, encoded),
            )

    def add_images(self, titles: Iterable[str], limit: int | None = None) -> int:
        added = 0
        with self.transaction() as conn:
            for title in titles:
                if limit is not None and self.image_count(conn) >= limit:
                    break
                cur = conn.execute("INSERT OR IGNORE INTO images(dump_title) VALUES(?)", (title,))
                added += cur.rowcount
        return added

    @staticmethod
    def image_count(conn: sqlite3.Connection) -> int:
        return int(conn.execute("SELECT COUNT(*) FROM images").fetchone()[0])

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            result = {"found": self.image_count(conn)}
            for key, sql in {
                "metadata_done": "metadata_status='done'",
                "ALLOW_PD": "classification='ALLOW_PD'",
                "ALLOW_CC0": "classification='ALLOW_CC0'",
                "ALLOW_CC_BY": "classification='ALLOW_CC_BY'",
                "ALLOW_CC_BY_SA": "classification='ALLOW_CC_BY_SA'",
                "REVIEW": "classification='REVIEW'",
                "DENY": "classification='DENY'",
                "manual_approved": "manual_override LIKE 'ALLOW_%'",
                "manual_denied": "manual_override='DENY'",
                "downloaded": "download_status='done'",
                "converted": "convert_status='done'",
            }.items():
                result[key] = int(conn.execute(f"SELECT COUNT(*) FROM images WHERE {sql}").fetchone()[0])
        result["allow"] = sum(result[k] for k in ("ALLOW_PD", "ALLOW_CC0", "ALLOW_CC_BY", "ALLOW_CC_BY_SA"))
        return result
