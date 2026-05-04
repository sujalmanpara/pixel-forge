#!/usr/bin/env python3
"""
Figma JSON → HTML/React/Next.js generator.
Pure algorithmic conversion — zero LLM, zero network calls.

Usage:
    python3 generate.py --input ./figma-data/ --output ./output/ [--framework html|react|nextjs] [--tailwind] [--responsive]
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import OrderedDict
from pathlib import Path


# ─── Helpers ───────────────────────────────────────────────────────────────

def rgba_from_figma(color, alpha_override=None):
    """Convert Figma color {r,g,b,a} (0-1 floats) to CSS rgba string."""
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    a = alpha_override if alpha_override is not None else color.get("a", 1)
    if a >= 0.999:
        return f"rgb({r}, {g}, {b})"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def hex_from_figma(color):
    """Convert Figma color to hex string."""
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def sanitize_class(node):
    """Generate a CSS class name from node name + id."""
    name = node.get("name", "element")
    name = name.replace(" ", "-").replace("/", "-").replace(".", "-").lower()
    # Remove non-alphanumeric except hyphens
    name = "".join(c if c.isalnum() or c == "-" else "-" for c in name)
    # Collapse multiple hyphens
    while "--" in name:
        name = name.replace("--", "-")
    name = name.strip("-")
    nid = node.get("id", "0-0").replace(":", "-").replace(";", "-")
    # Remove any remaining invalid CSS identifier chars
    nid = "".join(c if c.isalnum() or c == "-" else "-" for c in nid)
    # Edge case: truncate long class names (some Figma nodes have very long names)
    full = f"fig-{name}-{nid}"
    if len(full) > 60:
        full = full[:57] + nid[-3:] if len(nid) >= 3 else full[:60]
    return full


def to_pascal_case(name):
    """Convert a Figma layer name to PascalCase component name."""
    # Remove generic prefixes/patterns
    name = re.sub(r'^(Section\s*[-–—]\s*)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'^(Frame\s+\d+)$', 'Section', name, flags=re.IGNORECASE)
    # Remove non-alphanumeric except spaces/hyphens
    name = re.sub(r'[^a-zA-Z0-9\s\-_]', '', name)
    # Split on spaces, hyphens, underscores
    words = re.split(r'[\s\-_]+', name.strip())
    words = [w for w in words if w]
    if not words:
        return "Component"
    result = "".join(w[0].upper() + w[1:] for w in words)
    # Ensure starts with letter
    if result and not result[0].isalpha():
        result = "C" + result
    return result or "Component"


def to_kebab_case(pascal):
    """PascalCase → kebab-case."""
    s = re.sub(r'([A-Z])', r'-\1', pascal).lstrip('-').lower()
    return s


def figma_align_to_css(value, axis="primary"):
    """Convert Figma alignment enums to CSS flex values."""
    mapping = {
        "MIN": "flex-start",
        "CENTER": "center",
        "MAX": "flex-end",
        "SPACE_BETWEEN": "space-between",
    }
    return mapping.get(value, "flex-start")


def escape_jsx_text(text):
    """Escape special characters for JSX text content.
    Handles <, >, &, {, } which have special meaning in JSX."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Edge case: { and } are JSX expression delimiters — must escape them
    text = text.replace("{", "{'{'}")
    text = text.replace("}", "{'}'}")
    return text


def asset_path_for_node(node_id, assets_dir):
    """Check if an asset image exists for the given node ID."""
    # Edge case: Figma IDs may contain semicolons (e.g. I457360;111468207)
    sanitized = node_id.replace(":", "-").replace(";", "-")
    for candidate in [f"{sanitized}.png", f"{node_id}.png", f"{sanitized}.jpg", f"{node_id}.jpg"]:
        if os.path.exists(os.path.join(assets_dir, candidate)):
            return candidate  # Return just filename, caller adds prefix
    return None


def count_descendants(node):
    """Count total descendant nodes."""
    count = 0
    for child in node.get("children", []):
        count += 1 + count_descendants(child)
    return count


# ─── Tailwind CSS Mapping ─────────────────────────────────────────────────

# Spacing scale: px → Tailwind unit (px/4)
def px_to_tw_spacing(px_val):
    """Convert px to nearest Tailwind spacing value."""
    val = float(px_val)
    # Tailwind spacing: 0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 72, 80, 96
    scale = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 72, 80, 96]
    tw_val = val / 4
    closest = min(scale, key=lambda x: abs(x - tw_val))
    if closest == int(closest):
        return str(int(closest))
    return str(closest)


FONT_SIZE_MAP = {
    12: "text-xs", 14: "text-sm", 16: "text-base", 18: "text-lg",
    20: "text-xl", 24: "text-2xl", 30: "text-3xl", 36: "text-4xl",
    48: "text-5xl", 60: "text-6xl", 72: "text-7xl", 96: "text-8xl", 128: "text-9xl",
}

FONT_WEIGHT_MAP = {
    100: "font-thin", 200: "font-extralight", 300: "font-light",
    400: "font-normal", 500: "font-medium", 600: "font-semibold",
    700: "font-bold", 800: "font-extrabold", 900: "font-black",
}

BORDER_RADIUS_MAP = {
    0: "", 2: "rounded-sm", 4: "rounded", 6: "rounded-md",
    8: "rounded-lg", 12: "rounded-xl", 16: "rounded-2xl", 24: "rounded-3xl",
}


def css_to_tailwind_classes(styles, color_map=None):
    """Convert CSS properties dict to Tailwind classes + remaining CSS.
    
    Returns (tailwind_classes: list[str], remaining_css: dict)
    """
    tw = []
    remaining = OrderedDict()
    color_map = color_map or {}

    for prop, val in styles.items():
        matched = False

        if prop == "display" and val == "flex":
            tw.append("flex")
            matched = True
        elif prop == "display" and val == "grid":
            tw.append("grid")
            matched = True
        elif prop == "flex-direction":
            if val == "column":
                tw.append("flex-col")
            elif val == "row":
                pass  # default
            matched = True
        elif prop == "justify-content":
            jmap = {"flex-start": "justify-start", "center": "justify-center",
                     "flex-end": "justify-end", "space-between": "justify-between",
                     "space-around": "justify-around", "space-evenly": "justify-evenly"}
            if val in jmap:
                tw.append(jmap[val])
                matched = True
        elif prop == "align-items":
            amap = {"flex-start": "items-start", "center": "items-center",
                     "flex-end": "items-end", "stretch": "items-stretch",
                     "baseline": "items-baseline"}
            if val in amap:
                tw.append(amap[val])
                matched = True
        elif prop == "align-self":
            smap = {"stretch": "self-stretch", "center": "self-center",
                     "flex-start": "self-start", "flex-end": "self-end"}
            if val in smap:
                tw.append(smap[val])
                matched = True
        elif prop == "flex" and val == "1":
            tw.append("flex-1")
            matched = True
        elif prop == "gap":
            m = re.match(r'^([\d.]+)px$', val)
            if m:
                tw.append(f"gap-{px_to_tw_spacing(m.group(1))}")
                matched = True
        elif prop == "padding":
            m = re.match(r'^([\d.]+)px ([\d.]+)px ([\d.]+)px ([\d.]+)px$', val)
            if m:
                top, right, bottom, left = m.groups()
                if top == bottom and left == right:
                    if top == left:
                        tw.append(f"p-{px_to_tw_spacing(top)}")
                    else:
                        tw.append(f"px-{px_to_tw_spacing(left)}")
                        tw.append(f"py-{px_to_tw_spacing(top)}")
                else:
                    if top != "0": tw.append(f"pt-{px_to_tw_spacing(top)}")
                    if right != "0": tw.append(f"pr-{px_to_tw_spacing(right)}")
                    if bottom != "0": tw.append(f"pb-{px_to_tw_spacing(bottom)}")
                    if left != "0": tw.append(f"pl-{px_to_tw_spacing(left)}")
                matched = True
        elif prop == "width":
            if val == "100%":
                tw.append("w-full")
                matched = True
            # Fixed widths stay in CSS
        elif prop == "height":
            if val == "100%":
                tw.append("h-full")
                matched = True
        elif prop == "overflow" and val == "hidden":
            tw.append("overflow-hidden")
            matched = True
        elif prop == "position":
            pmap = {"relative": "relative", "absolute": "absolute", "fixed": "fixed", "sticky": "sticky"}
            if val in pmap:
                tw.append(pmap[val])
                matched = True
        elif prop == "opacity":
            try:
                oval = float(val)
                tw.append(f"opacity-{int(oval * 100)}")
                matched = True
            except ValueError:
                pass
        elif prop == "font-size":
            m = re.match(r'^([\d.]+)px$', val)
            if m:
                sz = round(float(m.group(1)))
                if sz in FONT_SIZE_MAP:
                    tw.append(FONT_SIZE_MAP[sz])
                    matched = True
                else:
                    tw.append(f"text-[{sz}px]")
                    matched = True
        elif prop == "font-weight":
            try:
                w = int(float(val))
                if w in FONT_WEIGHT_MAP:
                    tw.append(FONT_WEIGHT_MAP[w])
                    matched = True
            except ValueError:
                pass
        elif prop == "text-align":
            tmap = {"center": "text-center", "right": "text-right", "justify": "text-justify"}
            if val in tmap:
                tw.append(tmap[val])
                matched = True
        elif prop == "text-decoration":
            if val == "underline":
                tw.append("underline")
                matched = True
            elif val == "line-through":
                tw.append("line-through")
                matched = True
        elif prop == "text-transform":
            ttmap = {"uppercase": "uppercase", "lowercase": "lowercase", "capitalize": "capitalize"}
            if val in ttmap:
                tw.append(ttmap[val])
                matched = True
        elif prop == "border-radius":
            m = re.match(r'^([\d.]+)px$', val)
            if m:
                r_val = round(float(m.group(1)))
                if r_val in BORDER_RADIUS_MAP:
                    tw_cls = BORDER_RADIUS_MAP[r_val]
                    if tw_cls:
                        tw.append(tw_cls)
                elif r_val >= 9999:
                    tw.append("rounded-full")
                else:
                    tw.append(f"rounded-[{r_val}px]")
                matched = True
        elif prop == "background-color":
            hex_match = _extract_color_hex(val)
            if hex_match and hex_match.lower() in color_map:
                tw.append(f"bg-{color_map[hex_match.lower()]}")
                matched = True
            elif hex_match:
                tw.append(f"bg-[{hex_match}]")
                matched = True
        elif prop == "color":
            hex_match = _extract_color_hex(val)
            if hex_match and hex_match.lower() in color_map:
                tw.append(f"text-{color_map[hex_match.lower()]}")
                matched = True
            elif hex_match:
                tw.append(f"text-[{hex_match}]")
                matched = True
        elif prop == "border":
            # border: 1px solid #color
            m = re.match(r'^(\d+)px solid (.+)$', val)
            if m:
                bw = m.group(1)
                bc = m.group(2).strip()
                if bw == "1":
                    tw.append("border")
                else:
                    tw.append(f"border-[{bw}px]")
                hex_match = _extract_color_hex(bc)
                if hex_match and hex_match.lower() in color_map:
                    tw.append(f"border-{color_map[hex_match.lower()]}")
                elif hex_match:
                    tw.append(f"border-[{hex_match}]")
                matched = True

        if not matched:
            remaining[prop] = val

    return tw, remaining


