# IITB PML Semester 1 — IPL Image Dataset

> **Dataset on Hugging Face:** [goyaljai/IITB-PML-SEM1](https://huggingface.co/datasets/goyaljai/IITB-PML-SEM1)

963 IPL cricket images, uniformly processed to **800 × 600 px JPEG**, prepared for the Practical Machine Learning course, Semester 1, IIT Bombay.

## Dataset Details

| Property | Value |
|---|---|
| Total images | 963 |
| Format | JPEG |
| Dimensions | 800 × 600 px (all uniform) |
| Size | ~141 MB |

### Train / Test Split

| Split | Folder | Count | % |
|---|---|---|---|
| Train | `train/` | 674 | 70% |
| Test | `test/` | 289 | 30% |

> Split is random with `seed=42` for reproducibility.

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

# Download full dataset
dataset_dir = Path(snapshot_download(repo_id="goyaljai/IITB-PML-SEM1", repo_type="dataset"))

# Train and test paths
train_dir = dataset_dir / "train"
test_dir  = dataset_dir / "test"

train_images = sorted(train_dir.glob("*.jpg"))
test_images  = sorted(test_dir.glob("*.jpg"))

print(f"Train: {len(train_images)} images")
print(f"Test : {len(test_images)} images")
```

---

## Example: K-Means Clustering on Train Set, Evaluate on Test Set

Cluster IPL images by colour histogram features. Fit KMeans on the train split, then assign test images to the nearest cluster.

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
dataset_dir = Path(snapshot_download(repo_id="goyaljai/IITB-PML-SEM1", repo_type="dataset"))
train_images = sorted((dataset_dir / "train").glob("*.jpg"))
test_images  = sorted((dataset_dir / "test").glob("*.jpg"))
print(f"Train: {len(train_images)} | Test: {len(test_images)}")

# ── 2. Feature extraction (colour histogram) ─────────────────────────────────
def extract_histogram(path, bins=32):
    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    hist = []
    for ch in range(3):
        h, _ = np.histogram(arr[:, :, ch], bins=bins, range=(0, 256))
        hist.extend(h)
    return np.array(hist, dtype=float)

print("Extracting train features...")
X_train = normalize(np.array([extract_histogram(p) for p in train_images]))

print("Extracting test features...")
X_test  = normalize(np.array([extract_histogram(p) for p in test_images]))

# ── 3. Fit KMeans on train ───────────────────────────────────────────────────
N_CLUSTERS = 8
kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
train_labels = kmeans.fit_predict(X_train)

print("\nTrain cluster distribution:")
for k in range(N_CLUSTERS):
    print(f"  Cluster {k}: {np.sum(train_labels == k)} images")

# ── 4. Predict on test ───────────────────────────────────────────────────────
test_labels = kmeans.predict(X_test)

print("\nTest cluster distribution:")
for k in range(N_CLUSTERS):
    print(f"  Cluster {k}: {np.sum(test_labels == k)} images")

# ── 5. Visualise 5 train samples + 2 test samples per cluster ───────────────
COLS = 7  # 5 train + 2 test
fig, axes = plt.subplots(N_CLUSTERS, COLS, figsize=(COLS * 3, N_CLUSTERS * 2.5))

for k in range(N_CLUSTERS):
    tr_paths = [p for p, l in zip(train_images, train_labels) if l == k][:5]
    te_paths = [p for p, l in zip(test_images,  test_labels)  if l == k][:2]
    row_paths = tr_paths + te_paths
    for j in range(COLS):
        ax = axes[k][j]
        if j < len(row_paths):
            ax.imshow(mpimg.imread(row_paths[j]))
            if j == 0:
                ax.set_title(f"Cluster {k}", fontsize=9)
            if j == 5:
                ax.set_title("TEST →", fontsize=8, color="orange")
        ax.axis("off")

plt.suptitle("KMeans Clusters  |  cols 1-5: train   cols 6-7: test", fontsize=11)
plt.tight_layout()
plt.savefig("kmeans_clusters.png", dpi=100)
plt.show()
print("Saved kmeans_clusters.png")
```

### Tips
- Increase `N_CLUSTERS` (try 10–20) for finer groupings (team kits, ground types, crowd shots)
- Swap colour histograms for CNN embeddings (`torchvision` ResNet) for semantic clustering
- Use `inertia_` and elbow method to pick the optimal K

---

## Requirements

```
pip install huggingface_hub pillow scikit-learn matplotlib numpy
```
