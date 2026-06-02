import pandas as pd
import numpy as np
from pathlib import Path


# ============================================================
# HARD-CODED FILE PATHS
# ============================================================

SOURCE_CSV = "Dataset_Annotations.csv"
TARGET_TEMPLATE_CSV = "template.csv"
OUTPUT_CSV = "Edge_features.csv"


# ============================================================
# GRID SETTINGS
# ============================================================

IMAGE_WIDTH = 800
IMAGE_HEIGHT = 600

GRID_ROWS = 8
GRID_COLS = 8

CELL_WIDTH = IMAGE_WIDTH // GRID_COLS      # 100
CELL_HEIGHT = IMAGE_HEIGHT // GRID_ROWS    # 75


# ============================================================
# TARGET CSV STRUCTURE
# ============================================================

DEFAULT_TARGET_COLUMNS = [
    "image_file_name",
    "original_split",
    "fold_id",
    "cell_id",
    "cell_num",
    "grid_row",
    "grid_col",
    "x_min",
    "y_min",
    "x_max",
    "y_max",
    "y_team_id",
    "y_player_count",

    # Positional features
    "f_cell_row_norm",
    "f_cell_col_norm",
    "f_x_center_norm",
    "f_y_center_norm",

    # Edge feature columns
    "f_edge_density",
    "f_canny_count",
    "f_sobel_mean",
    "f_sobel_std",
    "f_laplacian_var",
    "f_contour_count",
]


EDGE_FEATURE_COLUMNS = [
    "f_edge_density",
    "f_canny_count",
    "f_sobel_mean",
    "f_sobel_std",
    "f_laplacian_var",
    "f_contour_count",
]


def get_target_columns():
    """
    Reads Test.csv to get the target structure.

    If Test.csv is malformed or missing commas, fallback to the default
    target column structure.
    """

    target_path = Path(TARGET_TEMPLATE_CSV)

    if not target_path.exists():
        print(f"{TARGET_TEMPLATE_CSV} not found. Using default target columns.")
        return DEFAULT_TARGET_COLUMNS.copy()

    try:
        template_df = pd.read_csv(TARGET_TEMPLATE_CSV)

        # If Test.csv has only 1 column, it is probably malformed.
        if len(template_df.columns) <= 1:
            print(
                f"{TARGET_TEMPLATE_CSV} appears malformed or not comma-separated. "
                "Using default target columns."
            )
            return DEFAULT_TARGET_COLUMNS.copy()

        target_columns = list(template_df.columns)

    except Exception as e:
        print(f"Could not read {TARGET_TEMPLATE_CSV}: {e}")
        print("Using default target columns.")
        return DEFAULT_TARGET_COLUMNS.copy()

    # Add required edge feature columns if absent
    for col in EDGE_FEATURE_COLUMNS:
        if col not in target_columns:
            target_columns.append(col)

    # Add required base columns if absent
    for col in DEFAULT_TARGET_COLUMNS:
        if col not in target_columns:
            target_columns.append(col)

    return target_columns


def convert_source_to_target():
    source_df = pd.read_csv(SOURCE_CSV)

    required_source_columns = ["Image File Name", "Train Or Test", "count"]
    cell_columns = [f"c{i:02d}" for i in range(1, 65)]

    required_source_columns.extend(cell_columns)

    missing_columns = [
        col for col in required_source_columns
        if col not in source_df.columns
    ]

    if missing_columns:
        raise ValueError(f"Missing columns in source CSV: {missing_columns}")

    target_columns = get_target_columns()

    output_rows = []

    for _, row in source_df.iterrows():
        image_file_name = row["Image File Name"]
        original_split = row["Train Or Test"]
        player_count = row["count"]

        for cell_num in range(1, 65):
            cell_id = f"c{cell_num:02d}"

            grid_row = (cell_num - 1) // GRID_COLS
            grid_col = (cell_num - 1) % GRID_COLS

            x_min = grid_col * CELL_WIDTH
            y_min = grid_row * CELL_HEIGHT
            x_max = x_min + CELL_WIDTH
            y_max = y_min + CELL_HEIGHT

            x_center = (x_min + x_max) / 2
            y_center = (y_min + y_max) / 2

            output_row = {
                "image_file_name": image_file_name,
                "original_split": original_split,
                "fold_id": -1,

                "cell_id": cell_id,
                "cell_num": cell_num,
                "grid_row": grid_row,
                "grid_col": grid_col,

                "x_min": x_min,
                "y_min": y_min,
                "x_max": x_max,
                "y_max": y_max,

                "y_team_id": row[cell_id],
                "y_player_count": player_count,

                "f_cell_row_norm": grid_row / (GRID_ROWS - 1),
                "f_cell_col_norm": grid_col / (GRID_COLS - 1),
                "f_x_center_norm": x_center / IMAGE_WIDTH,
                "f_y_center_norm": y_center / IMAGE_HEIGHT,

                # Edge feature values are placeholders for now.
                # These will be filled later after edge extraction.
                "f_edge_density": np.nan,
                "f_canny_count": np.nan,
                "f_sobel_mean": np.nan,
                "f_sobel_std": np.nan,
                "f_laplacian_var": np.nan,
                "f_contour_count": np.nan,
            }

            output_rows.append(output_row)

    output_df = pd.DataFrame(output_rows)

    # Ensure all target columns exist
    for col in target_columns:
        if col not in output_df.columns:
            output_df[col] = np.nan

    # Keep target column order
    output_df = output_df[target_columns]

    output_df.to_csv(OUTPUT_CSV, index=False)

    print(f"Converted file saved as: {OUTPUT_CSV}")
    print(f"Rows created: {len(output_df)}")
    print(f"Columns: {len(output_df.columns)}")
    print(output_df.head())


if __name__ == "__main__":
    convert_source_to_target()