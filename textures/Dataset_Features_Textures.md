# texture_feats.csv — Column Reference

Texture feature extraction for all 1005 images (`img_1.jpg` – `img_1005.jpg`) from the IPL Player Detection dataset.

## What is this?

Each image is divided into an **8×8 grid of 64 cells** (each 100×75 px). For every cell, two texture descriptors are extracted from the grayscale version of that cell patch:

- **LBP** (Local Binary Pattern) — 10 values — captures micro-texture patterns, fabric weave, logo edges
- **GLCM** (Grey Level Co-occurrence Matrix) — 16 values — captures contrast, homogeneity, energy, and correlation at 4 angles

The unit of observation is **one grid cell from one image**, not one image. Each image produces 64 rows.

---

## Columns

| Column(s) | Description |
|-----------|-------------|
| `Image File Name` | Image filename (e.g. `img_1.jpg`) |
| `Train Or Test` | `Train` or `Test` — from annotations CSV |
| `cell_row` | Grid row (1–8, top to bottom) |
| `cell_col` | Grid column (1–8, left to right) |
| `label` | Ground truth team ID for this cell (0–10, see label reference below) |
| `tex_00` … `tex_09` | LBP histogram — 10 normalized bins (each value = fraction of pixels with that pattern, sums to 1.0) |
| `tex_10` … `tex_13` | GLCM Contrast at 0°, 45°, 90°, 135° |
| `tex_14` … `tex_17` | GLCM Homogeneity at 0°, 45°, 90°, 135° |
| `tex_18` … `tex_21` | GLCM Energy at 0°, 45°, 90°, 135° |
| `tex_22` … `tex_25` | GLCM Correlation at 0°, 45°, 90°, 135° |

Total: 5 metadata columns + 26 feature columns = **31 columns** per row.

---

## Label reference

| Label | Team |
|-------|------|
| 0 | No team (background — grass, pitch, crowd, sky) |
| 1 | Chennai Super Kings (CSK) |
| 2 | Delhi Capitals (DC) |
| 3 | Gujarat Titans (GT) |
| 4 | Kolkata Knight Riders (KKR) |
| 5 | Lucknow Super Giants (LSG) |
| 6 | Mumbai Indians (MI) |
| 7 | Punjab Kings (PBKS) |
| 8 | Rajasthan Royals (RR) |
| 9 | Royal Challengers Bengaluru (RCB) |
| 10 | Sunrisers Hyderabad (SRH) |

---

## How features were extracted

```python
from skimage.feature import local_binary_pattern, graycomatrix, graycoprops
from skimage.color import rgb2gray
import numpy as np

# each cell is a (75, 100, 3) RGB patch
def extract_texture_features(cell_rgb):
    gray       = rgb2gray(cell_rgb)                # float [0, 1]
    gray_uint8 = (gray * 255).astype(np.uint8)

    # LBP — 10 values
    lbp     = local_binary_pattern(gray_uint8, 8, 1, method='uniform')
    hist, _ = np.histogram(lbp.ravel(), bins=10, range=(0, 10))
    hist    = hist.astype(float) / (hist.sum() + 1e-6)   # normalize to sum=1

    # GLCM — 16 values
    gray_q = (gray_uint8 / 8).astype(np.uint8)           # quantize to 32 levels
    glcm   = graycomatrix(gray_q, distances=[1],
                          angles=[0, np.pi/4, np.pi/2, 3*np.pi/4],
                          levels=32, symmetric=True, normed=True)
    glcm_feats = []
    for prop in ['contrast', 'homogeneity', 'energy', 'correlation']:
        glcm_feats.extend(graycoprops(glcm, prop)[0].tolist())

    return np.concatenate([hist, glcm_feats])   # 26 values
```

Images are 800×600 px. Each cell is sliced as:
```python
y1 = (cell_row - 1) * 75
x1 = (cell_col - 1) * 100
cell = img_array[y1:y1+75, x1:x1+100]
```

---

## How to regenerate for all 1005 images

