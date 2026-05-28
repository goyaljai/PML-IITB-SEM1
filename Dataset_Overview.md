# Dataset Overview — IITB PML Sem1 IPL Image Dataset

## Summary

| Property | Value |
|---|---|
| Total images | 1000 |
| Format | JPEG |
| Dimensions | 800 × 600 px (uniform) |
| Size | ~148 MB |
| Task | Grid-level team classification |
| Labels per image | 64 (8×8 grid, one label per cell) |
| Label range | 0–10 (0 = empty, 1–10 = IPL teams) |

---

## Image Groups

| Range | Type | Count |
|---|---|---|
| `img_1` – `img_250` | IPL game broadcast images (batch 1) | 250 |
| `img_251` – `img_287` | No-player images (crowd / scoreboard / venue wide-shots) | 37 |
| `img_288` – `img_1000` | IPL game broadcast images (batch 2) | 713 |

The no-player images were originally prefixed `np_`. They were inserted at indices 251–287 during the rename so their range stays identifiable.

---

## Train / Test Split

| Split | Folder | Count | % |
|---|---|---|---|
| Train | `train/` | 788 | 78.8% |
| Test | `test/` | 212 | 21.2% |

The split was assigned before annotation and is fixed. The 37 no-player images are distributed across both splits (18 train / 19 test).

---

## Grid Layout

Each image is divided into a uniform 8×8 grid:

```
+----+----+----+----+----+----+----+----+
| r0 | r0 | r0 | r0 | r0 | r0 | r0 | r0 |   row 0
+----+----+----+----+----+----+----+----+
| r1 | ...                              |   row 1
  ...
+----+----+----+----+----+----+----+----+
| r7 | r7 | r7 | r7 | r7 | r7 | r7 | r7 |   row 7
+----+----+----+----+----+----+----+----+
  c0   c1   c2   c3   c4   c5   c6   c7
```

- Cell size: 100 × 75 px
- Total cells: 64 per image
- Total labelled cells (all images): 64,000

Cell index (1-based, row-major): `cell_index = row * 8 + col + 1`

---

## Teams

| Label | Team | Primary Colour |
|---|---|---|
| 0 | Empty / No player | — |
| 1 | CSK — Chennai Super Kings | Gold |
| 2 | DC — Delhi Capitals | Navy |
| 3 | GT — Gujarat Titans | Dark Navy |
| 4 | KKR — Kolkata Knight Riders | Purple |
| 5 | LSG — Lucknow Super Giants | Teal |
| 6 | MI — Mumbai Indians | Blue |
| 7 | PBKS — Punjab Kings | Red |
| 8 | RR — Rajasthan Royals | Pink |
| 9 | RCB — Royal Challengers Bangalore | Dark Red |
| 10 | SRH — Sunrisers Hyderabad | Orange |

---

## Annotation Status

Annotation is in progress. Progress is tracked live at the annotation portal (http://35.207.192.90:8001).

Once complete, this repo will include:
- `annotations.csv` — flat 64-column label matrix per image
- `features.csv` — 3283-feature vector per cell (HSV + colour moments + HOG + LBP)

See `Label_Distribution.md` for the expected label breakdown once annotation is done.
