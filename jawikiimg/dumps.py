from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re
import time

import requests

from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .db import Database
from .http import HttpClient, check_free_space
from .sqlparser import iter_table_rows


JOB_NAMES = {"imagelinks": "imagelinkstable", "linktarget": "linktargettable"}
SNAPSHOT_HREF_RE = re.compile(r'''href=["'](\d{8})/["']''', re.IGNORECASE)


def _file_record(job: dict, kind: str) -> tuple[str, dict]:
    files = job.get("files", {})
    matches = [(name, meta) for name, meta in files.items() if name.endswith(f"-{kind}.sql.gz")]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} SQL dump, found {len(matches)}")
    return matches[0]


def _snapshot_dates(index_html: str) -> list[str]:
    """Return dump snapshot directory names, newest first."""
    return sorted(set(SNAPSHOT_HREF_RE.findall(index_html)), reverse=True)


def _status_is_complete(data: dict) -> bool:
    jobs = data.get("jobs", {})
    for kind, job_name in JOB_NAMES.items():
        job = jobs.get(job_name, {})
        if job.get("status") != "done":
            return False
        try:
            _file_record(job, kind)
        except RuntimeError:
            return False
    return True


def _get_status(client: HttpClient, base_url: str, snapshot_date: str | None) -> tuple[str, dict]:
    base_url = base_url.rstrip("/")
    if snapshot_date is not None:
        if not re.fullmatch(r"\d{8}", snapshot_date):
            raise ValueError("dump snapshot date must be YYYYMMDD")
        candidates = [snapshot_date]
    else:
        response = client.get(base_url + "/")
        candidates = _snapshot_dates(response.text)
        response.close()
        if not candidates:
            raise RuntimeError("no dated dump snapshots found in Wikimedia index")

    for candidate in candidates:
        status_url = f"{base_url}/{candidate}/dumpstatus.json"
        try:
            response = client.get(status_url)
        except requests.HTTPError as exc:
            # A directory may disappear during Wikimedia's snapshot rotation.
            if snapshot_date is None and exc.response is not None and exc.response.status_code == 404:
                continue
            raise
        data = response.json()
        response.close()
        if _status_is_complete(data):
            return candidate, data
        if snapshot_date is not None:
            raise RuntimeError(
                f"dump snapshot {snapshot_date} does not have completed imagelinks/linktarget jobs"
            )
    raise RuntimeError("no complete Wikimedia dump snapshot found for imagelinks and linktarget")


def fetch_dumps(
    settings: Settings,
    db: Database,
    control: Control,
    snapshot_date: str | None = None,
    progress: ProgressCallback = null_progress,
) -> str:
    settings.validate(network=True)
    settings.ensure_dirs()
    client = HttpClient(settings.user_agent, control)
    progress({"stage": "fetch-dumps", "phase": "discover", "current": "Dump一覧を確認中"})
    version, data = _get_status(client, settings.dump_base_url, snapshot_date)
    progress({
        "stage": "fetch-dumps", "phase": "discover", "current": version,
        "status": "done", "message": f"使用するDump: {version}",
    })
    jobs = data.get("jobs", {})
    previous_snapshot = db.get_state("snapshot_date")
    records = []
    for kind, job_name in JOB_NAMES.items():
        job = jobs.get(job_name, {})
        if job.get("status") != "done":
            raise RuntimeError(f"dump job {job_name} is not complete")
        filename, meta = _file_record(job, kind)
        url = meta.get("url") or f"{settings.dump_base_url}/{version}/{filename}"
        if url.startswith("/"):
            url = "https://dumps.wikimedia.org" + url
        records.append((kind, filename, meta, url))
    # All records came from a single dumpstatus document/version: no mixed snapshots.
    with db.transaction() as conn:
        for kind, filename, meta, url in records:
            conn.execute(
                "INSERT INTO dumps(kind,snapshot_date,url,local_path,sha1,size,status) "
                "VALUES(?,?,?,?,?,?, 'pending') ON CONFLICT(kind) DO UPDATE SET "
                "snapshot_date=excluded.snapshot_date,url=excluded.url,local_path=excluded.local_path," 
                "sha1=excluded.sha1,size=excluded.size," 
                "status=CASE WHEN dumps.snapshot_date=excluded.snapshot_date AND dumps.status='done' "
                "THEN 'done' ELSE 'pending' END",
                (
                    kind,
                    version,
                    url,
                    str(settings.dumps_dir / filename),
                    meta.get("sha1"),
                    int(meta["size"]) if meta.get("size") else None,
                ),
            )
    for kind, filename, meta, url in records:
        destination = settings.dumps_dir / filename
        with db.connect() as conn:
            status = conn.execute("SELECT status FROM dumps WHERE kind=?", (kind,)).fetchone()[0]
        if status == "done" and destination.exists():
            size = destination.stat().st_size
            progress({
                "stage": "fetch-dumps", "phase": kind, "current": filename,
                "done": size, "total": size, "unit": "bytes", "status": "reused",
                "message": "既存ファイルを再利用",
            })
            continue
        progress({
            "stage": "fetch-dumps", "phase": kind, "current": filename,
            "snapshot_date": version, "done": 0,
            "total": int(meta.get("size") or 0), "unit": "bytes",
        })
        check_free_space(settings.dumps_dir, settings.minimum_free_gib)
        _download_dump(
            client, url, destination, control, progress, kind, settings.minimum_free_gib
        )
        expected = meta.get("sha1")
        if expected and _sha1(destination) != expected:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"SHA1 mismatch for {filename}")
        with db.transaction() as conn:
            conn.execute("UPDATE dumps SET status='done', error=NULL WHERE kind=?", (kind,))
    if previous_snapshot and previous_snapshot != version:
        # Never combine image rows derived from one snapshot with dumps from another.
        with db.transaction() as conn:
            conn.execute("DELETE FROM images")
            conn.execute("DELETE FROM link_targets")
            conn.execute("DELETE FROM state WHERE key IN "
                         "('extract_complete','extract_limit','linktarget_extract_complete',"
                         "'build_complete')")
    db.set_state("snapshot_date", version)
    return version


