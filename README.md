# IITB PML Semester 1 — IPL Player Detection Dataset

> **Kaggle:** [goyaljai0207/ipl-player-detection-iitb-pml](https://www.kaggle.com/datasets/goyaljai0207/ipl-player-detection-iitb-pml)
> **HuggingFace:** [goyaljai/IPL-Player-Detection-IITB-PML](https://huggingface.co/datasets/goyaljai/IPL-Player-Detection-IITB-PML)

1005 IPL cricket broadcast images annotated with **8×8 grid team labels** and **player counts**, prepared for the Python for Machine Learning course, Semester 1, IIT Bombay.

**Keywords:** IPL dataset, cricket player detection, IPL team classification, cricket image dataset, broadcast frame annotation, player count dataset, cricket computer vision, sports detection dataset, IITB machine learning, cricket jersey detection, multi-label cricket dataset, IPL 2024 dataset

## Dataset Details

| Property | Value |
|---|---|
| Total images | 1005 |
| Format | JPEG |
| Dimensions | 800 × 600 px (all uniform) |
| Annotation | 8×8 grid cell labels + player count |
| Teams | 10 IPL teams (CSK, DC, GT, KKR, LSG, MI, PBKS, RR, RCB, SRH) |

### Train / Test Split

| Split | Folder | Count |
|---|---|---|
| Train | `train/` | 793 |
| Test | `test/` | 212 |

### Team Distribution (1005 images, any-cell presence)

| Team | Images |
|------|--------|
| MI | 177 |
| RCB | 153 |
| GT | 131 |
| RR | 131 |
| CSK | 130 |
| PBKS | 127 |
| LSG | 115 |
| KKR | 112 |
| DC | 110 |
| SRH | 107 |

### Label Schema (`annotations.csv`)

| Column | Description |
|--------|-------------|
| `Image File Name` | `img_NNN.jpg` |
| `Train Or Test` | `Train` or `Test` |
| `count` | Total players visible in image (0–20) |
| `c01`–`c64` | Team ID per grid cell (row-major, 8 cols/row) |

**Team IDs:** 0=empty, 1=CSK, 2=DC, 3=GT, 4=KKR, 5=LSG, 6=MI, 7=PBKS, 8=RR, 9=RCB, 10=SRH

---

## How to Load (HuggingFace)

```python
from huggingface_hub import snapshot_download
from pathlib import Path
import pandas as pd

dataset_dir = Path(snapshot_download(repo_id="goyaljai/IPL-Player-Detection-IITB-PML", repo_type="dataset"))

train_images = sorted((dataset_dir / "train").glob("*.jpg"))
test_images  = sorted((dataset_dir / "test").glob("*.jpg"))
annotations  = pd.read_csv(dataset_dir / "annotations.csv")

print(f"Train: {len(train_images)} | Test: {len(test_images)}")
print(annotations.head())
```

---

## How to Load (Kaggle)

```python
import kagglehub
import pandas as pd
from pathlib import Path
from PIL import Image

# Download dataset
path = kagglehub.dataset_download("goyaljai0207/ipl-player-detection-iitb-pml")

# Load annotations
df = pd.read_csv(f"{path}/annotations.csv")
print(df.head())

# Load an image
img = Image.open(f"{path}/train/img_1.jpg")
img.show()

# Get 8x8 label grid for first image
row = df.iloc[0]
grid = [[int(row[f'c{r*8+c+1:02d}']) for c in range(8)] for r in range(8)]
print(grid)
```

Or load directly into a DataFrame using the Kaggle Pandas adapter:

```python
# pip install kagglehub[pandas-datasets]
import kagglehub
from kagglehub import KaggleDatasetAdapter

df = kagglehub.load_dataset(
  KaggleDatasetAdapter.PANDAS,
  "goyaljai0207/ipl-player-detection-iitb-pml",
  "",  # empty string loads annotations.csv by default
)

print("First 5 records:", df.head())
```

---

## Example: Team Classification with Annotations

```python
import kagglehub, pandas as pd, numpy as np
from pathlib import Path
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

path = kagglehub.dataset_download("goyaljai0207/ipl-player-detection-iitb-pml")
df = pd.read_csv(f"{path}/annotations.csv")

TEAMS = {0:'empty',1:'CSK',2:'DC',3:'GT',4:'KKR',5:'LSG',6:'MI',7:'PBKS',8:'RR',9:'RCB',10:'SRH'}

def extract_histogram(img_path, bins=32):
    img = Image.open(img_path).convert("RGB")
    arr = np.array(img)
    return np.concatenate([np.histogram(arr[:,:,c], bins=bins, range=(0,256))[0] for c in range(3)])

train_df = df[df['Train Or Test'] == 'Train']
test_df  = df[df['Train Or Test'] == 'Test']

X_train = np.array([extract_histogram(f"{path}/train/{r['Image File Name']}") for _, r in train_df.iterrows()])
X_test  = np.array([extract_histogram(f"{path}/test/{r['Image File Name']}") for _, r in test_df.iterrows()])

# Predict dominant team per image
y_train = [TEAMS[max(set([r[f'c{i:02d}'] for i in range(1,65)]), key=lambda x: [r[f'c{i:02d}'] for i in range(1,65)].count(x))] for _, r in train_df.iterrows()]
y_test  = [TEAMS[max(set([r[f'c{i:02d}'] for i in range(1,65)]), key=lambda x: [r[f'c{i:02d}'] for i in range(1,65)].count(x))] for _, r in test_df.iterrows()]

clf = RandomForestClassifier(n_estimators=100, random_state=42)
clf.fit(X_train, y_train)
print(classification_report(y_test, clf.predict(X_test)))
```

---

## Requirements

```
pip install huggingface_hub kagglehub pillow scikit-learn pandas numpy matplotlib opencv
```

---

## Citation

```
@dataset{ipl_player_detection_2026,
  title   = {IPL Player Detection Dataset — IITB PML Sem1},
  author  = {Goyal, Jai and contributors},
  year    = {2026},
  url     = {https://www.kaggle.com/datasets/goyaljai0207/ipl-player-detection-iitb-pml}
}
```
