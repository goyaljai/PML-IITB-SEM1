# Labelling Process — How We Annotate

## What We're Labelling

Each of the 1000 IPL broadcast images is divided into an 8×8 grid (64 cells). Every cell gets one of 11 labels: 0 for empty (no visible player), or 1–10 for the IPL team whose player(s) appear in that cell.

The goal is cell-level team identification — not just "which teams are in this image" but "exactly which cells contain players from which team."

---

## The Tool

A custom web annotation tool was built specifically for this task, available at **http://35.207.192.90:8001**.

### Interface

- The image is displayed at 800×600 px with the 8×8 grid overlaid as a semi-transparent canvas
- Each team has a distinct colour; painting a cell fills it with that team's colour
- The current label state is always visible — previously saved annotations load automatically

### Controls

| Action | Control |
|---|---|
| Select team CSK–RCB | Keys `1`–`9` |
| Select SRH (label 10) | Key `0` |
| Erase a cell | Key `E` or right-click |
| Next image | `Space` or `→` |
| Previous image | `←` |
| Jump to next unannotated | `Tab` |
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Shift+Z` |

### Saving

Autosave fires 800ms after the last paint action. Any pending save is flushed before navigating away. The status badge (bottom-right) shows: `Unsaved → Saving → Saved`.

---

## Who Annotates

Five annotators, all with admin access:

| Annotator | Username |
|---|---|
| Jai Goyal | jai |
| Sharon | sharon |
| Rishabh | rishabh |
| Ashutosh | ashutosh |
| Udit | udit |

Each image is claimed by one annotator at a time. Locks auto-expire after 3 minutes of inactivity; any admin can force-unlock a stuck image.

---

## Annotation Rules

1. **Paint every cell containing a visible player** with that player's team label
2. **Leave empty cells at 0** — background, grass, crowd, scoreboards, watermarks, etc.
3. **Partial visibility counts** — if a player's jersey is visible enough to identify the team, label it
4. **Ambiguous cells** — if you genuinely cannot tell which team, leave as 0
5. **No-player images (img_251–img_287)** — these are crowd shots / venue wide-shots with no identifiable players. Leave all 64 cells at 0 and move on
6. **Two teams on screen** — both teams may appear in the same image (e.g. fielder + batsman). Label each cell with whichever team's player occupies it
7. **Umpires / support staff** — label 0 (empty), not a team

---

## Quality Notes

- Each image is annotated by exactly one person
- Admins can overwrite any annotation if a correction is needed
- All cells saved as all-zeros delete the annotation record — the image reverts to "pending" in the sidebar
- The annotation portal shows live progress: annotated / total and per-user counts

---

## Output Format

Annotations are stored in SQLite as an 8×8 JSON array per image. At export time:

**CSV:** One row per image, columns `c01`–`c64` (row-major order)

```
Image File Name, Train Or Test, c01, c02, ..., c64
img_1.jpg, Train, 0, 0, 6, 6, 6, 0, 0, 0, ...
```

**JSON:**
```json
{
  "image": "img_1.jpg",
  "split": "train",
  "labels": [[0,0,6,6,...], [0,6,6,6,...], ...],
  "features": [0,0,6,6,...,0]
}
```
