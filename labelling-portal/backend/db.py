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
    dataset_dir = Path("/Users/jai.goyal/Documents/ipl/final_dataset")
    
    # 1. Insert all images
    for f in sorted(dataset_dir.rglob("*.jpg")):
        try:
            conn.execute("INSERT OR IGNORE INTO images (filename) VALUES (?)", (f.name,))
            added += conn.execute("SELECT changes()").fetchone()[0]
        except Exception:
            pass
            
    # 2. Insert annotations from Dataset_Annotations.csv
    csv_path = Path("/Users/jai.goyal/PML-IITB-SEM1/Dataset_Annotations.csv")
    if csv_path.exists():
        import pandas as pd
        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            img_name = row['Image File Name']
            img_row = conn.execute("SELECT id FROM images WHERE filename=?", (img_name,)).fetchone()
            if img_row:
                img_id = img_row["id"]
                # Build labels JSON array (8x8)
                labels = [[0]*8 for _ in range(8)]
                for i in range(1, 65):
                    val = row[f'c{i:02d}']
                    if pd.notna(val) and val > 0:
                        labels[(i-1)//8][(i-1)%8] = int(val)
                count = int(row['count']) if pd.notna(row['count']) else None
                labels_str = json.dumps(labels)
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO annotations (image_id, annotator, labels, count)
                        VALUES (?, ?, ?, ?)
                    """, (img_id, 'jai', labels_str, count))
                    conn.execute("UPDATE images SET status='done' WHERE id=?", (img_id,))
                except Exception:
                    pass
    conn.commit()
    conn.close()
    return added


init_db()
