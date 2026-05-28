# features_sample.csv — Column Reference

Sample feature extraction for 10 images (`img_1.jpg` – `img_10.jpg`) from the IPL Player Detection dataset.

## What is this?

A demonstration of one feature engineering approach: **RGB color histograms + channel statistics** extracted per image. This is a baseline — you can regenerate this for all 1005 images using `annotations.csv` + the images on HuggingFace.

---

## Columns

| Column(s) | Description |
|-----------|-------------|
| `filename` | Image filename (e.g. `img_1.jpg`) |
| `hist_r_00` … `hist_r_31` | Normalized histogram of the **Red** channel (32 bins, 0–255). Each value = fraction of pixels in that bin. |
| `hist_g_00` … `hist_g_31` | Normalized histogram of the **Green** channel (32 bins). |
| `hist_b_00` … `hist_b_31` | Normalized histogram of the **Blue** channel (32 bins). |
| `mean_r`, `mean_g`, `mean_b` | Per-channel pixel mean (0–255). |
| `std_r`, `std_g`, `std_b` | Per-channel pixel standard deviation. |

Total: 1 + 32×3 + 3 + 3 = **103 columns** per image.

---

## How features were extracted

```python
from PIL import Image
import numpy as np

img = Image.open("img_1.jpg").convert("RGB")
arr = np.array(img)  # shape: (600, 800, 3)

# 32-bin normalized histogram per channel
for ch in range(3):
    hist, _ = np.histogram(arr[:,:,ch], bins=32, range=(0,256))
    hist = hist / hist.sum()  # normalize to sum=1

# Channel mean and std
mean = arr.mean(axis=(0,1))   # shape: (3,)
std  = arr.std(axis=(0,1))
```

Images are 800×600 px, already uniform — no resizing needed.

---

## How to regenerate for all 1005 images

```python
from huggingface_hub import snapshot_download
from pathlib import Path
import pandas as pd, numpy as np
from PIL import Image

dataset_dir = Path(snapshot_download("goyaljai/IITB-PML-SEM1", repo_type="dataset"))
annotations = pd.read_csv(dataset_dir / "annotations.csv")

rows = []
for _, ann in annotations.iterrows():
    split = ann["Train Or Test"].lower()
    img_path = dataset_dir / split / ann["Image File Name"]
    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)

    row = {"filename": ann["Image File Name"]}
    for ci, ch in enumerate(["r", "g", "b"]):
        hist, _ = np.histogram(arr[:,:,ci], bins=32, range=(0,256))
        hist = hist / hist.sum()
        for bi, v in enumerate(hist):
            row[f"hist_{ch}_{bi:02d}"] = v
        row[f"mean_{ch}"] = arr[:,:,ci].mean()
        row[f"std_{ch}"]  = arr[:,:,ci].std()
    rows.append(row)

features_df = pd.DataFrame(rows)
features_df.to_csv("features_all.csv", index=False)
```

---

## What you can do with these features

| Task | Target column(s) from `annotations.csv` | Suggested algorithm |
|------|------------------------------------------|---------------------|
| Dominant team classification | Derive from `c01`–`c64` (most frequent non-zero value) | Random Forest, SVM, kNN |
| Player count regression | `count` | Linear Regression, Ridge, Gradient Boosting |
| Multi-label team detection | One-hot encode all teams present in `c01`–`c64` | Multi-label classifier |
| Empty/occupied cell prediction | Individual `c01`–`c64` values (0 vs non-zero) | Logistic Regression per cell |

Color histograms are a weak but fast baseline — IPL team jerseys have distinctive colors (CSK yellow, RCB red, MI blue, etc.), so even simple histogram features give above-random accuracy.
