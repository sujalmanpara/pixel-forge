#!/usr/bin/env python3
"""
PixelForge: diff.py
Direct pixel-diff comparison between a screenshot and Figma reference.
For full automated validation, use validate.py instead.

Usage:
    # Compare a live URL against a single reference
    python3 diff.py --page "http://localhost:3088" --reference ./figma-data/screenshots/section-01-hero.png --output ./figma-data/diff/

    # Compare a live URL against a directory of references
    python3 diff.py --page "http://localhost:3088" --reference ./figma-data/screenshots/ --output ./figma-data/diff/

    # Compare an existing screenshot (no browser needed)
    python3 diff.py --screenshot ./my-screenshot.png --reference ./figma-data/screenshots/section-01-hero.png --output ./figma-data/diff/

Screenshot tool:
    Set SCREENSHOT_TOOL=/path/to/your/script for custom browser automation.
    Or install: npm i puppeteer  (Node.js) | pip install playwright (Python)

Outputs:
    {output}/diff-{name}.png    — diff overlay image (red = different pixels)
    {output}/report.json        — JSON report with match scores
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageChops, ImageFilter, ImageDraw
except ImportError:
    print("Installing Pillow...", file=sys.stderr)
    os.system(f"{sys.executable} -m pip install Pillow -q")
    from PIL import Image, ImageChops, ImageFilter, ImageDraw

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


def _detect_screenshot_method():
    """Detect available screenshot tool."""
    custom = os.environ.get("SCREENSHOT_TOOL")
    if custom and os.path.exists(custom):
        return f"custom:{custom}"
    try:
        r = subprocess.run(["node", "-e", "require('puppeteer')"], capture_output=True, timeout=10)
        if r.returncode == 0:
            return "puppeteer"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        r = subprocess.run([sys.executable, "-c", "import playwright"], capture_output=True, timeout=10)
        if r.returncode == 0:
            return "playwright"
    except subprocess.TimeoutExpired:
        pass
    return "none"


def screenshot_url(url, output_path, full_page=True, viewport_width=1920):
    """Take a screenshot of a URL."""
    method = _detect_screenshot_method()

    if method == "none":
        raise FileNotFoundError(
            "No screenshot tool found. Install one:\n"
            "  npm i puppeteer\n"
            "  pip install playwright && playwright install chromium\n"
            "  export SCREENSHOT_TOOL=/path/to/your/script\n"
            "Or provide --screenshot with an existing screenshot."
        )

    if method == "puppeteer":
        tmp = tempfile.NamedTemporaryFile(suffix=".js", delete=False)
        tmp.write(_PUPPETEER_SCRIPT.encode())
        tmp.close()
        result = subprocess.run(
            ["node", tmp.name, url, output_path, str(viewport_width)],
            capture_output=True, text=True, timeout=60
        )
        os.unlink(tmp.name)
    elif method == "playwright":
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        tmp.write(_PLAYWRIGHT_SCRIPT.encode())
        tmp.close()
        result = subprocess.run(
            [sys.executable, tmp.name, url, output_path, str(viewport_width)],
            capture_output=True, text=True, timeout=60
        )
        os.unlink(tmp.name)
    elif method.startswith("custom:"):
        tool = method.split(":", 1)[1]
        result = subprocess.run(
            [tool, url, output_path, str(viewport_width)],
            capture_output=True, text=True, timeout=120
        )
    else:
        raise RuntimeError(f"Unknown screenshot method: {method}")

    if result.returncode != 0:
        raise RuntimeError(f"Screenshot failed: {result.stderr}")
    if not os.path.exists(output_path):
        raise RuntimeError(f"Screenshot file not created at {output_path}")
    return output_path


# ── Image Comparison ──────────────────────────────────────────────────────────

def compare_images(actual_path, reference_path, output_dir, label="diff"):
    """
    Compare two images pixel-by-pixel.
    Returns: dict with match_percent, diff_image path, hot_regions
    """
    os.makedirs(output_dir, exist_ok=True)

    actual = Image.open(actual_path).convert("RGBA")
    reference = Image.open(reference_path).convert("RGBA")

    actual_w, actual_h = actual.size
    ref_w, ref_h = reference.size

    if (actual_w, actual_h) != (ref_w, ref_h):
        print(f"  Resizing reference from {ref_w}×{ref_h} to {actual_w}×{actual_h}")
        reference = reference.resize((actual_w, actual_h), Image.LANCZOS)

    diff = ImageChops.difference(actual, reference)
    diff_rgb = diff.convert("RGB")
    diff_pixels = list(diff_rgb.getdata())

    total_pixels = actual_w * actual_h
    threshold = 20
    different_pixels = 0
    hot_pixels = []

    for i, (pr, pg, pb) in enumerate(diff_pixels):
        magnitude = (pr + pg + pb) / 3
        if magnitude > threshold:
            different_pixels += 1
            if magnitude > 60:
                x = i % actual_w
                y = i // actual_w
                hot_pixels.append((x, y))

    match_percent = round((1 - different_pixels / total_pixels) * 100, 2)

    # Generate diff overlay (red = different)
    diff_overlay = actual.copy().convert("RGBA")
    overlay_layer = Image.new("RGBA", actual.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_layer)
    for x, y in hot_pixels[:5000]:
        draw.point((x, y), fill=(255, 0, 0, 150))
    diff_overlay = Image.alpha_composite(diff_overlay, overlay_layer)

    diff_path = os.path.join(output_dir, f"{label}.png")
    diff_overlay.convert("RGB").save(diff_path)

    # Detect hot regions (10×10 grid)
    grid_size = 10
    cell_w = max(1, actual_w // grid_size)
    cell_h = max(1, actual_h // grid_size)
    hot_regions = []
    diff_array = list(diff.getdata())

    for row in range(grid_size):
        for col in range(grid_size):
            x_start = col * cell_w
            y_start = row * cell_h
            x_end = min(x_start + cell_w, actual_w)
            y_end = min(y_start + cell_h, actual_h)
            cell_diff = 0
            cell_count = 0
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    i = y * actual_w + x
                    if i < len(diff_array):
                        pr, pg, pb, _ = diff_array[i]
                        cell_diff += (pr + pg + pb) / 3
                        cell_count += 1
            if cell_count > 0:
                cell_avg_diff = cell_diff / cell_count
                if cell_avg_diff > threshold:
                    hot_regions.append({
                        'x': x_start,
                        'y': y_start,
                        'width': x_end - x_start,
                        'height': y_end - y_start,
                        'avgDiff': round(cell_avg_diff, 1),
                        'severity': 'high' if cell_avg_diff > 60 else 'medium'
                    })

    hot_regions.sort(key=lambda r: -r['avgDiff'])

    return {
        'label': label,
        'match_percent': match_percent,
        'different_pixels': different_pixels,
        'total_pixels': total_pixels,
        'actual_size': [actual_w, actual_h],
        'reference_size': [ref_w, ref_h],
        'diff_image': diff_path,
        'hot_regions': hot_regions[:20]
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='PixelForge diff — visual comparison between implementation and Figma reference'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--page', help='URL to screenshot and compare')
    group.add_argument('--screenshot', help='Path to existing screenshot to compare')

    parser.add_argument('--reference', required=True,
                        help='Reference PNG path or directory of PNGs')
    parser.add_argument('--output', required=True, help='Output directory for diff images')
    parser.add_argument('--viewport-width', type=int, default=1920,
                        help='Viewport width for screenshot (default: 1920)')

    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    results = []
    actual_paths = []

    if args.screenshot:
        if not os.path.exists(args.screenshot):
            print(f"Error: screenshot not found: {args.screenshot}", file=sys.stderr)
            sys.exit(1)
        actual_paths.append(args.screenshot)
    else:
        screenshot_path = os.path.join(args.output, 'actual.png')
        try:
            screenshot_url(args.page, screenshot_path, viewport_width=args.viewport_width)
            actual_paths.append(screenshot_path)
        except Exception as e:
            print(f"Error taking screenshot: {e}", file=sys.stderr)
            sys.exit(1)

    reference_paths = []
    if os.path.isdir(args.reference):
        reference_paths = sorted([
            os.path.join(args.reference, f)
            for f in os.listdir(args.reference)
            if f.endswith('.png') and not f.startswith('.')
        ])
    else:
        reference_paths = [args.reference]

    if not reference_paths:
        print("Error: no reference images found", file=sys.stderr)
        sys.exit(1)

    if len(actual_paths) == 1 and len(reference_paths) > 1:
        for i, ref_path in enumerate(reference_paths):
            label = os.path.splitext(os.path.basename(ref_path))[0]
            print(f"Comparing against {os.path.basename(ref_path)}...")
            result = compare_images(actual_paths[0], ref_path, args.output, label=f"diff-{label}")
            results.append(result)
            print(f"  Match: {result['match_percent']}%")
    else:
        for actual_path, ref_path in zip(actual_paths, reference_paths):
            label = os.path.splitext(os.path.basename(ref_path))[0]
            print(f"Comparing {os.path.basename(actual_path)} vs {os.path.basename(ref_path)}...")
            result = compare_images(actual_path, ref_path, args.output, label=f"diff-{label}")
            results.append(result)
            print(f"  Match: {result['match_percent']}%")

    report = {
        'summary': {
            'total_comparisons': len(results),
            'average_match': round(sum(r['match_percent'] for r in results) / len(results), 2) if results else 0,
            'min_match': min(r['match_percent'] for r in results) if results else 0,
            'passed': all(r['match_percent'] >= 90 for r in results)
        },
        'comparisons': results
    }

    report_path = os.path.join(args.output, 'report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    avg = report['summary']['average_match']
    passed = report['summary']['passed']
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"\n--- Diff Report ---")
    print(f"Average match: {avg}% {status}")
    print(f"Report: {report_path}")

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
