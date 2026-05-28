# Label Distribution

> **Status:** Annotation in progress. This document will be updated with final statistics once all 1000 images are labelled.

---

## Expected Structure

Once annotation is complete, the dataset will contain **64,000 labelled cells** (1000 images × 64 cells each).

### Cell-Level Distribution (expected)

The majority of cells will be label 0 (empty) — broadcast frames typically show a small number of players against a large background of pitch, grass, crowd, and graphics.

Expected rough breakdown based on typical IPL broadcast frames:

| Label | Team | Expected % of cells |
|---|---|---|
| 0 | Empty | ~65–75% |
| 1–10 | Any team | ~25–35% combined |

Within labelled (non-zero) cells, distribution across the 10 teams depends on how many images feature each team. Since images come from multiple IPL seasons and matchups, all 10 teams should appear, but some fixture-heavy teams may have more coverage.

### No-Player Images

The 37 no-player images (img_251–img_287) contribute 37 × 64 = **2,368 cells**, all label 0. This is built into the dataset intentionally — these images are hard negatives for the classifier.

---

## Final Stats (to be filled post-annotation)

### Overall Cell Counts

| Label | Team | Train cells | Test cells | Total cells | % of total |
|---|---|---|---|---|---|
| 0 | Empty | — | — | — | — |
| 1 | CSK | — | — | — | — |
| 2 | DC | — | — | — | — |
| 3 | GT | — | — | — | — |
| 4 | KKR | — | — | — | — |
| 5 | LSG | — | — | — | — |
| 6 | MI | — | — | — | — |
| 7 | PBKS | — | — | — | — |
| 8 | RR | — | — | — | — |
| 9 | RCB | — | — | — | — |
| 10 | SRH | — | — | — | — |
| **Total** | | **50,432** | **13,568** | **64,000** | **100%** |

### Images Per Team (images where team appears at least once)

| Team | Train images | Test images | Total |
|---|---|---|---|
| CSK | — | — | — |
| DC | — | — | — |
| GT | — | — | — |
| KKR | — | — | — |
| LSG | — | — | — |
| MI | — | — | — |
| PBKS | — | — | — |
| RR | — | — | — |
| RCB | — | — | — |
| SRH | — | — | — |

### Annotator Breakdown

| Annotator | Images annotated |
|---|---|
| jai | — |
| sharon | — |
| rishabh | — |
| ashutosh | — |
| udit | — |
| **Total** | **1000** |

---

## How to Compute From annotations.csv

```python
import pandas as pd

df = pd.read_csv("annotations.csv")
cell_cols = [f"c{i:02d}" for i in range(1, 65)]

# Team label counts across all cells
flat = df[cell_cols].values.flatten()
counts = pd.Series(flat).value_counts().sort_index()

teams = {0:"Empty",1:"CSK",2:"DC",3:"GT",4:"KKR",5:"LSG",6:"MI",7:"PBKS",8:"RR",9:"RCB",10:"SRH"}
for label, count in counts.items():
    print(f"{teams[label]:6s}  {count:8,d}  ({count/len(flat)*100:.1f}%)")
```

```python
# Per-team image count (images where team appears at least once)
for label in range(1, 11):
    mask = (df[cell_cols] == label).any(axis=1)
    print(f"{teams[label]:6s}: {mask.sum()} images")
```