def _extract_color_hex(css_color):
    """Try to extract hex from an rgb/rgba or hex color string."""
    css_color = css_color.strip()
    if css_color.startswith("#"):
        return css_color
    m = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', css_color)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


# ─── Responsive Breakpoints ────────────────────────────────────────────────

BREAKPOINT_TABLET = 768
BREAKPOINT_DESKTOP = 1280


def _responsive_value(prop, val, node=None):
    """Compute (mobile, tablet, desktop) values for a CSS property.
    Desktop = original Figma value. Mobile/tablet = scaled down per rules.
    Returns tuple of 3 strings. If no scaling needed, all three are identical.
    """
    desktop_val = val

    if prop == "padding":
        m = re.match(r'^([\d.]+)px ([\d.]+)px ([\d.]+)px ([\d.]+)px$', val)
        if m:
            values = [float(x) for x in m.groups()]
            if max(values) > 100:
                mobile = [16 if v > 100 else v for v in values]
                tablet = [40 if v > 100 else v for v in values]
                return (
                    f"{mobile[0]}px {mobile[1]}px {mobile[2]}px {mobile[3]}px",
                    f"{tablet[0]}px {tablet[1]}px {tablet[2]}px {tablet[3]}px",
                    desktop_val,
                )

    elif prop == "gap":
        m = re.match(r'^([\d.]+)px$', val)
        if m and float(m.group(1)) > 40:
            return ("16px", "24px", desktop_val)

    elif prop == "font-size":
        m = re.match(r'^([\d.]+)px$', val)
        if m:
            size = float(m.group(1))
            if size > 48:
                return (f"{round(size * 0.5)}px", f"{round(size * 0.75)}px", desktop_val)

    elif prop == "width":
        m = re.match(r'^([\d.]+)px$', val)
        if m and float(m.group(1)) > 600:
            return ("100%", "100%", desktop_val)

    return (desktop_val, desktop_val, desktop_val)


def compute_responsive(styles, node):
    """Split desktop styles into mobile-first responsive variants.

    Returns (mobile_base, tablet_overrides, desktop_overrides).
    - mobile_base: complete set of properties with mobile values
    - tablet_overrides: only properties that differ from mobile at tablet
    - desktop_overrides: only properties that differ from tablet at desktop
    """
    mobile = OrderedDict()
    tablet = OrderedDict()
    desktop = OrderedDict()

    for prop, val in styles.items():
        mob_val, tab_val, desk_val = _responsive_value(prop, val, node)
        mobile[prop] = mob_val
        if tab_val != mob_val:
            tablet[prop] = tab_val
        if desk_val != tab_val:
            desktop[prop] = desk_val

    # Horizontal flex → stack on mobile if children are too wide
    layout_mode = node.get("layoutMode") if node else None
    if layout_mode == "HORIZONTAL" and styles.get("flex-direction") == "row":
        children = node.get("children", []) if node else []
        total_w = sum(c.get("absoluteBoundingBox", {}).get("width", 0) for c in children)
        if total_w > 500:
            mobile["flex-direction"] = "column"
            if total_w > 768:
                desktop["flex-direction"] = "row"
            else:
                tablet["flex-direction"] = "row"

    return mobile, tablet, desktop


def _apply_responsive(styles, node, css_rules, cls_key, use_tailwind, color_map):
    """Apply responsive splitting. Stores base in css_rules[cls_key],
    overrides in css_rules['@tablet cls_key'] and css_rules['@desktop cls_key'].
    Returns (tw_classes_list, has_remaining_css).
    """
    mobile, tab_over, desk_over = compute_responsive(styles, node)

    if use_tailwind:
        base_tw, base_rem = css_to_tailwind_classes(mobile, color_map)
        tab_tw, tab_rem = css_to_tailwind_classes(tab_over, color_map)
        desk_tw, desk_rem = css_to_tailwind_classes(desk_over, color_map)
        all_tw = base_tw + [f"md:{c}" for c in tab_tw] + [f"lg:{c}" for c in desk_tw]
        if base_rem:
            css_rules[cls_key] = base_rem
        if tab_rem:
            css_rules[f"@tablet {cls_key}"] = tab_rem
        if desk_rem:
            css_rules[f"@desktop {cls_key}"] = desk_rem
        return all_tw, bool(base_rem)
    else:
        css_rules[cls_key] = mobile
        if tab_over:
            css_rules[f"@tablet {cls_key}"] = tab_over
        if desk_over:
            css_rules[f"@desktop {cls_key}"] = desk_over
        return [], True


# ─── Style Extraction ──────────────────────────────────────────────────────

class StyleCollector:
    """Collects unique colors and fonts across the design."""

    def __init__(self):
        self.colors = OrderedDict()  # hex -> var name
        self.fonts = OrderedDict()   # family -> var name
        self._color_counter = 0
        self._font_counter = 0

    def register_color(self, hex_val):
        if hex_val not in self.colors:
            self._color_counter += 1
            self.colors[hex_val] = f"--color-{self._color_counter}"
        return f"var({self.colors[hex_val]})"

    def register_font(self, family):
        if family not in self.fonts:
            self._font_counter += 1
            self.fonts[family] = f"--font-{self._font_counter}"
        return f"var({self.fonts[family]})"

    def css_root(self):
        lines = [":root {"]
        for hex_val, var_name in self.colors.items():
            lines.append(f"  {var_name}: {hex_val};")
        for family, var_name in self.fonts.items():
            lines.append(f"  {var_name}: '{family}', sans-serif;")
        lines.append("}")
        return "\n".join(lines)

    def tailwind_color_map(self):
        """Return hex -> tailwind-friendly-name map for custom colors."""
        result = {}
        for hex_val in self.colors:
            name = _hex_to_tw_name(hex_val)
            result[hex_val.lower()] = name
        return result

    def tailwind_config_colors(self):
        """Return dict of tw_name -> hex for tailwind.config.ts."""
        result = OrderedDict()
        for hex_val in self.colors:
            name = _hex_to_tw_name(hex_val)
            result[name] = hex_val.upper() if hex_val.startswith('#') else hex_val
        return result

    def tailwind_config_fonts(self):
        """Return dict of tw_name -> [family, fallback] for tailwind.config.ts."""
        result = OrderedDict()
        for family in self.fonts:
            slug = family.lower().replace(" ", "-")
            result[slug] = [family, "sans-serif"]
        return result


def _hex_to_tw_name(hex_val):
    """Convert hex color to a Tailwind-friendly name."""
    h = hex_val.lstrip('#').lower()
    # Common names
    common = {
        "ffffff": "white", "000000": "black", "ff0000": "red",
        "00ff00": "green", "0000ff": "blue",
    }
    if h in common:
        return common[h]
    # For colors with alpha in hex (8 chars), use prefix
    if len(h) > 6:
        return f"c-{h[:6]}-{h[6:]}"
    return f"c-{h}"


# ─── Node → CSS ───────────────────────────────────────────────────────────

