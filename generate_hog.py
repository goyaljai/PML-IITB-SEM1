import pandas as pd
import numpy as np
from skimage.feature import hog
from skimage.color import rgb2gray
from PIL import Image
from pathlib import Path
from huggingface_hub import snapshot_download
import os

print("Downloading dataset...")
dataset_dir = Path(snapshot_download(repo_id="goyaljai/IPL-Player-Detection-IITB-PML", repo_type="dataset"))
print("Dataset ready.")

annotations = pd.read_csv("Dataset_Annotations.csv")

hog_data = []

total_images = len(annotations)
print(f"Extracting HOG for {total_images} images...")

for idx, row in annotations.iterrows():
    img_name = row['Image File Name']
    split = row['Train Or Test'].lower()
    
    img_path = dataset_dir / split / img_name
    if not img_path.exists():
        continue
        
    try:
        img_rgb = np.array(Image.open(img_path).convert('RGB'))
    except:
        continue
        
    for r in range(8):
        for c in range(8):
            x1 = c * 100
            y1 = r * 75
            cell_rgb = img_rgb[y1:y1+75, x1:x1+100]
            gray = rgb2gray(cell_rgb)
            
            # Extract simple 9-bin HOG for the whole cell
            fd = hog(gray, orientations=9, pixels_per_cell=(75, 100),
                     cells_per_block=(1, 1), feature_vector=True, channel_axis=None)
            
            row_dict = {
                'Image File Name': img_name,
                'cell_row': r,
                'cell_col': c
            }
            for i, val in enumerate(fd):
                row_dict[f'hog_bin_{i}'] = val
            hog_data.append(row_dict)
            
    if (idx + 1) % 100 == 0:
        print(f"Processed {idx+1}/{total_images} images")

df_hog = pd.DataFrame(hog_data)
df_hog.to_csv("Individual_Feature_CSVs/Dataset_Features_HOG.csv", index=False)
print("HOG Features saved to Individual_Feature_CSVs/Dataset_Features_HOG.csv")
