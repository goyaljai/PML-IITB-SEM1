from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from auth import get_current_user
from db import get_db
from events import notify
import json

router = APIRouter()

LOCK_TIMEOUT_SECONDS = 180


class SaveAnnotation(BaseModel):
    labels: List[List[int]]  # 8x8
    count: Optional[int] = None  # player count 0-20


@router.get("/annotations/{image_id}")
def get_annotation(image_id: int, user=Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT labels, annotator, count, updated_at FROM annotations WHERE image_id=?",
        (image_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"labels": [[0]*8 for _ in range(8)], "annotator": None, "count": None}
    return {
        "labels": json.loads(row["labels"]),
        "annotator": row["annotator"],
        "count": row["count"],
        "updated_at": row["updated_at"]
    }


@router.post("/annotations/{image_id}")
def save_annotation(image_id: int, body: SaveAnnotation, user=Depends(get_current_user)):
    if len(body.labels) != 8 or any(len(r) != 8 for r in body.labels):
        raise HTTPException(400, "Labels must be 8x8")

    conn = get_db()

    # Check if already annotated by someone else (admins can overwrite any annotation)
    existing = conn.execute(
        "SELECT annotator FROM annotations WHERE image_id=?", (image_id,)
    ).fetchone()
    if existing and existing["annotator"] != user["username"] and user["role"] != "admin":
        conn.close()
        raise HTTPException(423, f"Already annotated by {existing['annotator']}")

    # Check lock — must hold the lock to save
    lock_row = conn.execute("""
        SELECT locked_by FROM images
        WHERE id=? AND (
            locked_by=? OR
            locked_by IS NULL OR
            (strftime('%s','now') - strftime('%s', locked_at)) > ?
        )
    """, (image_id, user["username"], LOCK_TIMEOUT_SECONDS)).fetchone()

    if not lock_row:
        conn.close()
        raise HTTPException(423, "Image is locked by another user")

    flat = [v for row in body.labels for v in row]
    all_empty = not any(v != 0 for v in flat)

    # Check if this is a designated no-player image (img_251–img_287) — keep as done even if all zeros
    img_row = conn.execute("SELECT filename FROM images WHERE id=?", (image_id,)).fetchone()
    filename = img_row["filename"] if img_row else ""
    try:
        num = int(filename.replace("img_", "").replace(".jpg", ""))
        is_no_player = 251 <= num <= 287
    except ValueError:
        is_no_player = False

    # No-player images always get count=0
    effective_count = 0 if is_no_player else body.count
    has_count = effective_count is not None and 0 <= effective_count <= 20

    if all_empty and not is_no_player and effective_count != 0:
        # No meaningful annotation — delete record and reset to pending
        conn.execute("DELETE FROM annotations WHERE image_id=?", (image_id,))
        conn.execute("UPDATE images SET status='pending', locked_by=NULL, locked_at=NULL WHERE id=?", (image_id,))
    else:
        count_val = effective_count if has_count else None
        # Only mark done when count is also set
        new_status = 'done' if has_count else 'pending'
        conn.execute("""
            INSERT INTO annotations (image_id, annotator, labels, count, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(image_id) DO UPDATE SET
                labels=excluded.labels,
                annotator=excluded.annotator,
                count=excluded.count,
                updated_at=CURRENT_TIMESTAMP
        """, (image_id, user["username"], json.dumps(body.labels), count_val))
        conn.execute("UPDATE images SET status=?, locked_by=NULL, locked_at=NULL WHERE id=?", (new_status, image_id))

    conn.commit()
    conn.close()
    notify()
    return {"ok": True}
