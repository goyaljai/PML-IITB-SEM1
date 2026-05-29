from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from auth import get_current_user
from db import get_db, seed_images
from events import notify

router = APIRouter()

DATASET_DIR = Path("/opt/ipl-annotator/images")
LOCK_TIMEOUT_SECONDS = 180  # 3 minutes


@router.post("/seed")
def seed(user=Depends(get_current_user)):
    added = seed_images()
    return {"added": added}


@router.get("/images")
def list_images(user=Depends(get_current_user)):
    conn = get_db()
    # Expire stale locks
    conn.execute("""
        UPDATE images SET locked_by=NULL, locked_at=NULL
        WHERE locked_by IS NOT NULL
          AND (strftime('%s','now') - strftime('%s', locked_at)) > ?
    """, (LOCK_TIMEOUT_SECONDS,))
    conn.commit()

    rows = conn.execute("""
        SELECT i.id, i.filename, i.status, i.locked_by, i.locked_at,
               a.annotator, a.updated_at as annotated_at
        FROM images i
        LEFT JOIN annotations a ON i.id = a.image_id
        ORDER BY CAST(SUBSTR(i.filename, 5, LENGTH(i.filename)-8) AS INTEGER)
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/images/progress")
def progress(user=Depends(get_current_user)):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM images WHERE status='done'").fetchone()[0]
    mine = conn.execute(
        "SELECT COUNT(*) FROM annotations a JOIN images i ON i.id=a.image_id WHERE i.status='done' AND a.annotator=?",
        (user["username"],)
    ).fetchone()[0]
    per_user = conn.execute(
        """SELECT a.annotator, COUNT(*) as cnt
           FROM annotations a JOIN images i ON i.id=a.image_id
           WHERE i.status='done'
           GROUP BY a.annotator ORDER BY cnt DESC"""
    ).fetchall()
    pending = total - done
    conn.close()
    return {
        "total": total, "annotated": done, "mine": mine, "pending": pending,
        "per_user": {r["annotator"]: r["cnt"] for r in per_user}
    }


@router.post("/images/{image_id}/lock")
def lock_image(image_id: int, user=Depends(get_current_user)):
    conn = get_db()

    # Expire stale locks first
    conn.execute("""
        UPDATE images SET locked_by=NULL, locked_at=NULL
        WHERE locked_by IS NOT NULL
          AND (strftime('%s','now') - strftime('%s', locked_at)) > ?
    """, (LOCK_TIMEOUT_SECONDS,))

    row = conn.execute("SELECT status, locked_by, annotator FROM images i LEFT JOIN annotations a ON i.id=a.image_id WHERE i.id=?", (image_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Image not found")

    # Already annotated by someone else (admin can override)
    if row["status"] == "done" and row["annotator"] and row["annotator"] != user["username"]:
        if user["role"] != "admin":
            conn.close()
            raise HTTPException(423, f"Already annotated by {row['annotator']}")

    # Locked by someone else (admin can override)
    if row["locked_by"] and row["locked_by"] != user["username"]:
        if user["role"] != "admin":
            conn.close()
            raise HTTPException(423, f"Currently being edited by {row['locked_by']}")

    conn.execute("""
        UPDATE images SET locked_by=?, locked_at=CURRENT_TIMESTAMP WHERE id=?
    """, (user["username"], image_id))
    conn.commit()
    conn.close()
    notify()
    return {"ok": True}


@router.post("/images/{image_id}/unlock")
def unlock_image(image_id: int, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("""
        UPDATE images SET locked_by=NULL, locked_at=NULL
        WHERE id=? AND locked_by=?
    """, (image_id, user["username"]))
    conn.commit()
    conn.close()
    notify()
    return {"ok": True}


@router.post("/images/{image_id}/force-unlock")
def force_unlock(image_id: int, user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    conn = get_db()
    conn.execute("UPDATE images SET locked_by=NULL, locked_at=NULL WHERE id=?", (image_id,))
    conn.commit()
    conn.close()
    notify()
    return {"ok": True}


@router.post("/images/{image_id}/heartbeat")
def heartbeat(image_id: int, user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("""
        UPDATE images SET locked_at=CURRENT_TIMESTAMP
        WHERE id=? AND locked_by=?
    """, (image_id, user["username"]))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int):
    conn = get_db()
    row = conn.execute("SELECT filename FROM images WHERE id=?", (image_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Image not found")
    path = DATASET_DIR / row["filename"]
    if not path.exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(str(path), media_type="image/jpeg")
