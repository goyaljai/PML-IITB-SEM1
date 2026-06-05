# IPL Player Detection — CSV Transformation and Edge Feature Extraction

This README explains two parts of the edge-feature workflow for the IPL player detection project:

1. `csv_transformation.py` — converts the original annotation CSV into a cell-level feature CSV structure.
2. `Extracting_Edge_Features.ipynb` — populates the edge-feature columns for each image cell.

The goal is not to train a model in these files. The goal is to prepare a clean feature table that can later be merged with color and texture features and used in the machine learning pipeline.

---

## 1. CSV Data Transfer and Transformation

### Input and output files

The script uses hard-coded file paths:

```python
SOURCE_CSV = "Dataset_Annotations.csv"
TARGET_TEMPLATE_CSV = "template.csv"
OUTPUT_CSV = "Edge_features.csv"
```

- `SOURCE_CSV` is the original annotation file.
- `TARGET_TEMPLATE_CSV` is used as a reference for the desired column structure.
- `OUTPUT_CSV` is the generated cell-level CSV.

The original annotation file is in wide format, where each image has one row and cell labels are stored across columns `c01` to `c64`.

Example source structure:

```text
Image File Name, Train Or Test, count, c01, c02, ..., c64
```

The transformed output is in long format, where each row represents one image-cell pair.

Example target structure:

```text
image_file_name, original_split, cell_id, cell_num, grid_row, grid_col, x_min, y_min, x_max, y_max, y_team_id, ...
```

This conversion is necessary because the project prediction task is cell-wise. Each 800×600 image is divided into an 8×8 grid, so each image produces 64 rows.

```text
1 image = 64 cell-level rows
1000 images = 64,000 cell-level rows
```

---

### What `csv_transformation.py` does

The script performs the following steps:

1. Reads `Dataset_Annotations.csv`.
2. Checks that the required source columns are present:
   - `Image File Name`
   - `Train Or Test`
   - `count`
   - `c01` to `c64`
3. Reads the target template file `Test.csv` to preserve the expected column order where possible.
4. Falls back to a default target column list if `Test.csv` is missing or malformed.
5. Iterates through each image row in the source CSV.
6. Expands each image into 64 rows, one row per grid cell.
7. Calculates grid position and pixel boundaries for each cell.
8. Copies the label from `c01`–`c64` into `y_team_id`.
9. Adds positional features.
10. Adds empty placeholder columns for edge features.
11. Saves the final file as `Test_converted.csv`.

---

### Why the data is converted to cell-level format

The final project output requires predictions for `c01` to `c64`. Therefore, the model should be trained on cell-level samples:

```text
features of one cell → team label for that cell
```

This structure also makes it easier to merge features created by different team members. For example:

```python
final_df = edge_df.merge(color_df, on=["image_file_name", "cell_id"])
final_df = final_df.merge(texture_df, on=["image_file_name", "cell_id"])
```

---

## 2. Explanation of Columns and Features

### Metadata columns

| Column | Meaning | Why it is included |
|---|---|---|
| `image_file_name` | Name of the image file | Used to match each row with the correct image |
| `original_split` | Original train/test split from source data | Preserved as metadata; not used for edge extraction |
| `fold_id` | Placeholder for cross-validation fold | Useful later during ML validation |
| `cell_id` | Cell name from `c01` to `c64` | Main key for merging and tracking cells |
| `cell_num` | Numeric cell number from 1 to 64 | Easier for calculations than string cell IDs |
| `grid_row` | Row index of the cell, from 0 to 7 | Helps locate the cell vertically |
| `grid_col` | Column index of the cell, from 0 to 7 | Helps locate the cell horizontally |
| `x_min`, `y_min`, `x_max`, `y_max` | Pixel boundaries of the cell | Required to crop the cell region from the image |

These columns are mostly identifiers and structural metadata. They are useful for feature extraction, debugging, merging, and validation.

---

### Target and label columns

| Column | Meaning | Usage |
|---|---|---|
| `y_team_id` | Cell label from 0 to 10 | Main target variable for classification |
| `y_player_count` | Player count from the source CSV | Useful for EDA, but should not be used as a model input if it represents image-level ground truth |

`y_team_id` is copied from the original `c01`–`c64` columns. For example, the value in source column `c29` becomes the `y_team_id` for row `cell_id = c29`.

`y_player_count` should be treated carefully. If it represents the true number of players in the full image, it can cause label leakage because this information will not be known for unseen test images.

---

### Positional feature columns

