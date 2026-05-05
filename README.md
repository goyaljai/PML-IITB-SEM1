---
license: cc-by-4.0
task_categories:
  - image-classification
  - image-feature-extraction
tags:
  - ipl
  - cricket
  - sports
  - image-dataset
size_categories:
  - n<1K
---

# IITB PML Semester 1 — IPL Image Dataset

963 IPL cricket images, uniformly processed to **800 × 600 px JPEG**, prepared for the Practical Machine Learning course, Semester 1, IIT Bombay.

## Dataset Details

| Property | Value |
|---|---|
| Total images | 963 |
| Format | JPEG |
| Dimensions | 800 × 600 px (all uniform) |
| Size | ~141 MB |

### Source breakdown
| Source | Count |
|---|---|
| FINAL_VERIFIED_IPL_2 | 277 |
| FINAL_VERIFIED_IPL_686 | 686 |

### Processing pipeline
- **4:3 images (915):** direct resize to 800×600 via Lanczos — full frame preserved
- **Non-4:3 images (48):** scale-to-cover + centre crop to 800×600

---

## How to Load

```python
from huggingface_hub import snapshot_download
from pathlib import Path
from PIL import Image
import numpy as np

# Download dataset
dataset_dir = snapshot_download(repo_id="goyaljai/IITB-PML-SEM1", repo_type="dataset")
image_paths = sorted(Path(dataset_dir).rglob("*.jpg"))
print(f"Loaded {len(image_paths)} images")
```

---

## Example: K-Means Clustering

Cluster the IPL images into N groups based on colour histogram features.

```python
from huggingface_hub import snapshot_download
from pathlib import Path
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

# ── 1. Download dataset ──────────────────────────────────────────────────────
dataset_dir = snapshot_download(repo_id="goyaljai/IITB-PML-SEM1", repo_type="dataset")
image_paths = sorted(Path(dataset_dir).rglob("*.jpg"))
print(f"Found {len(image_paths)} images")

# ── 2. Extract colour histogram features ────────────────────────────────────
def extract_histogram(path, bins=32):
    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    hist = []
    for channel in range(3):  # R, G, B
        h, _ = np.histogram(arr[:, :, channel], bins=bins, range=(0, 256))
        hist.extend(h)
    return np.array(hist, dtype=float)

features = np.array([extract_histogram(p) for p in image_paths])
features = normalize(features)  # L2 normalise
print(f"Feature matrix: {features.shape}")

# ── 3. K-Means clustering ────────────────────────────────────────────────────
N_CLUSTERS = 8
kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
labels = kmeans.fit_predict(features)

for k in range(N_CLUSTERS):
    count = np.sum(labels == k)
    print(f"Cluster {k}: {count} images")

# ── 4. Visualise 5 samples per cluster ──────────────────────────────────────
fig, axes = plt.subplots(N_CLUSTERS, 5, figsize=(15, N_CLUSTERS * 3))
for k in range(N_CLUSTERS):
    cluster_paths = [p for p, l in zip(image_paths, labels) if l == k]
    samples = cluster_paths[:5]
    for j, path in enumerate(samples):
        axes[k][j].imshow(mpimg.imread(path))
        axes[k][j].axis("off")
        if j == 0:
            axes[k][j].set_title(f"Cluster {k}", fontsize=10)

plt.tight_layout()
plt.savefig("kmeans_clusters.png", dpi=100)
plt.show()
print("Saved kmeans_clusters.png")
```

### Tips
- Increase `N_CLUSTERS` (try 10–20) for finer-grained groupings (team kits, ground types, crowd shots)
- Swap colour histograms for CNN embeddings (`torchvision` ResNet) for semantic clustering
- Use `KMeans(init='k-means++')` (default) for faster convergence

---

## Requirements

```
pip install huggingface_hub pillow scikit-learn matplotlib numpy
```
