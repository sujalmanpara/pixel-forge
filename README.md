<p align="center">
  <h1 align="center">🔥 Pixel Forge</h1>
  <p align="center"><strong>Turn Figma designs into pixel-perfect code. Automatically.</strong></p>
  <p align="center">
    <a href="#quick-start">Quick Start</a> •
    <a href="#how-it-works">How It Works</a> •
    <a href="#battle-tested">Battle Tested</a> •
    <a href="#vs-competitors">vs Competitors</a>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/accuracy-95%25+-brightgreen?style=for-the-badge" />
  <img src="https://img.shields.io/badge/figma_api-REST-blue?style=for-the-badge" />
  <img src="https://img.shields.io/badge/MCP-not_required-orange?style=for-the-badge" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" />
</p>

---

**Pixel Forge** extracts every design token, image, and layout detail from your Figma file — then builds the code, validates it with a visual diff, and auto-refines until it hits **90%+ pixel accuracy**. No MCP server. No browser plugins. Just the Figma REST API and Python.

```
Figma URL → Extract → Build → Validate → Auto-Refine → ✅ 95%+ match
```

## ✨ Features

🎯 **One-Command Extraction** — Colors, fonts, spacing, images, screenshots — all pulled from Figma in a single command

🧠 **Smart Token Analysis** — Generates a complete design spec with CSS custom properties, ready to copy into code

🔄 **Auto-Validation Loop** — Screenshots your build, pixel-diffs against Figma, and auto-refines until 90%+ accuracy

🖼️ **Batch Image Export** — Exports all images at 2x/3x/4x resolution with proper naming

🔤 **Font Intelligence** — 54 premium-to-free font mappings (Vastago Grotesk → Sora, etc.) with Google Fonts URLs

🌐 **Browser Agnostic** — Validation works with Puppeteer, Playwright, or any headless browser

📐 **Fixed Viewport** — Locked 1920px viewport for consistent pixel comparisons

📊 **Section Scoring** — Per-section accuracy breakdown so you know exactly what needs fixing

## 🚀 Quick Start

**1. Install dependencies**
```bash
pip install -r requirements.txt
# For validation, install ONE of:
npm i puppeteer          # recommended
# or: pip install playwright && playwright install chromium
```

**2. Get your Figma token**