def build_styles(node, parent, collector, assets_dir):
    """Build a CSS property dict for a node."""
    styles = OrderedDict()
    ntype = node.get("type", "")
    bbox = node.get("absoluteBoundingBox", {})
    parent_bbox = parent.get("absoluteBoundingBox", {}) if parent else {}
    parent_has_layout = parent and parent.get("layoutMode")

    # ── Layout mode (FRAME / INSTANCE) ──
    if ntype in ("FRAME", "INSTANCE"):
        layout_mode = node.get("layoutMode")
        if layout_mode:
            styles["display"] = "flex"
            styles["flex-direction"] = "column" if layout_mode == "VERTICAL" else "row"

            primary = node.get("primaryAxisAlignItems", "MIN")
            counter = node.get("counterAxisAlignItems", "MIN")
            styles["justify-content"] = figma_align_to_css(primary)
            styles["align-items"] = figma_align_to_css(counter)

            pt = node.get("paddingTop", 0)
            pr = node.get("paddingRight", 0)
            pb = node.get("paddingBottom", 0)
            pl = node.get("paddingLeft", 0)
            if any([pt, pr, pb, pl]):
                styles["padding"] = f"{pt}px {pr}px {pb}px {pl}px"

            gap = node.get("itemSpacing", 0)
            if gap:
                styles["gap"] = f"{gap}px"
        else:
            # No auto-layout → use relative positioning
            styles["position"] = "relative"

    elif ntype == "RECTANGLE":
        pass  # Just a styled div

    # ── Sizing ──
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)

    if parent_has_layout:
        # Child of a flex parent
        layout_align = node.get("layoutAlign")
        layout_grow = node.get("layoutGrow", 0)

        if layout_align == "STRETCH":
            styles["align-self"] = "stretch"
        
        if layout_grow and layout_grow > 0:
            styles["flex"] = "1"

        # Determine sizing based on parent direction
        parent_dir = parent.get("layoutMode", "VERTICAL")
        h_sizing = node.get("layoutSizingHorizontal", "FIXED")
        v_sizing = node.get("layoutSizingVertical", "FIXED")

        if h_sizing == "FIXED" and w:
            styles["width"] = f"{w}px"
        elif h_sizing == "FILL":
            styles["align-self"] = "stretch"
            # In horizontal layout, FILL means flex:1
            if parent_dir == "HORIZONTAL":
                styles["flex"] = "1"
            else:
                styles["width"] = "100%"
        # HUG = auto, no width needed

        if v_sizing == "FIXED" and h:
            styles["height"] = f"{h}px"
        elif v_sizing == "FILL":
            if parent_dir == "VERTICAL":
                styles["flex"] = "1"
            else:
                styles["height"] = "100%"
    else:
        # Absolute positioning within non-layout parent
        if parent and ntype != "FRAME" or (parent and not parent.get("layoutMode") and parent.get("type") in ("FRAME", "INSTANCE")):
            if parent and not parent.get("layoutMode") and parent.get("type") in ("FRAME", "INSTANCE"):
                px = parent_bbox.get("x", 0)
                py = parent_bbox.get("y", 0)
                styles["position"] = "absolute"
                styles["left"] = f"{bbox.get('x', 0) - px}px"
                styles["top"] = f"{bbox.get('y', 0) - py}px"

        if w:
            styles["width"] = f"{w}px"
        if h:
            styles["height"] = f"{h}px"

    # ── Visual: Fills ──
    fills = [f for f in node.get("fills", []) if f.get("visible", True) is not False]
    if fills and ntype != "TEXT":
        fill = fills[0]
        if fill.get("type") == "SOLID" and fill.get("color"):
            color = fill["color"]
            opacity = fill.get("opacity", color.get("a", 1))
            hex_val = hex_from_figma(color)
            css_color = rgba_from_figma(color, alpha_override=opacity if opacity < 1 else None)
            collector.register_color(hex_val)
            # Skip transparent/nearly transparent backgrounds
            if opacity > 0.01:
                styles["background-color"] = css_color
        elif fill.get("type") == "IMAGE":
            img_file = asset_path_for_node(node.get("id", ""), assets_dir)
            if img_file:
                styles["background-image"] = f"url(assets/{img_file})"
                styles["background-size"] = "cover"
                styles["background-position"] = "center"
        elif "GRADIENT" in fill.get("type", ""):
            # Basic gradient support
            handle_points = fill.get("gradientHandlePositions", [])
            stops = fill.get("gradientStops", [])
            if stops:
                stop_strs = []
                for stop in stops:
                    c = stop.get("color", {})
                    pos = stop.get("position", 0)
                    stop_strs.append(f"{rgba_from_figma(c)} {round(pos * 100)}%")
                styles["background"] = f"linear-gradient(180deg, {', '.join(stop_strs)})"

    # ── Visual: Strokes ──
    strokes = [s for s in node.get("strokes", []) if s.get("visible", True) is not False]
    if strokes:
        stroke = strokes[0]
        weight = node.get("strokeWeight", 1)
        if stroke.get("type") == "SOLID" and stroke.get("color"):
            color_css = rgba_from_figma(stroke["color"])
            align = node.get("strokeAlign", "INSIDE")
            if align == "INSIDE":
                styles["border"] = f"{weight}px solid {color_css}"
            else:
                styles["border"] = f"{weight}px solid {color_css}"

    # ── Effects ──
    effects = [e for e in node.get("effects", []) if e.get("visible", True) is not False]
    shadows = []
    blurs = []
    for effect in effects:
        etype = effect.get("type", "")
        if etype in ("DROP_SHADOW", "INNER_SHADOW"):
            offset = effect.get("offset", {})
            x = offset.get("x", 0)
            y = offset.get("y", 0)
            radius = effect.get("radius", 0)
            spread = effect.get("spread", 0)
            color = effect.get("color", {"r": 0, "g": 0, "b": 0, "a": 0.25})
            inset = "inset " if etype == "INNER_SHADOW" else ""
            shadow_str = f"{inset}{x}px {y}px {radius}px {spread}px {rgba_from_figma(color)}"
            shadows.append(shadow_str)
        elif etype == "LAYER_BLUR":
            blurs.append(f"blur({effect.get('radius', 0)}px)")
        elif etype == "BACKGROUND_BLUR":
            styles["backdrop-filter"] = f"blur({effect.get('radius', 0)}px)"

    if shadows:
        styles["box-shadow"] = ", ".join(shadows)
    if blurs:
        styles["filter"] = " ".join(blurs)

    # ── Corner radius ──
    cr = node.get("cornerRadius")
    if cr and cr > 0:
        styles["border-radius"] = f"{cr}px"
    else:
        # Check individual corners
        tl = node.get("rectangleCornerRadii")
        if tl and any(r > 0 for r in tl):
            styles["border-radius"] = " ".join(f"{r}px" for r in tl)

    # ── Opacity ──
    opacity = node.get("opacity")
    if opacity is not None and opacity < 1:
        styles["opacity"] = str(round(opacity, 3))

    # ── Clip ──
    if node.get("clipsContent"):
        styles["overflow"] = "hidden"

    # ── TEXT-specific styles ──
    if ntype == "TEXT":
        style = node.get("style", {})
        font_family = style.get("fontFamily", "Inter")
        collector.register_font(font_family)

        styles["font-family"] = f"'{font_family}', sans-serif"
        
        font_size = style.get("fontSize", 16)
        styles["font-size"] = f"{font_size}px"
        
        font_weight = style.get("fontWeight", 400)
        if font_weight != 400:
            styles["font-weight"] = str(int(font_weight))

        line_height = style.get("lineHeightPx")
        if line_height:
            styles["line-height"] = f"{line_height}px"

        letter_spacing = style.get("letterSpacing", 0)
        if letter_spacing:
            styles["letter-spacing"] = f"{letter_spacing}px"

        text_align = style.get("textAlignHorizontal", "LEFT")
        align_map = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFIED": "justify"}
        ta = align_map.get(text_align, "left")
        if ta != "left":
            styles["text-align"] = ta

        # Text color from fills
        if fills:
            fill = fills[0]
            if fill.get("type") == "SOLID" and fill.get("color"):
                color = fill["color"]
                hex_val = hex_from_figma(color)
                collector.register_color(hex_val)
                styles["color"] = rgba_from_figma(color)

        # Text decoration
        text_dec = style.get("textDecoration")
        if text_dec == "UNDERLINE":
            styles["text-decoration"] = "underline"
        elif text_dec == "STRIKETHROUGH":
            styles["text-decoration"] = "line-through"

        # Text transform
        text_case = style.get("textCase")
        if text_case == "UPPER":
            styles["text-transform"] = "uppercase"
        elif text_case == "LOWER":
            styles["text-transform"] = "lowercase"

    return styles


# ─── Node → HTML ──────────────────────────────────────────────────────────

def text_tag(font_size):
    """Choose semantic HTML tag based on font size."""
    if font_size > 32:
        return "h1"
    elif font_size > 20:
        return "h2"
    elif font_size > 14:
        return "p"
    else:
        return "span"


def render_node(node, parent, collector, assets_dir, css_rules, depth=0):
    """Recursively render a Figma node to HTML string."""
    ntype = node.get("type", "")
    cls = sanitize_class(node)
    styles = build_styles(node, parent, collector, assets_dir)
    
    # Store CSS rule
    if styles:
        css_rules[f".{cls}"] = styles

    indent = "  " * depth

    if ntype == "TEXT":
        characters = node.get("characters", "")
        font_size = node.get("style", {}).get("fontSize", 16)
        tag = text_tag(font_size)
        # Escape HTML entities
        text = characters.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Preserve newlines
        text = text.replace("\n", "<br>\n")
        return f'{indent}<{tag} class="{cls}">{text}</{tag}>\n'

    elif ntype == "VECTOR":
        # Render as an empty div placeholder with dimensions
        return f'{indent}<div class="{cls}" aria-hidden="true"></div>\n'

    elif ntype == "RECTANGLE":
        # Check for image fill
        has_image = False
        for fill in node.get("fills", []):
            if fill.get("type") == "IMAGE":
                img_file = asset_path_for_node(node.get("id", ""), assets_dir)
                if img_file:
                    has_image = True
                    return f'{indent}<img class="{cls}" src="assets/{img_file}" alt="{node.get("name", "")}">\n'
        return f'{indent}<div class="{cls}"></div>\n'

    elif ntype in ("FRAME", "INSTANCE"):
        # Check if this is an image frame (has IMAGE fill and no meaningful children)
        for fill in node.get("fills", []):
            if fill.get("type") == "IMAGE":
                img_file = asset_path_for_node(node.get("id", ""), assets_dir)
                children = node.get("children", [])
                if img_file and not children:
                    return f'{indent}<img class="{cls}" src="assets/{img_file}" alt="{node.get("name", "")}">\n'

        children = node.get("children", [])
        if not children:
            return f'{indent}<div class="{cls}"></div>\n'

        html = f'{indent}<div class="{cls}">\n'
        for child in children:
            html += render_node(child, node, collector, assets_dir, css_rules, depth + 1)
        html += f'{indent}</div>\n'
        return html

    else:
        # Unknown type — render as div
        children = node.get("children", [])
        html = f'{indent}<div class="{cls}">\n'
        for child in children:
            html += render_node(child, node, collector, assets_dir, css_rules, depth + 1)
        html += f'{indent}</div>\n'
        return html


# ─── CSS Generation ───────────────────────────────────────────────────────

def generate_css(collector, css_rules):
    """Generate the complete CSS file content."""
    lines = []

    # CSS Reset
    lines.append("""/* Generated by figma-perfect generate.py */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

img {
  display: block;
  max-width: 100%;
  height: auto;
}
""")

    # Custom properties
    lines.append(collector.css_root())
    lines.append("")

    # All component rules
    for selector, props in css_rules.items():
        prop_lines = []
        for prop, val in props.items():
            prop_lines.append(f"  {prop}: {val};")
        lines.append(f"{selector} {{")
        lines.extend(prop_lines)
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


# ─── HTML Generation ──────────────────────────────────────────────────────

def collect_google_fonts(collector):
    """Build Google Fonts URL from collected font families."""
    families = list(collector.fonts.keys())
    if not families:
        return ""
    
    font_params = []
    for fam in families:
        # Common web-safe fonts don't need Google Fonts
        if fam.lower() in ("arial", "helvetica", "times new roman", "georgia", "verdana", "courier new"):
            continue
        safe_name = fam.replace(" ", "+")
        font_params.append(f"family={safe_name}:wght@300;400;500;600;700;800")
    
    if not font_params:
        return ""
    
    return f'  <link href="https://fonts.googleapis.com/css2?{"&".join(font_params)}&display=swap" rel="stylesheet">\n'


