# IPL Grid Annotation — Labelling Setup & Process

This document covers what we're labelling, the annotation rules, the tool we built, and the infrastructure behind it.

---

## What We're Labelling

Each of the 1000 IPL broadcast images is divided into an **8×8 grid** (64 cells, each 100×75 px). Every cell gets one of 11 labels:

| Label | Team |
|---|---|
| 0 | Empty / No player |
| 1 | CSK — Chennai Super Kings |
| 2 | DC — Delhi Capitals |
| 3 | GT — Gujarat Titans |
| 4 | KKR — Kolkata Knight Riders |
| 5 | LSG — Lucknow Super Giants |
| 6 | MI — Mumbai Indians |
| 7 | PBKS — Punjab Kings |
| 8 | RR — Rajasthan Royals |
| 9 | RCB — Royal Challengers Bangalore |
| 10 | SRH — Sunrisers Hyderabad |

The goal is cell-level team identification — not just "which teams are in this image" but **exactly which cells contain players from which team**. These 64 labels per image feed into per-cell feature extraction (HSV, colour moments, HOG, LBP) for a supervised classification model.

---

## Dataset

- **Total images:** 1000 (963 game images + 37 no-player images)
- **Image size:** 800 × 600 px JPEG (uniform)
- **Train/test split:** 788 train / 212 test (pre-assigned, preserved through all renames)
- **Naming:** `img_1.jpg` – `img_1000.jpg`
  - `img_1` – `img_250`: game images batch 1
  - `img_251` – `img_287`: no-player images (crowd / scoreboard / venue)
  - `img_288` – `img_1000`: game images batch 2

---

## Annotation Rules

1. **Paint every cell with a visible player** using that player's team label
2. **Leave empty cells at 0** — grass, crowd, scoreboard, watermarks, umpires, support staff
3. **Partial visibility counts** — if the jersey is identifiable, label it
4. **Ambiguous cells** — if you genuinely cannot tell, leave as 0
5. **Both teams on screen** — label each cell with whichever team's player occupies it (both teams can appear in the same image)
6. **No-player images (img_251–img_287)** — leave all 64 cells at 0, move on immediately

---

## Annotators

| Username | Password | Role |
|---|---|---|
| jai | jai | admin |
| sharon | sharon | admin |
| rishabh | rishabh | admin |
| ashutosh | ashutosh | admin |
| udit | udit | admin |

Each image is locked to one annotator at a time. Any admin can force-unlock a stuck image. Admins can also overwrite any annotation.

---

## Annotation Tool

A custom web tool was built for this task: **http://35.207.192.90:8001**

### How to Use

1. Log in with your credentials
2. The sidebar lists all 1000 images — green = done, white = pending, yellow padlock = locked by someone else
3. Press **Tab** to jump to the next pending image
4. Select a team from the toolbar or use keyboard shortcuts
5. Click or drag cells on the grid to paint labels
6. Autosave fires 800ms after the last paint — watch the **Saved** badge bottom-right
7. Press **Space** or **Tab** to move on — any pending save is flushed before switching
8. Use **Erase** (key `E`) or right-click to clear a cell back to 0
9. **Ctrl+Z** / **Ctrl+Shift+Z** to undo/redo

### Keyboard Shortcuts

| Action | Key |
|---|---|
| Select CSK–RCB | `1`–`9` |
| Select SRH (label 10) | `0` |
| Erase mode | `E` |
| Next image | `Space` or `→` |
| Previous image | `←` |
| Jump to next pending | `Tab` |
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Shift+Z` |

### Tool Features

- **Grid overlay** — 8×8 canvas rendered over the image; click or drag to paint
- **Autosave** — debounced 800ms save on every paint action; navigation flushes pending saves
- **Collaborative locking** — image locked to one user for 3 minutes, 30s heartbeat renewal, auto-expires
- **Undo/Redo** — 30-state history in the frontend
- **Live sidebar** — polls every 3s, shows who has what locked and what's done
- **Progress counter** — toolbar shows annotated/total and per-user count
- **Admin force-unlock** — unstick images locked by disconnected users

---

## Infrastructure

| | |
|---|---|
| **URL** | http://35.207.192.90:8001 |
| **VM** | `aosp-build-vm-3`, GCP `asia-south1-a` |
| **Backend** | FastAPI + uvicorn (4 workers), tmux session `ipl` |
| **DB** | SQLite WAL at `/opt/ipl-annotator/backend/annotator.db` |
| **Images** | `/opt/ipl-annotator/images/` |

To restart the server after a VM reboot:
```bash
tmux new-session -d -s ipl 'cd /opt/ipl-annotator/backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4'
```

---

## Feature Extraction

Once all 1000 images are annotated, click **⚗ Features** in the toolbar. This runs a background job (~20–30 min) that:

1. Reads all annotations from the DB
2. Opens each image, crops all 64 cells
3. Per cell computes: **HSV histogram** (96) + **Colour moments** (9) + **HOG** (3168) + **LBP** (10) = **3283 features**
4. Writes `features.csv` — 64,000 rows, one per cell

A live progress bar shows status. The file auto-downloads when done.

### features.csv Schema

```
image_filename, split, cell_index, row, col, label, team_name, player_count,
hsv_h_0..31, hsv_s_0..31, hsv_v_0..31,
cm_h_mean, cm_h_std, cm_h_skew, ..., cm_v_skew,
hog_0..3167,
lbp_0..9
```

---

## Export Formats

**⬇ CSV** — flat annotation table, one row per image:
```
Image File Name, Train Or Test, c01, c02, ..., c64
img_1.jpg, Train, 0, 0, 6, 6, 6, 0, 0, 0, ...
```

**⬇ JSON** — structured with full label matrix:
```json
{
  "image": "img_1.jpg",
  "split": "train",
  "labels": [[0,0,6,6,...], [0,6,6,6,...], ...],
  "features": [0,0,6,6,...,0]
}
```
