# IPL Player Detection — HSV/RGB Color Feature Extraction

This document explains the end-to-end pipeline in `Dataset_Features_HSV_RBG.ipynb` for extracting color-based features from IPL player images and training a Random Forest classifier.

---

## Overview

Each 800×600px image is divided into an **8×8 grid** of 64 patches (100×75px each). For every patch, a **192-dimensional color histogram vector** is extracted by concatenating 32-bin histograms across 6 color channels (R, G, B, H, S, V). A Random Forest classifier is trained on these vectors to predict which IPL team occupies each patch.

---

## Pipeline Phases

### Phase 1: Exploratory Data Analysis (EDA)
- **Image uniformity check**: Confirms all images are exactly 800×600px, enabling a fixed-size grid.
- **Label distribution**: Plots team balance (IDs 1–10) and player count per image. ~80% of cells are background (label 0), which is expected.
- **Spatial heatmap**: 8×8 heatmap showing where players most frequently appear. Players cluster in the mid-field rows, rarely at the top (sky) or extreme edges.

### Phase 1.5: Dominant Color Signatures per Team
- Samples up to 10 patches per team, filters out green grass pixels (Hue 0.15–0.45), and computes the average RGB and HSV values.
- Visualizes the dominant jersey color for each of the 10 IPL teams.

### Phase 2: Color Space Profiling (RGB vs HSV)
- Demonstrates why **HSV is more robust than RGB** for jersey detection under varying lighting.
- RGB histograms shift drastically between day and shadow lighting; the **Hue channel stays tightly clustered**.

### Phase 2.5: The 192-Dimensional Feature Vector
- Visualizes the exact feature vector used by the Random Forest for a sample patch.
- 6 segments of 32 bins each: Red (0–31), Green (32–63), Blue (64–95), Hue (96–127), Saturation (128–159), Value (160–191).

### Phase 3: Feature Engineering & Model Training
- **`extract_patch_features(patch)`**: Returns a 192-dim concatenated histogram vector per patch.
- Trains `RandomForestClassifier(n_estimators=100, class_weight='balanced', random_state=42, n_jobs=-1)`.
- Evaluates with classification report and confusion matrix.

### Phase 4: Prediction Visualization
- Runs the trained model on 20 random test images.
- Draws colored bounding boxes on the 8×8 grid:
  - 🟩 **Green** — correct prediction
  - 🟥 **Red** — wrong prediction (shows predicted vs actual team)

### Phase 5: Error Analysis — False Negatives
- Identifies patches where a player was annotated but the model predicted background (label 0).
- Visualizes the Hue histogram for these patches, showing the grass spike (Hue 0.15–0.45) dominating and drowning out the jersey signal.

---

## Output CSV

**File**: `Individual_Feature_CSVs/Dataset_Features_HSV_RGB.csv`

| Column | Description |
|---|---|
| `Image File Name` | Source image filename |
| `Train Or Test` | Dataset split |
| `cell_row` | Grid row (0–7) |
| `cell_col` | Grid column (0–7) |
| `label` | Team ID (0 = background, 1–10 = IPL teams) |
| `f000`–`f191` | 192-dim color histogram feature vector |

- **Rows**: 64,320 (1,005 images × 64 cells)
- **Columns**: 197 total (5 metadata + 192 features)

---

## Feature Engineering Details

```
extract_patch_features(patch):
    RGB histogram: 3 channels × 32 bins = 96 values  (f000–f095)
    HSV histogram: 3 channels × 32 bins = 96 values  (f096–f191)
    Total: 192-dimensional vector
```

Grid cell coordinates:
```
cell_row = i // 8    (0–7, top to bottom)
cell_col = i % 8    (0–7, left to right)
```

---

## Model Performance

- **Overall accuracy**: ~85%
- **Class imbalance**: Handled via `class_weight='balanced'`
- **Key weakness**: Small players whose jersey occupies <10% of a patch are drowned out by grass background pixels — a fundamental limitation of patch-level histogram features without object detection.

---

## Dependencies

```
numpy, pandas, matplotlib, seaborn
Pillow (PIL)
scikit-learn
huggingface_hub
tqdm
```
