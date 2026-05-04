#!/usr/bin/env python3
"""
PixelForge: validate.py
Automated visual validation — screenshots your rendered page and pixel-diffs it
against Figma reference screenshots. Outputs a structured JSON report with per-section scores.

Usage:
    python3 validate.py \
        --url "http://localhost:3088" \
        --screenshots ./figma-data/screenshots/ \
        --output ./figma-data/validation/ \
        --iteration 1

    # Custom viewport (default: 1920px — match your Figma canvas width)
    python3 validate.py \
        --url "http://localhost:3088" \
        --screenshots ./figma-data/screenshots/ \
        --output ./figma-data/validation/ \
        --iteration 2 \
        --viewport-width 1440

Screenshot tool priority: Puppeteer → Playwright → any tool at SCREENSHOT_TOOL env var
Install one:
    npm i puppeteer                                    # Node.js
    pip install playwright && playwright install chromium  # Python

Dependencies: Pillow (PIL), subprocess (stdlib)
"""

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

# ─── Auto-install Pillow if missing ──────────────────────────────────────────
try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    print("[validate] Installing Pillow…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "-q"])
    from PIL import Image, ImageChops, ImageDraw

# ─── Constants ────────────────────────────────────────────────────────────────
THRESHOLD_PASS = 85.0       # section >= 85 → PASS
THRESHOLD_WARN = 70.0       # section >= 70 → WARN  (else FAIL)
THRESHOLD_READY = 90.0      # overall >= 90 → READY_FOR_REVIEW
THRESHOLD_NEEDS = 75.0      # overall >= 75 → NEEDS_REFINEMENT  (else MAJOR_ISSUES)
MAX_ITERATIONS = 3
DEFAULT_VIEWPORT_WIDTH = 1920
DEFAULT_VIEWPORT_HEIGHT = 1080

# ─── Inline browser scripts ───────────────────────────────────────────────────

_PUPPETEER_SCRIPT = '''
const puppeteer = require('puppeteer');
(async () => {
  const url = process.argv[2];
  const output = process.argv[3];
  const width = parseInt(process.argv[4] || '1920');
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: width, height: 1080 });
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: output, fullPage: true });
  await browser.close();
  process.exit(0);
})();
'''

_PLAYWRIGHT_SCRIPT = '''
import sys, asyncio
from playwright.async_api import async_playwright

async def main():
    url, output, width = sys.argv[1], sys.argv[2], int(sys.argv[3] if len(sys.argv) > 3 else 1920)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": 1080})
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=output, full_page=True)
        await browser.close()

asyncio.run(main())
'''


# ─── Screenshot detection ─────────────────────────────────────────────────────

def _detect_screenshot_method() -> str:
    """
    Detect which screenshot tool is available.
    Priority: SCREENSHOT_TOOL env var → puppeteer → playwright → none

    Set SCREENSHOT_TOOL=/path/to/your/script to use any custom browser automation tool.
    The tool is called as: <tool> <url> <output_path> [<viewport_width>]
    """
    # Allow custom override via env var
    custom_tool = os.environ.get("SCREENSHOT_TOOL")
    if custom_tool and Path(custom_tool).exists():
        return f"custom:{custom_tool}"

    # Check Puppeteer
    try:
        r = subprocess.run(["node", "-e", "require('puppeteer')"], capture_output=True, timeout=10)
        if r.returncode == 0:
            return "puppeteer"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check Playwright
    try:
        r = subprocess.run([sys.executable, "-c", "import playwright"], capture_output=True, timeout=10)
        if r.returncode == 0:
            return "playwright"
    except subprocess.TimeoutExpired:
        pass

    return "none"


def take_screenshot(url: str, output_path: str, viewport_width: int = DEFAULT_VIEWPORT_WIDTH, retries: int = 1) -> bool:
    """
    Screenshot a URL with a FIXED viewport width.
    Tries: Puppeteer → Playwright → custom SCREENSHOT_TOOL env var.
    Fixed viewport ensures consistent screenshots for pixel diffing.
    """
    method = _detect_screenshot_method()
    print(f"[validate] Screenshot method: {method} (viewport: {viewport_width}px)")

    if method == "none":
        print("[validate] ERROR: No screenshot tool found!")
        print("[validate] Install one:")
        print("[validate]   npm i puppeteer")
        print("[validate]   pip install playwright && playwright install chromium")
        print("[validate]   export SCREENSHOT_TOOL=/path/to/your/screenshot/script")
        return False

    for attempt in range(retries + 1):
        success = False
        try:
            if method == "puppeteer":
                tmp_script = Path(output_path).parent / "_screenshot.js"
                tmp_script.write_text(_PUPPETEER_SCRIPT)
                result = subprocess.run(
                    ["node", str(tmp_script), url, output_path, str(viewport_width)],
                    capture_output=True, text=True, timeout=60
                )
                tmp_script.unlink(missing_ok=True)
                success = result.returncode == 0 and Path(output_path).exists()

            elif method == "playwright":
                tmp_script = Path(output_path).parent / "_screenshot.py"
                tmp_script.write_text(_PLAYWRIGHT_SCRIPT)
                result = subprocess.run(
                    [sys.executable, str(tmp_script), url, output_path, str(viewport_width)],
                    capture_output=True, text=True, timeout=60
                )
                tmp_script.unlink(missing_ok=True)
                success = result.returncode == 0 and Path(output_path).exists()

            elif method.startswith("custom:"):
                tool_path = method.split(":", 1)[1]
                result = subprocess.run(
                    [tool_path, url, output_path, str(viewport_width)],
                    capture_output=True, text=True, timeout=120
                )
                success = result.returncode == 0 and Path(output_path).exists()

            if success:
                return True

        except subprocess.TimeoutExpired:
            print(f"[validate] Screenshot timed out (attempt {attempt + 1})")
        except Exception as e:
            print(f"[validate] Screenshot error: {e}")

        if attempt < retries:
            print(f"[validate] Retrying ({attempt + 1}/{retries})…")

    return False


# ─── Image diff utilities ─────────────────────────────────────────────────────

def resize_to_match(img_a: Image.Image, img_b: Image.Image) -> tuple:
    """Resize img_b to match img_a dimensions if they differ."""
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.LANCZOS)
    return img_a, img_b


