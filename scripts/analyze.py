#!/usr/bin/env python3
"""
figma-perfect: analyze.py
Token extraction + font mapping + structure analysis.

Reads design.json (raw Figma API response) and produces:
  - tokens.json  — structured design tokens
  - spec.md      — human-readable implementation spec

Usage:
    python3 analyze.py --input ./figma-data/design.json --output ./figma-data/
    python3 analyze.py --input ./figma-data/design.json --output ./figma-data/ --pretty
"""

import argparse
import json
import math
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_MAP_PATH = os.path.join(SCRIPT_DIR, "../references/font-map.json")


# ── Font Map ──────────────────────────────────────────────────────────────────

def load_font_map():
    try:
        with open(FONT_MAP_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load font map: {e}", file=sys.stderr)
        return {}


def map_font(font_family, font_map):
    return font_map.get(font_family, font_family)


# ── Color Utilities ───────────────────────────────────────────────────────────

def rgba_to_hex(color, opacity=1.0):
    if not color:
        return "#000000"
    r = round(color.get('r', 0) * 255)
    g = round(color.get('g', 0) * 255)
    b = round(color.get('b', 0) * 255)
    a = round(color.get('a', 1.0) * opacity * 255)
    if a >= 255:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}{a:02X}"


def rgba_to_css(color, opacity=1.0):
    if not color:
        return "transparent"
    r = round(color.get('r', 0) * 255)
    g = round(color.get('g', 0) * 255)
    b = round(color.get('b', 0) * 255)
    a = round(color.get('a', 1.0) * opacity, 3)
    if a >= 1.0:
        return f"rgb({r}, {g}, {b})"
    return f"rgba({r}, {g}, {b}, {a})"


def compute_gradient_angle(handles):
    if not handles or len(handles) < 2:
        return 180
    start, end = handles[0], handles[1]
    dx = end['x'] - start['x']
    dy = end['y'] - start['y']
    angle = math.degrees(math.atan2(dy, dx)) + 90
    return round(angle % 360)


def gradient_to_css(fill):
    fill_type = fill.get('type', '')
    handles = fill.get('gradientHandlePositions', [])
    stops = fill.get('gradientStops', [])
    stop_strs = [
        f"{rgba_to_hex(s.get('color', {}))} {round(s.get('position', 0) * 100)}%"
        for s in stops
    ]
    stops_css = ', '.join(stop_strs)
    if fill_type == 'GRADIENT_LINEAR':
        return f"linear-gradient({compute_gradient_angle(handles)}deg, {stops_css})"
    elif fill_type == 'GRADIENT_RADIAL':
        return f"radial-gradient(circle, {stops_css})"
    elif fill_type == 'GRADIENT_ANGULAR':
        return f"conic-gradient({stops_css})"
    else:
        return f"linear-gradient({compute_gradient_angle(handles)}deg, {stops_css})"


# ── Node Tree Analysis ────────────────────────────────────────────────────────

