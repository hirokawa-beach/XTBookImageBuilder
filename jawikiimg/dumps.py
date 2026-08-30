from __future__ import annotations

from pathlib import Path
import hashlib
import os
import time

from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .db import Database
from .http import HttpClient, check_free_space
from .sqlparser import iter_table_rows


JOB_NAMES = {"imagelinks": "imagelinkstable", "linktarget": "linktargettable"}


def _file_record(job: dict, kind: str) -> tuple[str, dict]:
    files = job.get("files", {})
    matches = [(name, meta) for name, meta in files.items() if name.endswith(f"-{kind}.sql.gz")]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {kind} SQL dump, found {len(matches)}")
    return matches[0]


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
    status_url = f"{settings.dump_base_url}/{snapshot_date or 'latest'}/dumpstatus.json"
    response = client.get(status_url)
    data = response.json()
    response.close()
    version = str(data.get("version") or snapshot_date or "")
    if not version.isdigit() or len(version) != 8:
        raise RuntimeError(f"invalid dump snapshot version: {version!r}")
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
            continue
        progress({"stage": "fetch-dumps", "current": kind, "snapshot_date": version})
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
                         "('extract_complete','extract_limit','build_complete')")
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
                progress({"stage": "fetch-dumps", "current": kind, "done": received, "total": total})
                last = now
        fh.flush()
        os.fsync(fh.fileno())
    response.close()
    part.replace(destination)


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
        return db.counts()["found"]
    with db.connect() as conn:
        rows = conn.execute("SELECT kind,local_path,status FROM dumps").fetchall()
    paths = {row["kind"]: Path(row["local_path"]) for row in rows if row["status"] == "done"}
    if set(paths) != {"imagelinks", "linktarget"}:
        raise RuntimeError("both dump files must be downloaded before extraction")

    progress({"stage": "extract", "current": "linktarget"})
    with db.transaction() as conn:
        batch = []
        for index, row in enumerate(iter_table_rows(paths["linktarget"], "linktarget"), 1):
            control.checkpoint()
            if int(row.get("lt_namespace", -1)) == 6:
                batch.append((int(row["lt_id"]), str(row["lt_title"])))
            if len(batch) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO link_targets(target_id,title) VALUES(?,?)", batch)
                batch.clear()
                conn.commit()
            if index % 100000 == 0:
                progress({"stage": "extract", "current": "linktarget", "done": index})
        if batch:
            conn.executemany("INSERT OR REPLACE INTO link_targets(target_id,title) VALUES(?,?)", batch)

    progress({"stage": "extract", "current": "imagelinks"})
    found = db.counts()["found"]
    with db.transaction() as conn:
        cache: dict[int, str | None] = {}
        for index, row in enumerate(iter_table_rows(paths["imagelinks"], "imagelinks"), 1):
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
                progress({"stage": "extract", "current": "imagelinks", "done": index, "found": found})
            if limit is not None and found >= limit:
                break
    if limit is None:
        db.set_state("extract_complete", True)
    db.set_state("extract_limit", limit)
    progress({"stage": "extract", "current": "done", "found": found})
    return found
