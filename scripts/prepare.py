#!/usr/bin/env python3
"""
prepare.py — Component-level data package organizer for Figma designs.

Takes raw extract.py output and reorganizes it into per-component data packages
that an AI can use to build each component in one shot.

Usage:
    python3 prepare.py --input ./figma-data/ --output ./prepared/
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ─── Google Fonts lookup (common fonts) ───────────────────────────────────────

GOOGLE_FONTS = {
    "Inter", "Roboto", "Open Sans", "Lato", "Montserrat", "Poppins",
    "Raleway", "Nunito", "Ubuntu", "Playfair Display", "Merriweather",
    "Source Sans Pro", "Source Code Pro", "Fira Code", "JetBrains Mono",
    "DM Sans", "DM Serif Display", "Space Grotesk", "Space Mono",
    "Work Sans", "Outfit", "Manrope", "Sora", "Lexend", "Geist",
    "Plus Jakarta Sans", "IBM Plex Sans", "IBM Plex Mono",
    "Noto Sans", "Noto Serif", "PT Sans", "PT Serif", "Cabin",
    "Quicksand", "Barlow", "Mulish", "Rubik", "Karla", "Josefin Sans",
    "Comfortaa", "Arimo", "Teko", "Abel", "Bebas Neue", "Oswald",
    "Libre Franklin", "Crimson Text", "Bitter", "Overpass",
    "Red Hat Display", "Archivo", "Catamaran", "Chakra Petch",
    "Exo 2", "Figtree", "General Sans", "Clash Display",
    "Satoshi", "Cabinet Grotesk", "Switzer", "Synonym",
    "Bricolage Grotesque", "Instrument Sans", "Onest",
}

# Non-Google system fonts that need substitutes
FONT_SUBSTITUTIONS = {
    "SF Pro": "Inter",
    "SF Pro Display": "Inter",
    "SF Pro Text": "Inter",
    "SF Mono": "JetBrains Mono",
    "Helvetica": "Inter",
    "Helvetica Neue": "Inter",
    "Arial": "Inter",
    "Segoe UI": "Inter",
    "System UI": "Inter",
    ".SF NS": "Inter",
    "Apple Color Emoji": None,
    "Segoe UI Emoji": None,
}

# ─── Color naming ─────────────────────────────────────────────────────────────

def name_color(hex_color):
    """Give a human-readable name to a hex color."""
    h = hex_color.upper()
    simple = {
        "#000000": "black", "#FFFFFF": "white", "#FF0000": "red",
        "#00FF00": "green", "#0000FF": "blue", "#FFFF00": "yellow",
        "#FF00FF": "magenta", "#00FFFF": "cyan",
    }
    if h in simple:
        return simple[h]

    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    if lum < 30:
        return "near-black"
    if lum > 225:
        return "near-white"
    if r > 200 and g < 80 and b < 80:
        return "red"
    if r < 80 and g > 200 and b < 80:
        return "green"
    if r < 80 and g < 80 and b > 200:
        return "blue"
    if r > 200 and g > 200 and b < 80:
        return "yellow"
    if r > 200 and g < 80 and b > 200:
        return "purple"
    if r < 80 and g > 200 and b > 200:
        return "teal"
    if r > 180 and g > 100 and b < 50:
        return "orange"
    if abs(r - g) < 20 and abs(g - b) < 20:
        if lum < 100:
            return "dark-gray"
        if lum < 180:
            return "gray"
        return "light-gray"
    return f"color-{h[1:].lower()}"


# ─── Figma color helpers ──────────────────────────────────────────────────────

def figma_color_to_hex(color_obj):
    """Convert Figma RGBA (0-1) color to hex string."""
    if not color_obj:
        return None
    r = int(round(color_obj.get("r", 0) * 255))
    g = int(round(color_obj.get("g", 0) * 255))
    b = int(round(color_obj.get("b", 0) * 255))
    return f"#{r:02X}{g:02X}{b:02X}"


def get_solid_fill_color(fills):
    """Get first visible solid fill color as hex."""
    if not fills:
        return None
    for f in fills:
        if f.get("type") == "SOLID" and f.get("visible", True):
            return figma_color_to_hex(f.get("color"))
    return None


def get_bg_color(node):
    """Get background color from a node."""
    # Try fills first
    color = get_solid_fill_color(node.get("fills", []))
    if color:
        return color
    # Try backgroundColor
    bg = node.get("backgroundColor")
    if bg:
        return figma_color_to_hex(bg)
    return None


def luminance(hex_color):
    """Calculate relative luminance of a hex color (0=dark, 1=light)."""
    if not hex_color:
        return 0.5
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ─── Node walking / element extraction ────────────────────────────────────────

def has_image_fill(node):
    """Check if node has IMAGE type fill."""
    for f in node.get("fills", []):
        if f.get("type") == "IMAGE" and f.get("visible", True):
            return True
    return False


def get_image_ref(node):
    """Get imageRef from first IMAGE fill."""
    for f in node.get("fills", []):
        if f.get("type") == "IMAGE" and f.get("visible", True):
            return f.get("imageRef")
    return None


def classify_node(node):
    """Determine the element type of a Figma node."""
    ntype = node.get("type", "")
    name = node.get("name", "")
    name_lower = name.lower()
    style = node.get("style", {})
    font_size = style.get("fontSize", 16)
    children = node.get("children", [])
    has_layout = "layoutMode" in node

    if ntype == "TEXT":
        if font_size > 32:
            return "heading"
        elif font_size >= 16:
            return "paragraph"
        else:
            return "span"

    if ntype in ("FRAME", "INSTANCE", "COMPONENT", "COMPONENT_SET"):
        # Button detection
        btn_patterns = ["button", "cta", "btn"]
        if any(p in name_lower for p in btn_patterns):
            return "button"

        # Input detection
        input_patterns = ["input", "search", "field", "textfield", "text field", "text-field"]
        if any(p in name_lower for p in input_patterns):
            return "input"

        # Link detection
        link_patterns = ["link", "anchor"]
        if any(p in name_lower for p in link_patterns):
            return "link"

        # Icon detection
        icon_patterns = ["icon", "ico", "svg"]
        if any(p in name_lower for p in icon_patterns):
            return "icon"

        # Image fill
        if has_image_fill(node):
            return "image"

        # Container with children and layout
        if children and has_layout:
            return "container"

        # Container with children but no layout
        if children:
            return "container"

        # No children, might be decoration
        if not children:
            if has_image_fill(node):
                return "image"
            return "decoration"

    if ntype == "RECTANGLE":
        if has_image_fill(node):
            return "image"
        if not children:
            return "divider"

    if ntype == "VECTOR":
        return "icon"

    if ntype == "ELLIPSE":
        if has_image_fill(node):
            return "image"
        return "decoration"

    if ntype == "GROUP":
        return "container"

    return "container"


def extract_text_style(node):
    """Extract CSS-ready text style from a TEXT node."""
    style = node.get("style", {})
    fills = node.get("fills", [])
    result = {}

    if style.get("fontFamily"):
        result["font"] = style["fontFamily"]
    if style.get("fontSize"):
        result["fontSize"] = style["fontSize"]
    if style.get("fontWeight"):
        result["fontWeight"] = style["fontWeight"]

    color = get_solid_fill_color(fills)
    if color:
        result["color"] = color

    if style.get("lineHeightPx"):
        result["lineHeight"] = f"{style['lineHeightPx']}px"
    if style.get("letterSpacing") is not None:
        result["letterSpacing"] = f"{style['letterSpacing']}px"

    align_map = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFIED": "justify"}
    if style.get("textAlignHorizontal"):
        result["textAlign"] = align_map.get(style["textAlignHorizontal"], "left")

    opacity = node.get("opacity")
    if opacity is not None and opacity != 1:
        result["opacity"] = opacity

    return result


def extract_container_style(node):
    """Extract CSS-ready style for a container/frame node."""
    result = {}

    # Background
    bg = get_solid_fill_color(node.get("fills", []))
    if bg:
        result["background"] = bg

    # Border radius
    cr = node.get("cornerRadius")
    if cr:
        result["borderRadius"] = f"{cr}px"
    else:
        # Individual corner radii
        corners = []
        for key in ["topLeftRadius", "topRightRadius", "bottomRightRadius", "bottomLeftRadius"]:
            v = node.get(key, 0)
            corners.append(v)
        if any(c > 0 for c in corners):
            result["borderRadius"] = " ".join(f"{c}px" for c in corners)

    # Padding
    pt = node.get("paddingTop", 0)
    pr = node.get("paddingRight", 0)
    pb = node.get("paddingBottom", 0)
    pl = node.get("paddingLeft", 0)
    if any(v > 0 for v in [pt, pr, pb, pl]):
        if pt == pb and pl == pr:
            if pt == pl:
                result["padding"] = f"{pt}px"
            else:
                result["padding"] = f"{pt}px {pl}px"
        else:
            result["padding"] = f"{pt}px {pr}px {pb}px {pl}px"

    # Opacity
    opacity = node.get("opacity")
    if opacity is not None and opacity != 1:
        result["opacity"] = opacity

    # Border / stroke
    strokes = node.get("strokes", [])
    sw = node.get("strokeWeight", 0)
    if strokes and sw > 0:
        stroke_color = get_solid_fill_color(strokes)
        if stroke_color:
            result["border"] = f"{sw}px solid {stroke_color}"

    # Effects (shadows)
    for effect in node.get("effects", []):
        if effect.get("type") == "DROP_SHADOW" and effect.get("visible", True):
            c = effect.get("color", {})
            ox = effect.get("offset", {}).get("x", 0)
            oy = effect.get("offset", {}).get("y", 0)
            r = effect.get("radius", 0)
            a = c.get("a", 1)
            cr_r = int(c.get("r", 0) * 255)
            cr_g = int(c.get("g", 0) * 255)
            cr_b = int(c.get("b", 0) * 255)
            result["boxShadow"] = f"{ox}px {oy}px {r}px rgba({cr_r},{cr_g},{cr_b},{a:.2f})"
            break

    return result


def extract_layout(node):
    """Extract flex layout properties from a container node."""
    layout_mode = node.get("layoutMode")
    if not layout_mode:
        return None

    result = {"display": "flex"}

    if layout_mode == "VERTICAL":
        result["flexDirection"] = "column"
    else:
        result["flexDirection"] = "row"

    # Alignment
    pa = node.get("primaryAxisAlignItems", "MIN")
    ca = node.get("counterAxisAlignItems", "MIN")

    justify_map = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end",
                   "SPACE_BETWEEN": "space-between"}
    align_map = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end",
                 "BASELINE": "baseline"}

    result["justifyContent"] = justify_map.get(pa, "flex-start")
    result["alignItems"] = align_map.get(ca, "flex-start")

    # Gap
    gap = node.get("itemSpacing", 0)
    if gap > 0:
        result["gap"] = f"{gap}px"

    # Padding (same as container style)
    pt = node.get("paddingTop", 0)
    pr = node.get("paddingRight", 0)
    pb = node.get("paddingBottom", 0)
    pl = node.get("paddingLeft", 0)
    if any(v > 0 for v in [pt, pr, pb, pl]):
        if pt == pb and pl == pr:
            if pt == pl:
                result["padding"] = f"{pt}px"
            else:
                result["padding"] = f"{pt}px {pl}px"
        else:
            result["padding"] = f"{pt}px {pr}px {pb}px {pl}px"

    return result


def get_button_text(node):
    """Find text content in a button node's children."""
    if node.get("type") == "TEXT":
        return node.get("characters", "")
    for child in node.get("children", []):
        text = get_button_text(child)
        if text:
            return text
    return ""


