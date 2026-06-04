import nbformat as nbf
with open('Dataset_Features_FINAL.ipynb', 'r') as f:
    nb = nbf.read(f, as_version=4)

nb.cells[-2].source = """# Phase 20: Shape (HOG) vs. Intensity (Canny/Sobel)
In Chapter 3, we injected 15 Edge features. We can classify them into two families:
1. **Simple Edge Intensity (6 features):** `f_canny`, `f_sobel`, `f_laplacian`
2. **Shape Curvature (9 features):** `hog_bin_0` through `hog_bin_8`

Let's dive into the Random Forest's feature importances to see which family it prioritized, and specifically which HOG angles (e.g., vertical vs horizontal curves) helped it detect players!"""

with open('Dataset_Features_FINAL.ipynb', 'w') as f:
    nbf.write(nb, f)
print("Markdown fixed!")
