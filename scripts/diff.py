#!/usr/bin/env python3
"""
figma-perfect: diff.py
Visual comparison between implementation and Figma reference.

Usage:
    python3 diff.py --page "http://localhost:3088" --reference ./figma-data/screenshots/section-01-hero.png --output ./figma-data/diff/
    python3 diff.py --page "http://localhost:3088" --reference ./figma-data/screenshots/ --output ./figma-data/diff/
    python3 diff.py --screenshot ./my-screenshot.png --reference ./figma-data/screenshots/section-01-hero.png --output ./figma-data/diff/

Outputs:
    {output}/diff-{name}.png    — diff overlay image (red = different pixels)
    {output}/report.json        — JSON report with match scores and hot regions
    Prints match% to stdout
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageChops, ImageFilter, ImageDraw
    import PIL
except ImportError:
    print("Installing Pillow...", file=sys.stderr)
    os.system(f"{sys.executable} -m pip install Pillow -q")
    from PIL import Image, ImageChops, ImageFilter, ImageDraw
    import PIL

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CAMOUFOX_BROWSE = os.path.expanduser(
    "~/.openclaw/workspace/skills/camoufox-browser/scripts/browse.py"
)


# ── Screenshot ────────────────────────────────────────────────────────────────

def screenshot_url(url, output_path, full_page=True):
    """Take a screenshot of a URL using camoufox browse.py."""
    if not os.path.exists(CAMOUFOX_BROWSE):
        raise FileNotFoundError(
            f"Camoufox browse.py not found at {CAMOUFOX_BROWSE}. "
            "Install the camoufox-browser skill or provide --screenshot directly."
        )

    cmd = [
        sys.executable, CAMOUFOX_BROWSE,
        "screenshot", url,
        "-o", output_path,
    ]
    if full_page:
        cmd.append("--full-page")

    print(f"  Taking screenshot of {url}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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

    # Load images
    actual = Image.open(actual_path).convert("RGBA")
    reference = Image.open(reference_path).convert("RGBA")

    # Resize reference to match actual dimensions (or vice versa)
    actual_w, actual_h = actual.size
    ref_w, ref_h = reference.size

    if (actual_w, actual_h) != (ref_w, ref_h):
        print(f"  Resizing reference from {ref_w}×{ref_h} to {actual_w}×{actual_h}")
        reference = reference.resize((actual_w, actual_h), Image.LANCZOS)

    # Pixel diff
    diff = ImageChops.difference(actual, reference)

    # Create diff overlay (red = different pixels)
    diff_rgb = diff.convert("RGB")
    diff_pixels = list(diff_rgb.getdata())

    total_pixels = actual_w * actual_h
    threshold = 20  # pixel value difference threshold (0–255)
    different_pixels = 0
    hot_pixels = []  # (x, y) of significantly different pixels

    for i, (pr, pg, pb) in enumerate(diff_pixels):
        magnitude = (pr + pg + pb) / 3
        if magnitude > threshold:
            different_pixels += 1
            if magnitude > 60:  # very different
                x = i % actual_w
                y = i // actual_w
                hot_pixels.append((x, y))

    match_percent = round((1 - different_pixels / total_pixels) * 100, 2)

    # Generate diff overlay image
    diff_overlay = actual.copy().convert("RGBA")
    overlay_layer = Image.new("RGBA", actual.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_layer)

    # Color different regions red
    if hot_pixels:
        # Cluster hot pixels into regions (simplified: bounding box approach)
        for x, y in hot_pixels[:5000]:  # limit for performance
            draw.point((x, y), fill=(255, 0, 0, 150))

    diff_overlay = Image.alpha_composite(diff_overlay, overlay_layer)

    # Add match score text overlay
    try:
        from PIL import ImageFont
        # Use default font
        pass
    except Exception:
        pass

    diff_path = os.path.join(output_dir, f"{label}.png")
    diff_overlay.convert("RGB").save(diff_path)

    # Detect hot regions (grid-based)
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

    # Sort by severity
    hot_regions.sort(key=lambda r: -r['avgDiff'])

    return {
        'label': label,
        'match_percent': match_percent,
        'different_pixels': different_pixels,
        'total_pixels': total_pixels,
        'actual_size': [actual_w, actual_h],
        'reference_size': [ref_w, ref_h],
        'diff_image': diff_path,
        'hot_regions': hot_regions[:20]  # top 20 regions
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Visual diff between implementation and Figma reference screenshots'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--page', help='URL to screenshot and compare')
    group.add_argument('--screenshot', help='Path to existing screenshot to compare')

    parser.add_argument('--reference', required=True,
                        help='Path to reference PNG (or directory of PNGs for multiple sections)')
    parser.add_argument('--output', required=True, help='Output directory for diff images')
    parser.add_argument('--no-full-page', action='store_true',
                        help='Do not use full-page screenshot mode')
    parser.add_argument('--threshold', type=int, default=20,
                        help='Pixel difference threshold 0-255 (default: 20)')

    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    results = []

    # Determine actual screenshot(s)
    actual_paths = []

    if args.screenshot:
        if not os.path.exists(args.screenshot):
            print(f"Error: screenshot not found: {args.screenshot}", file=sys.stderr)
            sys.exit(1)
        actual_paths.append(args.screenshot)
    else:
        # Take screenshot of the URL
        screenshot_path = os.path.join(args.output, 'actual.png')
        try:
            screenshot_url(args.page, screenshot_path, full_page=not args.no_full_page)
            actual_paths.append(screenshot_path)
        except Exception as e:
            print(f"Error taking screenshot: {e}", file=sys.stderr)
            sys.exit(1)

    # Determine reference(s)
    reference_paths = []
    if os.path.isdir(args.reference):
        png_files = sorted([
            os.path.join(args.reference, f)
            for f in os.listdir(args.reference)
            if f.endswith('.png') and not f.startswith('.')
        ])
        reference_paths = png_files
    else:
        reference_paths = [args.reference]

    if not reference_paths:
        print("Error: no reference images found", file=sys.stderr)
        sys.exit(1)

    # Compare
    if len(actual_paths) == 1 and len(reference_paths) > 1:
        # Compare single actual against each reference section
        for i, ref_path in enumerate(reference_paths):
            label = os.path.splitext(os.path.basename(ref_path))[0]
            print(f"Comparing against {os.path.basename(ref_path)}...")
            result = compare_images(actual_paths[0], ref_path, args.output, label=f"diff-{label}")
            results.append(result)
            print(f"  Match: {result['match_percent']}% ({result['different_pixels']:,} / {result['total_pixels']:,} pixels differ)")
    else:
        # 1:1 comparison
        for actual_path, ref_path in zip(actual_paths, reference_paths):
            label = os.path.splitext(os.path.basename(ref_path))[0]
            print(f"Comparing {os.path.basename(actual_path)} vs {os.path.basename(ref_path)}...")
            result = compare_images(actual_path, ref_path, args.output, label=f"diff-{label}")
            results.append(result)
            print(f"  Match: {result['match_percent']}% ({result['different_pixels']:,} / {result['total_pixels']:,} pixels differ)")

    # Save report
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

    # Print summary
    print(f"\n--- Diff Report ---")
    avg = report['summary']['average_match']
    passed = report['summary']['passed']
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"Average match: {avg}% {status}")
    print(f"Report: {report_path}")

    if not passed:
        print("\nRegions needing attention:")
        for result in results:
            if result['match_percent'] < 90:
                print(f"\n  {result['label']}: {result['match_percent']}% match")
                for region in result.get('hot_regions', [])[:5]:
                    print(f"    - Region at ({region['x']}, {region['y']}) — avg diff: {region['avgDiff']} [{region['severity']}]")

    # Print JSON summary for machine consumption
    print(f"\n{json.dumps({'match_percent': avg, 'passed': passed, 'report': report_path})}")

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
