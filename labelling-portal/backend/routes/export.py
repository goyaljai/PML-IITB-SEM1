from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from auth import get_current_user
from db import get_db
import json
import csv
import io

router = APIRouter()

TEAMS = {0:"none",1:"CSK",2:"DC",3:"GT",4:"KKR",5:"LSG",6:"MI",7:"PBKS",8:"RR",9:"RCB",10:"SRH"}


from routes.images import TOP_IMAGES

@router.get("/export/csv")
def export_csv(user=Depends(get_current_user)):
    conn = get_db()
    placeholders = ','.join(['?'] * len(TOP_IMAGES))
    rows = conn.execute(f"""
        SELECT i.filename, i.split, a.labels, a.annotator, a.count
        FROM annotations a
        JOIN images i ON i.id = a.image_id
        WHERE i.status = 'done' AND i.filename IN ({placeholders})
        ORDER BY CAST(SUBSTR(i.filename, 5, LENGTH(i.filename)-8) AS INTEGER)
    """, tuple(TOP_IMAGES)).fetchall()
    conn.close()

    output = io.StringIO()
    cols = ["Image File Name", "Train Or Test", "count"] + [f"c{i+1:02d}" for i in range(64)]
    writer = csv.DictWriter(output, fieldnames=cols)
    writer.writeheader()

    for r in rows:
        labels = json.loads(r["labels"])
        flat = [v for row in labels for v in row]
        row_dict = {
            "Image File Name": r["filename"],
            "Train Or Test": r["split"].capitalize(),
            "count": r["count"] if r["count"] is not None else "",
        }
        for i, v in enumerate(flat):
            row_dict[f"c{i+1:02d}"] = v
        writer.writerow(row_dict)

    output.seek(0)
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=annotations.csv"}
    )


@router.get("/export/json")
def export_json(user=Depends(get_current_user)):
    conn = get_db()
    placeholders = ','.join(['?'] * len(TOP_IMAGES))
    rows = conn.execute(f"""
        SELECT i.filename, i.split, a.labels
        FROM annotations a
        JOIN images i ON i.id = a.image_id
        WHERE i.status = 'done' AND i.filename IN ({placeholders})
        ORDER BY i.split, i.filename
    """, tuple(TOP_IMAGES)).fetchall()
    conn.close()

    result = []
    for r in rows:
        labels = json.loads(r["labels"])
        flat = [v for row in labels for v in row]
        result.append({
            "image": r["filename"],
            "split": r["split"],
            "labels": labels,
            "features": flat,
        })

    output = json.dumps(result, indent=2)
    from fastapi.responses import Response
    return Response(
        content=output,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=annotations.json"}
    )


@router.get("/stats")
def stats(user=Depends(get_current_user)):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    annotated = conn.execute("SELECT COUNT(DISTINCT image_id) FROM annotations").fetchone()[0]
    per_user = conn.execute("""
        SELECT annotator, COUNT(*) as cnt FROM annotations GROUP BY annotator
    """).fetchall()
    team_dist = {}
    rows = conn.execute("SELECT labels FROM annotations").fetchall()
    for r in rows:
        flat = [v for row in json.loads(r["labels"]) for v in row]
        for v in flat:
            if v != 0:
                team_dist[TEAMS.get(v, str(v))] = team_dist.get(TEAMS.get(v, str(v)), 0) + 1
    conn.close()
    return {
        "total_images": total,
        "annotated": annotated,
        "pending": total - annotated,
        "per_user": {r["annotator"]: r["cnt"] for r in per_user},
        "team_cell_distribution": team_dist,
    }