def generate_html(body_html, collector, title="Generated Page"):
    """Generate the complete HTML file."""
    fonts_link = collect_google_fonts(collector)
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="styles.css">
{fonts_link}  <title>{title}</title>
</head>
<body>
{body_html}</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════════════
# ─── React Framework Output ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def render_node_jsx(node, parent, collector, assets_dir, css_rules, depth=0, use_tailwind=False, color_map=None, responsive=False):
    """Recursively render a Figma node to JSX string (for React components)."""
    ntype = node.get("type", "")
    cls = sanitize_class(node)
    styles = build_styles(node, parent, collector, assets_dir)

    # Determine class attribute
    tw_classes_str = ""
    if responsive and styles:
        tw_classes, has_remaining = _apply_responsive(
            styles, node, css_rules, f".{cls}", use_tailwind, color_map
        )
        tw_classes_str = " ".join(tw_classes)
        if has_remaining:
            class_attr = f'{cls} {tw_classes_str}'.strip() if tw_classes_str else cls
        else:
            class_attr = tw_classes_str if tw_classes_str else cls
    elif use_tailwind and styles:
        tw_classes, remaining = css_to_tailwind_classes(styles, color_map)
        if remaining:
            css_rules[f".{cls}"] = remaining
        tw_classes_str = " ".join(tw_classes)
        if remaining:
            class_attr = f'{cls} {tw_classes_str}'.strip() if tw_classes_str else cls
        else:
            class_attr = tw_classes_str if tw_classes_str else cls
    else:
        if styles:
            css_rules[f".{cls}"] = styles
        class_attr = cls

    indent = "  " * depth

    if ntype == "TEXT":
        characters = node.get("characters", "")
        font_size = node.get("style", {}).get("fontSize", 16)
        tag = text_tag(font_size)
        # Edge case: escape special chars for JSX ({, }, <, >, &)
        text = escape_jsx_text(characters)
        # Preserve newlines with <br />
        text = text.replace("\n", "<br />\n")
        return f'{indent}<{tag} className="{class_attr}">{text}</{tag}>\n'

    elif ntype == "VECTOR":
        return f'{indent}<div className="{class_attr}" aria-hidden="true"></div>\n'

    elif ntype == "RECTANGLE":
        for fill in node.get("fills", []):
            if fill.get("type") == "IMAGE":
                img_file = asset_path_for_node(node.get("id", ""), assets_dir)
                if img_file:
                    return f'{indent}<img className="{class_attr}" src="assets/{img_file}" alt="{node.get("name", "")}" />\n'
        return f'{indent}<div className="{class_attr}"></div>\n'

    elif ntype in ("FRAME", "INSTANCE"):
        for fill in node.get("fills", []):
            if fill.get("type") == "IMAGE":
                img_file = asset_path_for_node(node.get("id", ""), assets_dir)
                children = node.get("children", [])
                if img_file and not children:
                    return f'{indent}<img className="{class_attr}" src="assets/{img_file}" alt="{node.get("name", "")}" />\n'

        children = node.get("children", [])
        if not children:
            return f'{indent}<div className="{class_attr}"></div>\n'

        jsx = f'{indent}<div className="{class_attr}">\n'
        for child in children:
            jsx += render_node_jsx(child, node, collector, assets_dir, css_rules, depth + 1, use_tailwind, color_map, responsive)
        jsx += f'{indent}</div>\n'
        return jsx

    else:
        children = node.get("children", [])
        jsx = f'{indent}<div className="{class_attr}">\n'
        for child in children:
            jsx += render_node_jsx(child, node, collector, assets_dir, css_rules, depth + 1, use_tailwind, color_map, responsive)
        jsx += f'{indent}</div>\n'
        return jsx


def render_node_tsx_module(node, parent, collector, assets_dir, css_rules, depth=0, use_tailwind=False, color_map=None, img_prefix="", responsive=False):
    """Recursively render a Figma node to TSX with CSS modules."""
    ntype = node.get("type", "")
    cls = sanitize_class(node)
    styles_dict = build_styles(node, parent, collector, assets_dir)

    # For CSS modules, the key is a camelCase version
    css_module_key = _to_camel(cls)

    tw_classes_str = ""
    if responsive and styles_dict:
        tw_classes, has_remaining = _apply_responsive(
            styles_dict, node, css_rules, f".{css_module_key}", use_tailwind, color_map
        )
        tw_classes_str = " ".join(tw_classes)
        parts = []
        if has_remaining:
            parts.append(f"styles.{css_module_key}")
        if tw_classes_str:
            parts.append(f'"{tw_classes_str}"')
        if len(parts) > 1:
            class_attr_expr = "{`${" + parts[0] + "} " + tw_classes_str + "`}"
        elif parts and parts[0].startswith("styles."):
            class_attr_expr = f"{{{parts[0]}}}"
        else:
            class_attr_expr = f'"{tw_classes_str}"' if tw_classes_str else f"{{styles.{css_module_key}}}"
    elif use_tailwind and styles_dict:
        tw_classes, remaining = css_to_tailwind_classes(styles_dict, color_map)
        tw_classes_str = " ".join(tw_classes)
        if remaining:
            css_rules[f".{css_module_key}"] = remaining
        # Build className
        parts = []
        if remaining:
            parts.append(f"styles.{css_module_key}")
        if tw_classes_str:
            parts.append(f'"{tw_classes_str}"')
        if len(parts) > 1:
            class_attr_expr = "{`${" + parts[0] + "} " + tw_classes_str + "`}"
        elif parts and parts[0].startswith("styles."):
            class_attr_expr = f"{{{parts[0]}}}"
        else:
            class_attr_expr = f'"{tw_classes_str}"' if tw_classes_str else f"{{styles.{css_module_key}}}"
    else:
        if styles_dict:
            css_rules[f".{css_module_key}"] = styles_dict
        class_attr_expr = f"{{styles.{css_module_key}}}"

    indent = "  " * depth

    if ntype == "TEXT":
        characters = node.get("characters", "")
        font_size = node.get("style", {}).get("fontSize", 16)
        tag = text_tag(font_size)
        # Edge case: escape special chars for JSX ({, }, <, >, &)
        text = escape_jsx_text(characters)
        text = text.replace("\n", "<br />\n")
        return f'{indent}<{tag} className={class_attr_expr}>{text}</{tag}>\n'

    elif ntype == "VECTOR":
        # Edge case: use explicit close tag instead of self-closing <div />
        return f'{indent}<div className={class_attr_expr} aria-hidden="true"></div>\n'

    elif ntype == "RECTANGLE":
        for fill in node.get("fills", []):
            if fill.get("type") == "IMAGE":
                img_file = asset_path_for_node(node.get("id", ""), assets_dir)
                if img_file:
                    return f'{indent}<img className={class_attr_expr} src="{img_prefix}{img_file}" alt="{node.get("name", "")}" />\n'
        # Edge case: use explicit close tag instead of self-closing <div />
        return f'{indent}<div className={class_attr_expr}></div>\n'

    elif ntype in ("FRAME", "INSTANCE"):
        for fill in node.get("fills", []):
            if fill.get("type") == "IMAGE":
                img_file = asset_path_for_node(node.get("id", ""), assets_dir)
                children = node.get("children", [])
                if img_file and not children:
                    return f'{indent}<img className={class_attr_expr} src="{img_prefix}{img_file}" alt="{node.get("name", "")}" />\n'

        children = node.get("children", [])
        if not children:
            # Edge case: use explicit close tag instead of self-closing <div />
            return f'{indent}<div className={class_attr_expr}></div>\n'

        tsx = f'{indent}<div className={class_attr_expr}>\n'
        for child in children:
            tsx += render_node_tsx_module(child, node, collector, assets_dir, css_rules, depth + 1, use_tailwind, color_map, img_prefix, responsive)
        tsx += f'{indent}</div>\n'
        return tsx

    else:
        children = node.get("children", [])
        tsx = f'{indent}<div className={class_attr_expr}>\n'
        for child in children:
            tsx += render_node_tsx_module(child, node, collector, assets_dir, css_rules, depth + 1, use_tailwind, color_map, img_prefix, responsive)
        tsx += f'{indent}</div>\n'
        return tsx


def _to_camel(kebab_str):
    """Convert fig-some-name-1-2 to figSomeName12."""
    parts = kebab_str.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def split_components(root, collector, assets_dir):
    """Split root's direct children into separate components.
    
    Returns list of dicts: {name, pascal, node, children_nodes}
    """
    children = root.get("children", [])
    components = []
    seen_names = set()

    for i, child in enumerate(children):
        name = child.get("name", f"Section{i}")
        pascal = to_pascal_case(name)
        # Deduplicate names
        base = pascal
        counter = 1
        while pascal in seen_names:
            counter += 1
            pascal = f"{base}{counter}"
        seen_names.add(pascal)

        # Check if component is too large and should be split further
        desc_count = count_descendants(child)
        if desc_count > 100 and child.get("children"):
            # Split this large component's children into sub-components
            sub_components = []
            sub_seen = set()
            for j, sub_child in enumerate(child.get("children", [])):
                sub_name = sub_child.get("name", f"Sub{j}")
                sub_pascal = to_pascal_case(sub_name)
                sub_base = sub_pascal
                sc = 1
                while sub_pascal in sub_seen or sub_pascal in seen_names:
                    sc += 1
                    sub_pascal = f"{sub_base}{sc}"
                sub_seen.add(sub_pascal)
                seen_names.add(sub_pascal)
                sub_components.append({
                    "name": sub_name,
                    "pascal": sub_pascal,
                    "node": sub_child,
                    "is_sub": True,
                    "parent_pascal": pascal,
                })
            # Add the parent as a wrapper that imports sub-components
            components.append({
                "name": name,
                "pascal": pascal,
                "node": child,
                "sub_components": sub_components,
            })
        else:
            components.append({
                "name": name,
                "pascal": pascal,
                "node": child,
            })

        # Also check INSTANCE children for extraction
        # (they stay inside their parent for now; full extraction would be complex)

    return components