```python
from huggingface_hub import snapshot_download
from pathlib import Path
import pandas as pd, numpy as np
from PIL import Image
from skimage.feature import local_binary_pattern, graycomatrix, graycoprops
from skimage.color import rgb2gray

dataset_dir = Path(snapshot_download(repo_id="goyaljai/IPL-Player-Detection-IITB-PML", repo_type="dataset"))
annotations = pd.read_csv(dataset_dir / "annotations.csv")

GRID_ROWS, GRID_COLS = 8, 8
CELL_W, CELL_H       = 100, 75

def get_cell(img_array, cell_row, cell_col):
    y1 = (cell_row - 1) * CELL_H
    x1 = (cell_col - 1) * CELL_W
    return img_array[y1:y1+CELL_H, x1:x1+CELL_W]

def extract_texture_features(cell_rgb):
    gray       = rgb2gray(cell_rgb)
    gray_uint8 = (gray * 255).astype(np.uint8)
    lbp        = local_binary_pattern(gray_uint8, 8, 1, method='uniform')
    hist, _    = np.histogram(lbp.ravel(), bins=10, range=(0, 10))
    hist       = hist.astype(float) / (hist.sum() + 1e-6)
    gray_q     = (gray_uint8 / 8).astype(np.uint8)
    glcm       = graycomatrix(gray_q, distances=[1],
                              angles=[0, np.pi/4, np.pi/2, 3*np.pi/4],
                              levels=32, symmetric=True, normed=True)
    feats = []
    for prop in ['contrast', 'homogeneity', 'energy', 'correlation']:
        feats.extend(graycoprops(glcm, prop)[0].tolist())
    return np.concatenate([hist, feats])

rows = []
for _, ann in annotations.iterrows():
    split    = ann['Train Or Test']
    img_name = ann['Image File Name']
    img_path = dataset_dir / split.lower() / img_name
    img_rgb  = np.array(Image.open(img_path).convert('RGB'))

    for r in range(1, GRID_ROWS + 1):
        for c in range(1, GRID_COLS + 1):
            cell_idx = (r - 1) * 8 + c
            label    = ann[f'c{cell_idx:02d}']
            cell     = get_cell(img_rgb, r, c)
            feats    = extract_texture_features(cell)

            row = {'Image File Name': img_name, 'Train Or Test': split,
                   'cell_row': r, 'cell_col': c, 'label': int(label)}
            for i, v in enumerate(feats):
                row[f'tex_{i:02d}'] = round(float(v), 6)
            rows.append(row)

pd.DataFrame(rows).to_csv('texture_feats.csv', index=False)
```

Takes approximately **10 minutes** to run on 1005 images.

---

## Dataset summary

| Split | Images | Rows |
|-------|--------|------|
| Train | 793 | 50,752 |
| Test | 212 | 13,568 |
| **Total** | **1005** | **64,320** |

---

## Baseline evaluation (texture features only)

A Random Forest classifier (100 trees, `class_weight='balanced'`) trained on texture features alone gives:

| Metric | Value |
|--------|-------|
| Overall accuracy | 79.68% |
| Macro F1 | 0.1748 |
| Background recall (label=0) | 0.99 |
| Best team — SRH | F1 = 0.35 |
| Worst team — PBKS | F1 = 0.00 |

Texture features are effective at separating background cells (grass, pitch, sky) from jersey cells — background recall of 0.99 confirms this. Team-level F1 is low because team identity is primarily encoded in colour, not texture. These features complement colour and edge features in the merged model.

---

## What you can do with these features

| Task | Notes |
|------|-------|
| Background vs jersey detection | Binarize label (0 vs non-zero) — texture handles this well (recall=0.99) |
| Cell-level team classification | Use `label` as target, `tex_00`–`tex_25` as features — weak alone, strong when merged |
| Merge with other feature CSVs | Join on `Image File Name` + `cell_row` + `cell_col` |

Texture features work best when **merged** with colour (HSV histograms) and edge (HOG, Sobel) features. Colour features carry the primary discriminative power for team identification.

---

## Design decisions

**Gabor filters — considered and dropped**
Gabor filters were implemented and tested. At 75×100px cell size they added negligible discriminative power but increased runtime by 11× (11 min/100 images vs 1 min/100 images). GLCM at 4 angles already captures directional texture information. Dropped in favour of LBP + GLCM only.

**Grayscale conversion**
Texture is about patterns and structure, not colour. Converting to grayscale before LBP and GLCM removes colour information intentionally — colour is handled separately by the colour feature member. Formula used: `gray = 0.299×R + 0.587×G + 0.114×B` via `skimage.color.rgb2gray`.

**Cell-level not image-level**
Features are extracted per cell (64 per image) rather than per image. This is required by the project — the model must predict a team label for each grid cell independently.