def pixel_match_percent(img_a: Image.Image, img_b: Image.Image) -> tuple:
    """
    Returns (match_percent, diff_image).
    match_percent is 0–100 (higher = more similar).
    diff_image highlights differing pixels in red.
    """
    img_a = img_a.convert("RGB")
    img_b = img_b.convert("RGB")
    img_a, img_b = resize_to_match(img_a, img_b)

    diff = ImageChops.difference(img_a, img_b)
    diff_data = list(diff.getdata())

    total_pixels = len(diff_data)
    if total_pixels == 0:
        return 100.0, diff

    tolerance = 10  # tolerance for anti-aliasing
    different = sum(
        1 for r, g, b in diff_data
        if r > tolerance or g > tolerance or b > tolerance
    )

    match_pct = round((1.0 - different / total_pixels) * 100, 2)

    # Build highlighted diff image (red = different pixels)
    diff_vis = img_a.copy().convert("RGBA")
    draw = ImageDraw.Draw(diff_vis)
    w, h = diff_vis.size
    for idx, (r, g, b) in enumerate(diff_data):
        if r > tolerance or g > tolerance or b > tolerance:
            x = idx % w
            y = idx // w
            draw.point((x, y), fill=(255, 0, 0, 200))

    return match_pct, diff_vis.convert("RGB")


def crop_strip(img: Image.Image, y_start: int, y_end: int) -> Image.Image:
    """Crop a horizontal strip from an image."""
    return img.crop((0, y_start, img.width, y_end))


# ─── Section scoring ──────────────────────────────────────────────────────────

def score_sections(
    page_img: Image.Image,
    ref_screenshots: list,
    output_dir: Path,
) -> list:
    """
    Divide the page screenshot into N strips matching the N reference screenshots.
    Uses PROPORTIONAL heights based on each reference's actual height.
    """
    sections = []
    n = len(ref_screenshots)
    if n == 0:
        return sections

    # Calculate proportional strip heights
    ref_heights = []
    for ref_path in ref_screenshots:
        try:
            with Image.open(ref_path) as rimg:
                ref_heights.append(rimg.height)
        except Exception:
            ref_heights.append(100)

    total_ref_height = sum(ref_heights)
    page_h = page_img.height

    diff_dir = output_dir / "diff"
    diff_dir.mkdir(parents=True, exist_ok=True)

    cumulative_y = 0
    for i, ref_path in enumerate(ref_screenshots):
        section_name = Path(ref_path).stem
        proportion = ref_heights[i] / total_ref_height if total_ref_height > 0 else 1.0 / n
        strip_h = int(page_h * proportion)
        y_start = cumulative_y
        y_end = cumulative_y + strip_h if i < n - 1 else page_h
        cumulative_y = y_end

        try:
            ref_img = Image.open(ref_path).convert("RGB")
        except Exception as e:
            print(f"[validate] Could not open {ref_path}: {e}")
            sections.append({
                "name": section_name,
                "match": 0.0,
                "status": "ERROR",
                "priority": "HIGH",
                "error": str(e),
            })
            continue

        page_strip = crop_strip(page_img, y_start, y_end)
        match_pct, diff_img = pixel_match_percent(page_strip, ref_img)

        diff_path = diff_dir / f"{section_name}-diff.png"
        diff_img.save(str(diff_path))

        if match_pct >= THRESHOLD_PASS:
            status = "PASS"
            priority = None
        elif match_pct >= THRESHOLD_WARN:
            status = "WARN"
            priority = "MEDIUM"
        else:
            status = "FAIL"
            priority = "HIGH"

        entry = {
            "name": section_name,
            "match": match_pct,
            "status": status,
            "diff_image": str(diff_path.relative_to(output_dir.parent) if output_dir.parent.exists() else diff_path),
        }
        if priority:
            entry["priority"] = priority

        sections.append(entry)

    return sections