def _download_dump(client, url, destination, control, progress, kind, minimum_free_gib):
    part = destination.with_name(destination.name + ".part")
    existing = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else None
    response = client.get(url, stream=True, timeout=(20, 300), headers=headers)
    append = existing > 0 and response.status_code == 206
    if existing and not append:
        existing = 0
    mode = "ab" if append else "wb"
    total = existing + int(response.headers.get("Content-Length", 0))
    received = existing
    started = time.monotonic()
    last = time.monotonic()
    last_disk_check = last
    with part.open(mode) as fh:
        for chunk in response.iter_content(1024 * 1024):
            control.checkpoint()
            if not chunk:
                continue
            fh.write(chunk)
            received += len(chunk)
            now = time.monotonic()
            if now - last_disk_check >= 5:
                check_free_space(destination.parent, minimum_free_gib)
                last_disk_check = now
            if now - last >= 0.5:
                elapsed = max(0.001, now - started)
                progress({
                    "stage": "fetch-dumps", "phase": kind, "current": destination.name,
                    "done": received, "total": total, "unit": "bytes",
                    "rate": max(0, received - existing) / elapsed, "rate_unit": "B/s",
                    "elapsed": elapsed,
                })
                last = now
        fh.flush()
        os.fsync(fh.fileno())
    response.close()
    part.replace(destination)
    elapsed = max(0.001, time.monotonic() - started)
    progress({
        "stage": "fetch-dumps", "phase": kind, "current": destination.name,
        "done": received, "total": total, "unit": "bytes",
        "rate": max(0, received - existing) / elapsed, "rate_unit": "B/s",
        "elapsed": elapsed, "status": "done",
    })


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_images(
    settings: Settings,
    db: Database,
    control: Control,
    limit: int | None = None,
    progress: ProgressCallback = null_progress,
) -> int:
    if db.get_state("extract_complete") and (limit is None or db.counts()["found"] >= limit):
        found = db.counts()["found"]
        progress({
            "stage": "extract", "phase": "complete", "current": "抽出済みデータ",
            "done": found, "total": found, "unit": "items", "found": found,
            "status": "reused", "message": "SQLiteの抽出結果を再利用",
        })
        return found
    with db.connect() as conn:
        rows = conn.execute("SELECT kind,local_path,status FROM dumps").fetchall()
    paths = {row["kind"]: Path(row["local_path"]) for row in rows if row["status"] == "done"}
    if set(paths) != {"imagelinks", "linktarget"}:
        raise RuntimeError("both dump files must be downloaded before extraction")

    if db.get_state("linktarget_extract_complete"):
        with db.connect() as conn:
            target_count = int(conn.execute("SELECT COUNT(*) FROM link_targets").fetchone()[0])
        progress({
            "stage": "extract", "phase": "linktarget", "current": "File名前空間の対応表",
            "done": target_count, "total": target_count, "unit": "rows",
            "status": "reused", "message": "SQLiteの解析済みデータを再利用",
        })
    else:
        link_started = time.monotonic()
        link_rows = 0
        link_matches = 0
        last_link_event = 0.0

        def link_bytes(done_bytes, total_bytes):
            nonlocal last_link_event
            now = time.monotonic()
            if now - last_link_event >= 0.5 or done_bytes >= total_bytes:
                elapsed = max(0.001, now - link_started)
                progress({
                    "stage": "extract", "phase": "linktarget",
                    "current": "File名前空間の対応表を解析",
                    "done": done_bytes, "total": total_bytes, "unit": "bytes",
                    "rows": link_rows, "matched": link_matches,
                    "rate": link_rows / elapsed, "rate_unit": "rows/s",
                    "elapsed": elapsed,
                })
                last_link_event = now

        with db.transaction() as conn:
            batch = []
            for index, row in enumerate(
                iter_table_rows(paths["linktarget"], "linktarget", link_bytes), 1
            ):
                link_rows = index
                control.checkpoint()
                if int(row.get("lt_namespace", -1)) == 6:
                    batch.append((int(row["lt_id"]), str(row["lt_title"])))
                    link_matches += 1
                if len(batch) >= 5000:
                    conn.executemany(
                        "INSERT OR REPLACE INTO link_targets(target_id,title) VALUES(?,?)", batch
                    )
                    batch.clear()
                    conn.commit()
            if batch:
                conn.executemany(
                    "INSERT OR REPLACE INTO link_targets(target_id,title) VALUES(?,?)", batch
                )
        db.set_state("linktarget_extract_complete", True)
        progress({
            "stage": "extract", "phase": "linktarget", "current": "File名前空間の対応表",
            "done": paths["linktarget"].stat().st_size,
            "total": paths["linktarget"].stat().st_size, "unit": "bytes",
            "rows": link_rows, "matched": link_matches,
            "elapsed": max(0.001, time.monotonic() - link_started), "status": "done",
        })

    image_started = time.monotonic()
    image_rows = 0
    last_image_event = 0.0
    found = db.counts()["found"]

    def image_bytes(done_bytes, total_bytes):
        nonlocal last_image_event
        now = time.monotonic()
        if now - last_image_event >= 0.5 or done_bytes >= total_bytes:
            elapsed = max(0.001, now - image_started)
            progress({
                "stage": "extract", "phase": "imagelinks",
                "current": "標準記事で使われる画像を抽出",
                "done": done_bytes, "total": total_bytes, "unit": "bytes",
                "rows": image_rows, "found": found,
                "rate": image_rows / elapsed, "rate_unit": "rows/s", "elapsed": elapsed,
            })
            last_image_event = now

    with db.transaction() as conn:
        cache: dict[int, str | None] = {}
        for index, row in enumerate(
            iter_table_rows(paths["imagelinks"], "imagelinks", image_bytes), 1
        ):
            image_rows = index
            control.checkpoint()
            if int(row.get("il_from_namespace", 0)) != 0:
                continue
            if "il_to" in row:  # pre-linktarget schema
                title = str(row["il_to"])
            elif "il_target_id" in row:
                target_id = int(row["il_target_id"])
                if target_id not in cache:
                    target = conn.execute(
                        "SELECT title FROM link_targets WHERE target_id=?", (target_id,)
                    ).fetchone()
                    cache[target_id] = None if target is None else str(target[0])
                    if len(cache) > 50000:
                        cache.clear()
                title = cache.get(target_id)
                if title is None:
                    continue
            else:
                raise RuntimeError("unsupported imagelinks schema: il_to/il_target_id missing")
            cur = conn.execute("INSERT OR IGNORE INTO images(dump_title) VALUES(?)", (title,))
            found += cur.rowcount
            if index % 100000 == 0:
                conn.commit()
            if limit is not None and found >= limit:
                break
    if limit is None:
        db.set_state("extract_complete", True)
    db.set_state("extract_limit", limit)
    progress({
        "stage": "extract", "phase": "imagelinks", "current": "画像タイトル抽出",
        "done": paths["imagelinks"].stat().st_size if limit is None else None,
        "total": paths["imagelinks"].stat().st_size if limit is None else None,
        "unit": "bytes", "rows": image_rows, "found": found,
        "elapsed": max(0.001, time.monotonic() - image_started),
        "status": "limited" if limit is not None else "done",
        "message": f"上限{limit}件に到達" if limit is not None else "抽出完了",
    })
    return found