def generate_react_output(root, collector, assets_dir, output_dir, use_tailwind=False, title="Generated App", responsive=False):
    """Generate React project output."""
    output_dir = Path(output_dir)
    comp_dir = output_dir / "components"
    comp_dir.mkdir(parents=True, exist_ok=True)

    color_map = collector.tailwind_color_map() if use_tailwind else None
    components = split_components(root, collector, assets_dir)

    # Generate each component
    for comp in components:
        pascal = comp["pascal"]
        node = comp["node"]
        sub_comps = comp.get("sub_components", [])

        if sub_comps:
            # This component has sub-components — render them first
            for sc in sub_comps:
                sc_css_rules = OrderedDict()
                sc_jsx = render_node_jsx(sc["node"], node, collector, assets_dir, sc_css_rules, depth=2, use_tailwind=use_tailwind, color_map=color_map, responsive=responsive)
                _write_react_component(comp_dir, sc["pascal"], sc_jsx, sc_css_rules, use_tailwind)

            # Wrapper component that imports sub-components
            wrapper_css_rules = OrderedDict()
            root_styles = build_styles(node, None, collector, assets_dir)
            cls = sanitize_class(node)
            if root_styles:
                if responsive:
                    tw_cls, _ = _apply_responsive(
                        root_styles, node, wrapper_css_rules, f".{cls}", use_tailwind, color_map
                    )
                    class_attr = f'{cls} {" ".join(tw_cls)}'.strip() if tw_cls else cls
                elif use_tailwind:
                    tw_cls, remaining = css_to_tailwind_classes(root_styles, color_map)
                    if remaining:
                        wrapper_css_rules[f".{cls}"] = remaining
                    class_attr = f'{cls} {" ".join(tw_cls)}'.strip() if tw_cls else cls
                else:
                    wrapper_css_rules[f".{cls}"] = root_styles
                    class_attr = cls
            else:
                class_attr = cls

            imports = "\n".join(f"import {sc['pascal']} from './{sc['pascal']}';" for sc in sub_comps)
            sub_renders = "\n".join(f"        <{sc['pascal']} />" for sc in sub_comps)
            wrapper_jsx = f"""import React from 'react';
import './{pascal}.css';
{imports}

export default function {pascal}() {{
  return (
    <section className="{class_attr}">
{sub_renders}
    </section>
  );
}}
"""
            with open(comp_dir / f"{pascal}.jsx", "w") as f:
                f.write(wrapper_jsx)
            _write_css_file(comp_dir / f"{pascal}.css", wrapper_css_rules)
        else:
            css_rules = OrderedDict()
            jsx_body = render_node_jsx(node, None, collector, assets_dir, css_rules, depth=3, use_tailwind=use_tailwind, color_map=color_map, responsive=responsive)

            # Wrap in component
            kebab = to_kebab_case(pascal)
            root_cls = sanitize_class(node)
            root_styles = css_rules.pop(f".{root_cls}", None)
            if root_styles:
                css_rules[f".{kebab}"] = root_styles
                if use_tailwind:
                    tw_cls, remaining = css_to_tailwind_classes(root_styles, color_map)
                    if remaining:
                        css_rules[f".{kebab}"] = remaining
                    else:
                        css_rules.pop(f".{kebab}", None)
                    class_attr = f'{kebab} {" ".join(tw_cls)}'.strip() if tw_cls else kebab
                else:
                    class_attr = kebab
            else:
                class_attr = kebab

            _write_react_component(comp_dir, pascal, jsx_body, css_rules, use_tailwind, class_attr)

    # Generate App.jsx
    comp_imports = "\n".join(f"import {c['pascal']} from './components/{c['pascal']}';" for c in components)
    comp_renders = "\n".join(f"      <{c['pascal']} />" for c in components)
    app_jsx = f"""import React from 'react';
import './index.css';
{comp_imports}

export default function App() {{
  return (
    <div className="app">
{comp_renders}
    </div>
  );
}}
"""
    with open(output_dir / "App.jsx", "w") as f:
        f.write(app_jsx)

    # Generate index.css (global styles)
    global_css = _generate_global_css(collector)
    with open(output_dir / "index.css", "w") as f:
        f.write(global_css)

    # Generate package.json
    pkg = {
        "name": _slugify(title),
        "version": "0.1.0",
        "private": True,
        "dependencies": {
            "react": "^18.3.1",
            "react-dom": "^18.3.1",
            "react-scripts": "5.0.1"
        },
        "scripts": {
            "start": "react-scripts start",
            "build": "react-scripts build"
        },
        "browserslist": {
            "production": [">0.2%", "not dead", "not op_mini all"],
            "development": ["last 1 chrome version"]
        }
    }
    with open(output_dir / "package.json", "w") as f:
        json.dump(pkg, f, indent=2)

    return components


def _write_react_component(comp_dir, pascal, jsx_body, css_rules, use_tailwind, class_attr=None):
    """Write a single React component file + CSS."""
    kebab = to_kebab_case(pascal)
    if class_attr is None:
        class_attr = kebab

    component_code = f"""import React from 'react';
import './{pascal}.css';

export default function {pascal}() {{
  return (
    <section className="{class_attr}">
{jsx_body}    </section>
  );
}}
"""
    with open(comp_dir / f"{pascal}.jsx", "w") as f:
        f.write(component_code)

    _write_css_file(comp_dir / f"{pascal}.css", css_rules)


def _write_css_file(path, css_rules):
    """Write CSS rules to file, with responsive media queries if present."""
    normal, tablet, desktop = _split_responsive_rules(css_rules)
    lines = [f"/* Generated by figma-perfect */\n"]
    for selector, props in normal.items():
        prop_lines = [f"  {p}: {v};" for p, v in props.items()]
        lines.append(f"{selector} {{")
        lines.extend(prop_lines)
        lines.append("}\n")
    if tablet:
        lines.append(f"@media (min-width: {BREAKPOINT_TABLET}px) {{")
        for selector, props in tablet.items():
            prop_lines = [f"    {p}: {v};" for p, v in props.items()]
            lines.append(f"  {selector} {{")
            lines.extend(prop_lines)
            lines.append("  }")
        lines.append("}\n")
    if desktop:
        lines.append(f"@media (min-width: {BREAKPOINT_DESKTOP}px) {{")
        for selector, props in desktop.items():
            prop_lines = [f"    {p}: {v};" for p, v in props.items()]
            lines.append(f"  {selector} {{")
            lines.extend(prop_lines)
            lines.append("  }")
        lines.append("}\n")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def _generate_global_css(collector):
    """Generate global CSS with reset and custom properties."""
    return f"""/* Generated by figma-perfect generate.py */
* {{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}}

body {{
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

img {{
  display: block;
  max-width: 100%;
  height: auto;
}}

{collector.css_root()}
"""


def _slugify(title):
    """Convert title to package-name-friendly slug."""
    return re.sub(r'[^a-z0-9-]', '-', title.lower()).strip('-')[:50]


# ═══════════════════════════════════════════════════════════════════════════
# ─── Next.js Framework Output ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def _write_nextjs_config_files(output_dir, app_dir, collector, use_tailwind, title):
    """Write shared Next.js config: globals.css, tailwind, package.json, tsconfig, etc."""
    output_dir = Path(output_dir)
    app_dir = Path(app_dir)
    
    # globals.css
    if use_tailwind:
        globals_css = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n* { margin: 0; padding: 0; box-sizing: border-box; }\nbody { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }\nimg { display: block; max-width: 100%; height: auto; }\n"
    else:
        globals_css = _generate_global_css(collector)
    with open(app_dir / "globals.css", "w") as f:
        f.write(globals_css)

    # tailwind.config.ts
    if use_tailwind:
        tw_colors = collector.tailwind_config_colors()
        tw_fonts = collector.tailwind_config_fonts()
        color_entries = ",\n".join(f"        '{k}': '{v}'" for k, v in tw_colors.items())
        font_entries = ",\n".join(f"        '{k}': {json.dumps(v)}" for k, v in tw_fonts.items())
        tw_config = f'import type {{ Config }} from "tailwindcss";\n\nconst config: Config = {{\n  content: ["./app/**/*.{{ts,tsx}}", "./components/**/*.{{ts,tsx}}"],\n  theme: {{\n    extend: {{\n      colors: {{\n{color_entries}\n      }},\n      fontFamily: {{\n{font_entries}\n      }},\n    }},\n  }},\n  plugins: [],\n}};\nexport default config;\n'
        with open(output_dir / "tailwind.config.ts", "w") as f:
            f.write(tw_config)

    # package.json
    deps = {"next": "^14.2.0", "react": "^18.3.1", "react-dom": "^18.3.1"}
    dev_deps = {"@types/node": "^20.14.0", "@types/react": "^18.3.3", "@types/react-dom": "^18.3.0", "typescript": "^5.5.0"}
    if use_tailwind:
        dev_deps.update({"tailwindcss": "^3.4.0", "postcss": "^8.4.38", "autoprefixer": "^10.4.19"})
    pkg = {"name": _slugify(title), "version": "0.1.0", "private": True,
           "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
           "dependencies": deps, "devDependencies": dev_deps}
    with open(output_dir / "package.json", "w") as f:
        json.dump(pkg, f, indent=2)

    # tsconfig.json
    tsconfig = {"compilerOptions": {"lib": ["dom", "dom.iterable", "esnext"], "allowJs": True,
        "skipLibCheck": True, "strict": True, "noEmit": True, "esModuleInterop": True,
        "module": "esnext", "moduleResolution": "bundler", "resolveJsonModule": True,
        "isolatedModules": True, "jsx": "preserve", "incremental": True,
        "plugins": [{"name": "next"}], "paths": {"@/*": ["./*"]}},
        "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
        "exclude": ["node_modules"]}
    with open(output_dir / "tsconfig.json", "w") as f:
        json.dump(tsconfig, f, indent=2)

    # postcss + next config
    if use_tailwind:
        with open(output_dir / "postcss.config.js", "w") as f:
            f.write("module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };\n")
    with open(output_dir / "next.config.js", "w") as f:
        f.write('/** @type {import(\'next\').NextConfig} */\nconst nextConfig = {};\nmodule.exports = nextConfig;\n')