class Analyzer:
    def __init__(self, font_map):
        self.font_map = font_map
        self.colors = {}         # hex → count
        self.fonts = {}          # (family, size, weight) → details
        self.font_subs = {}      # original → substitute
        self.shadows = []
        self.radii = {}          # value_str → count
        self.spacing_values = [] # itemSpacing values
        self.padding_values = [] # padding values
        self.sections = []
        self.all_nodes = []

    def analyze_root(self, root_node):
        """Entry point: analyze from root node."""
        # First pass: collect sections (direct children)
        for child in root_node.get('children', []):
            section = self._analyze_section(child)
            self.sections.append(section)
        # Second pass: walk everything for global tokens
        self._walk(root_node, depth=0)
        return self._build_output()

    def _analyze_section(self, node):
        """Analyze a top-level section node."""
        bbox = node.get('absoluteBoundingBox', {})
        section = {
            'name': node.get('name', 'Section'),
            'nodeId': node.get('id', ''),
            'type': node.get('type', ''),
            'width': bbox.get('width', 0),
            'height': bbox.get('height', 0),
            'children': []
        }

        # Background
        for fill in node.get('fills', []):
            if not fill.get('visible', True):
                continue
            ft = fill.get('type', '')
            if ft == 'SOLID':
                section['background'] = rgba_to_hex(fill.get('color', {}), fill.get('opacity', 1.0))
                section['backgroundCss'] = rgba_to_css(fill.get('color', {}), fill.get('opacity', 1.0))
                break
            elif ft.startswith('GRADIENT'):
                section['background'] = gradient_to_css(fill)
                section['backgroundCss'] = section['background']
                break

        # Children summary
        for child in node.get('children', []):
            child_summary = self._summarize_node(child)
            section['children'].append(child_summary)

        return section

    def _summarize_node(self, node):
        """Create a concise summary of a node for the spec."""
        bbox = node.get('absoluteBoundingBox', {})
        summary = {
            'id': node.get('id'),
            'name': node.get('name'),
            'type': node.get('type'),
            'width': bbox.get('width', 0),
            'height': bbox.get('height', 0),
        }

        # Background
        for fill in node.get('fills', []):
            if not fill.get('visible', True):
                continue
            ft = fill.get('type', '')
            if ft == 'SOLID':
                summary['background'] = rgba_to_hex(fill.get('color', {}), fill.get('opacity', 1.0))
                break
            elif ft.startswith('GRADIENT'):
                summary['background'] = gradient_to_css(fill)
                break
            elif ft == 'IMAGE':
                summary['background'] = 'IMAGE'
                summary['imageRef'] = fill.get('imageRef', '')
                break

        # Text content
        if node.get('type') == 'TEXT':
            style = node.get('style', {})
            family = style.get('fontFamily', '')
            summary['text'] = node.get('characters', '')[:80]
            summary['font'] = f"{self.font_map.get(family, family)} {style.get('fontSize')}px/{style.get('fontWeight')}"

        # Corner radius
        cr = node.get('cornerRadius')
        if cr:
            summary['cornerRadius'] = cr

        # Layout
        lm = node.get('layoutMode')
        if lm and lm != 'NONE':
            summary['layout'] = lm.lower()
            summary['gap'] = node.get('itemSpacing', 0)

        return summary

    def _walk(self, node, depth):
        """Walk tree collecting global tokens."""
        node_type = node.get('type', '')

        # Node record
        node_record = {
            'id': node.get('id'),
            'name': node.get('name'),
            'type': node_type,
            'depth': depth,
        }

        # Colors from fills
        for fill in node.get('fills', []):
            if not fill.get('visible', True):
                continue
            ft = fill.get('type', '')
            if ft == 'SOLID':
                color = rgba_to_hex(fill.get('color', {}), fill.get('opacity', 1.0))
                self.colors[color] = self.colors.get(color, 0) + 1
                node_record['fill'] = color
            elif ft.startswith('GRADIENT'):
                css = gradient_to_css(fill)
                self.colors[css] = self.colors.get(css, 0) + 1

        # Typography
        if node_type == 'TEXT':
            style = node.get('style', {})
            family = style.get('fontFamily', '')
            if family:
                substitute = self.font_map.get(family, family)
                if family != substitute:
                    self.font_subs[family] = substitute
                key = (family, style.get('fontSize'), style.get('fontWeight'))
                if key not in self.fonts:
                    self.fonts[key] = {
                        'family': family,
                        'substitute': substitute,
                        'size': style.get('fontSize'),
                        'weight': style.get('fontWeight'),
                        'lineHeight': style.get('lineHeightPx'),
                        'letterSpacing': style.get('letterSpacing', 0),
                        'italic': style.get('italic', False),
                        'textAlign': style.get('textAlignHorizontal', 'LEFT')
                    }

        # Shadows
        for eff in node.get('effects', []):
            if not eff.get('visible', True):
                continue
            eff_type = eff.get('type', '')
            if eff_type in ('DROP_SHADOW', 'INNER_SHADOW'):
                color = eff.get('color', {})
                offset = eff.get('offset', {'x': 0, 'y': 0})
                radius = eff.get('radius', 0)
                spread = eff.get('spread', 0)
                color_css = rgba_to_css(color)
                inset = "inset " if eff_type == 'INNER_SHADOW' else ""
                shadow = {
                    'type': eff_type,
                    'x': offset.get('x', 0),
                    'y': offset.get('y', 0),
                    'blur': radius,
                    'spread': spread,
                    'color': rgba_to_hex(color),
                    'css': f"{inset}{offset.get('x',0)}px {offset.get('y',0)}px {radius}px {spread}px {color_css}"
                }
                if shadow['css'] not in [s.get('css') for s in self.shadows]:
                    self.shadows.append(shadow)

        # Corner radii
        cr = node.get('cornerRadius')
        rcr = node.get('rectangleCornerRadii')
        if rcr and any(v != 0 for v in rcr):
            key = f"{rcr[0]}/{rcr[1]}/{rcr[2]}/{rcr[3]}"
            self.radii[key] = self.radii.get(key, 0) + 1
        elif cr is not None and cr != 0:
            key = str(cr)
            self.radii[key] = self.radii.get(key, 0) + 1

        # Spacing
        item_spacing = node.get('itemSpacing')
        if item_spacing and item_spacing > 0:
            self.spacing_values.append(item_spacing)
        for pad_key in ('paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'):
            val = node.get(pad_key)
            if val and val > 0:
                self.padding_values.append(val)

        self.all_nodes.append(node_record)

        for child in node.get('children', []):
            self._walk(child, depth + 1)

    def _build_output(self):
        """Build the final tokens.json structure."""

        # Sort colors by frequency
        sorted_colors = sorted(self.colors.items(), key=lambda x: -x[1])
        color_dict = {}
        for i, (color, _) in enumerate(sorted_colors):
            if color.startswith('#') and len(color) in (7, 9):
                if i == 0:
                    color_dict['primary'] = color
                elif i == 1:
                    color_dict['secondary'] = color
                else:
                    color_dict[f'color{i+1}'] = color
            else:
                color_dict[f'gradient{i+1}'] = color

        # Sort fonts by size desc (headings first)
        font_list = sorted(self.fonts.values(), key=lambda f: -(f.get('size') or 0))

        # Common spacing values
        unique_spacing = sorted(set(self.spacing_values + self.padding_values))
        spacing_dict = {}
        if unique_spacing:
            spacing_dict['common'] = unique_spacing
            # Try to identify semantic values
            if len(unique_spacing) >= 1:
                spacing_dict['smallest'] = unique_spacing[0]
            if len(unique_spacing) >= 2:
                spacing_dict['small'] = unique_spacing[1]
            if unique_spacing:
                spacing_dict['largest'] = unique_spacing[-1]

        # Radii: sort by frequency
        sorted_radii = sorted(self.radii.items(), key=lambda x: -x[1])
        radii_dict = {}
        for i, (val, _) in enumerate(sorted_radii):
            labels = ['card', 'button', 'input', 'badge', 'pill']
            label = labels[i] if i < len(labels) else f'radius{i+1}'
            # Parse value
            try:
                numeric = float(val.split('/')[0])
                if numeric >= 100:
                    label = 'pill'
                elif numeric >= 20:
                    label = 'card' if i == 0 else label
            except ValueError:
                pass
            radii_dict[label] = val

        return {
            'colors': color_dict,
            'fonts': font_list,
            'fontSubstitutions': self.font_subs,
            'spacing': spacing_dict,
            'radii': radii_dict,
            'shadows': self.shadows,
            'sections': self.sections
        }


