# IPL Grid Annotation — Labelling Setup & Process

This document describes the annotation infrastructure built for the IITB PML Sem1 project, how it works, and how to use it.

---

## Overview

We needed to label **1000 IPL cricket broadcast images** at a fine-grained level — not just "which teams are playing" but **which cells of an 8×8 grid contain players from which team**. Each image is divided into a 64-cell grid (8 rows × 8 columns, each cell 100×75 px), and every cell gets an integer label:

| Label | Team |
|---|---|
| 0 | Empty / No player |
| 1 | CSK |
| 2 | DC |
| 3 | GT |
| 4 | KKR |
| 5 | LSG |
| 6 | MI |
| 7 | PBKS |
| 8 | RR |
| 9 | RCB |
| 10 | SRH |

This gives us a **64-label annotation per image**, which will be used downstream to extract per-cell features (HSV histograms, colour moments, HOG descriptors, LBP texture) for a supervised classification model.

---

## Dataset

- **Total images:** 1000 (963 original game images + 37 "no-player" images)
- **Image size:** 800 × 600 px JPEG (all uniform)
- **Train/test split:** 788 train / 212 test (pre-assigned, not touched during renaming)
- **Naming convention:** `img_1.jpg` through `img_1000.jpg`
  - `img_1` – `img_250`: original game images (first batch)
  - `img_251` – `img_287`: the 37 no-player images (inserted in the middle)
  - `img_288` – `img_1000`: original game images (second batch)

The no-player images were originally named with a `np_` prefix. They were renumbered into the middle of the sequence intentionally so the index range stays clean while keeping them identifiable by position. The `split` column (train/test) in the database was preserved through the rename.

---

## Annotation Tool

A custom web-based annotation tool was built from scratch for this project. It runs as a FastAPI backend + React/Vite frontend.

### Architecture

```
browser  ──→  React frontend (Vite)
               └─ served from /opt/ipl-annotator/frontend/dist (production)
                  or localhost:5173 (dev)

               ──→  FastAPI backend (port 8001)
                       ├─ SQLite DB (annotator.db)
                       │     ├─ users table
                       │     ├─ images table (filename, split, status, lock state)
                       │     └─ annotations table (image_id, annotator, labels JSON, updated_at)
                       └─ Images on disk (/opt/ipl-annotator/images/)
```

### Key Features

**Grid painting interface**
Click or drag across the 8×8 overlay to paint team labels onto cells. The grid is rendered as a canvas overlay on top of the actual image. Each team has a distinct colour and a keyboard shortcut (keys 1–9 for CSK–RCB, key `0` for SRH which has label 10).

**Real-time autosave**
Every paint action triggers a debounced save (800ms). The backend receives the full 8×8 label matrix and upserts it. The frontend shows a live save badge (Unsaved → Saving → Saved).

**Collaborative locking**
Multiple annotators work simultaneously. When a user opens an image, it gets locked to them for 3 minutes. The lock auto-refreshes via a heartbeat every 30 seconds. Other users see the image as locked in the sidebar. Locks expire automatically if the user closes the tab without unlocking.

**Fast navigation**
- Arrow keys / Space: previous/next image
- Tab: jump to the next unannotated (pending) image
- Keyboard shortcuts for all team labels

**Undo/Redo**
Full undo/redo history (up to 30 states) stored in the frontend — Ctrl+Z / Ctrl+Shift+Z. Undo/redo also triggers autosave.

**Live sidebar**
The image list polls every 3 seconds and updates each image's status (pending/done), who annotated it, and who currently has it locked.

**Admin controls**
All 5 annotators have admin role. Admins can:
- Force-unlock any image stuck under another user's lock
- Overwrite any annotation (other users can only edit their own)
- Export annotations as CSV or JSON
- Trigger feature extraction (see below)

**Progress counter**
Top bar shows: `annotated / total done · mine mine`. Updates in real time.

---

## Infrastructure

The tool is deployed on a GCP VM (`aosp-build-vm-3`, zone `asia-south1-a`).