def generate_nextjs_output(root, collector, assets_dir, output_dir, use_tailwind=False, title="Generated App", responsive=False):
    """Generate Next.js App Router project."""
    output_dir = Path(output_dir)
    app_dir = output_dir / "app"
    comp_dir = output_dir / "components"
    public_dir = output_dir / "public" / "assets"

    app_dir.mkdir(parents=True, exist_ok=True)
    comp_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    color_map = collector.tailwind_color_map() if use_tailwind else None
    components = split_components(root, collector, assets_dir)

    # Generate each component in its own directory
    for comp in components:
        pascal = comp["pascal"]
        node = comp["node"]
        sub_comps = comp.get("sub_components", [])
        c_dir = comp_dir / pascal
        c_dir.mkdir(parents=True, exist_ok=True)

        if sub_comps:
            # Generate sub-components
            for sc in sub_comps:
                sc_dir = comp_dir / sc["pascal"]
                sc_dir.mkdir(parents=True, exist_ok=True)
                sc_css_rules = OrderedDict()
                sc_tsx = render_node_tsx_module(sc["node"], node, collector, assets_dir, sc_css_rules, depth=2, use_tailwind=use_tailwind, color_map=color_map, img_prefix="/assets/", responsive=responsive)
                _write_nextjs_component(sc_dir, sc["pascal"], sc_tsx, sc_css_rules, use_tailwind)

            # Wrapper
            wrapper_css_rules = OrderedDict()
            root_styles = build_styles(node, None, collector, assets_dir)
            css_module_key = _to_camel(sanitize_class(node))
            if root_styles:
                if responsive:
                    tw_cls, has_rem = _apply_responsive(
                        root_styles, node, wrapper_css_rules, f".{css_module_key}", use_tailwind, color_map
                    )
                    parts = []
                    if has_rem:
                        parts.append(f"styles.{css_module_key}")
                    if tw_cls:
                        parts.append(f'"{" ".join(tw_cls)}"')
                    if len(parts) > 1:
                        class_expr = "{`${" + parts[0] + "} " + " ".join(tw_cls) + "`}"
                    elif parts and parts[0].startswith("styles."):
                        class_expr = f"{{{parts[0]}}}"
                    else:
                        class_expr = f'"{" ".join(tw_cls)}"' if tw_cls else f"{{styles.{css_module_key}}}"
                elif use_tailwind:
                    tw_cls, remaining = css_to_tailwind_classes(root_styles, color_map)
                    if remaining:
                        wrapper_css_rules[f".{css_module_key}"] = remaining
                    # Build className expression
                    parts = []
                    if remaining:
                        parts.append(f"styles.{css_module_key}")
                    if tw_cls:
                        parts.append(f'"{" ".join(tw_cls)}"')
                    if len(parts) > 1:
                        class_expr = "{`${" + parts[0] + "} " + " ".join(tw_cls) + "`}"
                    elif parts and parts[0].startswith("styles."):
                        class_expr = f"{{{parts[0]}}}"
                    else:
                        class_expr = f'"{" ".join(tw_cls)}"'
                else:
                    wrapper_css_rules[f".{css_module_key}"] = root_styles
                    class_expr = f"{{styles.{css_module_key}}}"
            else:
                class_expr = f"{{styles.wrapper}}"

            imports = "\n".join(f"import {sc['pascal']} from '../{sc['pascal']}';" for sc in sub_comps)
            sub_renders = "\n".join(f"        <{sc['pascal']} />" for sc in sub_comps)
            wrapper_tsx = f"""import styles from './styles.module.css';
{imports}

export default function {pascal}() {{
  return (
    <section className={class_expr}>
{sub_renders}
    </section>
  );
}}
"""
            with open(c_dir / "index.tsx", "w") as f:
                f.write(wrapper_tsx)
            # Edge case: pass nextjs=True so url(assets/...) becomes url(/assets/...)
            _write_css_module(c_dir / "styles.module.css", wrapper_css_rules, nextjs=True)
        else:
            css_rules = OrderedDict()
            tsx_body = render_node_tsx_module(node, None, collector, assets_dir, css_rules, depth=3, use_tailwind=use_tailwind, color_map=color_map, img_prefix="/assets/", responsive=responsive)
            _write_nextjs_component(c_dir, pascal, tsx_body, css_rules, use_tailwind)

    # Generate app/layout.tsx
    font_families = list(collector.fonts.keys())
    google_fonts = [f for f in font_families if f.lower() not in ("arial", "helvetica", "times new roman", "georgia", "verdana", "courier new", "segoe ui")]

    font_imports = ""
    font_vars = ""
    font_class_names = ""
    if google_fonts:
        font_import_lines = []
        font_var_lines = []
        font_cn_parts = []
        for gf in google_fonts:
            var_name = gf.lower().replace(" ", "_")
            font_import_lines.append(f"import {{ {gf.replace(' ', '_')} }} from 'next/font/google';")
            font_var_lines.append(f"const {var_name} = {gf.replace(' ', '_')}({{ subsets: ['latin'], weight: ['300', '400', '500', '600', '700', '800'] }});")
            font_cn_parts.append(f"${{{var_name}.className}}")
        font_imports = "\n".join(font_import_lines)
        font_vars = "\n".join(font_var_lines)
        font_class_names = " ".join(font_cn_parts)

    layout_tsx = f"""import type {{ Metadata }} from 'next';
import './globals.css';
{font_imports}

{font_vars}

export const metadata: Metadata = {{
  title: '{title}',
  description: 'Generated by figma-perfect',
}};

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode;
}}) {{
  return (
    <html lang="en">
      <body className={{`{font_class_names}`}}>
        {{children}}
      </body>
    </html>
  );
}}
"""
    with open(app_dir / "layout.tsx", "w") as f:
        f.write(layout_tsx)

    # Generate app/page.tsx
    page_imports = "\n".join(f"import {c['pascal']} from '../components/{c['pascal']}';" for c in components)
    page_renders = "\n".join(f"      <{c['pascal']} />" for c in components)
    page_tsx = f"""{page_imports}

export default function Home() {{
  return (
    <main>
{page_renders}
    </main>
  );
}}
"""
    with open(app_dir / "page.tsx", "w") as f:
        f.write(page_tsx)

    # Write shared config files
    _write_nextjs_config_files(output_dir, app_dir, collector, use_tailwind, title)

    return components


def _write_nextjs_component(c_dir, pascal, tsx_body, css_rules, use_tailwind):
    """Write a Next.js component (index.tsx + styles.module.css)."""
    css_module_key = to_kebab_case(pascal)

    has_styles = bool(css_rules)
    import_line = "import styles from './styles.module.css';" if has_styles else ""

    # Edge case: always wrap in single <div> to avoid multi-root JSX errors
    # Re-indent tsx_body lines to sit cleanly inside the wrapper
    body_lines = tsx_body.rstrip('\n').split('\n')
    indented_lines = []
    for line in body_lines:
        if line.strip():  # non-empty lines get proper indentation
            indented_lines.append('      ' + line.lstrip())
        else:
            indented_lines.append('')
    indented_body = '\n'.join(indented_lines)
    component_code = f"""{import_line}

export default function {pascal}() {{
  return (
    <div>
{indented_body}
    </div>
  );
}}
"""
    with open(c_dir / "index.tsx", "w") as f:
        f.write(component_code)

    # Edge case: pass nextjs=True so url(assets/...) becomes url(/assets/...)
    _write_css_module(c_dir / "styles.module.css", css_rules, nextjs=True)


def _split_responsive_rules(css_rules):
    """Split css_rules into (normal, tablet, desktop) OrderedDicts.
    Keys prefixed with '@tablet ' or '@desktop ' are extracted."""
    normal = OrderedDict()
    tablet = OrderedDict()
    desktop = OrderedDict()
    for key, props in css_rules.items():
        if key.startswith("@tablet "):
            tablet[key[8:]] = props
        elif key.startswith("@desktop "):
            desktop[key[9:]] = props
        else:
            normal[key] = props
    return normal, tablet, desktop


def _write_css_module(path, css_rules, nextjs=False):
    """Write CSS module rules to file, with responsive media queries if present."""
    normal, tablet, desktop = _split_responsive_rules(css_rules)

    def _fix_props(props):
        fixed = {}
        for p, v in props.items():
            if nextjs and "url(assets/" in str(v):
                v = v.replace("url(assets/", "url(/assets/")
            fixed[p] = v
        return fixed

    lines = ["/* Generated by figma-perfect */\n"]
    for selector, props in normal.items():
        fp = _fix_props(props)
        prop_lines = [f"  {p}: {v};" for p, v in fp.items()]
        lines.append(f"{selector} {{")
        lines.extend(prop_lines)
        lines.append("}\n")
    if tablet:
        lines.append(f"@media (min-width: {BREAKPOINT_TABLET}px) {{")
        for selector, props in tablet.items():
            fp = _fix_props(props)
            prop_lines = [f"    {p}: {v};" for p, v in fp.items()]
            lines.append(f"  {selector} {{")
            lines.extend(prop_lines)
            lines.append("  }")
        lines.append("}\n")
    if desktop:
        lines.append(f"@media (min-width: {BREAKPOINT_DESKTOP}px) {{")
        for selector, props in desktop.items():
            fp = _fix_props(props)
            prop_lines = [f"    {p}: {v};" for p, v in fp.items()]
            lines.append(f"  {selector} {{")
            lines.extend(prop_lines)
            lines.append("  }")
        lines.append("}\n")
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# ─── Smart Analysis: Two-Pass Architecture ───────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def structure_hash(node):
    """Compute a structural fingerprint ignoring text content and images."""
    t = node.get('type', 'UNKNOWN')
    children = node.get('children', [])
    if not children:
        return t
    child_hashes = [structure_hash(c) for c in children]
    return f"{t}[{','.join(child_hashes)}]"


def _collect_all_nodes(node, parent=None, depth=0, result=None):
    """Flatten tree into list of (node, parent, depth) tuples."""
    if result is None:
        result = []
    result.append((node, parent, depth))
    for child in node.get('children', []):
        _collect_all_nodes(child, node, depth + 1, result)
    return result


def _derive_component_name(nodes):
    """Derive a component name from a group of similar nodes."""
    # Try parent names first, then node names
    names = [n.get('name', '') for n in nodes]
    # Find common meaningful name
    for name in names:
        if name and not name.startswith('Frame') and not re.match(r'^Frame \d+', name):
            return to_pascal_case(name)
    # Try first non-generic name
    for name in names:
        if name:
            return to_pascal_case(name)
    return "SharedComponent"


def _extract_texts_ordered(node):
    """DFS collect all TEXT node characters in order."""
    texts = []
    if node.get('type') == 'TEXT':
        texts.append(node.get('characters', ''))
    for child in node.get('children', []):
        texts.extend(_extract_texts_ordered(child))
    return texts


def _extract_images_ordered(node):
    """DFS collect all nodes with IMAGE fills, returning node IDs."""
    images = []
    fills = node.get('fills', [])
    for f in fills:
        if f.get('type') == 'IMAGE':
            images.append(node.get('id', ''))
            break
    for child in node.get('children', []):
        images.extend(_extract_images_ordered(child))
    return images


def _extract_variable_data(nodes):
    """For a group of structurally identical nodes, find what varies.
    
    Returns:
        - prop_names: list of prop names (e.g. ['title', 'description', 'image'])
        - instances_data: list of dicts, one per node, with prop values
        - prop_types: dict of prop_name -> 'string' | 'image'
    """
    if len(nodes) < 2:
        return [], [], {}
    
    # Collect texts and images from each instance
    all_texts = [_extract_texts_ordered(n) for n in nodes]
    all_images = [_extract_images_ordered(n) for n in nodes]
    
    # Find which text positions vary
    text_count = min(len(t) for t in all_texts) if all_texts else 0
    variable_text_indices = []
    for i in range(text_count):
        values = set(all_texts[j][i] for j in range(len(nodes)) if i < len(all_texts[j]))
        if len(values) > 1:
            variable_text_indices.append(i)
    
    # Find which image positions vary
    img_count = min(len(im) for im in all_images) if all_images else 0
    variable_img_indices = []
    for i in range(img_count):
        values = set(all_images[j][i] for j in range(len(nodes)) if i < len(all_images[j]))
        if len(values) > 1:
            variable_img_indices.append(i)
    
    # Generate prop names
    prop_names = []
    prop_types = {}
    text_prop_names = []
    
    # Name text props based on content hints
    for idx, ti in enumerate(variable_text_indices):
        # Try to derive a name from the TEXT node's parent name
        sample_text = all_texts[0][ti] if all_texts[0] else ''
        if idx == 0:
            name = 'title'
        elif idx == 1:
            name = 'description'
        elif idx == 2:
            name = 'subtitle'
        else:
            name = f'text{idx + 1}'
        text_prop_names.append(name)
        prop_names.append(name)
        prop_types[name] = 'string'
    
    img_prop_names = []
    for idx, ii in enumerate(variable_img_indices):
        name = 'image' if idx == 0 else f'image{idx + 1}'
        img_prop_names.append(name)
        prop_names.append(name)
        prop_types[name] = 'image'
    
    # Build instance data
    instances_data = []
    for ni, node in enumerate(nodes):
        data = {}
        texts = all_texts[ni] if ni < len(all_texts) else []
        images = all_images[ni] if ni < len(all_images) else []
        
        for pi, ti in enumerate(variable_text_indices):
            if ti < len(texts):
                data[text_prop_names[pi]] = texts[ti]
            else:
                data[text_prop_names[pi]] = ''
        
        for pi, ii in enumerate(variable_img_indices):
            if ii < len(images):
                node_id = images[ii]
                sanitized = node_id.replace(':', '-').replace(';', '-')
                data[img_prop_names[pi]] = f'/assets/{sanitized}.png'
            else:
                data[img_prop_names[pi]] = ''
        
        instances_data.append(data)
    
    return prop_names, instances_data, prop_types


