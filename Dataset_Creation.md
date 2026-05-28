# Dataset Creation — How We Built the IPL Image Dataset

## Overview

This document describes how the 1000-image IPL dataset was collected, filtered, and prepared. The raw data came from two professional sports data APIs; significant cleaning was required before the images were usable for annotation.

---

## Data Sources

### 1. BCCI Official API
Images were sourced using an official BCCI API key, giving access to the internal media library attached to each match. This provided high-quality broadcast and gallery images directly from the governing body, including:
- Live match broadcast frames
- Official team photographs
- Ground and crowd coverage

### 2. CricketAPI v5
Additional images were pulled from [CricketAPI v5](https://www.cricketapi.com/v5/docs/association-player-stats-rest-api), specifically the association and match media endpoints. This gave access to:
- Per-match image galleries
- Player headshots and team group shots
- Venue and pre-match coverage

### 3. Opta Cricket API
Opta's cricket data feed was used as a supplementary source. Opta is a premium sports analytics provider used by broadcasters and leagues. The image endpoints provided:
- Broadcast-style in-play frames
- Ball-by-ball event images (boundaries, wickets, milestones)
- Player action shots during specific deliveries

---

## Raw Collection

Images were fetched per match across multiple IPL seasons. Each match API call returned a gallery of images attached to that fixture. The raw pull resulted in several thousand images before any filtering.

Key parameters used during collection:
- **Seasons covered:** Multiple IPL seasons (to ensure all 10 teams represented)
- **Match types:** League stage, playoffs, and finals
- **Image format:** JPEG (some PNGs were converted)
- **Target resolution:** Minimum 800×600 px (images below this were discarded at source)

---

## Cleaning Pipeline

The raw gallery had significant noise. The following cleaning steps were applied sequentially.

### Step 1 — Remove Small / Low Resolution Images

A large fraction of API responses included thumbnail-sized images (used for previews or metadata entries). Any image below **800×600 px** was discarded.

- Many match galleries returned 5–10 thumbnail variants of the same shot at different resolutions
- Only the highest-resolution variant was retained
- Images with extreme aspect ratios (e.g. portrait-orientation sponsor banners) were also dropped

### Step 2 — Remove Non-Cricket Images

Not all images in a match gallery are of the game itself. Common contaminants included:
- **Sponsor and brand creatives** — full-frame logo cards, trophy sponsorship images, DLF/Tata IPL branding slides
- **Scorecard graphics** — post-match stat overlays with no ground/player content
- **Social media cards** — pre-designed quote cards, "Player of the Match" announcement graphics
- **Press conference images** — players at podiums, indoor press rooms with no ground visible
- **Award ceremony shots** — trophy lifts, medal ceremonies in front of stage backdrops

These were filtered by a combination of:
1. **Filename/caption keyword filter** — API metadata often contained tags like `sponsor`, `award`, `presser`, `graphic`
2. **Manual review pass** — remaining ambiguous images reviewed and dropped if no pitch/ground/crowd was visible

### Step 3 — Filter API Noise / Corrupt Responses

Some galleries returned due to API pagination issues or internal CDN errors:
- **Duplicate images** with different filenames (same SHA-256 hash) — deduplicated, one copy kept
- **Partially downloaded images** — JPEG files that were truncated mid-download, showing as corrupt or with a grey/black bottom portion. Detected by attempting to open and decode each file with PIL
- **Wrong-match images** — occasionally the gallery endpoint for Match X returned images tagged to a different fixture. These were spotted by metadata mismatch (team names in API response vs. teams in filename)
- **Watermark-heavy images** — some syndicated images had large opaque watermarks covering >30% of the frame. These were removed as they would confuse the annotation grid

### Step 4 — Remove Non-Ground / Non-Crowd Images

Even after the above, some legitimate cricket images were not suitable for grid annotation. These included:
- **Close-up player portraits** — single player face filling the frame (no spatial team context)
- **Overhead drone shots** — bird's-eye view of stadium with no player detail visible at cell level
- **Boundary rope / wide-angle empty ground shots** — no players present
- **Stumps / pitch close-ups** — no teams visible

These were filtered by requiring at least a portion of the image to show identifiable player jersey colours at the 100×75 px cell level.

### Step 5 — Standardise Resolution

All surviving images were resized to a uniform **800×600 px** using high-quality Lanczos resampling. This ensures:
- Identical grid cell dimensions (100×75 px) across all images
- Consistent feature vector sizes during extraction
- No per-image normalisation required at training time

### Step 6 — No-Player Image Set

37 intentional "hard negative" images were added separately — crowd shots, scoreboard frames, and venue wide-shots confirmed to contain no visible players. These are the `np_` prefixed originals, renamed to `img_251`–`img_287`. They form the all-zero ground truth (every cell = 0) and help the classifier learn background vs. player distinction.

---

## Final Dataset Composition

| Stage | Images Remaining |
|---|---|
| Raw API pull | ~5,000+ |
| After resolution filter | ~3,200 |
| After non-cricket filter | ~2,100 |
| After API noise / dedup | ~1,800 |
| After non-ground filter | ~1,100 |
| After standardisation + manual curation | **963** game images |
| + No-player images added | **1000 total** |

---

## File Naming

All images were renamed from their original API-assigned UUIDs (e.g. `cb25_5968_627486_KKR.jpg`) to a clean sequential scheme:

```
img_1.jpg   →   img_250.jpg    (game images, batch 1)
img_251.jpg →   img_287.jpg    (no-player images)
img_288.jpg →   img_1000.jpg   (game images, batch 2)
```

The rename was done via a two-pass script (rename to temp first, then to final name) to avoid filename collisions. The train/test split column in the database was preserved through the rename — only filenames changed, not split assignments.

---

## Data Quality Notes

- All images are from official/licensed sources (BCCI, Opta, CricketAPI) — not scraped from public websites
- No player face recognition was used at any stage; labels are team-level only
- The 37 no-player images were manually verified to contain zero player jerseys at any resolution
- Duplicate frame sequences (consecutive broadcast frames showing the same scene) were not deduplicated — each frame may look similar to adjacent ones, which is acceptable for a classification task
