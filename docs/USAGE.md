# figma-perfect

**Convert Figma designs to pixel-perfect code using the Figma REST API. No MCP required.**

Use this skill when:
- User shares a Figma URL and wants code
- User says "implement this design", "build from Figma", "convert design to code", "pixel-perfect"
- User wants to turn a Figma file into HTML, React, Next.js, Vue, or any other framework
- User asks to extract Figma tokens, colors, fonts, or spacing values

**Does NOT use MCP** — works entirely via Figma REST API + Python scripts.

---

## Philosophy: Save Tokens, Keep Quality

This skill is designed to **minimize LLM token usage while maximizing output quality.**

```
Layer 1: Algorithm (generate.py) → 85%+ accuracy, ZERO tokens
Layer 2: LLM refinement → targeted fixes only, minimal tokens → 92%+
Layer 3: User wants more? → Structured refinement via validate-loop
          (section scores tell you EXACTLY what’s wrong → fix only that)
```

**Why this is better than raw prompting:**
- Raw prompt: "build this Figma" → LLM generates everything from scratch → 300k+ tokens, inconsistent
- This skill: algorithm handles mechanical work, LLM does only judgment → 50-80k tokens, structured

**The rule:** Never use LLM tokens for work that rules can handle. Colors, spacing, flexbox, fonts — that's math, not intelligence. Reserve the LLM for: what looks wrong, what should be interactive, how to fix ambiguous layouts.

**For users refining further:** The validate-loop gives per-section scores so you know EXACTLY which section needs work and why. One targeted prompt ("fix the footer spacing") beats ten blind ones ("make it more accurate").

---

## Prerequisites

