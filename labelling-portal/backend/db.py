import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "annotator.db"
DATASET_DIR = Path("/opt/ipl-annotator/images")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'annotator'
        );

        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            split TEXT DEFAULT 'train',
            status TEXT DEFAULT 'pending',
            locked_by TEXT DEFAULT NULL,
            locked_at TIMESTAMP DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL UNIQUE,
            annotator TEXT NOT NULL,
            labels TEXT NOT NULL,
            count INTEGER DEFAULT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO users VALUES ('sharon',   'sharon',   'admin');
        INSERT OR IGNORE INTO users VALUES ('rishabh',  'rishabh',  'admin');
        INSERT OR IGNORE INTO users VALUES ('ashutosh', 'ashutosh', 'admin');
        INSERT OR IGNORE INTO users VALUES ('udit',     'udit',     'admin');
        INSERT OR IGNORE INTO users VALUES ('jai',      'jai',      'admin');
    """)
    conn.commit()

    # Idempotent migration: add count column if missing
    try:
        conn.execute("ALTER TABLE annotations ADD COLUMN count INTEGER DEFAULT NULL")
        conn.commit()
    except Exception:
        pass  # column already exists

    # Any done image without a count is not fully annotated — reset to pending
    conn.execute("""
        UPDATE images SET status='pending'
        WHERE status='done' AND id IN (
            SELECT image_id FROM annotations WHERE count IS NULL
        )
    """)
    conn.commit()
    conn.close()


def seed_images():
    conn = get_db()
    added = 0
    for f in sorted(DATASET_DIR.glob("*.jpg")):
        try:
            conn.execute("INSERT OR IGNORE INTO images (filename) VALUES (?)", (f.name,))
            added += conn.execute("SELECT changes()").fetchone()[0]
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


init_db()
