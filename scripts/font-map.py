#!/usr/bin/env python3
"""
figma-perfect: font-map.py
Font substitution helper — maps premium/proprietary fonts to Google Fonts alternatives.

Usage:
    python3 font-map.py "Vastago Grotesk"           → Sora
    python3 font-map.py "SF Pro Display"            → Inter
    python3 font-map.py --all                       → Full mapping table
    python3 font-map.py --add "My Font" "Inter"     → Add custom mapping
    python3 font-map.py --search "grotesk"          → Search by keyword
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_MAP_PATH = os.path.join(SCRIPT_DIR, "../references/font-map.json")


def load_font_map():
    """Load font map from JSON file."""
    if not os.path.exists(FONT_MAP_PATH):
        print(f"Error: font-map.json not found at {FONT_MAP_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(FONT_MAP_PATH, 'r') as f:
        return json.load(f)


def save_font_map(font_map):
    """Save updated font map to JSON file."""
    with open(FONT_MAP_PATH, 'w') as f:
        json.dump(font_map, f, indent=2, ensure_ascii=False)


def lookup_font(font_name, font_map):
    """Look up a font substitution. Case-insensitive."""
    # Exact match
    if font_name in font_map:
        return font_map[font_name]
    # Case-insensitive match
    font_lower = font_name.lower()
    for key, value in font_map.items():
        if key.lower() == font_lower:
            return value
    return None


def search_fonts(query, font_map):
    """Search font map by keyword."""
    query_lower = query.lower()
    results = []
    for original, substitute in font_map.items():
        if query_lower in original.lower() or query_lower in substitute.lower():
            results.append((original, substitute))
    return results


def print_table(font_map):
    """Print full mapping table."""
    # Calculate column widths
    max_orig = max(len(k) for k in font_map.keys())
    max_sub = max(len(v) for v in font_map.values())
    max_orig = max(max_orig, 20)
    max_sub = max(max_sub, 20)

    header = f"{'Original Font':<{max_orig}}  →  {'Google Fonts Substitute':<{max_sub}}"
    separator = "-" * len(header)

    print(header)
    print(separator)

    for original, substitute in sorted(font_map.items()):
        same = original == substitute
        sub_display = f"{substitute} (already Google Font)" if same else substitute
        print(f"{original:<{max_orig}}  →  {sub_display}")

    print(separator)
    print(f"Total: {len(font_map)} mappings")


def main():
    parser = argparse.ArgumentParser(
        description='Font substitution helper for figma-perfect skill',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 font-map.py "Vastago Grotesk"          # Look up a font
  python3 font-map.py --all                      # Show all mappings
  python3 font-map.py --search "grotesk"         # Search by keyword
  python3 font-map.py --add "Custom Font" "Inter"  # Add new mapping
  python3 font-map.py --json "Vastago Grotesk"   # Output as JSON
        """
    )

    parser.add_argument('font', nargs='?', help='Font name to look up')
    parser.add_argument('--all', action='store_true', help='Show all mappings as table')
    parser.add_argument('--search', metavar='QUERY', help='Search font map by keyword')
    parser.add_argument('--add', nargs=2, metavar=('ORIGINAL', 'SUBSTITUTE'),
                        help='Add a custom font mapping')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--google-fonts-url', action='store_true',
                        help='Output Google Fonts import URL for a font')

    args = parser.parse_args()

    # Need at least one action
    if not any([args.font, args.all, args.search, args.add]):
        parser.print_help()
        sys.exit(1)

    font_map = load_font_map()

    # Add custom mapping
    if args.add:
        original, substitute = args.add
        font_map[original] = substitute
        save_font_map(font_map)
        print(f"Added: {original} → {substitute}")
        return

    # Show all
    if args.all:
        if args.json:
            print(json.dumps(font_map, indent=2, ensure_ascii=False))
        else:
            print_table(font_map)
        return

    # Search
    if args.search:
        results = search_fonts(args.search, font_map)
        if not results:
            print(f"No fonts found matching '{args.search}'")
            sys.exit(0)
        if args.json:
            print(json.dumps(dict(results), indent=2))
        else:
            print(f"Fonts matching '{args.search}':")
            for original, substitute in results:
                print(f"  {original} → {substitute}")
        return

    # Single font lookup
    if args.font:
        substitute = lookup_font(args.font, font_map)
        if substitute is None:
            print(f"No mapping found for '{args.font}'", file=sys.stderr)
            print(f"  → Defaulting to: {args.font}")
            print(f"  (Add custom mapping with: python3 font-map.py --add \"{args.font}\" \"YourChoice\")")
            if args.json:
                print(json.dumps({'original': args.font, 'substitute': args.font, 'found': False}))
            else:
                print(args.font)
            sys.exit(0)

        if args.json:
            output = {
                'original': args.font,
                'substitute': substitute,
                'found': True,
                'same': args.font == substitute
            }
            if args.google_fonts_url:
                slug = substitute.replace(' ', '+')
                output['googleFontsUrl'] = f"https://fonts.googleapis.com/css2?family={slug}:wght@300;400;500;600;700;800;900&display=swap"
            print(json.dumps(output, indent=2))
        else:
            print(substitute)
            if args.google_fonts_url:
                slug = substitute.replace(' ', '+')
                url = f"https://fonts.googleapis.com/css2?family={slug}:wght@300;400;500;600;700;800;900&display=swap"
                print(f"Google Fonts URL: {url}")

        return


if __name__ == '__main__':
    main()