def overall_status(match_pct: float, iteration: int) -> str:
    if iteration >= MAX_ITERATIONS:
        return "MAX_ITERATIONS_REACHED"
    if match_pct >= THRESHOLD_READY:
        return "READY_FOR_REVIEW"
    if match_pct >= THRESHOLD_NEEDS:
        return "NEEDS_REFINEMENT"
    return "MAJOR_ISSUES"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Validate rendered page against Figma reference screenshots."
    )
    parser.add_argument("--url", required=True, help="URL of the rendered page (e.g. http://localhost:3088)")
    parser.add_argument("--screenshots", required=True, help="Directory containing Figma reference screenshots")
    parser.add_argument("--output", required=True, help="Directory to write validation results")
    parser.add_argument("--iteration", type=int, default=1, help="Current refinement iteration (1–3)")
    parser.add_argument("--threshold", type=float, default=THRESHOLD_READY, help="Pass threshold (default 90)")
    parser.add_argument("--viewport-width", type=int, default=DEFAULT_VIEWPORT_WIDTH,
                        help="Fixed viewport width for screenshot (default 1920)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    diff_dir = output_dir / "diff"
    diff_dir.mkdir(parents=True, exist_ok=True)

    screenshots_dir = Path(args.screenshots)
    if not screenshots_dir.exists():
        print(f"[validate] ERROR: Screenshots directory not found: {screenshots_dir}")
        sys.exit(1)

    all_refs = sorted(screenshots_dir.glob("*.png"))
    full_ref = next((p for p in all_refs if p.stem == "full"), None)
    section_refs = [p for p in all_refs if p.stem != "full" and p.stem.startswith("section-")]

    if not all_refs:
        print("[validate] ERROR: No reference screenshots found. Did extract.py run?")
        sys.exit(1)

    print(f"[validate] Taking screenshot of {args.url} (viewport: {args.viewport_width}px)…")
    page_shot_path = str(output_dir / "page-current.png")
    ok = take_screenshot(args.url, page_shot_path, viewport_width=args.viewport_width)

    if not ok:
        print("[validate] ERROR: Failed to screenshot page after retries.")
        report = {
            "error": "screenshot_failed",
            "url": args.url,
            "iteration": args.iteration,
        }
        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2))
        sys.exit(2)

    page_img = Image.open(page_shot_path).convert("RGB")

    # ── Full-page diff ──
    full_match = None
    full_diff_path = None
    if full_ref:
        print(f"[validate] Diffing full page against {full_ref.name} …")
        ref_img = Image.open(full_ref).convert("RGB")
        full_match, full_diff_img = pixel_match_percent(page_img, ref_img)
        full_diff_path = str(diff_dir / "full-diff.png")
        full_diff_img.save(full_diff_path)
        print(f"[validate] Full-page match: {full_match}%")
    else:
        print("[validate] No full.png reference — using section averages only.")

    # ── Per-section diff ──
    print(f"[validate] Scoring {len(section_refs)} sections …")
    sections = score_sections(page_img, section_refs, output_dir)

    # ── Overall score ──
    if sections:
        avg_section = round(sum(s["match"] for s in sections) / len(sections), 2)
    else:
        avg_section = None

    if full_match is not None and avg_section is not None:
        overall = round(full_match * 0.6 + avg_section * 0.4, 2)
    elif full_match is not None:
        overall = round(full_match, 2)
    elif avg_section is not None:
        overall = round(avg_section, 2)
    else:
        overall = 0.0

    status = overall_status(overall, args.iteration)

    failing = sorted([s for s in sections if s["status"] == "FAIL"], key=lambda x: x["match"])
    warning = sorted([s for s in sections if s["status"] == "WARN"], key=lambda x: x["match"])
    worst = [s["name"] for s in failing[:3]] + [s["name"] for s in warning[:2]]

    report = {
        "overall_match": overall,
        "status": status,
        "sections": sections,
        "worst_sections": worst,
        "iteration": args.iteration,
        "max_iterations": MAX_ITERATIONS,
        "threshold": args.threshold,
        "diff_image": full_diff_path or None,
        "page_screenshot": page_shot_path,
    }

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n[validate] ─────────────────────────────────────")
    print(f"[validate] Overall match : {overall}%")
    print(f"[validate] Status        : {status}")
    print(f"[validate] Sections      : {len(sections)} scored")
    if worst:
        print(f"[validate] Worst sections: {', '.join(worst)}")
    print(f"[validate] Report        → {report_path}")
    print(f"[validate] ─────────────────────────────────────\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
