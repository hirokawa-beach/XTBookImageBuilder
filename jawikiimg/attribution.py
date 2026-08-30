from __future__ import annotations

from pathlib import Path
import csv
import html
import json

from .db import Database
from .license import ALLOW_STATES


FIELDS = (
    "dump_title", "canonical_title", "artist", "attribution", "credit",
    "license_short_name", "license_url", "description_url", "sha1", "mime",
    "classification", "classification_reason",
)


def write_attribution(db: Database, output_dir: Path, snapshot_date: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    placeholders = ",".join("?" for _ in ALLOW_STATES)
    query = (
        f"SELECT {','.join(FIELDS)} FROM images WHERE classification IN ({placeholders}) "
        "AND convert_status='done' ORDER BY dump_title COLLATE NOCASE"
    )
    params = tuple(sorted(ALLOW_STATES))
    with (output_dir / "licenses.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        with db.connect() as conn:
            writer.writerows(dict(row) for row in conn.execute(query, params))
    html_path = output_dir / "ATTRIBUTION.html"
    with html_path.open("w", encoding="utf-8") as out:
        out.write(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>画像の帰属情報</title>
<style>body{{font-family:sans-serif;line-height:1.45;margin:2rem}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #aaa;padding:.35rem;text-align:left;vertical-align:top}}thead{{background:#eee}}</style></head>
<body><h1>XTBook 日本語Wikipedia画像辞書 — 帰属情報</h1>
<p>Wikipedia dump snapshot: {html.escape(snapshot_date)}. This list contains only images included in the dictionary.</p>
<table><thead><tr><th>元ファイル名</th><th>作者 / Attribution</th><th>ライセンス</th><th>説明ページ</th></tr></thead>
<tbody>""")
        with db.connect() as conn:
            for row in conn.execute(query, params):
                title = html.escape(row["dump_title"] or "")
                creator = html.escape(row["attribution"] or row["artist"] or row["credit"] or "(not supplied)")
                license_name = html.escape(row["license_short_name"] or "")
                license_url = html.escape(row["license_url"] or "", quote=True)
                description_url = html.escape(row["description_url"] or "", quote=True)
                license_html = f'<a href="{license_url}">{license_name}</a>' if license_url else license_name
                source_html = f'<a href="{description_url}">Wikimedia description page</a>'
                out.write(f"<tr><td>{title}</td><td>{creator}</td><td>{license_html}</td><td>{source_html}</td></tr>\n")
        out.write("</tbody></table></body></html>")


def write_report(db: Database, output_dir: Path, snapshot_date: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = db.counts()
    review_fields = (
        "dump_title", "canonical_title", "classification", "classification_reason",
        "license_short_name", "license_url", "artist", "attribution", "credit",
        "description_url", "attribution_required", "copyrighted", "non_free",
        "permission", "restrictions_text",
    )
    error_fields = ("dump_title", "metadata_status", "download_status", "convert_status", "error")
    with (output_dir / "review.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=review_fields)
        writer.writeheader()
        with db.connect() as conn:
            writer.writerows(dict(row) for row in conn.execute(
                f"SELECT {','.join(review_fields)} FROM images "
                "WHERE classification IN ('REVIEW','DENY') ORDER BY id"
            ))
    with (output_dir / "errors.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=error_fields)
        writer.writeheader()
        with db.connect() as conn:
            writer.writerows(dict(row) for row in conn.execute(
                f"SELECT {','.join(error_fields)} FROM images WHERE error IS NOT NULL ORDER BY id"
            ))
    with db.connect() as conn:
        error_count = int(conn.execute("SELECT COUNT(*) FROM images WHERE error IS NOT NULL").fetchone()[0])
    report = {
        "snapshot_date": snapshot_date,
        "counts": counts,
        "review_and_deny_file": "review.csv",
        "errors_file": "errors.csv",
        "error_count": error_count,
        "policy": {"automatic_allow": sorted(ALLOW_STATES), "review_and_deny_downloaded": False},
    }
    path = output_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