Go to [Figma Settings → Access Tokens](https://www.figma.com/settings) → Generate a Personal Access Token.

**3. Extract & build**
```bash
# Extract everything from your Figma design
python3 scripts/extract.py \
  --url "https://www.figma.com/design/YOUR_FILE/Design?node-id=1-2" \
  --token "YOUR_FIGMA_TOKEN" \
  --output ./figma-data/

# Your design data is now in ./figma-data/
# → tokens.json (all design tokens)
# → spec.md (complete design specification)
# → assets/ (all images at 2x)
# → screenshots/ (section-by-section + full page)
```

## 🏗️ How It Works

```
┌──────────────────────────────────────────────────────────┐
│                    PIXEL FORGE PIPELINE                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Phase 0: DISCOVER                                       │
│  ├─ Detect tech stack (React? Next.js? HTML?)            │
│  ├─ Check for existing codebase                          │
│  └─ Confirm scope (full page / sections / components)    │
│                                                          │
│  Phase 1: EXTRACT ──────────────────── extract.py        │
│  ├─ Fetch Figma JSON via REST API                        │
│  ├─ Parse design tokens (colors, fonts, spacing)         │
│  ├─ Export all images at 2x resolution                   │
│  ├─ Screenshot each section + full page                  │
│  └─ Generate spec.md + tokens.json                       │
│                                                          │
│  Phase 2: BUILD                                          │
│  ├─ Generate code using extracted tokens                 │
│  ├─ Map premium fonts → free alternatives                │
│  ├─ Use real exported images (not placeholders)          │
│  └─ CSS custom properties for all tokens                 │
│                                                          │
│  Phase 3: VALIDATE ─────────────────── validate.py       │
│  ├─ Screenshot rendered page (fixed 1920px viewport)     │
│  ├─ Pixel diff against Figma reference                   │
│  ├─ Score: overall + per-section breakdown               │
│  └─ Generate diff overlay images                         │
│                                                          │
│  Phase 4: AUTO-REFINE (max 3 iterations)                 │
│  ├─ If score < 90%: identify worst sections              │
│  ├─ Fix targeted sections (not full rebuild)             │
│  ├─ Re-validate → re-score                               │
│  └─ Repeat until 90%+ or max iterations                  │
│                                                          │
│  Phase 5: PRESENT ──────────────────── checkpoint        │
│  ├─ Show per-section scores (✅ ⚠️ ❌)                    │
│  ├─ Font substitution notes                              │
│  └─ Preview URL                                          │
│                                                          │
│  Phase 6: POLISH                                         │
│  └─ Apply user feedback → re-validate → done             │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## 🎯 Battle Tested

Tested on **3 real Figma designs** with varying complexity:

| Design | Type | Sections | Final Accuracy |
|--------|------|----------|---------------|
| SaaS Landing Page | Marketing, dark theme | 7 sections, 33 images | **95.0%** |
| Hiring Platform | Product page, cards + CTA | 5 sections, gradient bg | **96.9%** |
| Creator Dashboard | Multi-section, mixed content | 3 sections, case studies | **95.0%** |

**Average accuracy: 95.6%** across all test designs.

### What gets extracted

From a single Figma URL, Pixel Forge pulls:

| Data | Example |
|------|---------|
| 🎨 Colors | 71 unique colors with CSS variables |
| 🔤 Fonts | 33 font styles with size, weight, line-height |
| 📏 Spacing | Padding, margins, gaps from auto-layout |
| 🖼️ Images | 33 images at 2x resolution |
| 📸 Screenshots | Per-section + full page reference shots |
| 📄 Spec | Complete design specification in Markdown |

## ⚔️ vs Competitors

| Feature | Pixel Forge | Anima | Locofy | Figma Dev Mode | Builder.io |
|---------|:-----------:|:-----:|:------:|:--------------:|:----------:|
| Accuracy | **95%+** | ~70% | ~75% | Manual | ~80% |
| Auto-validation | ✅ | ❌ | ❌ | ❌ | ❌ |
| Auto-refinement | ✅ | ❌ | ❌ | ❌ | ❌ |
| Quality scoring | ✅ | ❌ | ❌ | ❌ | ❌ |
| Font mapping | ✅ 54 fonts | ❌ | ❌ | ❌ | ❌ |
| Batch image export | ✅ | Partial | ✅ | Manual | ✅ |
| No MCP required | ✅ | ✅ | ✅ | N/A | ✅ |
| No browser plugin | ✅ | ❌ | ❌ | ❌ | ❌ |
| Open source | ✅ MIT | ❌ | ❌ | ❌ | Partial |
| Free | ✅ | Freemium | Paid | Paid | Freemium |

## 📁 Project Structure

```
pixel-forge/
├── scripts/
│   ├── extract.py          # Figma API extraction (tokens, images, screenshots)
│   ├── analyze.py          # Token analysis & spec generation
│   ├── validate.py         # Visual validation loop (screenshot + diff)
│   ├── diff.py             # Pixel diff comparison
│   ├── font-map.py         # Premium → free font mapping (54 fonts)
│   └── serve.py            # Simple preview server
├── references/
│   ├── font-map.json       # Font mapping database
│   ├── api-reference.md    # Figma REST API reference
│   ├── token-reference.md  # Design token format documentation
│   └── quality-gate.md     # Validation scoring methodology
├── docs/
│   └── USAGE.md            # Detailed usage guide
├── requirements.txt
├── LICENSE
└── README.md
```

## 🛠️ All Scripts

### extract.py — Pull everything from Figma
```bash
python3 scripts/extract.py --url "FIGMA_URL" --token "TOKEN" --output ./figma-data/

# Dry run (parse URL, no API calls)
python3 scripts/extract.py --url "FIGMA_URL" --token "TOKEN" --dry-run

# From file key directly
python3 scripts/extract.py --file-key "abc123" --node-id "1:2" --token "TOKEN" --output ./figma-data/
```

### validate.py — Visual validation
```bash
# Run validation (auto-detects Puppeteer → Playwright → fallback)
python3 scripts/validate.py \
  --url "http://localhost:3088" \
  --screenshots ./figma-data/screenshots/ \
  --output ./figma-data/validation/ \
  --iteration 1

# Custom viewport (default: 1920px)
python3 scripts/validate.py --url "http://localhost:3088" ... --viewport-width 1440
```

### font-map.py — Font lookup
```bash
# Look up a premium font
python3 scripts/font-map.py "Vastago Grotesk"
# → Sora (Google Fonts) — https://fonts.google.com/specimen/Sora

# All mappings
python3 scripts/font-map.py --all
```

### serve.py — Preview server
```bash
python3 scripts/serve.py --dir ./output/ --port 3088
```

## 🔤 Font Mapping (54 fonts)

Pixel Forge includes 54 premium-to-free font mappings. When your Figma uses a paid font, it automatically suggests the closest free alternative:

| Premium Font | Free Alternative | Source |
|---|---|---|
| Vastago Grotesk | Sora | Google Fonts |
| Ethnocentric | Russo One | Google Fonts |
| Gilroy | Poppins | Google Fonts |
| Circular | Inter | Google Fonts |
| Avenir | Nunito | Google Fonts |
| Proxima Nova | Montserrat | Google Fonts |
| Futura | Jost | Google Fonts |
| Helvetica Neue | Inter | Google Fonts |
| ... | *+46 more* | Google Fonts |

## 📊 Validation Report

After validation, you get a structured JSON report:

```json
{
  "overall_match": 95.04,
  "status": "READY_FOR_REVIEW",
  "sections": [
    { "name": "section-01-Hero", "match": 94.2, "status": "PASS" },
    { "name": "section-02-Features", "match": 91.8, "status": "PASS" },
    { "name": "section-03-CTA", "match": 88.5, "status": "PASS" }
  ],
  "worst_sections": [],
  "iteration": 2,
  "diff_image": "validation/diff/full-diff.png"
}
```

Section scoring:
- ✅ **PASS** — ≥ 85% match
- ⚠️ **WARN** — ≥ 70% match  
- ❌ **FAIL** — < 70% match

## 🤝 Contributing

Pull requests welcome! Areas that need work:

- [ ] React/Next.js component output (currently HTML + CSS)
- [ ] Tailwind CSS generation
- [ ] Responsive breakpoint detection
- [ ] Structural diff (beyond pixel comparison)
- [ ] More font mappings
- [ ] Animation/interaction detection

## 📝 License

MIT — do whatever you want with it.

---

<p align="center">
  Built by <a href="https://github.com/sujalmanpara">Sujal Manpara</a> 🇮🇳
</p>