def build_element(node, asset_map, all_colors, all_fonts):
    """Build an element dict from a Figma node, recursively."""
    elem_type = classify_node(node)
    ntype = node.get("type", "")
    style = {}
    layout = None
    content = None
    image = None
    children_elems = []

    # Collect colors from fills
    for f in node.get("fills", []):
        if f.get("type") == "SOLID" and f.get("visible", True):
            hex_c = figma_color_to_hex(f.get("color"))
            if hex_c:
                all_colors[hex_c] += 1

    # Collect fonts
    node_style = node.get("style", {})
    if node_style.get("fontFamily"):
        font_fam = node_style["fontFamily"]
        weight = node_style.get("fontWeight", 400)
        if font_fam not in all_fonts:
            all_fonts[font_fam] = set()
        all_fonts[font_fam].add(int(weight))

    if ntype == "TEXT":
        content = node.get("characters", "")
        style = extract_text_style(node)
    elif elem_type == "button":
        content = get_button_text(node)
        style = extract_container_style(node)
        # Also get text style from first TEXT child
        for child in node.get("children", []):
            if child.get("type") == "TEXT":
                text_style = extract_text_style(child)
                style.update({k: v for k, v in text_style.items() if k not in style})
                break
    elif elem_type == "image":
        style = extract_container_style(node)
        # Find asset
        img_ref = get_image_ref(node)
        nid = node.get("id", "")
        asset_name = nid.replace(":", "-") + ".png"
        if asset_name in asset_map:
            image = asset_name
    else:
        style = extract_container_style(node)
        layout = extract_layout(node)

    # Recurse into children (but not for buttons/text)
    if elem_type not in ("heading", "paragraph", "span", "button", "image", "divider", "icon", "decoration"):
        for child in node.get("children", []):
            child_elem = build_element(child, asset_map, all_colors, all_fonts)
            if child_elem:
                children_elems.append(child_elem)
    elif elem_type in ("button",):
        # Still collect colors/fonts from children without building elements
        _collect_deep(node, all_colors, all_fonts)

    # Build result
    result = {
        "id": node.get("id", ""),
        "type": elem_type,
    }
    if content:
        result["content"] = content
    if style:
        result["style"] = style
    if layout:
        result["layout"] = layout
    if children_elems:
        result["children"] = children_elems
    if image:
        result["image"] = image

    return result