| Column | Meaning | Why it was selected |
|---|---|---|
| `f_cell_row_norm` | Normalized grid row position | Gives vertical spatial context |
| `f_cell_col_norm` | Normalized grid column position | Gives horizontal spatial context |
| `f_x_center_norm` | Normalized x-coordinate of the cell center | Represents the horizontal center of the cell in image coordinates |
| `f_y_center_norm` | Normalized y-coordinate of the cell center | Represents the vertical center of the cell in image coordinates |

These are not edge features. They are position/context features.

They are included because cricket images often have spatial structure. For example, background and crowd regions may appear more often near the top, while pitch and player body regions may appear more often in the middle or lower parts of the image.

For final modeling, the team may choose to use either:

```text
f_cell_row_norm, f_cell_col_norm
```

or:

```text
f_x_center_norm, f_y_center_norm
```

Using all four may introduce redundancy because row position and y-center encode similar information, and column position and x-center encode similar information.

---

## 3. Edge Features Selected

The transformation script creates these edge-feature columns as placeholders. The Jupyter notebook later fills them with actual values.

| Feature | Meaning | Why it was selected |
|---|---|---|
| `f_edge_density` | Ratio of Canny edge pixels to total pixels in the cell | Normalized measure of how much edge structure exists in a cell |
| `f_canny_count` | Raw count of Canny edge pixels | Captures total number of detected edge pixels |
| `f_sobel_mean` | Mean Sobel gradient magnitude in the cell | Captures average edge strength |
| `f_sobel_std` | Standard deviation of Sobel gradient magnitude | Captures variation in edge strength |
| `f_laplacian_var` | Variance of Laplacian response | Captures sharpness and high-frequency detail |
| `f_contour_count` | Number of contours found in the Canny edge map | Captures structural complexity inside the cell |

These features were selected because the project does not allow CNN-style automatic feature learning. Therefore, handcrafted image features are required. Edge features help represent visual structure such as player outlines, jersey boundaries, bats, arms, logos, folds, and high-detail regions.

---

### Why these edge features are useful

#### `f_edge_density`

This feature measures how much of the cell contains detected edges.

```text
f_edge_density = number of Canny edge pixels / cell area
```

For this project, each cell is normally 100×75 pixels, so the cell area is 7500 pixels.

A player-containing cell may have more edges because of body outlines, jersey boundaries, arms, pads, bats, and text/logos. A plain grass or pitch cell may have fewer edges.

---

#### `f_canny_count`

This is the raw number of Canny edge pixels.

It is similar to `f_edge_density`, but it is not normalized. Since all cells are expected to have the same size, this feature remains comparable across cells. It is included because some models may still benefit from the raw count.

---

#### `f_sobel_mean`

Sobel features measure gradient strength. A high value means the cell has stronger intensity transitions.

This can help identify regions with sharp player boundaries, jersey edges, and object contours.

---

#### `f_sobel_std`

This measures how much the Sobel edge strength varies within the cell.

A cell containing both smooth background and sharp player boundaries may have high variation. A uniformly flat cell may have low variation.

---

#### `f_laplacian_var`

Laplacian variance is often used as a sharpness or high-frequency detail measure.

Cells containing jerseys, logos, text, faces, bats, gloves, or other detailed regions may produce higher Laplacian variance than smooth background cells.

---

#### `f_contour_count`

Contours are extracted from the Canny edge map. The number of contours gives a rough measure of the amount of local structure in the cell.

A player cell may have multiple contours from body parts, jersey patterns, and equipment. However, crowd/background cells can also produce many contours, so this feature should be combined with color and texture features later.

---

## 4. Jupyter Notebook: Edge Feature Extraction

The notebook `Extracting_Edge_Features.ipynb` populates the placeholder edge columns created by the transformation script.

### Main goal

The notebook does not create train/test splits and does not train a model. Its only goal is:

```text
Read cell-level CSV → load images → calculate edge features per cell → save populated CSV
```

---

### Step-by-step explanation

#### Step 1: Import libraries

The notebook imports:

- `pandas` for reading and writing CSV files
- `numpy` for numerical calculations
- `cv2` from OpenCV for image processing
- `Path` for file path handling
- `snapshot_download` from `huggingface_hub` for accessing the dataset

---

#### Step 2: Configure paths and constants

The notebook defines:

```python
TARGET_CSV = "Edge_features.csv"
OUTPUT_CSV = "Edge_features_populated.csv"
```

It also defines the fixed image and grid settings:

```python
IMAGE_WIDTH = 800
IMAGE_HEIGHT = 600
GRID_ROWS = 8
GRID_COLS = 8
```

This matches the project requirement that each image should be resized to 800×600 and divided into 64 cells.

---

#### Step 3: Read the target CSV