- **URL:** http://35.207.192.90:8001
- **Backend:** uvicorn with 4 workers, running inside a `tmux` session named `ipl`
- **Database:** SQLite at `/opt/ipl-annotator/backend/annotator.db` (WAL mode for concurrent reads)
- **Images:** `/opt/ipl-annotator/images/`
- **Firewall:** GCP VPC rule `ipl-annotator` on `glancecdn-sandbox-main-vpc` allowing TCP:8001

To restart the server after a VM reboot:
```bash
tmux new-session -d -s ipl 'cd /opt/ipl-annotator/backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4'
```

---

## Annotators

| Username | Password | Role |
|---|---|---|
| jai | jai | admin |
| sharon | sharon | admin |
| rishabh | rishabh | admin |
| ashutosh | ashutosh | admin |
| udit | udit | admin |

---

## Annotation Process

1. Open http://35.207.192.90:8001 and log in
2. The sidebar shows all 1000 images. Green = annotated, white = pending, yellow padlock = locked by someone else
3. Press **Tab** to jump to the next pending image
4. Select a team from the toolbar (or use keyboard shortcut)
5. Click/drag cells on the grid to label them
6. Autosave fires 800ms after the last paint — watch the "Saved" badge
7. Press Space or Tab to move to the next image — pending save is flushed before navigating
8. Use Erase mode (key `E`) or right-click to clear a cell back to 0
9. Ctrl+Z / Ctrl+Shift+Z to undo/redo

**Ground truth for no-player images (img_251–img_287):** All 64 cells should be labelled 0 (empty). These images are crowd shots, scoreboards, or venue wide-shots with no visible players.

---

## Feature Extraction

Once all 1000 images are annotated, an admin can click the **⚗ Features** button in the toolbar. This triggers a background extraction job that:

1. Reads all annotations from the database
2. Opens each image, resizes to 800×600, crops 64 cells
3. For each cell, computes:
   - **HSV histogram** (96 features: 32 bins × 3 channels)
   - **Colour moments** (9 features: mean/std/skew for H, S, V)
   - **HOG descriptor** (3168 features: 9 orientations, 8×8 px cells, 2×2 block norm)
   - **LBP texture histogram** (10 features: uniform LBP, P=8, R=1)
   - **Player count** heuristic: number of grid columns containing that team ÷ 2
4. Writes everything to `/opt/ipl-annotator/features.csv` (~64,000 rows, one per cell)

The toolbar shows a live progress bar (polls every 2s). When extraction completes, `features.csv` auto-downloads. Total extraction time for 1000 images ≈ 20–30 minutes.

### CSV Schema

```
image_filename, split, cell_index, row, col, label, team_name, player_count,
hsv_h_0..31, hsv_s_0..31, hsv_v_0..31,
cm_h_mean, cm_h_std, cm_h_skew, cm_s_mean, ..., cm_v_skew,
hog_0..3167,
lbp_0..9
```

Total features per cell: **3283**

---

## Export Formats

The **⬇ CSV** button exports a flat annotation CSV:

```
Image File Name, Train Or Test, c01, c02, ..., c64
img_1.jpg, Train, 0, 0, 3, 3, ...
```

The **⬇ JSON** button exports:
```json
[
  {
    "image": "img_1.jpg",
    "split": "train",
    "labels": [[0,0,...], [3,3,...],...],
    "features": [0,0,3,3,...,0]
  }
]
```

---

## Technical Notes

**Save race fix:** Navigation (Space/Tab/Arrow) now flushes any pending debounced save synchronously before switching images. Previously, fast navigation could silently drop the last paint on an image.

**Atomic CSV writes:** Feature extraction writes to `features.tmp` and renames to `features.csv` only on completion. A mid-run crash leaves no corrupt file.

**Multi-worker job state:** Feature extraction status is persisted to `.feat_job.json` on disk so all 4 uvicorn workers see the same state when polled.

**All-empty save:** If a user clears all 64 cells, the annotation record is deleted and the image reverts to "pending" — it won't appear as annotated in the export.