def _collect_deep(node, all_colors, all_fonts):
    """Collect colors and fonts from all descendants without building elements."""
    for f in node.get("fills", []):
        if f.get("type") == "SOLID" and f.get("visible", True):
            hex_c = figma_color_to_hex(f.get("color"))
            if hex_c:
                all_colors[hex_c] += 1
    ns = node.get("style", {})
    if ns.get("fontFamily"):
        ff = ns["fontFamily"]
        w = int(ns.get("fontWeight", 400))
        if ff not in all_fonts:
            all_fonts[ff] = set()
        all_fonts[ff].add(w)
    for c in node.get("children", []):
        _collect_deep(c, all_colors, all_fonts)


# ─── Repeated pattern detection ───────────────────────────────────────────────

def structure_hash(node, depth=0):
    """Create a hash representing the structure (types + depths) of a node tree."""
    if depth > 10:
        return ""
    ntype = node.get("type", "")
    children = node.get("children", [])
    child_hashes = [structure_hash(c, depth + 1) for c in children]
    sig = f"{ntype}:{len(children)}:[{','.join(child_hashes)}]"
    return hashlib.md5(sig.encode()).hexdigest()[:8]


def extract_repeated_data(nodes):
    """Extract variable data from structurally similar nodes."""
    data = []
    for node in nodes:
        item = {}
        _extract_texts_and_images(node, item, prefix="")
        data.append(item)
    return data


