from __future__ import annotations

from collections.abc import Iterable
import json

from .db import Database
from .license import classify, supported_allow_state


def _ids(values: Iterable[int]) -> tuple[int, ...]:
    result = tuple(dict.fromkeys(int(value) for value in values))
    if not result:
        raise ValueError("画像が選択されていません")
    return result


def approve_reviews(db: Database, image_ids: Iterable[int], note: str) -> int:
    ids = _ids(image_ids)
    placeholders = ",".join("?" for _ in ids)
    with db.transaction() as conn:
        rows = conn.execute(
            f"SELECT id,dump_title,classification,classification_reason,license_short_name,license_url,"
            f"manual_override FROM images WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
        if len(rows) != len(ids):
            raise ValueError("選択された画像の一部が見つかりません")
        updates = []
        for row in rows:
            if row["classification"] != "REVIEW" or row["manual_override"] is not None:
                raise ValueError(f"{row['dump_title']}: 自動REVIEWの画像だけを承認できます")
            state = supported_allow_state(row["license_short_name"] or "", row["license_url"] or "")
            if state is None:
                raise ValueError(
                    f"{row['dump_title']}: 対応ライセンスを一意に特定できないため承認できません"
                )
            previous = str(row["classification_reason"] or "")
            audit_note = note.strip() or "GUIで内容を確認"
            reason = f"manual approval ({state}): {audit_note}; previous: {previous}"
            updates.append((state, reason, state, audit_note, int(row["id"])))
        conn.executemany(
            """UPDATE images SET classification=?,classification_reason=?,manual_override=?,
            manual_note=?,manual_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            updates,
        )
    return len(updates)


def deny_reviews(db: Database, image_ids: Iterable[int], note: str) -> int:
    ids = _ids(image_ids)
    placeholders = ",".join("?" for _ in ids)
    with db.transaction() as conn:
        rows = conn.execute(
            f"SELECT id,dump_title,classification,classification_reason,manual_override "
            f"FROM images WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
        if len(rows) != len(ids):
            raise ValueError("選択された画像の一部が見つかりません")
        updates = []
        for row in rows:
            if row["classification"] != "REVIEW" or row["manual_override"] is not None:
                raise ValueError(f"{row['dump_title']}: 自動REVIEWの画像だけを手動DENYにできます")
            audit_note = note.strip() or "GUIで内容を確認"
            reason = f"manual deny: {audit_note}; previous: {row['classification_reason'] or ''}"
            updates.append((reason, audit_note, int(row["id"])))
        conn.executemany(
            """UPDATE images SET classification='DENY',classification_reason=?,manual_override='DENY',
            manual_note=?,manual_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            updates,
        )
    return len(updates)


def clear_manual_decisions(db: Database, image_ids: Iterable[int]) -> int:
    ids = _ids(image_ids)
    placeholders = ",".join("?" for _ in ids)
    with db.transaction() as conn:
        rows = conn.execute(
            f"SELECT id,dump_title,extmetadata_json,manual_override FROM images "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
        if len(rows) != len(ids):
            raise ValueError("選択された画像の一部が見つかりません")
        updates = []
        for row in rows:
            if row["manual_override"] is None:
                raise ValueError(f"{row['dump_title']}: 手動判定されていません")
            extmetadata = json.loads(row["extmetadata_json"] or "{}")
            decision = classify(extmetadata)
            updates.append((decision.state, decision.reason, int(row["id"])))
        conn.executemany(
            """UPDATE images SET classification=?,classification_reason=?,manual_override=NULL,
            manual_note=NULL,manual_updated_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            updates,
        )
    return len(updates)