def analyze_tree(root_node):
    """Two-pass analysis: scan entire tree, find repeated patterns and instances.
    
    Returns dict with:
        - repeated_patterns: groups of nodes with identical structure hash (2+ nodes)
        - component_instances: groups of INSTANCE nodes sharing componentId
        - section_boundaries: top-level children names
    """
    result = {
        'repeated_patterns': {},
        'component_instances': {},
        'section_boundaries': [],
    }
    
    # Section boundaries = top-level children
    for child in root_node.get('children', []):
        result['section_boundaries'].append({
            'name': child.get('name', ''),
            'pascal': to_pascal_case(child.get('name', 'Section')),
            'nodeId': child.get('id', ''),
        })
    
    # Collect all nodes with their hashes
    all_nodes = _collect_all_nodes(root_node)
    
    # Group by structure hash (only non-leaf nodes with children)
    hash_groups = {}  # hash -> list of nodes
    for node, parent, depth in all_nodes:
        children = node.get('children', [])
        if not children:
            continue
        # Only consider nodes with at least 2 children (complex enough to be a component)
        if len(children) < 2:
            continue
        h = structure_hash(node)
        # Skip very simple hashes
        if h.count('[') < 1:
            continue
        if h not in hash_groups:
            hash_groups[h] = []
        hash_groups[h].append(node)
    
    # Filter: keep groups with 3+ instances (real repeated patterns)
    for h, nodes in hash_groups.items():
        if len(nodes) < 3:
            continue
        # Avoid overly large patterns (entire sections matching)
        if len(h) > 200:
            continue
        
        component_name = _derive_component_name(nodes)
        prop_names, instances_data, prop_types = _extract_variable_data(nodes)
        
        # Only keep if there's actual variable data
        if not prop_names:
            continue
        
        result['repeated_patterns'][h] = {
            'count': len(nodes),
            'component_name': component_name,
            'prop_names': prop_names,
            'prop_types': prop_types,
            'instances': [
                {'nodeId': n.get('id', ''), 'data': instances_data[i]}
                for i, n in enumerate(nodes)
            ],
            'template_node': nodes[0],
            'node_ids': set(n.get('id', '') for n in nodes),
        }
    
    # Collect INSTANCE nodes grouped by componentId
    instance_groups = {}  # componentId -> list of nodes
    for node, parent, depth in all_nodes:
        if node.get('type') == 'INSTANCE' and node.get('componentId'):
            cid = node['componentId']
            if cid not in instance_groups:
                instance_groups[cid] = []
            instance_groups[cid].append(node)
    
    for cid, nodes in instance_groups.items():
        if len(nodes) < 2:
            continue
        component_name = _derive_component_name(nodes)
        prop_names, instances_data, prop_types = _extract_variable_data(nodes)
        
        result['component_instances'][cid] = {
            'count': len(nodes),
            'component_name': component_name,
            'prop_names': prop_names,
            'prop_types': prop_types,
            'instances': [
                {'nodeId': n.get('id', ''), 'data': instances_data[i] if i < len(instances_data) else {}}
                for i, n in enumerate(nodes)
            ],
            'template_node': nodes[0],
            'node_ids': set(n.get('id', '') for n in nodes),
        }
    
    return result


# ─── Smart Generation (Next.js with shared components) ────────────────────

def _generate_shared_component_tsx(comp_name, prop_names, prop_types, template_node, collector, assets_dir, use_tailwind, color_map):
    """Generate a shared component TSX from a template node."""
    # Build interface
    interface_lines = []
    for pname in prop_names:
        interface_lines.append(f"  {pname}: string;")
    
    interface_str = f"interface {comp_name}Props {{\n" + "\n".join(interface_lines) + "\n}"
    
    # Generate the component body from template node, replacing variable data with props
    css_rules = OrderedDict()
    body = _smart_render(template_node, None, collector, assets_dir, css_rules, 
                         depth=2, use_tailwind=use_tailwind, color_map=color_map,
                         mode='template', prop_names=prop_names, prop_types=prop_types,
                         text_index=[0], img_index=[0])
    
    # Build component file
    props_destructure = ", ".join(prop_names)
    
    tsx = f"""{interface_str}

export function {comp_name}({{ {props_destructure} }}: {comp_name}Props) {{
  return (
{body}  );
}}
"""
    return tsx, css_rules


def _smart_render(node, parent, collector, assets_dir, css_rules, depth=0,
                  use_tailwind=False, color_map=None, mode='section',
                  prop_names=None, prop_types=None, text_index=None, img_index=None,
                  analysis=None, used_patterns=None):
    """Unified smart renderer. mode='template' replaces variable data with props;
    mode='section' replaces repeated nodes with component references."""
    ntype = node.get('type', '')
    node_id = node.get('id', '')
    cls = sanitize_class(node)
    indent = "    " * depth
    is_template = (mode == 'template')

    # Section mode: check if node is a repeated pattern instance
    if mode == 'section' and used_patterns and analysis:
        for h, pat in analysis['repeated_patterns'].items():
            if node_id in pat['node_ids']:
                for inst in pat['instances']:
                    if inst['nodeId'] == node_id:
                        ps = " ".join(f'{k}="{v}"' for k, v in inst['data'].items())
                        return f'{indent}<{pat["component_name"]} {ps} />\n'
                break
        for cid, pat in analysis['component_instances'].items():
            if node_id in pat['node_ids']:
                for inst in pat['instances']:
                    if inst['nodeId'] == node_id:
                        ps = " ".join(f'{k}="{v}"' for k, v in inst['data'].items())
                        if ps:
                            return f'{indent}<{pat["component_name"]} {ps} />\n'
                        break
                break

    # Build class attribute
    styles = build_styles(node, parent, collector, assets_dir)
    if use_tailwind and styles:
        tw_classes, remaining = css_to_tailwind_classes(styles, color_map)
        if remaining:
            css_rules[f".{cls}"] = remaining
        tw_str = " ".join(tw_classes)
        class_attr = f"{cls} {tw_str}".strip() if remaining else tw_str
    else:
        if styles:
            css_rules[f".{cls}"] = styles
        class_attr = cls

    # Helper for image prop substitution in template mode
    def _try_img_prop():
        if is_template and img_index is not None:
            img_props = [p for p in prop_names if prop_types.get(p) == 'image']
            ii = img_index[0]
            img_index[0] += 1
            if ii < len(img_props):
                return f'{indent}<img className="{class_attr}" src={{{img_props[ii]}}} alt="" />\n'
        return None

    if ntype == 'TEXT':
        characters = node.get('characters', '')
        font_size = node.get('style', {}).get('fontSize', 16)
        tag = text_tag(font_size)
        if is_template and text_index is not None:
            ti = text_index[0]
            text_index[0] += 1
            text_props = [p for p in prop_names if prop_types.get(p) == 'string']
            if ti < len(text_props):
                return f'{indent}<{tag} className="{class_attr}">{{{text_props[ti]}}}</{tag}>\n'
        return f'{indent}<{tag} className="{class_attr}">{escape_jsx_text(characters)}</{tag}>\n'

    elif ntype == 'VECTOR':
        return f'{indent}<div className="{class_attr}" aria-hidden="true"></div>\n'

    elif ntype == 'RECTANGLE':
        for fill in node.get('fills', []):
            if fill.get('type') == 'IMAGE':
                r = _try_img_prop()
                if r: return r
                img_file = asset_path_for_node(node_id, assets_dir)
                if img_file:
                    return f'{indent}<img className="{class_attr}" src="/assets/{img_file}" alt="{node.get("name", "")}" />\n'
        return f'{indent}<div className="{class_attr}"></div>\n'

    elif ntype in ('FRAME', 'INSTANCE'):
        for fill in node.get('fills', []):
            if fill.get('type') == 'IMAGE':
                children = node.get('children', [])
                if not children:
                    r = _try_img_prop()
                    if r: return r
                    img_file = asset_path_for_node(node_id, assets_dir)
                    if img_file:
                        return f'{indent}<img className="{class_attr}" src="/assets/{img_file}" alt="{node.get("name", "")}" />\n'
        children = node.get('children', [])
        if not children:
            return f'{indent}<div className="{class_attr}"></div>\n'
        jsx = f'{indent}<div className="{class_attr}">\n'
        for child in children:
            jsx += _smart_render(child, node, collector, assets_dir, css_rules, depth + 1,
                                 use_tailwind, color_map, mode, prop_names, prop_types,
                                 text_index, img_index, analysis, used_patterns)
        jsx += f'{indent}</div>\n'
        return jsx

    else:
        children = node.get('children', [])
        jsx = f'{indent}<div className="{class_attr}">\n'
        for child in children:
            jsx += _smart_render(child, node, collector, assets_dir, css_rules, depth + 1,
                                 use_tailwind, color_map, mode, prop_names, prop_types,
                                 text_index, img_index, analysis, used_patterns)
        jsx += f'{indent}</div>\n'
        return jsx


