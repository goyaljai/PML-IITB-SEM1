from fastapi import HTTPException, Header
from db import get_db
import base64


def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decoded = base64.b64decode(authorization[6:]).decode()
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    conn = get_db()
    row = conn.execute(
        "SELECT username, role FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": row["username"], "role": row["role"]}