def _extract_texts_and_images(node, item, prefix):
    """Recursively extract text and image data from a node."""
    ntype = node.get("type", "")
    name = node.get("name", "")

    if ntype == "TEXT":
        key = _clean_key(name or prefix or "text")
        # Avoid duplicate keys
        if key in item:
            key = f"{key}_{len(item)}"
        item[key] = node.get("characters", "")
    elif has_image_fill(node):
        key = _clean_key(name or prefix or "image")
        nid = node.get("id", "")
        item[key] = nid.replace(":", "-") + ".png"

    for i, child in enumerate(node.get("children", [])):
        child_prefix = f"{prefix}_{i}" if prefix else str(i)
        _extract_texts_and_images(child, item, child_prefix)


def _clean_key(name):
    """Clean a node name into a usable JSON key."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_').lower()[:30]


def detect_repeated(section_node):
    """Find repeated patterns in a section. Returns (component_name, nodes) or None."""
    children = section_node.get("children", [])
    if len(children) < 3:
        return None

    # Hash each direct child
    hashes = {}
    for child in children:
        h = structure_hash(child)
        if h not in hashes:
            hashes[h] = []
        hashes[h].append(child)

    # Find groups of 3+
    for h, nodes in hashes.items():
        if len(nodes) >= 3:
            # Use the name of the first node as component name
            name = nodes[0].get("name", "Item")
            # Clean up the name
            name = re.sub(r'\s*\d+$', '', name).strip()
            if not name:
                name = "Item"
            return (name, nodes)

    # Also check grandchildren (nested in a container)
    for child in children:
        result = detect_repeated(child)
        if result:
            return result

    return None


# ─── Screenshot handling ──────────────────────────────────────────────────────

def match_screenshot(section_idx, section_name, screenshots_dir, all_screenshots):
    """Find the best matching screenshot for a section."""
    if not all_screenshots:
        return None

    # Try matching by order number
    prefix = f"section-{section_idx + 1:02d}-"
    for ss in all_screenshots:
        if ss.startswith(prefix):
            return os.path.join(screenshots_dir, ss)

    # Try matching by name
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', section_name).lower()
    for ss in all_screenshots:
        clean_ss = re.sub(r'[^a-zA-Z0-9]', '', ss).lower()
        if clean_name and clean_name in clean_ss:
            return os.path.join(screenshots_dir, ss)

    return None


def crop_from_full(full_png_path, bbox, root_bbox, output_path):
    """Crop a component screenshot from the full page screenshot."""
    if not HAS_PIL or not os.path.exists(full_png_path):
        return False

    try:
        img = Image.open(full_png_path)
        img_w, img_h = img.size

        # Calculate scale factor
        root_w = root_bbox.get("width", img_w)
        root_h = root_bbox.get("height", img_h)
        scale_x = img_w / root_w if root_w > 0 else 1
        scale_y = img_h / root_h if root_h > 0 else 1

        # Calculate crop coordinates relative to root
        x = (bbox.get("x", 0) - root_bbox.get("x", 0)) * scale_x
        y = (bbox.get("y", 0) - root_bbox.get("y", 0)) * scale_y
        w = bbox.get("width", 100) * scale_x
        h = bbox.get("height", 100) * scale_y

        # Clamp to image bounds
        x = max(0, int(x))
        y = max(0, int(y))
        x2 = min(img_w, int(x + w))
        y2 = min(img_h, int(y + h))

        if x2 <= x or y2 <= y:
            return False

        cropped = img.crop((x, y, x2, y2))
        cropped.save(output_path)
        return True
    except Exception:
        return False


# ─── Main prepare logic ──────────────────────────────────────────────────────

def prepare(input_dir, output_dir):
    """Main prepare function."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Load design.json
    design_file = input_path / "design.json"
    if not design_file.exists():
        print(f"ERROR: {design_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(design_file) as f:
        design = json.load(f)

    # Get root node
    root = design.get("root", design)
    if "children" not in root and "document" in design:
        root = design["document"]

    # Page info
    page_name = design.get("name", root.get("name", "Unknown"))
    root_bbox = root.get("absoluteBoundingBox", {})
    page_width = root_bbox.get("width", 1920)
    page_height = root_bbox.get("height", 0)

    # Detect theme from root background
    root_bg = get_bg_color(root)
    if not root_bg:
        root_bg = "#FFFFFF"
    is_dark = luminance(root_bg) < 0.3

    # Build asset map
    assets_dir = input_path / "assets"
    asset_files = set()
    if assets_dir.exists():
        asset_files = set(os.listdir(assets_dir))

    # Screenshots
    screenshots_dir = input_path / "screenshots"
    all_screenshots = []
    if screenshots_dir.exists():
        all_screenshots = sorted([f for f in os.listdir(screenshots_dir) if f.endswith(".png") and f != "full.png"])
    full_png = screenshots_dir / "full.png"

    # ── Process sections ──────────────────────────────────────────────────────

    sections = root.get("children", [])
    all_colors = Counter()
    all_fonts = {}  # font_family -> set of weights
    text_colors = Counter()  # for finding primary text color
    accent_colors = Counter()  # for finding accent color

    # Collect text colors separately
    def collect_text_colors(node):
        if node.get("type") == "TEXT":
            color = get_solid_fill_color(node.get("fills", []))
            if color:
                text_colors[color] += 1
        for c in node.get("children", []):
            collect_text_colors(c)

    for section in sections:
        collect_text_colors(section)

    # Create output structure
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "global").mkdir(exist_ok=True)
    (output_path / "components").mkdir(exist_ok=True)

    structure_sections = []
    component_summaries = []
    total_assets = 0
    used_folder_names = set()

    for idx, section in enumerate(sections):
        section_name = section.get("name", f"Section-{idx + 1}")
        # Clean section name for folder
        folder_name = re.sub(r'[^\w\-]', '', section_name.replace(' ', '-'))
        if not folder_name:
            folder_name = f"Section-{idx + 1}"
        # Deduplicate folder names
        base_name = folder_name
        counter = 2
        while folder_name in used_folder_names:
            folder_name = f"{base_name}-{counter}"
            counter += 1
        used_folder_names.add(folder_name)

        section_bbox = section.get("absoluteBoundingBox", {})
        section_height = section_bbox.get("height", 0)

        comp_dir = output_path / "components" / folder_name
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "assets").mkdir(exist_ok=True)

        # Build spec.json
        elem = build_element(section, asset_files, all_colors, all_fonts)

        # Detect repeated patterns
        repeated = detect_repeated(section)
        repeated_info = None
        if repeated:
            comp_name, repeated_nodes = repeated
            repeated_data = extract_repeated_data(repeated_nodes)
            if repeated_data:
                repeated_info = {
                    "component": comp_name,
                    "count": len(repeated_nodes),
                    "dataFile": "repeated.json"
                }
                # Write repeated.json
                with open(comp_dir / "repeated.json", "w") as f:
                    json.dump(repeated_data, f, indent=2)

        # If we have repeated patterns, add reference in spec
        spec = {
            "name": section_name,
            "order": idx + 1,
            "width": section_bbox.get("width", page_width),
            "height": section_height,
            "elements": elem.get("children", [elem]),
        }
        if repeated_info:
            spec["repeated"] = repeated_info

        with open(comp_dir / "spec.json", "w") as f:
            json.dump(spec, f, indent=2)

        # Copy assets for this component
        component_assets = set()
        _find_component_assets(section, component_assets)
        copied_assets = 0
        for asset_name in component_assets:
            if asset_name in asset_files:
                src = assets_dir / asset_name
                dst = comp_dir / "assets" / asset_name
                if src.exists():
                    shutil.copy2(src, dst)
                    copied_assets += 1
        total_assets += copied_assets

        # Handle screenshot
        screenshot_src = match_screenshot(idx, section_name, str(screenshots_dir), all_screenshots)
        if screenshot_src and os.path.exists(screenshot_src):
            shutil.copy2(screenshot_src, comp_dir / "screenshot.png")
        elif full_png.exists() and section_bbox and root_bbox:
            crop_from_full(str(full_png), section_bbox, root_bbox, str(comp_dir / "screenshot.png"))

        # Count elements
        elem_count = _count_elements(elem)

        structure_sections.append({
            "name": section_name,
            "order": idx + 1,
            "height": section_height,
            "folder": f"components/{folder_name}"
        })

        # Build summary description
        desc_parts = []
        if repeated_info:
            desc_parts.append(f"{repeated_info['count']} repeated {repeated_info['component']}s (see repeated.json)")
        desc_parts.append(f"{elem_count} elements")
        if copied_assets > 0:
            desc_parts.append(f"{copied_assets} assets")

        component_summaries.append({
            "name": section_name,
            "height": section_height,
            "description": ", ".join(desc_parts),
            "has_repeated": repeated_info is not None
        })

    # ── Build theme.json ──────────────────────────────────────────────────────

    # Find primary text color (most common text fill)
    primary_text = "#FFFFFF" if is_dark else "#000000"
    if text_colors:
        primary_text = text_colors.most_common(1)[0][0]

    # Find accent color (most common non-black/white/gray color)
    accent = None
    for color, count in all_colors.most_common():
        lum = luminance(color)
        # Skip near-black, near-white, and grays
        h = color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        is_gray = abs(r - g) < 30 and abs(g - b) < 30
        if not is_gray and 0.05 < lum < 0.95:
            accent = color
            break

    if not accent:
        accent = "#3B82F6"  # Default blue

    theme = {
        "mode": "dark" if is_dark else "light",
        "background": root_bg,
        "text": primary_text,
        "accent": accent
    }

    with open(output_path / "theme.json", "w") as f:
        json.dump(theme, f, indent=2)

    # ── Build structure.json ──────────────────────────────────────────────────

    structure = {
        "page": page_name,
        "width": page_width,
        "height": page_height,
        "theme": "dark" if is_dark else "light",
        "sections": structure_sections
    }

    with open(output_path / "structure.json", "w") as f:
        json.dump(structure, f, indent=2)

    # ── Build global/colors.json ──────────────────────────────────────────────

    # Build color usage map
    color_usage = {}
    for color, count in all_colors.most_common():
        usages = []
        if color == root_bg:
            usages.append("background")
        if color == primary_text:
            usages.append("primary text")
        if color == accent:
            usages.append("accent")
        if color in text_colors:
            if "primary text" not in usages:
                usages.append("text")
        if not usages:
            usages.append("decorative")

        color_usage[color] = ", ".join(usages)

    palette = []
    for color, count in all_colors.most_common():
        palette.append({
            "hex": color,
            "name": name_color(color),
            "usage": color_usage.get(color, "decorative")
        })

    colors_json = {
        "palette": palette,
        "count": len(palette)
    }

    with open(output_path / "global" / "colors.json", "w") as f:
        json.dump(colors_json, f, indent=2)

    # ── Build global/fonts.json ───────────────────────────────────────────────

    fonts_list = []
    substitutions = []

    for family, weights in sorted(all_fonts.items()):
        sorted_weights = sorted(weights)
        is_google = family in GOOGLE_FONTS

        if family in FONT_SUBSTITUTIONS:
            sub = FONT_SUBSTITUTIONS[family]
            if sub:
                substitutions.append({
                    "original": family,
                    "substitute": sub,
                    "reason": "Not on Google Fonts"
                })
            continue

        weight_str = ";".join(str(w) for w in sorted_weights)
        url_family = family.replace(" ", "+")

        font_entry = {
            "family": family,
            "weights": sorted_weights,
        }

        if is_google:
            font_entry["googleFontsUrl"] = f"https://fonts.googleapis.com/css2?family={url_family}:wght@{weight_str}&display=swap"
            font_entry["isGoogleFont"] = True
        else:
            # Try to find it on Google Fonts anyway (generous matching)
            font_entry["googleFontsUrl"] = f"https://fonts.googleapis.com/css2?family={url_family}:wght@{weight_str}&display=swap"
            font_entry["isGoogleFont"] = False

        fonts_list.append(font_entry)

    fonts_json = {
        "fonts": fonts_list,
        "substitutions": substitutions
    }

    with open(output_path / "global" / "fonts.json", "w") as f:
        json.dump(fonts_json, f, indent=2)

    # ── Build summary.md ──────────────────────────────────────────────────────

    font_summary = []
    for fe in fonts_list:
        weights = fe["weights"]
        if len(weights) == 1:
            w_str = str(weights[0])
        else:
            w_str = f"{weights[0]}-{weights[-1]}"
        font_summary.append(f"{fe['family']} ({w_str})")

    sub_summary = [f"{s['original']} → {s['substitute']}" for s in substitutions]

    lines = [
        "# Prepared Data Package",
        "",
        f"## Page: {page_name} ({int(page_width)} x {int(page_height)}px, {'dark' if is_dark else 'light'} theme)",
        "",
        f"## Components ({len(structure_sections)}):",
    ]

    for i, cs in enumerate(component_summaries):
        lines.append(f"{i + 1}. **{cs['name']}** — {cs['description']}, {int(cs['height'])}px height")

    lines.extend([
        "",
        f"## Assets: {total_assets} images",
        f"## Colors: {len(palette)} unique",
        f"## Fonts: {', '.join(font_summary) if font_summary else 'none detected'}",
    ])

    if sub_summary:
        lines.append(f"## Substitutions: {', '.join(sub_summary)}")

    with open(output_path / "summary.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"✅ Prepared {len(structure_sections)} components from '{page_name}'")
    print(f"   Output: {output_path}")
    print(f"   Theme: {'dark' if is_dark else 'light'} | Colors: {len(palette)} | Fonts: {len(fonts_list)}")
    print(f"   Assets: {total_assets} | Substitutions: {len(substitutions)}")


def _find_component_assets(node, assets):
    """Recursively find all asset filenames referenced by a node tree."""
    if has_image_fill(node):
        nid = node.get("id", "")
        asset_name = nid.replace(":", "-") + ".png"
        assets.add(asset_name)
    for child in node.get("children", []):
        _find_component_assets(child, assets)


def _count_elements(elem):
    """Count total elements in an element tree."""
    count = 1
    for child in elem.get("children", []):
        count += _count_elements(child)
    return count


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Prepare Figma data into per-component packages")
    parser.add_argument("--input", required=True, help="Input directory (from extract.py)")
    parser.add_argument("--output", required=True, help="Output directory for prepared data")
    args = parser.parse_args()

    prepare(args.input, args.output)


if __name__ == "__main__":
    main()