- Python 3.7+
- A Figma **Personal Access Token** (from https://www.figma.com/settings → Access Tokens)
- The target Figma file URL (e.g. `https://www.figma.com/design/abc123/MyDesign?node-id=217-3340`)
- `pip install requests Pillow` (scripts auto-install if missing)

**Get the user's Figma token if not already in memory/tools. It's required — don't start without it.**

---

## Skill Directory

All scripts are at:
```
.//scripts/
```

References:
```
.//references/
```

Set `SKILL_DIR` at the start of every session:
```bash
SKILL_DIR=./  # path to pixel-forge root
```

---

## Complete Lifecycle

```
Figma URL
   ↓
Phase 0: DISCOVER     (interactive — ask user what's missing)
   ↓
Phase 1: EXTRACT      (automatic, silent)
   ↓
Phase 2: BUILD        (automatic, silent)
   ↓
Phase 3: VALIDATE     (automatic, silent)
   ↓
Phase 4: AUTO-REFINE  (automatic, silent — max 3 iterations)
   ↓
Phase 5: PRESENT ──── CHECKPOINT: STOP and show user results
   ↓ (only if user wants changes)
Phase 6: FUNCTIONAL   (add interactivity — buttons, routing, forms, state)
   ↓
Phase 7: POLISH       (targeted fixes based on user feedback)
   ↓
DONE: Final code ready
```

---

## Phase 0 — DISCOVER (interactive)

**Before doing anything, figure out what you're working with.** Don't assume — ask.

This phase runs ONCE at the start. Gather everything you need so the rest of the pipeline is fully automatic.

### Step 0.1: Check what the user provided

The user MUST provide:
- ✅ Figma URL
- ✅ Figma Personal Access Token (or already stored in TOOLS.md)

If either is missing, ask immediately. Don't proceed without both.

### Step 0.2: Detect or ask for tech stack

First, try to AUTO-DETECT by scanning the project directory:

```
Check for:                    → Framework:
package.json with "next"      → Next.js (React)
package.json with "react"     → React
package.json with "vue"       → Vue.js
package.json with "nuxt"      → Nuxt (Vue)
package.json with "svelte"    → Svelte
tailwind.config.*             → Tailwind CSS
tsconfig.json                 → TypeScript
*.xcodeproj / Package.swift   → SwiftUI
build.gradle.kts + compose    → Kotlin Compose
None of the above             → Ask user
```

If auto-detection fails OR no project directory exists, ask:

```
🛠️ What tech stack should I use?

1. HTML + CSS (standalone, no framework)
2. React + Tailwind CSS
3. Next.js + Tailwind CSS
4. Vue.js
5. Other (tell me)

Or if this goes into an existing project, point me to the directory.
```

### Step 0.3: Check for existing codebase

Ask if not obvious:

```
📁 Is this a new project or going into an existing one?

A) New project — I'll generate standalone files
B) Existing project — point me to the repo/directory
```

If existing project:
1. Scan for existing **components** (buttons, cards, modals, etc.)
2. Scan for existing **design tokens** (CSS variables, Tailwind theme, etc.)
3. Scan for existing **layout patterns** (sidebar, grid system, etc.)
4. Note: "I found these existing components: [list]. I'll reuse them instead of rebuilding."

### Step 0.4: Ask about scope

```
📐 What should I build?

A) Full page — all sections from the Figma frame
B) Specific sections — tell me which ones
C) Just components — extract reusable components only
D) Just tokens — extract design tokens/CSS variables only
```

### Step 0.5: Confirm and proceed

Before starting the pipeline, confirm:

```
✅ Ready to build:

- Figma: [URL]
- Stack: React + Tailwind CSS
- Project: New (standalone)
- Scope: Full page (all sections)
- Output: ./figma-output/

Starting extraction... (this will run silently until I have results)
```

### Discovery shortcuts

**If the user provides everything upfront** (URL + token + "build it in React"), skip to confirmation and proceed. Don't ask questions you already have answers to.

**If working in a known project** (e.g., creator-vault with Next.js + Tailwind), auto-detect and confirm without asking.

**If the user says "just build it"**, default to:
- Stack: HTML + CSS (standalone)
- Scope: Full page
- Project: New

And confirm before proceeding.

---

## Phase 1 — EXTRACT (automatic, silent)

Run `extract.py` to pull everything from Figma in one shot:

```bash
python3 $SKILL_DIR/scripts/extract.py \
  --url "FIGMA_URL" \
  --token "FIGMA_TOKEN" \
  --output ./figma-data/
```

**What you get:**
```
figma-data/
├── design.json              # Raw Figma node tree (full API response)
├── tokens.json              # Extracted design tokens (colors, fonts, etc.)
├── spec.md                  # Human-readable implementation spec
├── screenshots/
│   ├── full.png             # Full frame screenshot
│   ├── section-01-Hero.png  # Per-section screenshots
│   └── section-02-...png
└── assets/
    ├── 217-3340.png         # Exported image fills
    └── ...
```

**Dry run first to verify URL parsing:**
```bash
python3 $SKILL_DIR/scripts/extract.py \
  --url "FIGMA_URL" \
  --token "FIGMA_TOKEN" \
  --dry-run
```

**Error handling:**
- If Figma API returns 403 → token invalid or file not shared. Tell the user immediately. Do NOT proceed.
- If extract finds 0 sections → warn the user their Figma file may not be structured properly.
- If rate-limited (429) → extract.py auto-retries.

After extraction, always read `figma-data/spec.md` and check font substitutions:

```bash
cat figma-data/spec.md
python3 $SKILL_DIR/scripts/font-map.py --all
```

---

## Phase 2 — BUILD (automatic, silent)

### 2a — Run generate.py (ALWAYS do this first — zero cost)

```bash
# Detect framework from Phase 0 discovery, then generate:
python3 $SKILL_DIR/scripts/generate.py --input ./figma-data/ --output ./output/ --framework nextjs --tailwind
```

**Framework selection (from Phase 0):**
| User wants | Command |
|---|---|
| Next.js + Tailwind (default) | `--framework nextjs --tailwind` |
| React | `--framework react` |
| Plain HTML | `--framework html` |

**What generate.py produces (0 LLM tokens, ~50ms):**
- Complete project scaffold with proper file structure
- React/Next.js components split by Figma sections
- CSS from design tokens (colors, fonts, spacing, shadows)
- Tailwind config generated from Figma tokens
- Real image assets linked
- ~85-90% visual accuracy out of the box

**Why generate.py first:**
- Deterministic: same input = same output every time
- Free: zero API calls, zero tokens
- Fast: 50ms execution
- LLM then only does JUDGMENT work (what's wrong + how to fix + add functionality)

### 2b — Detect project context (if integrating into existing project)

```bash
# Is there an existing project?
ls package.json tailwind.config.js tsconfig.json 2>/dev/null

# What framework?
cat package.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(list(d.get('dependencies',{}).keys())[:20])"
```

**If integrating into existing project:** skip generate.py, instead use extracted tokens to hand-build components that match existing patterns.

**Decision matrix (for existing projects):**
| Context | Output |
|---|---|
| No project found | Use generate.py output directly |
| React/Next.js + Tailwind | Use generate.py `--nextjs --tailwind`, merge into project |
| React/Next.js (no Tailwind) | Use generate.py `--react`, adapt CSS |
| Vue | Generate HTML, manually convert (Vue not yet supported) |
| Existing design system | Extend existing tokens, follow naming conventions |

### 2b — Generate code

**Rules (non-negotiable):**

1. **NEVER guess a value** — every pixel, color, font size comes from `figma-data/tokens.json`
2. **NEVER use placeholder images** — use actual files from `figma-data/assets/` or flag as missing
3. **Document ALL font substitutions** in a comment at the top of the file
4. **CSS custom properties for ALL tokens** — no hardcoded values in components
5. **Build section by section** — one section at a time

**Token usage pattern:**
```css
/* Font substitutions: Vastago Grotesk → Sora, Ethnocentric → Russo One */
:root {
  --color-primary: #10C656;
  --color-dark: #1E1E1E;
  --font-heading: 'Sora', sans-serif;
  --size-heading: 72px;
  --weight-heading: 700;
  --lh-heading: 86.4px;
  --radius-card: 15px;
  --shadow-card: 0px 4px 20px 0px rgba(0,0,0,0.1);
}
```

### 2c — Start preview server

```bash
# Start in background so agent can continue
python3 $SKILL_DIR/scripts/serve.py --dir ./output/ --port 3088 &
SERVER_PID=$!
echo "Preview: http://localhost:3088 (PID $SERVER_PID)"
```

Or for Next.js/Vite projects:
```bash
npm run dev &
```

---

## Phase 3 — VALIDATE (automatic, silent)

Run the validation script to get scores:

```bash
python3 $SKILL_DIR/scripts/validate-loop.py \
  --url "http://localhost:3088" \
  --screenshots ./figma-data/screenshots/ \
  --output ./figma-data/validation/ \
  --iteration 1
```

**Read the report:**
```bash
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

**Error handling:**
- If screenshot fails → validate-loop.py retries once automatically, then writes an error report. If it fails, tell the user and offer a manual screenshot path.
- If diff fails → present without scores, note the issue.

---

## Phase 4 — AUTO-REFINE (automatic, silent — max 3 iterations)

```
REPEAT up to 3 times:
  Read report.json
  IF overall >= 90% → EXIT loop (go to Phase 5)
  IF iteration >= 3 → EXIT loop (go to Phase 5 with best result)
  
  Get worst_sections from report
  Fix FAIL sections first (match < 70%), then WARN (match < 85%)
  Max 3 sections per refinement pass
  
  After each fix:
    Re-run validate-loop.py --iteration N
    IF section got WORSE → revert that change
  
  iteration += 1
```

**Quality Gate Rules:**
- NEVER present to user below 75% overall match — keep refining
- NEVER exceed 3 auto-refinement iterations — present best result regardless
- Only fix sections scoring below 80%
- Each pass focuses on max 3 sections (targeted, not full rebuild)
- **STOP visual refinement at 85%+ overall** — remaining gap is usually rendering engine differences
- After 85%+, move to Phase 6 (functionality) immediately

**Common fixes by issue type:**

| Issue | Fix |
|---|---|
| Font looks different | Verify Google Fonts link is in `<head>`, check `font-map.py` output |
| Colors off | Compare hex values in `tokens.json`, check `rgba()` for opacity fills |
| Spacing wrong | Check `gap`, `padding` values in `tokens.json` |
| Image missing | Verify file in `figma-data/assets/`, check `imageRef` in `design.json` |
| Shadow wrong | Check CSS `box-shadow` syntax, verify rgba values from `design.json` |
| Layout broken | Check flexbox mapping from `layoutMode` in tokens |
| Border radius off | Use `rectangleCornerRadii` (per-corner) or `cornerRadius` from tokens |

---

## Phase 5 — PRESENT TO USER ⛔ CHECKPOINT

**STOP here. Show results. Ask what they want.**

After the loop exits, present a clean score card:

```
🎯 Figma → Code: {overall}% match

✅ Hero: 94%
✅ Trending: 91%
✅ Platform: 93%
✅ How It Works: 95%
⚠️ Why Creators: 82% — card mockups differ slightly
✅ FAQ: 90%
⚠️ Footer: 85% — icon cluster layout

Font subs: Vastago Grotesk → Sora, Ethnocentric → Russo One

View it at: http://localhost:3088
Want me to refine the weak sections, or ship it?
```

**Format rules:**
- ✅ for PASS (≥ 85%), ⚠️ for WARN (≥ 70%), ❌ for FAIL (< 70%)
- WARN/FAIL lines get a brief reason (1 phrase, not a paragraph)
- ALWAYS include font substitutions
- ALWAYS include the preview URL
- ALWAYS include per-section scores, not just overall
- End with a clear action question

**If MAX_ITERATIONS_REACHED and score < 75%:**
```
🎯 Figma → Code: 71% match (3 iterations)

After 3 refinement passes, some sections still need work. Here's
where things stand:

❌ Hero: 68% — layout structure differs significantly
✅ Trending: 91%
…

I've hit the iteration limit. Want me to take a different approach
on the Hero section, or should we continue from here?
```

---

## Phase 6 — FUNCTIONAL (add interactivity)

**After visual accuracy hits 85%+, shift focus to making it WORK.**

Visual accuracy above 85% is "good enough" for most production use. The remaining 5-15% gap is often unfixable rendering engine differences (Figma vs browser). Don't waste tokens chasing pixel-perfect when the app has dead buttons.

### Priority Order (STRICT)

| Priority | What | Token budget |
|----------|------|-------------|
| **P0** | Buttons/links clickable | 10-20% |
| **P1** | Navigation/routing works | 10-20% |
| **P2** | Forms submit + validate | 10-20% |
| **P3** | Hover/active states | 10% |
| **P4** | Animations/transitions | 5% |
| **P5** | Pixel-perfect visual polish | Remaining |

### What to add (based on Figma context)

**Detect from node names + structure:**
- Nodes named "Button", "CTA", "Link" → add `onClick`, `href`, cursor pointer
- Nodes named "Nav", "Navbar", "Menu" → add navigation links
- Nodes named "Input", "Search", "Field" → add `<input>` with placeholder
- Nodes named "Card" with links → make entire card clickable
- Nodes named "Tab", "Filter" → add tab switching state
- Pagination components → add page state + handlers

**Add basic interactions:**
```tsx
// Buttons
<button onClick={() => {}} className="cursor-pointer hover:opacity-80 transition">

// Links
<a href="#section" className="hover:underline">

// Cards
<div className="cursor-pointer hover:shadow-lg transition-shadow">

// Inputs
<input type="text" placeholder="Search..." className="focus:ring-2" />
```

**Framework-specific routing:**
- Next.js: Use `<Link href="/page">` from `next/link`
- React: Use `react-router-dom` or anchor tags
- HTML: Standard `<a href="#">`

### Anti-pattern: DON'T do this

❌ Spending 3+ iterations chasing 90% pixel score when buttons don't work
❌ Obsessing over image rendering differences (Chrome ≠ Figma, that's normal)
❌ Burning 40k+ tokens on visual refinement while app has zero interactivity

### Do this instead

✅ Hit 85%+ visual → stop visual refinement
✅ Spend tokens on making the app FUNCTIONAL
✅ One quick visual pass (max 1 iteration) for obvious layout issues
✅ Accept that image rendering will always differ by 5-10% between tools

---

## Phase 7 — USER FEEDBACK POLISH (only if user wants changes)

Accept any of these responses and act accordingly:

| User says | Action |
|-----------|--------|
| "ship it" / "looks good" / "done" | Deliver final code. Done. |
| "fix the footer" | Targeted fix on footer only. Re-validate. Re-present scores. |
| "make buttons work" | Add interactivity to buttons (Phase 6). |
| "refine more" | One more auto-refinement pass (same loop as Phase 4). |
| Specific feedback | Apply the exact change. Re-validate. Re-present. |

**Rules:**
- Max **1 more refinement round** after user feedback
- After applying user feedback, re-run `validate-loop.py` and show updated scores
- Present scores again in the same format

---

## Quick Reference — All Scripts

### generate.py (ZERO LLM tokens — algorithmic baseline)
```bash
# HTML output (default)
python3 $SKILL_DIR/scripts/generate.py --input ./figma-data/ --output ./output/

# React components
python3 $SKILL_DIR/scripts/generate.py --input ./figma-data/ --output ./output/ --framework react

# Next.js + Tailwind (recommended)
python3 $SKILL_DIR/scripts/generate.py --input ./figma-data/ --output ./output/ --framework nextjs --tailwind
```

**Frameworks:** `html` (default), `react`, `nextjs`
**Tailwind:** Add `--tailwind` to generate utility classes + `tailwind.config.ts`
**Speed:** ~50ms, deterministic, same input = same output every time
**Accuracy:** 85-90% visual match without any LLM

### extract.py
```bash
# Full extraction
python3 $SKILL_DIR/scripts/extract.py --url "URL" --token "TOKEN" --output ./figma-data/

# Dry run (parse URL only, no API calls)
python3 $SKILL_DIR/scripts/extract.py --url "URL" --token "TOKEN" --dry-run

# From file key + node ID directly
python3 $SKILL_DIR/scripts/extract.py --file-key "abc123" --node-id "217:3340" --token "TOKEN" --output ./figma-data/

# Quiet mode
python3 $SKILL_DIR/scripts/extract.py --url "URL" --token "TOKEN" --output ./figma-data/ --quiet
```

### validate-loop.py
```bash
# Run validation (iteration 1) — auto-detects screenshot tool (puppeteer > playwright > camoufox)
python3 $SKILL_DIR/scripts/validate-loop.py \
  --url "http://localhost:3088" \
  --screenshots ./figma-data/screenshots/ \
  --output ./figma-data/validation/ \
  --iteration 1

# Custom viewport width (default is 1920px — match your Figma canvas)
python3 $SKILL_DIR/scripts/validate-loop.py \
  --url "http://localhost:3088" \
  --screenshots ./figma-data/screenshots/ \
  --output ./figma-data/validation/ \
  --iteration 1 \
  --viewport-width 1440

# Subsequent iterations
python3 $SKILL_DIR/scripts/validate-loop.py \
  --url "http://localhost:3088" \
  --screenshots ./figma-data/screenshots/ \
  --output ./figma-data/validation/ \
  --iteration 2
```

**Screenshot tool priority:** Puppeteer (most reliable, fixed viewport) → Playwright → Camoufox
**Install one:** `npm i puppeteer` or `pip install playwright && playwright install chromium`
**Fixed viewport:** All methods enforce the same viewport width for consistent diffs.

### serve.py
```bash
# Serve ./output/ on port 3088 (foreground — use & to background)
python3 $SKILL_DIR/scripts/serve.py --dir ./output/ --port 3088 &

# Custom port
python3 $SKILL_DIR/scripts/serve.py --dir ./output/ --port 4000 &
```

### analyze.py
```bash
# Re-analyze (regenerate tokens.json + spec.md from design.json)
python3 $SKILL_DIR/scripts/analyze.py --input figma-data/design.json --output figma-data/

# With summary
python3 $SKILL_DIR/scripts/analyze.py --input figma-data/design.json --output figma-data/ --summary --pretty
```

### diff.py (legacy — use validate-loop.py instead)
```bash
# Direct compare
python3 $SKILL_DIR/scripts/diff.py --page "http://localhost:3088" --reference figma-data/screenshots/ --output figma-data/diff/
```

### font-map.py
```bash
# Look up a font
python3 $SKILL_DIR/scripts/font-map.py "Vastago Grotesk"

# Show all mappings
python3 $SKILL_DIR/scripts/font-map.py --all

# Get Google Fonts URL
python3 $SKILL_DIR/scripts/font-map.py "Vastago Grotesk" --google-fonts-url

# Add custom mapping
python3 $SKILL_DIR/scripts/font-map.py --add "Custom Font" "Inter"
```

---

## Project Detection Logic

```bash
# Detect framework
if [ -f "next.config.js" ] || [ -f "next.config.mjs" ]; then echo "Next.js"
elif [ -f "vite.config.ts" ] || [ -f "vite.config.js" ]; then echo "Vite/React"
elif [ -f "nuxt.config.ts" ]; then echo "Nuxt/Vue"
else echo "Unknown/Plain"; fi

# Detect Tailwind
[ -f "tailwind.config.js" ] || [ -f "tailwind.config.ts" ] && echo "Tailwind detected"

# Existing components
ls src/components/ src/ui/ components/ 2>/dev/null | head -20
```

If existing CSS variables or Tailwind theme config exist, **prefer those over generating new ones** — unless they diverge significantly from Figma values.

---

## Integration with interface-design Skill

This skill handles **extraction and pixel accuracy**. The `interface-design` skill handles **production polish**.

After achieving ≥ 90% match and the user approves:
- Hand off to `interface-design` for responsive breakpoints
- Add hover states, transitions, accessibility
- Optimize for production (lazy loading, etc.)

---

## Success Checklist

- [ ] `extract.py` completed without errors
- [ ] `spec.md` reviewed, font substitutions confirmed
- [ ] All image assets from `figma-data/assets/` (no placeholders)
- [ ] CSS custom properties for all tokens
- [ ] `validate-loop.py` run — score ≥ 90% (or best-effort after 3 iterations)
- [ ] Score card presented to user with per-section breakdown
- [ ] User approved or feedback applied

---

## Troubleshooting

**403 Forbidden from Figma API**
→ Token invalid or file not shared. Check token at figma.com/settings and verify file sharing. Tell user — don't proceed.

**Node not found (404)**
→ The node-id in the URL may use `-` but API needs `:`. `extract.py` handles this automatically.

**Rate limited (429)**
→ `extract.py` auto-retries. For large files, run during off-hours.

**Screenshot blank / validation fails**
→ `validate-loop.py` retries once. If still failing, check camoufox-browser skill is installed. Alternatively pass `--screenshot` with a manual screenshot to `diff.py`.

**Font looks wrong**
→ Run `font-map.py` to confirm substitute. Verify Google Fonts `<link>` is actually in `<head>`.

**Score stuck below 75% after 3 iterations**
→ The design may have structural issues. Present current best to user, explain what's different, ask how they want to proceed.

**Extract finds 0 sections**
→ Warn user: Figma file may not be structured with named frames/sections. Ask them to verify the node-id points to the right frame.
