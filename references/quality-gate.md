# Quality Gate Reference

This document describes the automated validation loop used by figma-perfect to
ensure pixel fidelity before any output reaches the user.

---

## Overview

After code is generated, figma-perfect runs a **3-iteration automated loop**:

1. Screenshot the live page → diff against Figma references → score
2. If score < 90%, fix the worst sections → re-score
3. Repeat up to 3 times
4. Present results to the user with a clean score card

The user **never sees a score below 75%** — the agent keeps refining until that
floor is met or iterations are exhausted.

---

## Score Thresholds

### Overall Page Score

| Score | Status | Meaning |
|-------|--------|---------|
| ≥ 90% | `READY_FOR_REVIEW` | Pixel-accurate — present to user |
| ≥ 75% | `NEEDS_REFINEMENT` | Decent but has weak spots — auto-refine |
| < 75% | `MAJOR_ISSUES` | Significant layout/style problems — auto-refine |
| Any, iteration ≥ 3 | `MAX_ITERATIONS_REACHED` | Best effort — present regardless |

### Per-Section Scores

| Score | Status | Priority | Action |
|-------|--------|----------|--------|
| ≥ 85% | `PASS` | — | No fix needed |
| ≥ 70% | `WARN` | MEDIUM | Fix if refinement slots available |
| < 70% | `FAIL` | HIGH | Fix first |

---

## How Sections Are Divided

The page screenshot is divided into **equal horizontal strips** — one strip per
reference screenshot exported from Figma.

Example: If `figma-data/screenshots/` contains:
```
full.png             ← used for full-page diff (60% weight)
section-01-Hero.png  ← strip 1 of page
section-02-Nav.png   ← strip 2
section-03-Cards.png ← strip 3
...
```

The page height is divided by `N` section screenshots (excluding `full.png`).
Each strip is diffed against its corresponding Figma reference.

**Overall score formula:**
```
overall = full_page_match × 0.6 + section_average × 0.4
```
(If `full.png` is absent, only the section average is used.)

---

## Validation Loop Algorithm

```
iteration = 1
while iteration <= 3:
    screenshot page → diff → score all sections
    
    if overall >= 90% or iteration >= 3:
        break
    
    identify FAIL sections (priority: match ASC)
    identify WARN sections (priority: match ASC)
    
    fix_targets = FAIL[:3] + WARN[:2]   # max 3–5 sections per pass
    
    for each section in fix_targets:
        apply targeted fix
        re-diff that section to verify
        if section got WORSE → revert fix
    
    iteration += 1

present results to user
```

### Key rules
- Max **3 sections** fixed per iteration (targeted, not full rebuild)
- FAIL sections take priority over WARN
- After fixing, **re-diff to verify** — revert if worse
- Never exceed 3 total iterations

---

## Tips for Improving Low-Scoring Sections

### Typography issues (most common)
- **Wrong font**: Run `font-map.py` to confirm substitution mapping. Verify
  the Google Fonts `<link>` is actually in the `<head>`.
- **Wrong size/weight**: Cross-check `tokens.json` → `typography` section.
  Values should be in `px`, not `rem` (Figma exports px).
- **Wrong line-height**: Figma line-height is often in px. CSS needs the
  matching value or a unitless ratio.

### Color issues
- **Slightly off colors**: Check that hex values were copied from `tokens.json`,
  not manually guessed.
- **Opacity layers**: Figma uses fills with opacity. In CSS, use `rgba()` or
  a semi-transparent background rather than `opacity` on the element itself.
- **Gradient wrong**: Inspect `fills` array in `design.json` for exact stops.

### Layout/spacing issues
- **Padding/gap off**: Check `paddingTop/Right/Bottom/Left` and
  `itemSpacing` in `tokens.json`.
- **Element misaligned**: Check `primaryAxisAlignItems` / `counterAxisAlignItems`
  (maps to `justify-content` / `align-items`).
- **Overflow clipping**: Figma `clipsContent: true` → CSS `overflow: hidden`.

### Image/asset issues
- **Missing image**: Verify file exists in `figma-data/assets/`. Check the
  `imageRef` in `design.json` matches the filename.
- **Wrong aspect ratio**: Figma exports at original dimensions. Use
  `object-fit: cover` and set explicit width/height.
- **Image not loading**: Check the `src` path is relative to the HTML file's
  location (not the working directory).

### Shadow/border issues
- **Shadow wrong**: Compare `boxShadow` CSS to `effects` array in `design.json`.
  Figma shadow format: `x y blur spread color`.
- **Border radius off**: Use `rectangleCornerRadii` (per-corner) or
  `cornerRadius` (uniform) from `design.json`.

### Structural issues
- **Section order wrong**: Check screenshot numbering matches DOM order.
- **Section height too short**: Ensure no `height: 100vh` capping a taller section.
- **Sticky header overlap**: If a nav sticks, account for it in section offsets.

---

## User Checkpoint Format

When presenting results to the user (Phase 5), always use this format:

```
🎯 Figma → Code: {overall}% match

{per-section lines with emoji indicators}

Font subs: {original} → {substitute}, …

View it at: http://localhost:{PORT}
Want me to refine the weak sections, or ship it?
```

**Emoji indicators:**
- ✅ PASS (≥ 85%)
- ⚠️ WARN (≥ 70%, < 85%) — include a brief reason
- ❌ FAIL (< 70%) — include a brief reason

**Example:**
```
🎯 Figma → Code: 91% match

✅ Hero: 94%
✅ Trending: 91%
✅ Platform: 93%
✅ How It Works: 95%
⚠️ Why Creators: 82% — card mockup images differ slightly
✅ FAQ: 90%
⚠️ Footer: 85% — icon cluster spacing

Font subs: Vastago Grotesk → Sora, Ethnocentric → Russo One

View it at: http://localhost:3088
Want me to refine the weak sections, or ship it?
```

**Accepted user responses:**
| Response | Action |
|----------|--------|
| "ship it" / "looks good" / "done" | Finish — deliver final code |
| "fix the footer" | Targeted fix on named section only |
| "refine more" | One more auto-refinement pass |
| Specific feedback ("make the hero font bigger") | Apply change directly |

Max **2 user interactions** after the initial checkpoint.

---

## validate-loop.py Quick Reference

```bash
# Basic usage
python3 $SKILL_DIR/scripts/validate-loop.py \
    --url "http://localhost:3088" \
    --screenshots ./figma-data/screenshots/ \
    --output ./figma-data/validation/ \
    --iteration 1

# Read the report
cat figma-data/validation/report.json | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('Overall:', r['overall_match'], '%', '-', r['status'])
for s in r['sections']:
    icon = '✅' if s['status']=='PASS' else ('⚠️' if s['status']=='WARN' else '❌')
    print(f\"  {icon} {s['name']}: {s['match']}%\")
print('Worst:', r['worst_sections'])
"
```

**Report fields:**
| Field | Description |
|-------|-------------|
| `overall_match` | Blended full-page + section-average score |
| `status` | `READY_FOR_REVIEW` / `NEEDS_REFINEMENT` / `MAJOR_ISSUES` / `MAX_ITERATIONS_REACHED` |
| `sections` | Per-section breakdown with name, match %, status, diff_image path |
| `worst_sections` | Names of lowest-scoring sections (FAIL first, then WARN) |
| `iteration` | Which iteration this report is from |
| `diff_image` | Path to full-page diff PNG (red = different) |
| `page_screenshot` | Path to the page screenshot taken during this run |