The notebook reads the existing feature CSV:

```python
df = pd.read_csv(TARGET_CSV)
```

This CSV should already contain one row per image-cell pair. The notebook uses columns such as:

- `image_file_name`
- `cell_id`
- `x_min`
- `y_min`
- `x_max`
- `y_max`

The label columns are not used for edge extraction.

---

#### Step 4: Ensure required columns exist

The notebook checks that all edge-feature columns exist. If any are missing, they are added with blank values.

It also checks for cell boundary columns:

```text
x_min, y_min, x_max, y_max
```

If these are missing but `cell_num` exists, the notebook recreates the cell boundaries using the 8×8 grid logic.

This makes the notebook more robust because it can work with a CSV that already has boundaries or a CSV that only has cell numbers.

---

#### Step 5: Download/cache the Hugging Face dataset and build an image index

The notebook uses:

```python
dataset_dir = Path(snapshot_download(repo_id=HF_REPO_ID, repo_type=HF_REPO_TYPE))
```

This gives access to the dataset files through a local cache directory.

The notebook then searches all image files inside the dataset directory and builds a lookup table:

```text
image_file_name → full image path
```

This avoids unnecessary train/test-specific logic. At this stage, the task is only to locate images and calculate features, not to perform train/test modeling.

---

#### Step 6: Locate image files

A helper function `find_image_path(image_file_name)` receives the image file name from the CSV and returns the matching file path from the image index.

If the file is not found, the image is recorded in a `missing_images` list and skipped.

---

#### Step 7: Compute edge maps once per image

For each image, the notebook:

1. Loads the image using OpenCV.
2. Resizes it to 800×600.
3. Converts it to grayscale.
4. Applies Gaussian blur to reduce noise.
5. Computes the Canny edge map.
6. Computes Sobel gradients and Sobel magnitude.
7. Computes the Laplacian response.

The important design decision is that edge maps are computed once for the full image, not separately for every cell.

This is better because:

- It is faster.
- It avoids cell-boundary artifacts.
- It keeps edge detection consistent across the full image.

---

#### Step 8: Extract features for each cell

After computing full-image edge maps, the notebook crops each cell using:

```text
x_min, y_min, x_max, y_max
```

Then it calculates:

- `f_edge_density`
- `f_canny_count`
- `f_sobel_mean`
- `f_sobel_std`
- `f_laplacian_var`
- `f_contour_count`

These values are written back into the corresponding row of the DataFrame.

---

#### Step 9: Group by image for efficient processing

The notebook groups rows by `image_file_name`.

This means each image is loaded once, edge maps are calculated once, and then all 64 cell rows are populated from those maps.

This is more efficient than loading the same image separately for every cell.

---

#### Step 10: Validate and save output

The notebook checks how many missing values remain in the edge-feature columns. Missing values usually mean that an image was not found or could not be read.

Finally, the populated CSV is saved as:

```text
Edge_features_populated.csv
```

The original input CSV is not overwritten.

---

## 5. Recommended Execution Order

Run the files in this order:

### Step 1: Convert annotations into cell-level format

```bash
python csv_transformation.py
```

Expected output:

```text
Test_converted.csv
```

### Step 2: Use or rename the converted CSV as the edge-feature input

For example, if the notebook expects `Edge_features.csv`, either rename the file or update the notebook variable:

```python
TARGET_CSV = "Test_converted.csv"
```

### Step 3: Run the Jupyter notebook

Run all cells in:

```text
Extracting_Edge_Features.ipynb
```

Expected output:

```text
Edge_features_populated.csv
```

---

## 6. Notes for Modeling

- The edge-feature CSV should be merged with color and texture feature CSVs using `image_file_name` and `cell_id`.
- Do not use `y_team_id` as an input feature. It is the target label.
- Be careful with `y_player_count`; if it is ground-truth image-level information, it should not be used as a model feature.
- For validation, avoid randomly splitting rows because 64 rows come from the same image. Prefer image-wise splitting or `GroupKFold` using `image_file_name` as the group.
- Edge features alone may not be enough to classify IPL teams, because team identification depends heavily on jersey color and texture. Edge features are meant to complement color and texture features.

---

## 7. Final Output

After both scripts are run, the final edge-feature file should contain one row per image-cell with populated edge features:

```text
image_file_name, cell_id, x_min, y_min, x_max, y_max, y_team_id, f_edge_density, f_canny_count, f_sobel_mean, f_sobel_std, f_laplacian_var, f_contour_count
```

This file can then be merged into the full feature-engineering dataset for downstream EDA, preprocessing, scaling, cross-validation, and model training.
