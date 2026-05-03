# PML-IITB-SEM1

## Course Project: Automated Detection of Teams of Players Using IPL Jersey Identification

### Overview
- **Weightage:** 40 marks (20%)
- **Team Size:** Maximum 4 members
- **Submission Deadline:** **June 06, 2026, 23:55 Hrs**
- **Evaluation Mode:** Presentation, video, and submitted artifacts (dataset, code, model weights, CSV outputs)

## Problem Statement
Build an ML system that analyzes cricket images and:
1. Detects player presence in image regions.
2. Counts players.
3. Classifies each detected player by IPL franchise using jersey cues (color, pattern, logo).

> Only player presence and team affiliation are required. Player name identification is **not** required.

The model should generalize across diverse match contexts (lighting, camera angles, player appearances, and occlusions).

## Dataset Requirements
You must create your own labeled dataset from reliable online cricket image sources.

### Coverage and Balance
- Ensure all IPL franchises are adequately represented.
- Recommended: at least **100 instances per franchise**.
- Teams are encouraged to collaborate for a larger, balanced labeled dataset.

### Image Content Expectations
Include images with:
- Multiple players from different IPL franchises in one frame.
- Distinct jerseys (color/design/logo variation).
- Pose/orientation/body-visibility variation.
- Different conditions (lighting, camera angle, crowd background, occlusions).
- Both single-player and multi-player scenes.
- No-player images (e.g., pitch/crowd/background) for generalization.

### Technical Constraints
- All images must be **4:3** aspect ratio.
- Resize to **800 x 600** pixels.
- Downsampling is allowed.
- Do **not** upscale images below 800x600.
- Include a short dataset README describing image sources.

## Modeling Task
- Divide each **800 x 600** image into an **8 x 8 grid** (64 cells).
- Predict one class per cell:
  - `0` No team
  - `1` Chennai Super Kings (CSK)
  - `2` Delhi Capitals (DC)
  - `3` Gujarat Titans (GT)
  - `4` Kolkata Knight Riders (KKR)
  - `5` Lucknow Super Giants (LSG)
  - `6` Mumbai Indians (MI)
  - `7` Punjab Kings (PBKS)
  - `8` Rajasthan Royals (RR)
  - `9` Royal Challengers Bengaluru (RCB)
  - `10` Sunrisers Hyderabad (SRH)

If multiple players appear in a cell, predicting **any one** valid team in that cell is acceptable.

### Important Restriction
- You may use hand-crafted image feature engineering.
- Methods that automatically learn image features (e.g., **CNNs or equivalents**) should **not** be used.

### Model Artifact
- Save trained model as: `model_<teamname>.pkl`

## Output Format (Predictions CSV)
Run your final model on both train and test sets and generate a CSV with columns:
- `Image File Name, Train Or Test, c01, c02, ..., c64`

Each cell column (`c01` to `c64`) must contain an integer `0-10` as per class mapping.

## Deliverables
1. **Dataset**
   - As per required count/size/format.
   - Include folder structure + README/TXT with sources.
2. **Source Code**
   - Data processing, feature engineering, training, inference scripts/notebooks.
3. **Performance Metrics**
   - Report train/test performance.
4. **Model Weights**
   - Trained `.pkl` file.
5. **Pipeline Code**
   - Loads pickle model, accepts test instance, produces required output.
6. **Predictions CSV**
   - In specified format.
7. **Presentation**
   - Structured deck covering approach, methodology, results.
8. **Video (~5 min)**
   - End-to-end workflow, challenges, learnings.

## Presentation Guidelines
- No fixed slide limit, but keep concise and complete.
- Title slide must include all team member names and roll numbers.
- After title slide, include max 3 executive summary slides.
- Remaining slides should cover:
  - Problem understanding
  - Methods and paths explored (including failures/dead-ends)
  - Metrics, observations, conclusions
  - Challenges and learnings
- Video duration should not exceed **5:00** by more than **15 seconds** (penalty applies).

## Evaluation Criteria
| Criteria | Marks |
|---|---:|
| Problem detailing, solution approach, completeness, DS process followed | 15 |
| Quality on train/test + hold-out data, observations, analysis, conclusions | 15 |
| Documentation quality (presentation + video) | 10 |

---

## Suggested Initial Repository Structure

```text
PML-IITB-SEM1/
  README.md
  data/
    raw/
    processed/
    labels/
  notebooks/
  src/
  models/
  outputs/
    predictions/
  reports/
```