def generate_smart_nextjs(root, collector, assets_dir, output_dir, use_tailwind=False, title="Generated App", responsive=False):
    """Generate Next.js output with smart component deduplication."""
    output_dir = Path(output_dir)
    app_dir = output_dir / "app"
    comp_dir = output_dir / "components"
    shared_dir = comp_dir / "shared"
    sections_dir = comp_dir / "sections"
    data_dir = output_dir / "data"
    public_dir = output_dir / "public" / "assets"
    
    for d in [app_dir, shared_dir, sections_dir, data_dir, public_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    color_map = collector.tailwind_color_map() if use_tailwind else None
    
    # ─── Pass 1: Analyze ───
    analysis = analyze_tree(root)
    
    # ─── Pass 2: Generate shared components ───
    shared_components = []  # list of {name, file_path, data_file}
    used_patterns = set()  # track which patterns we generated components for
    
    # Generate from repeated patterns
    for h, pattern in analysis['repeated_patterns'].items():
        comp_name = pattern['component_name']
        # Deduplicate component names
        base_name = comp_name
        counter = 1
        existing_names = [sc['name'] for sc in shared_components]
        while comp_name in existing_names:
            counter += 1
            comp_name = f"{base_name}{counter}"
        pattern['component_name'] = comp_name
        
        tsx_content, comp_css = _generate_shared_component_tsx(
            comp_name, pattern['prop_names'], pattern['prop_types'],
            pattern['template_node'], collector, assets_dir, use_tailwind, color_map
        )
        
        # Write component file
        comp_file = shared_dir / f"{comp_name}.tsx"
        with open(comp_file, 'w') as f:
            f.write(tsx_content)
        
        # Write CSS if any
        if comp_css:
            css_file = shared_dir / f"{comp_name}.module.css"
            _write_css_module(css_file, comp_css, nextjs=True)
        
        # Generate data file
        data_var_name = to_kebab_case(comp_name).replace('-', '_') + 's'
        data_content = _generate_data_file(data_var_name, pattern['prop_names'], 
                                           pattern['prop_types'],
                                           [inst['data'] for inst in pattern['instances']])
        data_file = data_dir / f"{to_kebab_case(comp_name)}s.ts"
        with open(data_file, 'w') as f:
            f.write(data_content)
        
        shared_components.append({
            'name': comp_name,
            'data_var': data_var_name,
            'data_file': f"@/data/{to_kebab_case(comp_name)}s",
            'pattern_hash': h,
        })
        used_patterns.add(h)
    
    # Generate from component instances
    for cid, pattern in analysis['component_instances'].items():
        if not pattern['prop_names']:
            continue
        comp_name = pattern['component_name']
        base_name = comp_name
        counter = 1
        existing_names = [sc['name'] for sc in shared_components]
        while comp_name in existing_names:
            counter += 1
            comp_name = f"{base_name}{counter}"
        pattern['component_name'] = comp_name
        
        tsx_content, comp_css = _generate_shared_component_tsx(
            comp_name, pattern['prop_names'], pattern['prop_types'],
            pattern['template_node'], collector, assets_dir, use_tailwind, color_map
        )
        
        comp_file = shared_dir / f"{comp_name}.tsx"
        with open(comp_file, 'w') as f:
            f.write(tsx_content)
        
        if comp_css:
            css_file = shared_dir / f"{comp_name}.module.css"
            _write_css_module(css_file, comp_css, nextjs=True)
        
        data_var_name = to_kebab_case(comp_name).replace('-', '_') + 's'
        data_content = _generate_data_file(data_var_name, pattern['prop_names'],
                                           pattern['prop_types'],
                                           [inst['data'] for inst in pattern['instances']])
        data_file = data_dir / f"{to_kebab_case(comp_name)}s.ts"
        with open(data_file, 'w') as f:
            f.write(data_content)
        
        shared_components.append({
            'name': comp_name,
            'data_var': data_var_name,
            'data_file': f"@/data/{to_kebab_case(comp_name)}s",
            'pattern_hash': None,
            'component_id': cid,
        })
    
    # ─── Generate section components ───
    section_components = []
    seen_names = set()
    for child in root.get('children', []):
        name = child.get('name', 'Section')
        pascal = to_pascal_case(name)
        base = pascal
        counter = 1
        while pascal in seen_names:
            counter += 1
            pascal = f"{base}{counter}"
        seen_names.add(pascal)
        
        css_rules = OrderedDict()
        section_body = _smart_render(
            child, root, collector, assets_dir, css_rules, depth=2,
            use_tailwind=use_tailwind, color_map=color_map, mode='section',
            analysis=analysis, used_patterns=used_patterns
        )
        
        # Determine imports needed for this section
        section_imports = []
        for sc in shared_components:
            # Check if any instance of this component is within this section
            pattern = None
            if sc.get('pattern_hash'):
                pattern = analysis['repeated_patterns'].get(sc['pattern_hash'])
            elif sc.get('component_id'):
                pattern = analysis['component_instances'].get(sc['component_id'])
            if pattern:
                for inst in pattern['instances']:
                    # Simple check: is the component name referenced in section body?
                    if f"<{sc['name']}" in section_body:
                        section_imports.append(sc)
                        break
        
        # Write section component
        import_lines = []
        for si in section_imports:
            import_lines.append(f"import {{ {si['name']} }} from '@/components/shared/{si['name']}';")
        
        imports_str = "\n".join(import_lines)
        has_css = bool(css_rules)
        
        section_tsx = f"""{f"import styles from './{pascal}.module.css';" if has_css else ''}
{imports_str}

export default function {pascal}() {{
  return (
    <section>
{section_body}    </section>
  );
}}
"""
        with open(sections_dir / f"{pascal}.tsx", 'w') as f:
            f.write(section_tsx)
        
        if has_css:
            _write_css_module(sections_dir / f"{pascal}.module.css", css_rules, nextjs=True)
        
        section_components.append({'pascal': pascal})
    
    # ─── Generate app files ───
    # layout.tsx
    font_families = list(collector.fonts.keys())
    google_fonts = [f for f in font_families if f.lower() not in 
                    ("arial", "helvetica", "times new roman", "georgia", "verdana", "courier new", "segoe ui")]
    
    font_imports = ""
    font_vars = ""
    font_class_names = ""
    if google_fonts:
        font_import_lines = []
        font_var_lines = []
        font_cn_parts = []
        for gf in google_fonts:
            var_name = gf.lower().replace(" ", "_")
            font_import_lines.append(f"import {{ {gf.replace(' ', '_')} }} from 'next/font/google';")
            font_var_lines.append(f"const {var_name} = {gf.replace(' ', '_')}({{ subsets: ['latin'], weight: ['300', '400', '500', '600', '700', '800'] }});")
            font_cn_parts.append(f"${{{var_name}.className}}")
        font_imports = "\n".join(font_import_lines)
        font_vars = "\n".join(font_var_lines)
        font_class_names = " ".join(font_cn_parts)
    
    layout_tsx = f"""import type {{ Metadata }} from 'next';
import './globals.css';
{font_imports}

{font_vars}

export const metadata: Metadata = {{
  title: '{title}',
  description: 'Generated by figma-perfect',
}};

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode;
}}) {{
  return (
    <html lang="en">
      <body className={{`{font_class_names}`}}>
        {{children}}
      </body>
    </html>
  );
}}
"""
    with open(app_dir / "layout.tsx", 'w') as f:
        f.write(layout_tsx)
    
    # page.tsx
    page_imports = "\n".join(
        f"import {sc['pascal']} from '@/components/sections/{sc['pascal']}';" 
        for sc in section_components
    )
    page_renders = "\n".join(f"      <{sc['pascal']} />" for sc in section_components)
    page_tsx = f"""{page_imports}

export default function Home() {{
  return (
    <main>
{page_renders}
    </main>
  );
}}
"""
    with open(app_dir / "page.tsx", 'w') as f:
        f.write(page_tsx)
    
    # Write shared config files (globals.css, tailwind, package.json, tsconfig, etc.)
    _write_nextjs_config_files(output_dir, app_dir, collector, use_tailwind, title)
    
    return section_components, shared_components


def _generate_data_file(var_name, prop_names, prop_types, instances_data):
    """Generate a TypeScript data file with extracted arrays."""
    # Build type
    type_name = ''.join(w.capitalize() for w in var_name.split('_')) + 'Item'
    type_lines = [f"export interface {type_name} {{"]
    for pname in prop_names:
        type_lines.append(f"  {pname}: string;")
    type_lines.append("}")
    
    # Build data array
    items = []
    for data in instances_data:
        props = []
        for pname in prop_names:
            val = data.get(pname, '').replace("'", "\\'")
            props.append(f"    {pname}: '{val}'")
        items.append("  {\n" + ",\n".join(props) + "\n  }")
    
    data_str = ",\n".join(items)
    
    return f"""{chr(10).join(type_lines)}

export const {var_name}: {type_name}[] = [
{data_str}
];
"""


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Figma JSON → HTML/React/Next.js generator")
    parser.add_argument("--input", required=True, help="Input directory with design.json and tokens.json")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--framework", default="html", choices=["html", "react", "nextjs"],
                        help="Output framework (default: html)")
    parser.add_argument("--tailwind", action="store_true", help="Use Tailwind CSS utility classes")
    parser.add_argument("--responsive", action="store_true", help="Generate responsive breakpoints (mobile/tablet/desktop)")
    parser.add_argument("--smart", action="store_true", help="Enable smart analysis: detect repeated patterns, generate shared components")
    args = parser.parse_args()

    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()

    # Load design data
    design_path = input_dir / "design.json"
    tokens_path = input_dir / "tokens.json"
    assets_dir = input_dir / "assets"

    if not design_path.exists():
        print(f"Error: {design_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(design_path) as f:
        design = json.load(f)

    root = design.get("root")
    if not root:
        print("Error: No 'root' key in design.json", file=sys.stderr)
        sys.exit(1)

    # Load tokens (optional enrichment)
    tokens = {}
    if tokens_path.exists():
        with open(tokens_path) as f:
            tokens = json.load(f)

    # Prepare output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine assets output location
    if args.framework == "nextjs":
        output_assets = output_dir / "public" / "assets"
    else:
        output_assets = output_dir / "assets"

    output_assets.mkdir(parents=True, exist_ok=True)

    if assets_dir.exists():
        # Copy assets
        if output_assets.exists():
            shutil.rmtree(output_assets)
        shutil.copytree(str(assets_dir), str(output_assets))

    # Initialize collector
    collector = StyleCollector()

    # Pre-register colors from tokens if available
    summary = tokens.get("summary", {})
    for color_hex in summary.get("colors", []):
        collector.register_color(color_hex.lower())

    for font_info in summary.get("fonts", []):
        collector.register_font(font_info.get("family", "Inter"))

    title = design.get("name", "Generated Page")

    if args.framework == "html":
        # ── Original HTML path (unchanged) ──
        css_rules = OrderedDict()
        body_html = render_node(root, None, collector, str(assets_dir), css_rules, depth=1)

        html_content = generate_html(body_html, collector, title)
        with open(output_dir / "index.html", "w") as f:
            f.write(html_content)

        css_content = generate_css(collector, css_rules)
        with open(output_dir / "styles.css", "w") as f:
            f.write(css_content)

        print(f"✅ Generated HTML: {output_dir}/")
        print(f"   CSS rules: {len(css_rules)}")

    elif args.framework == "react":
        components = generate_react_output(root, collector, str(assets_dir), output_dir, use_tailwind=args.tailwind, title=title, responsive=args.responsive)
        print(f"✅ Generated React: {output_dir}/")
        print(f"   Components: {len(components)}")

    elif args.framework == "nextjs":
        if args.smart:
            sections, shared = generate_smart_nextjs(root, collector, str(assets_dir), output_dir, use_tailwind=args.tailwind, title=title, responsive=args.responsive)
            print(f"✅ Generated Next.js (smart): {output_dir}/")
            print(f"   Sections: {len(sections)}")
            print(f"   Shared components: {len(shared)}")
        else:
            components = generate_nextjs_output(root, collector, str(assets_dir), output_dir, use_tailwind=args.tailwind, title=title, responsive=args.responsive)
            print(f"✅ Generated Next.js: {output_dir}/")
            print(f"   Components: {len(components)}")
        if args.tailwind:
            print(f"   Tailwind: enabled")

    print(f"   Colors: {len(collector.colors)}")
    print(f"   Fonts: {len(collector.fonts)}")
    print(f"   Assets: {len(list(output_assets.iterdir())) if output_assets.exists() else 0}")


if __name__ == "__main__":
    main()
