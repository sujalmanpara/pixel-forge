#!/usr/bin/env python3
"""
PixelForge: extract.py
All-in-one Figma data fetcher — pulls design tokens, screenshots, and assets in one shot.

Usage:
    python3 extract.py --url "FIGMA_URL" --token "TOKEN" --output ./figma-data/
    python3 extract.py --file-key "abc123" --node-id "217:3340" --token "TOKEN" --output ./figma-data/

Outputs:
    {output}/design.json              — raw Figma API response (full node tree)
    {output}/tokens.json              — extracted design tokens (colors, fonts, spacing, etc.)
    {output}/spec.md                  — human-readable implementation spec
    {output}/screenshots/             — full-page + per-section screenshots (PNG)
    {output}/assets/                  — exported image fills
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlparse, parse_qs

try:
    import requests
except ImportError:
    print("Installing requests...", file=sys.stderr)
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

FIGMA_API = "https://api.figma.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_MAP_PATH = os.path.join(SCRIPT_DIR, "../references/font-map.json")


# ── URL Parsing ──────────────────────────────────────────────────────────────

def parse_figma_url(url):
    """Parse a Figma URL and return (file_key, node_id or None)."""
    parsed = urlparse(url)
    path_match = re.match(r'^/(design|file|proto)/([^/]+)', parsed.path)
    if not path_match:
        raise ValueError(f"Not a valid Figma URL: {url}")
    file_key = path_match.group(2)
    params = parse_qs(parsed.query)
    node_id = None
    if 'node-id' in params:
        raw_id = params['node-id'][0]
        node_id = raw_id.replace('-', ':')
    return file_key, node_id


# ── API Helpers ───────────────────────────────────────────────────────────────

def api_get(token, path, params=None, retries=3):
    """Make a Figma API GET request with retry/backoff."""
    url = f"{FIGMA_API}{path}"
    headers = {"X-Figma-Token": token}
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  Rate limited. Waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 2 ** attempt
                print(f"  Server error {resp.status_code}. Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


def download_file(url, dest_path, retries=3):
    """Download a URL to a local file."""
    for attempt in range(retries):
        try:
            urllib.request.urlretrieve(url, dest_path)
            return
        except Exception as e:
            if attempt == retries - 1:
                print(f"  Failed to download {url}: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)


# ── Color Utilities ───────────────────────────────────────────────────────────

def rgba_to_hex(color, opacity=1.0):
    """Convert Figma RGBA (0–1 floats) to hex string."""
    if color is None:
        return "#000000"
    r = round(color.get('r', 0) * 255)
    g = round(color.get('g', 0) * 255)
    b = round(color.get('b', 0) * 255)
    a = round(color.get('a', 1.0) * opacity * 255)
    if a >= 255:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}{a:02X}"


def rgba_to_css(color, opacity=1.0):
    """Convert Figma RGBA to CSS rgba() string."""
    if color is None:
        return "transparent"
    r = round(color.get('r', 0) * 255)
    g = round(color.get('g', 0) * 255)
    b = round(color.get('b', 0) * 255)
    a = round(color.get('a', 1.0) * opacity, 3)
    if a >= 1.0:
        return f"rgb({r}, {g}, {b})"
    return f"rgba({r}, {g}, {b}, {a})"


def compute_gradient_angle(handles):
    """Compute CSS gradient angle from Figma handle positions."""
    if not handles or len(handles) < 2:
        return 0
    start = handles[0]
    end = handles[1]
    dx = end['x'] - start['x']
    dy = end['y'] - start['y']
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad) + 90
    return round(angle_deg % 360)


def gradient_to_css(fill):
    """Convert a Figma gradient fill to CSS gradient string."""
    fill_type = fill.get('type', '')
    handles = fill.get('gradientHandlePositions', [])
    stops = fill.get('gradientStops', [])
    stop_strs = []
    for stop in stops:
        color = rgba_to_hex(stop.get('color', {}))
        pct = round(stop.get('position', 0) * 100)
        stop_strs.append(f"{color} {pct}%")
    stops_css = ', '.join(stop_strs)

    if fill_type == 'GRADIENT_LINEAR':
        angle = compute_gradient_angle(handles)
        return f"linear-gradient({angle}deg, {stops_css})"
    elif fill_type == 'GRADIENT_RADIAL':
        return f"radial-gradient(circle, {stops_css})"
    elif fill_type == 'GRADIENT_ANGULAR':
        return f"conic-gradient({stops_css})"
    else:
        angle = compute_gradient_angle(handles)
        return f"linear-gradient({angle}deg, {stops_css})"


# ── Font Map ──────────────────────────────────────────────────────────────────

def load_font_map():
    """Load font substitution map from references/font-map.json."""
    try:
        with open(FONT_MAP_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def map_font(font_family, font_map):
    """Get Google Fonts substitute for a premium font, or return as-is."""
    return font_map.get(font_family, font_family)


# ── Node Tree Walking ─────────────────────────────────────────────────────────

def walk_nodes(node, visitor, depth=0):
    """Walk the node tree recursively, calling visitor(node, depth) on each."""
    visitor(node, depth)
    for child in node.get('children', []):
        walk_nodes(child, visitor, depth + 1)


def collect_image_nodes(root_node):
    """Find all nodes with IMAGE-type fills. Returns list of node IDs."""
    image_node_ids = []

    def visit(node, depth):
        fills = node.get('fills', [])
        for fill in fills:
            if fill.get('type') == 'IMAGE' and fill.get('visible', True):
                node_id = node.get('id')
                if node_id and node_id not in image_node_ids:
                    image_node_ids.append(node_id)

    walk_nodes(root_node, visit)
    return image_node_ids


def collect_top_level_sections(root_node):
    """Get direct children of root node (for section screenshots)."""
    children = root_node.get('children', [])
    return [
        {'id': c.get('id'), 'name': c.get('name', f"section-{i}")}
        for i, c in enumerate(children)
        if c.get('id')
    ]


# ── Token Extraction ──────────────────────────────────────────────────────────

def extract_node_tokens(node, font_map):
    """Extract all design tokens from a single node."""
    tokens = {}
    node_type = node.get('type', '')

    # Dimensions
    bbox = node.get('absoluteBoundingBox')
    if bbox:
        tokens['dimensions'] = {
            'x': bbox.get('x', 0),
            'y': bbox.get('y', 0),
            'width': bbox.get('width', 0),
            'height': bbox.get('height', 0)
        }

    # Opacity
    opacity = node.get('opacity')
    if opacity is not None and opacity != 1.0:
        tokens['opacity'] = opacity

    # Fills (colors, gradients, images)
    fills = node.get('fills', [])
    if fills:
        parsed_fills = []
        for fill in fills:
            if not fill.get('visible', True):
                continue
            fill_type = fill.get('type', '')
            parsed_fill = {'type': fill_type}
            if fill_type == 'SOLID':
                parsed_fill['color'] = rgba_to_hex(fill.get('color', {}), fill.get('opacity', 1.0))
                parsed_fill['css'] = rgba_to_css(fill.get('color', {}), fill.get('opacity', 1.0))
            elif fill_type in ('GRADIENT_LINEAR', 'GRADIENT_RADIAL', 'GRADIENT_ANGULAR', 'GRADIENT_DIAMOND'):
                parsed_fill['css'] = gradient_to_css(fill)
                parsed_fill['stops'] = [
                    {'color': rgba_to_hex(s.get('color', {})), 'position': s.get('position', 0)}
                    for s in fill.get('gradientStops', [])
                ]
            elif fill_type == 'IMAGE':
                parsed_fill['imageRef'] = fill.get('imageRef', '')
                parsed_fill['scaleMode'] = fill.get('scaleMode', 'FILL')
                scale_map = {'FILL': 'cover', 'FIT': 'contain', 'CROP': 'cover', 'TILE': 'repeat'}
                parsed_fill['objectFit'] = scale_map.get(fill.get('scaleMode', 'FILL'), 'cover')
            parsed_fills.append(parsed_fill)
        tokens['fills'] = parsed_fills

    # Strokes (borders)
    strokes = node.get('strokes', [])
    stroke_weight = node.get('strokeWeight')
    if strokes and stroke_weight:
        parsed_strokes = []
        for stroke in strokes:
            if stroke.get('type') == 'SOLID':
                parsed_strokes.append({
                    'color': rgba_to_hex(stroke.get('color', {}), stroke.get('opacity', 1.0)),
                    'css': rgba_to_css(stroke.get('color', {}), stroke.get('opacity', 1.0))
                })
        if parsed_strokes:
            tokens['border'] = {
                'width': stroke_weight,
                'strokes': parsed_strokes,
                'align': node.get('strokeAlign', 'INSIDE'),
                'css': f"{stroke_weight}px solid {parsed_strokes[0]['color']}"
            }

    # Corner radius
    corner_radius = node.get('cornerRadius')
    rect_radii = node.get('rectangleCornerRadii')
    if rect_radii and any(r != 0 for r in rect_radii):
        tokens['borderRadius'] = {
            'values': rect_radii,
            'css': f"{rect_radii[0]}px {rect_radii[1]}px {rect_radii[2]}px {rect_radii[3]}px"
        }
    elif corner_radius is not None and corner_radius != 0:
        tokens['borderRadius'] = {
            'value': corner_radius,
            'css': f"{corner_radius}px"
        }

    # Effects (shadows, blur)
    effects = node.get('effects', [])
    if effects:
        parsed_effects = []
        for effect in effects:
            if not effect.get('visible', True):
                continue
            eff_type = effect.get('type', '')
            parsed_eff = {'type': eff_type}
            if eff_type in ('DROP_SHADOW', 'INNER_SHADOW'):
                color = effect.get('color', {})
                offset = effect.get('offset', {'x': 0, 'y': 0})
                radius = effect.get('radius', 0)
                spread = effect.get('spread', 0)
                color_css = rgba_to_css(color)
                inset = "inset " if eff_type == 'INNER_SHADOW' else ""
                parsed_eff.update({
                    'x': offset.get('x', 0),
                    'y': offset.get('y', 0),
                    'blur': radius,
                    'spread': spread,
                    'color': rgba_to_hex(color),
                    'colorCss': color_css,
                    'css': f"{inset}{offset.get('x',0)}px {offset.get('y',0)}px {radius}px {spread}px {color_css}"
                })
            elif eff_type == 'LAYER_BLUR':
                radius = effect.get('radius', 0)
                parsed_eff.update({'radius': radius, 'css': f"blur({radius}px)"})
            elif eff_type == 'BACKGROUND_BLUR':
                radius = effect.get('radius', 0)
                parsed_eff.update({'radius': radius, 'css': f"blur({radius}px)"})
            parsed_effects.append(parsed_eff)
        tokens['effects'] = parsed_effects

    # Layout (Auto Layout / Flexbox)
    layout_mode = node.get('layoutMode')
    if layout_mode and layout_mode != 'NONE':
        justify_map = {
            'MIN': 'flex-start', 'CENTER': 'center', 'MAX': 'flex-end',
            'SPACE_BETWEEN': 'space-between', 'SPACE_AROUND': 'space-around',
            'SPACE_EVENLY': 'space-evenly'
        }
        align_map = {
            'MIN': 'flex-start', 'CENTER': 'center', 'MAX': 'flex-end', 'BASELINE': 'baseline'
        }
        tokens['layout'] = {
            'mode': layout_mode,
            'flexDirection': 'row' if layout_mode == 'HORIZONTAL' else 'column',
            'justifyContent': justify_map.get(node.get('primaryAxisAlignItems', 'MIN'), 'flex-start'),
            'alignItems': align_map.get(node.get('counterAxisAlignItems', 'MIN'), 'flex-start'),
            'gap': node.get('itemSpacing', 0),
            'padding': {
                'top': node.get('paddingTop', 0),
                'right': node.get('paddingRight', 0),
                'bottom': node.get('paddingBottom', 0),
                'left': node.get('paddingLeft', 0)
            },
            'wrap': node.get('layoutWrap', 'NO_WRAP') == 'WRAP',
            'sizingH': node.get('layoutSizingHorizontal', 'FIXED'),
            'sizingV': node.get('layoutSizingVertical', 'FIXED')
        }

    # Typography
    if node_type == 'TEXT':
        style = node.get('style', {})
        font_family = style.get('fontFamily', '')
        tokens['text'] = {
            'content': node.get('characters', ''),
            'fontFamily': font_family,
            'fontFamilySubstitute': map_font(font_family, font_map),
            'fontSize': style.get('fontSize'),
            'fontWeight': style.get('fontWeight'),
            'lineHeightPx': style.get('lineHeightPx'),
            'letterSpacing': style.get('letterSpacing', 0),
            'textAlign': style.get('textAlignHorizontal', 'LEFT').lower(),
            'italic': style.get('italic', False),
            'textDecoration': style.get('textDecoration', 'NONE'),
            'textCase': style.get('textCase', 'ORIGINAL')
        }

    return tokens


def extract_all_tokens(root_node, font_map):
    """Walk entire node tree and extract tokens per node, plus global summary."""
    all_nodes = []
    colors_seen = set()
    fonts_seen = []
    font_subs = {}
    shadows_seen = []
    radii_seen = set()

    def visit(node, depth):
        node_tokens = extract_node_tokens(node, font_map)
        if node_tokens:
            all_nodes.append({
                'id': node.get('id'),
                'name': node.get('name'),
                'type': node.get('type'),
                'depth': depth,
                'tokens': node_tokens
            })

        # Collect global colors
        for fill in node_tokens.get('fills', []):
            if 'color' in fill:
                colors_seen.add(fill['color'])

        # Collect fonts
        text = node_tokens.get('text')
        if text and text.get('fontFamily'):
            font_entry = {
                'family': text['fontFamily'],
                'substitute': text['fontFamilySubstitute'],
                'size': text.get('fontSize'),
                'weight': text.get('fontWeight'),
                'lineHeight': text.get('lineHeightPx'),
                'letterSpacing': text.get('letterSpacing', 0)
            }
            key = (text['fontFamily'], text.get('fontSize'), text.get('fontWeight'))
            if not any((f['family'], f.get('size'), f.get('weight')) == key for f in fonts_seen):
                fonts_seen.append(font_entry)
            if text['fontFamily'] != text['fontFamilySubstitute']:
                font_subs[text['fontFamily']] = text['fontFamilySubstitute']

        # Collect border radii
        border_radius = node_tokens.get('borderRadius')
        if border_radius:
            val = border_radius.get('value') or str(border_radius.get('values', ''))
            radii_seen.add(str(val))

        # Collect shadows
        for eff in node_tokens.get('effects', []):
            if eff.get('type') in ('DROP_SHADOW', 'INNER_SHADOW') and 'css' in eff:
                if eff['css'] not in [s.get('css') for s in shadows_seen]:
                    shadows_seen.append(eff)

    walk_nodes(root_node, visit)

    sections = []
    for child in root_node.get('children', []):
        bbox = child.get('absoluteBoundingBox', {})
        section = {
            'name': child.get('name', 'Section'),
            'nodeId': child.get('id'),
            'type': child.get('type'),
            'width': bbox.get('width', 0),
            'height': bbox.get('height', 0),
            'childCount': len(child.get('children', []))
        }
        fills = child.get('fills', [])
        for fill in fills:
            if not fill.get('visible', True):
                continue
            if fill.get('type') == 'SOLID':
                section['background'] = rgba_to_hex(fill.get('color', {}), fill.get('opacity', 1.0))
                break
            elif fill.get('type', '').startswith('GRADIENT'):
                section['background'] = gradient_to_css(fill)
                break
        sections.append(section)

    return {
        'nodes': all_nodes,
        'summary': {
            'colors': sorted(colors_seen),
            'fonts': fonts_seen,
            'fontSubstitutions': font_subs,
            'radii': list(radii_seen),
            'shadows': shadows_seen,
            'sections': sections
        }
    }


# ── Spec Generation ───────────────────────────────────────────────────────────

def generate_spec(design_name, tokens_data, output_dir):
    """Generate a human-readable spec.md from extracted tokens."""
    summary = tokens_data.get('summary', {})
    sections = summary.get('sections', [])
    colors = summary.get('colors', [])
    fonts = summary.get('fonts', [])
    font_subs = summary.get('fontSubstitutions', {})
    shadows = summary.get('shadows', [])
    radii = summary.get('radii', [])

    lines = [
        f"# Implementation Spec — {design_name}",
        "",
        "Generated by PixelForge/scripts/extract.py",
        "",
        "---",
        "",
        "## Design Tokens",
        "",
        "### Colors",
    ]

    for color in colors:
        lines.append(f"- `{color}`")

    lines += [
        "",
        "### Typography",
        "",
        "| Font Family | Substitute | Size | Weight | Line Height | Letter Spacing |",
        "|---|---|---|---|---|---|",
    ]

    for font in fonts:
        family = font.get('family', '')
        sub = font.get('substitute', family)
        size = font.get('size', '—')
        weight = font.get('weight', '—')
        lh = font.get('lineHeight', '—')
        ls = font.get('letterSpacing', 0)
        sub_note = f"**{sub}**" if sub != family else sub
        lines.append(f"| {family} | {sub_note} | {size}px | {weight} | {lh}px | {ls} |")

    if font_subs:
        lines += [
            "",
            "### Font Substitutions",
            "",
            "_These fonts require substitution (not on Google Fonts):_",
            "",
        ]
        for original, substitute in font_subs.items():
            lines.append(f"- `{original}` → `{substitute}`")

    if shadows:
        lines += [
            "",
            "### Shadows",
            "",
        ]
        for shadow in shadows:
            lines.append(f"- `{shadow.get('css', '')}`")

    if radii:
        lines += [
            "",
            "### Border Radii",
            "",
        ]
        for r in radii:
            lines.append(f"- `{r}px`")

    lines += [
        "",
        "---",
        "",
        "## Sections",
        "",
    ]

    for i, section in enumerate(sections, 1):
        screenshot_name = f"section-{i:02d}-{section['name'].lower().replace(' ', '-')}.png"
        lines += [
            f"### {i}. {section['name']} ({section['nodeId']})",
            "",
            f"- **Dimensions:** {section['width']}px × {section['height']}px",
            f"- **Type:** {section['type']}",
            f"- **Children:** {section['childCount']} direct children",
        ]
        if 'background' in section:
            lines.append(f"- **Background:** `{section['background']}`")
        lines += [
            f"- **Screenshot:** `screenshots/{screenshot_name}`",
            "",
        ]

    lines += [
        "---",
        "",
        "## Implementation Notes",
        "",
        "- Use CSS custom properties for all token values",
        "- Font substitutions are pre-applied — use the Substitute column",
        "- Image assets are in `assets/` directory",
        "- Section screenshots are in `screenshots/` directory",
        "- Run `validate.py` after implementation to validate accuracy",
        "",
    ]

    spec_content = "\n".join(lines)
    spec_path = os.path.join(output_dir, 'spec.md')
    with open(spec_path, 'w') as f:
        f.write(spec_content)
    return spec_path


# ── Main Extraction Logic ─────────────────────────────────────────────────────

def run_extraction(file_key, node_id, token, output_dir, verbose=True):
    """Main extraction: fetch everything, save to output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'screenshots'), exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'assets'), exist_ok=True)

    font_map = load_font_map()

    # 1. Fetch node tree
    if verbose:
        print(f"[1/6] Fetching node tree for {node_id} from file {file_key}...")

    if node_id:
        api_node_id = node_id.replace('-', ':')
        data = api_get(token, f"/v1/files/{file_key}/nodes", {
            "ids": api_node_id,
            "depth": 100
        })
        nodes_data = data.get('nodes', {})
        root_key = api_node_id
        if root_key not in nodes_data:
            root_key = list(nodes_data.keys())[0] if nodes_data else None
        if not root_key:
            raise ValueError(f"Node {node_id} not found in response")
        root_node = nodes_data[root_key]['document']
        design_name = data.get('name', 'Figma Design')
    else:
        data = api_get(token, f"/v1/files/{file_key}", {"depth": 5})
        design_name = data.get('name', 'Figma Design')
        document = data.get('document', {})
        pages = document.get('children', [])
        root_node = pages[0] if pages else document

    # Save raw design.json
    design_path = os.path.join(output_dir, 'design.json')
    with open(design_path, 'w') as f:
        json.dump({'name': design_name, 'fileKey': file_key, 'nodeId': node_id, 'root': root_node}, f, indent=2)
    if verbose:
        print(f"  ✓ Saved design.json ({os.path.getsize(design_path):,} bytes)")

    # 2. Fetch full-page screenshot
    if verbose:
        print(f"[2/6] Fetching full screenshot...")
    try:
        img_resp = api_get(token, f"/v1/images/{file_key}", {
            "ids": node_id or root_node.get('id', ''),
            "format": "png",
            "scale": "2"
        })
        images = img_resp.get('images', {})
        full_img_url = list(images.values())[0] if images else None
        if full_img_url:
            full_img_path = os.path.join(output_dir, 'screenshots', 'full.png')
            download_file(full_img_url, full_img_path)
            if verbose:
                print(f"  ✓ Saved screenshots/full.png")
    except Exception as e:
        print(f"  ⚠ Full screenshot failed: {e}", file=sys.stderr)

    # 3. Find top-level sections and image nodes
    if verbose:
        print(f"[3/6] Analyzing node tree...")

    top_sections = collect_top_level_sections(root_node)
    image_node_ids = collect_image_nodes(root_node)

    if verbose:
        print(f"  ✓ Found {len(top_sections)} sections")
        print(f"  ✓ Found {len(image_node_ids)} image nodes")

    # 4. Screenshot each section
    if top_sections:
        if verbose:
            print(f"[4/6] Screenshotting {len(top_sections)} sections...")
        section_ids = [s['id'] for s in top_sections]

        for batch_start in range(0, len(section_ids), 50):
            batch = section_ids[batch_start:batch_start + 50]
            try:
                img_resp = api_get(token, f"/v1/images/{file_key}", {
                    "ids": ",".join(batch),
                    "format": "png",
                    "scale": "2"
                })
                section_images = img_resp.get('images', {})
                for i, section in enumerate(top_sections[batch_start:batch_start + 50], batch_start + 1):
                    img_url = section_images.get(section['id'])
                    if img_url:
                        safe_name = re.sub(r'[^\w\-]', '-', section['name'])
                        filename = f"section-{i:02d}-{safe_name}.png"
                        dest = os.path.join(output_dir, 'screenshots', filename)
                        download_file(img_url, dest)
                        if verbose:
                            print(f"  ✓ screenshots/{filename}")
                        section['screenshot'] = filename
            except Exception as e:
                print(f"  ⚠ Section screenshot batch failed: {e}", file=sys.stderr)
    else:
        if verbose:
            print(f"[4/6] No top-level sections found, skipping section screenshots")

    # 5. Export image assets
    if image_node_ids:
        if verbose:
            print(f"[5/6] Exporting {len(image_node_ids)} image assets...")
        for batch_start in range(0, len(image_node_ids), 50):
            batch = image_node_ids[batch_start:batch_start + 50]
            try:
                img_resp = api_get(token, f"/v1/images/{file_key}", {
                    "ids": ",".join(batch),
                    "format": "png",
                    "scale": "2"
                })
                asset_images = img_resp.get('images', {})
                for node_id_asset, img_url in asset_images.items():
                    if img_url:
                        safe_id = node_id_asset.replace(':', '-')
                        dest = os.path.join(output_dir, 'assets', f"{safe_id}.png")
                        download_file(img_url, dest)
                        if verbose:
                            print(f"  ✓ assets/{safe_id}.png")
            except Exception as e:
                print(f"  ⚠ Asset export batch failed: {e}", file=sys.stderr)
    else:
        if verbose:
            print(f"[5/6] No image fill nodes found")

    # Also fetch image fill catalog
    try:
        fill_catalog = api_get(token, f"/v1/files/{file_key}/images")
        fills_catalog_path = os.path.join(output_dir, 'image-fills-catalog.json')
        with open(fills_catalog_path, 'w') as f:
            json.dump(fill_catalog, f, indent=2)
    except Exception:
        pass  # Not critical

    # 6. Extract tokens and generate spec
    if verbose:
        print(f"[6/6] Extracting design tokens...")

    tokens_data = extract_all_tokens(root_node, font_map)

    tokens_path = os.path.join(output_dir, 'tokens.json')
    with open(tokens_path, 'w') as f:
        json.dump(tokens_data, f, indent=2)
    if verbose:
        print(f"  ✓ Saved tokens.json ({os.path.getsize(tokens_path):,} bytes)")

    spec_path = generate_spec(design_name, tokens_data, output_dir)
    if verbose:
        print(f"  ✓ Saved spec.md")

    if verbose:
        print(f"\n✅ Extraction complete → {output_dir}")
        print(f"   design.json    — raw node tree")
        print(f"   tokens.json    — extracted design tokens")
        print(f"   spec.md        — implementation spec")
        print(f"   screenshots/   — {len(top_sections) + 1} screenshots")
        print(f"   assets/        — {len(image_node_ids)} image exports")

    return {
        'design_path': design_path,
        'tokens_path': tokens_path,
        'spec_path': spec_path,
        'sections': top_sections,
        'image_count': len(image_node_ids)
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='PixelForge extractor — fetches everything from a Figma URL in one command'
    )
    parser.add_argument('--url', help='Figma design URL')
    parser.add_argument('--file-key', help='Figma file key (alternative to --url)')
    parser.add_argument('--node-id', help='Node ID in format 217:3340 (optional)')
    parser.add_argument('--token', required=True, help='Figma personal access token')
    parser.add_argument('--output', default='./figma-data', help='Output directory (default: ./figma-data)')
    parser.add_argument('--dry-run', action='store_true', help='Parse URL and show what would be fetched, then exit')
    parser.add_argument('--quiet', action='store_true', help='Suppress progress output')

    args = parser.parse_args()

    if args.url:
        file_key, node_id = parse_figma_url(args.url)
        print(f"Parsed URL:")
        print(f"  File key: {file_key}")
        print(f"  Node ID:  {node_id or '(none — fetching whole file)'}")
    elif args.file_key:
        file_key = args.file_key
        node_id = args.node_id
    else:
        parser.error("Either --url or --file-key is required")

    if args.dry_run:
        print("\n[DRY RUN] Would fetch:")
        print(f"  GET /v1/files/{file_key}/nodes?ids={node_id}&depth=100")
        print(f"  GET /v1/images/{file_key}?ids={node_id}&format=png&scale=2")
        print(f"  Output: {args.output}")
        return

    run_extraction(
        file_key=file_key,
        node_id=node_id,
        token=args.token,
        output_dir=args.output,
        verbose=not args.quiet
    )


if __name__ == '__main__':
    main()
