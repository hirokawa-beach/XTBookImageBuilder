from __future__ import annotations

from collections.abc import Iterator
import json
import time

from .config import Settings
from .control import Control, ProgressCallback, null_progress
from .db import Database
from .http import HttpClient, RateLimiter
from .license import metadata_value


EXT_FIELDS = (
    "LicenseShortName", "LicenseUrl", "Artist", "Credit", "Attribution",
    "AttributionRequired", "Copyrighted", "NonFree", "Permission", "Restrictions",
)


def _chunks(rows, size: int):
    chunk = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class MetadataFetcher:
    def __init__(self, settings: Settings, db: Database, control: Control, client=None):
        self.settings = settings
        self.db = db
        self.control = control
        self.client = client or HttpClient(
            settings.user_agent, control, RateLimiter(settings.api_requests_per_second)
        )

    def run(self, progress: ProgressCallback = null_progress) -> int:
        self.settings.validate(network=True)
        with self.db.connect() as conn:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM images WHERE metadata_status!='done'"
            ).fetchone()[0])
        done = 0
        started = time.monotonic()
        last_id = 0
        while True:
            with self.db.connect() as conn:
                batch = conn.execute(
                    "SELECT id,dump_title FROM images WHERE metadata_status!='done' "
                    "AND id>? ORDER BY id LIMIT ?",
                    (last_id, self.settings.api_batch_size),
                ).fetchall()
            if not batch:
                break
            last_id = int(batch[-1]["id"])
            self.control.checkpoint()
            titles = ["File:" + str(row["dump_title"]) for row in batch]
            params = {
                "action": "query", "format": "json", "formatversion": 2,
                "prop": "imageinfo", "titles": "|".join(titles),
                "iiprop": "canonicaltitle|url|size|sha1|mime|thumbmime|extmetadata",
                "iiurlwidth": self.settings.thumbnail_width,
                "iiextmetadatalanguage": "en", "iimetadataversion": "latest",
                "iiextmetadatafilter": "|".join(EXT_FIELDS), "maxlag": 5,
            }
            try:
                response = self.client.get(self.settings.api_url, params=params)
                payload = response.json()
                response.close()
                if "error" in payload:
                    raise RuntimeError(json.dumps(payload["error"], ensure_ascii=False))
                self._store_batch(batch, payload)
            except Exception as exc:
                with self.db.transaction() as conn:
                    conn.executemany(
                        "UPDATE images SET metadata_status='error', error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        [(str(exc), int(row["id"])) for row in batch],
                    )
                raise
            done += len(batch)
            elapsed = max(0.001, time.monotonic() - started)
            progress({
                "stage": "metadata", "done": done, "total": total,
                "api_rate": done / elapsed, "current": titles[-1],
            })
        return done

    def _store_batch(self, requested, payload):
        normalized = {item["from"]: item["to"] for item in payload.get("query", {}).get("normalized", [])}
        pages = payload.get("query", {}).get("pages", [])
        by_title = {page.get("title"): page for page in pages}
        with self.db.transaction() as conn:
            for row in requested:
                requested_title = "File:" + str(row["dump_title"])
                title = normalized.get(requested_title, requested_title)
                page = by_title.get(title)
                if page is None:
                    # API can return a further normalized/redirected title; match underscore-insensitively.
                    key = title.replace("_", " ").casefold()
                    page = next((p for p in pages if str(p.get("title", "")).casefold() == key), None)
                info = (page or {}).get("imageinfo", [])
                if not page or not info:
                    conn.execute(
                        "UPDATE images SET metadata_status='done',classification='REVIEW',"
                        "classification_reason=?,api_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        ("file missing or imageinfo unavailable", json.dumps(page, ensure_ascii=False), row["id"]),
                    )
                    continue
                image = info[0]
                ext = image.get("extmetadata") or {}
                fields = {key: metadata_value(ext, key) for key in EXT_FIELDS}
                conn.execute(
                    """UPDATE images SET canonical_title=?,pageid=?,thumb_url=?,mime=?,thumb_mime=?,
                    sha1=?,width=?,height=?,byte_size=?,description_url=?,license_short_name=?,
                    license_url=?,artist=?,credit=?,attribution=?,attribution_required=?,copyrighted=?,
                    non_free=?,permission=?,restrictions_text=?,extmetadata_json=?,api_json=?,
                    metadata_status='done',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (
                        image.get("canonicaltitle") or page.get("title"), page.get("pageid"),
                        image.get("thumburl"), image.get("mime"), image.get("thumbmime"), image.get("sha1"),
                        image.get("width"), image.get("height"), image.get("size"), image.get("descriptionurl"),
                        fields["LicenseShortName"], fields["LicenseUrl"], fields["Artist"], fields["Credit"],
                        fields["Attribution"], fields["AttributionRequired"], fields["Copyrighted"],
                        fields["NonFree"], fields["Permission"], fields["Restrictions"],
                        json.dumps(ext, ensure_ascii=False), json.dumps(page, ensure_ascii=False), row["id"],
                    ),
                )


def classify_pending(db: Database, control: Control, progress: ProgressCallback = null_progress) -> int:
    from .license import classify

    with db.connect() as conn:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM images WHERE metadata_status='done' AND classification IS NULL"
        ).fetchone()[0])
    done, last_id = 0, 0
    while True:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id,extmetadata_json FROM images WHERE metadata_status='done' "
                "AND classification IS NULL AND id>? ORDER BY id LIMIT 5000", (last_id,),
            ).fetchall()
        if not rows:
            break
        last_id = int(rows[-1]["id"])
        with db.transaction() as conn:
            for row in rows:
                control.checkpoint()
                ext = json.loads(row["extmetadata_json"] or "{}")
                decision = classify(ext)
                conn.execute(
                    "UPDATE images SET classification=?,classification_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (decision.state, decision.reason, row["id"]),
                )
                done += 1
            progress({"stage": "classify", "done": done, "total": total})
    return total