# ── Spec Generation ───────────────────────────────────────────────────────────

def generate_spec(design_name, tokens, output_dir):
    """Generate human-readable spec.md."""
    colors = tokens.get('colors', {})
    fonts = tokens.get('fonts', [])
    font_subs = tokens.get('fontSubstitutions', {})
    spacing = tokens.get('spacing', {})
    radii = tokens.get('radii', {})
    shadows = tokens.get('shadows', [])
    sections = tokens.get('sections', [])

    lines = [
        f"# Implementation Spec — {design_name}",
        "",
        "_Generated by figma-perfect/scripts/analyze.py_",
        "",
        "---",
        "",
        "## Design Tokens",
        "",
        "### Colors",
        "",
    ]

    for name, value in colors.items():
        lines.append(f"- **{name}:** `{value}`")

    if font_subs:
        lines += [
            "",
            "### Font Substitutions",
            "",
            "| Original (Figma) | Substitute (Google Fonts) |",
            "|---|---|",
        ]
        for original, sub in font_subs.items():
            lines.append(f"| {original} | **{sub}** |")

    lines += [
        "",
        "### Typography",
        "",
        "| Font Family | Substitute | Size | Weight | Line Height | Letter Spacing | Italic |",
        "|---|---|---|---|---|---|---|",
    ]

    for font in fonts:
        family = font.get('family', '')
        sub = font.get('substitute', family)
        size = font.get('size', '—')
        weight = font.get('weight', '—')
        lh = font.get('lineHeight', '—')
        ls = font.get('letterSpacing', 0)
        italic = '✓' if font.get('italic') else ''
        sub_display = f"**{sub}**" if sub != family else sub
        lines.append(f"| {family} | {sub_display} | {size}px | {weight} | {lh and f'{lh:.1f}px' or '—'} | {ls} | {italic} |")

    if spacing:
        lines += [
            "",
            "### Spacing",
            "",
        ]
        for key, val in spacing.items():
            if isinstance(val, list):
                lines.append(f"- **{key}:** {', '.join(str(v) for v in val)}px")
            else:
                lines.append(f"- **{key}:** `{val}px`")

    if radii:
        lines += [
            "",
            "### Border Radii",
            "",
        ]
        for name, val in radii.items():
            lines.append(f"- **{name}:** `{val}px`")

    if shadows:
        lines += [
            "",
            "### Shadows",
            "",
        ]
        for shadow in shadows:
            lines.append(f"- `{shadow.get('css', '')}`")

    lines += [
        "",
        "---",
        "",
        "## CSS Custom Properties",
        "",
        "```css",
        ":root {",
    ]

    # Colors
    for name, value in colors.items():
        if value.startswith('#') and len(value) in (7, 9):
            lines.append(f"  --color-{name}: {value};")

    # Typography
    for i, font in enumerate(fonts[:5]):
        sub = font.get('substitute', font.get('family', 'Inter'))
        size = font.get('size', 16)
        weight = font.get('weight', 400)
        lh = font.get('lineHeight', '')
        label = 'heading' if i == 0 else ('subheading' if i == 1 else f'text-{i+1}')
        lines.append(f"  --font-{label}: '{sub}', sans-serif;")
        lines.append(f"  --size-{label}: {size}px;")
        lines.append(f"  --weight-{label}: {weight};")
        if lh:
            lines.append(f"  --lh-{label}: {lh:.1f}px;")

    # Radii
    for name, val in radii.items():
        lines.append(f"  --radius-{name}: {val}px;")

    lines += [
        "}",
        "```",
        "",
        "---",
        "",
        "## Sections",
        "",
    ]

    for i, section in enumerate(sections, 1):
        lines += [
            f"### {i}. {section['name']} ({section['nodeId']})",
            "",
            f"- **Dimensions:** {section['width']:.0f}px × {section['height']:.0f}px",
            f"- **Type:** {section['type']}",
        ]
        if 'background' in section:
            lines.append(f"- **Background:** `{section['background']}`")
        if 'backgroundCss' in section:
            lines.append(f"- **Background CSS:** `{section['backgroundCss']}`")

        children = section.get('children', [])
        if children:
            lines += [
                f"- **Direct children:** {len(children)}",
                "",
                "**Children:**",
                "",
            ]
            for child in children:
                child_type = child.get('type', '')
                child_name = child.get('name', '')
                child_w = child.get('width', 0)
                child_h = child.get('height', 0)
                bg = child.get('background', '')
                text_info = ''
                if child_type == 'TEXT':
                    content = child.get('text', '')
                    font_info = child.get('font', '')
                    text_info = f" — \"{content}\" ({font_info})"
                elif bg:
                    text_info = f" — bg: `{bg}`"
                lines.append(f"  - `{child_type}` **{child_name}** ({child_w:.0f}×{child_h:.0f}px){text_info}")

        lines.append("")

    lines += [
        "---",
        "",
        "## Implementation Checklist",
        "",
        "- [ ] Set up CSS custom properties from tokens above",
        "- [ ] Import Google Fonts substitutes",
        "- [ ] Reference images from `assets/` directory",
        "- [ ] Build sections in order (top → bottom)",
        "- [ ] Run `diff.py` to validate accuracy",
        "- [ ] Iterate until diff score ≥ 90%",
        "",
        "---",
        "",
        "_Never guess values. Every number above came from Figma API. If something is missing, re-run extract.py._",
    ]

    spec_content = "\n".join(lines)
    spec_path = os.path.join(output_dir, 'spec.md')
    with open(spec_path, 'w') as f:
        f.write(spec_content)
    return spec_path


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Analyze Figma design.json and produce tokens.json + spec.md'
    )
    parser.add_argument('--input', required=True, help='Path to design.json')
    parser.add_argument('--output', required=True, help='Output directory')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON output')
    parser.add_argument('--summary', action='store_true', help='Print summary to stdout after analysis')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    print(f"Loading {args.input}...")
    with open(args.input, 'r') as f:
        data = json.load(f)

    design_name = data.get('name', 'Figma Design')
    root_node = data.get('root', data)

    print(f"Analyzing: {design_name}")
    font_map = load_font_map()
    analyzer = Analyzer(font_map)
    tokens = analyzer.analyze_root(root_node)

    # Save tokens.json
    tokens_path = os.path.join(args.output, 'tokens.json')
    indent = 2 if args.pretty else None
    with open(tokens_path, 'w') as f:
        json.dump(tokens, f, indent=indent)
    print(f"✓ tokens.json ({os.path.getsize(tokens_path):,} bytes)")

    # Generate spec.md
    spec_path = generate_spec(design_name, tokens, args.output)
    print(f"✓ spec.md ({os.path.getsize(spec_path):,} bytes)")

    if args.summary:
        print("\n--- Summary ---")
        print(f"Colors: {len(tokens.get('colors', {}))}")
        print(f"Fonts: {len(tokens.get('fonts', []))}")
        print(f"Font substitutions: {len(tokens.get('fontSubstitutions', {}))}")
        subs = tokens.get('fontSubstitutions', {})
        for orig, sub in subs.items():
            print(f"  {orig} → {sub}")
        print(f"Sections: {len(tokens.get('sections', []))}")
        for section in tokens.get('sections', []):
            print(f"  - {section['name']} ({section.get('width', 0):.0f}×{section.get('height', 0):.0f}px)")
        print(f"Shadows: {len(tokens.get('shadows', []))}")
        print(f"Border radii: {len(tokens.get('radii', {}))}")

    print(f"\n✅ Analysis complete → {args.output}")


if __name__ == '__main__':
    main()
