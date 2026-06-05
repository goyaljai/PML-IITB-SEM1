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


TOP_IMAGES = ['img_271.jpg', 'img_522.jpg', 'img_517.jpg', 'img_661.jpg', 'img_889.jpg', 'img_18.jpg', 'img_281.jpg', 'img_68.jpg', 'img_67.jpg', 'img_753.jpg', 'img_776.jpg', 'img_201.jpg', 'img_91.jpg', 'img_86.jpg', 'img_88.jpg', 'img_605.jpg', 'img_888.jpg', 'img_749.jpg', 'img_276.jpg', 'img_423.jpg', 'img_790.jpg', 'img_490.jpg', 'img_10.jpg', 'img_299.jpg', 'img_768.jpg', 'img_425.jpg', 'img_217.jpg', 'img_804.jpg', 'img_267.jpg', 'img_457.jpg', 'img_73.jpg', 'img_72.jpg', 'img_347.jpg', 'img_24.jpg', 'img_815.jpg', 'img_89.jpg', 'img_138.jpg', 'img_379.jpg', 'img_33.jpg', 'img_353.jpg', 'img_344.jpg', 'img_402.jpg', 'img_814.jpg', 'img_417.jpg', 'img_135.jpg', 'img_515.jpg', 'img_90.jpg', 'img_992.jpg', 'img_456.jpg', 'img_454.jpg', 'img_422.jpg', 'img_298.jpg', 'img_717.jpg', 'img_750.jpg', 'img_1006.jpg', 'img_294.jpg', 'img_144.jpg']

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

    placeholders = ','.join(['?'] * len(TOP_IMAGES))
    rows = conn.execute(f"""
        SELECT i.id, i.filename, i.status, i.locked_by, i.locked_at,
               a.annotator, a.updated_at as annotated_at
        FROM images i
        LEFT JOIN annotations a ON i.id = a.image_id
        WHERE i.filename IN ({placeholders})
    """, tuple(TOP_IMAGES)).fetchall()
    conn.close()
    
    # Sort the rows exactly as they appear in the TOP_IMAGES array
    order_map = {filename: index for index, filename in enumerate(TOP_IMAGES)}
    sorted_rows = sorted([dict(r) for r in rows], key=lambda x: order_map[x['filename']])
    
    return sorted_rows


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


_HF_DATASET_DIR = None
def get_dataset_dir():
    return Path("/Users/jai.goyal/Documents/ipl/final_dataset")

@router.get("/images/{image_id}/file")
def get_image_file(image_id: int):
    conn = get_db()
    row = conn.execute("SELECT filename FROM images WHERE id=?", (image_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Image not found")
        
    dataset_dir = get_dataset_dir()
    
    path = dataset_dir / row["filename"]
        
    if not path.exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(str(path), media_type="image/jpeg")
