#!/usr/bin/env python3
"""
Figma interactivity injector — auto-detect interactive elements from Figma
design.json node names, text content, and structure, then patch generated
project files with event handlers, hover states, and proper semantic elements.

Everything is DATA-DRIVEN: all text, placeholders, and labels come from
the actual Figma JSON. Nothing is invented.

Detections are assigned confidence levels:
  HIGH   — Node name explicitly indicates interaction (Button, CTA, Input, etc.)
           Auto-applied without caveats.
  MEDIUM — Structure strongly suggests interaction (card grid, footer text links)
           Auto-applied WITH a /* TODO: verify interaction */ comment.
  LOW    — Ambiguous; might or might not be interactive.
           Listed in report only, NOT auto-applied.

Usage:
    python3 interactivity.py --input ./figma-data/ --project ./output/ --framework nextjs
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# ─── Detection patterns ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

# HIGH confidence: node name explicitly says it's interactive
BUTTON_EXPLICIT = re.compile(
    r'\b(button|cta|btn|submit)\b', re.IGNORECASE,
)
# HIGH: node name is explicitly a link
LINK_EXPLICIT = re.compile(
    r'\blink\b', re.IGNORECASE,
)
# HIGH: node name is explicitly an input/search
INPUT_EXPLICIT = re.compile(
    r'\b(input|text\s*field|search\s*bar|search\s*field)\b', re.IGNORECASE,
)
# HIGH: node name is explicitly pagination
PAGINATION_EXPLICIT = re.compile(
    r'\bpagination\b', re.IGNORECASE,
)
# HIGH: node name is explicitly nav/navbar
NAV_EXPLICIT = re.compile(
    r'\b(nav|navbar|navigation)\b', re.IGNORECASE,
)

# MEDIUM confidence: name suggests interaction but isn't explicit
BUTTON_SUGGESTIVE = re.compile(
    r'\b(sign\s*up|get\s*started|learn\s*more|download|subscribe|register|log\s*in|sign\s*in)\b',
    re.IGNORECASE,
)
SEARCH_SUGGESTIVE = re.compile(
    r'\b(search|email|password)\b', re.IGNORECASE,
)
CARD_PATTERN = re.compile(r'\bcard\b', re.IGNORECASE)
TAB_PATTERNS = re.compile(r'\b(tab|filter)\b', re.IGNORECASE)

# LOW confidence: structural hints only
FOOTER_PATTERN = re.compile(r'^footer$', re.IGNORECASE)
MENU_SUGGESTIVE = re.compile(r'\b(menu|header)\b', re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════
# ─── CSS class name generation (mirrors generate.py exactly) ──────────────
# ═══════════════════════════════════════════════════════════════════════════

def sanitize_class(node):
    """Generate a CSS class name from node name + id (must match generate.py)."""
    name = node.get("name", "element")
    name = name.replace(" ", "-").replace("/", "-").replace(".", "-").lower()
    name = "".join(c if c.isalnum() or c == "-" else "-" for c in name)
    while "--" in name:
        name = name.replace("--", "-")
    name = name.strip("-")
    nid = node.get("id", "0-0").replace(":", "-").replace(";", "-")
    nid = "".join(c if c.isalnum() or c == "-" else "-" for c in nid)
    full = f"fig-{name}-{nid}"
    if len(full) > 60:
        full = full[:57] + nid[-3:] if len(nid) >= 3 else full[:60]
    return full


def to_camel(kebab_str):
    """Convert fig-some-name-1-2 to figSomeName12 (must match generate.py)."""
    parts = kebab_str.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ═══════════════════════════════════════════════════════════════════════════
# ─── Figma tree helpers ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def collect_text_descendants(node):
    """Return list of {nodeId, name, characters} for all TEXT descendants."""
    results = []
    if node.get("type") == "TEXT":
        chars = node.get("characters", "")
        if chars and chars.strip():
            results.append({
                "nodeId": node["id"],
                "name": node.get("name", ""),
                "characters": chars,
                "node": node,
            })
        return results
    for child in node.get("children", []):
        results.extend(collect_text_descendants(child))
    return results


def build_node_path(target_id, node, path=None):
    """Build the ancestor path string for a node ID: 'Root > Frame > Child'."""
    if path is None:
        path = []
    current_path = path + [node.get("name", node.get("type", "?"))]
    if node.get("id") == target_id:
        return " > ".join(current_path)
    for child in node.get("children", []):
        result = build_node_path(target_id, child, current_path)
        if result:
            return result
    return None


def has_image_fill(node):
    """Check if a node has an IMAGE fill."""
    for fill in node.get("fills", []):
        if fill.get("type") == "IMAGE" and fill.get("visible", True) is not False:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# ─── Detection engine ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

class Detection:
    """A single detected interactive element, traced to a specific Figma node."""

    def __init__(self, node, interaction_type, confidence, reason, root):
        self.node = node
        self.node_id = node.get("id", "")
        self.node_name = node.get("name", "")
        self.node_type = node.get("type", "")
        self.interaction_type = interaction_type   # button, link, input, card, tab, pagination, nav, footer_link
        self.confidence = confidence               # HIGH, MEDIUM, LOW
        self.reason = reason                       # human-readable: why we think this is interactive
        self.node_path = build_node_path(self.node_id, root) or self.node_name

        # Data extracted from Figma (never invented)
        self.figma_text = None          # actual text from node.characters or first TEXT child
        self.figma_placeholder = None   # for inputs: actual placeholder from child TEXT node
        self.figma_children_text = []   # list of child text dicts
        self.sub_detections = []        # for pagination: number nodes, button nodes, etc.

        # Populate text from Figma data
        self._extract_text()

    def _extract_text(self):
        """Pull all text data from the Figma node itself — never invent."""
        if self.node.get("type") == "TEXT":
            self.figma_text = self.node.get("characters", "")
        else:
            texts = collect_text_descendants(self.node)
            if texts:
                self.figma_text = texts[0]["characters"]
            self.figma_children_text = texts

    def to_report_dict(self):
        d = OrderedDict()
        d["nodeId"] = self.node_id
        d["nodePath"] = self.node_path
        d["name"] = self.node_name
        d["type"] = self.interaction_type
        d["confidence"] = self.confidence
        d["reason"] = self.reason
        if self.figma_text:
            d["figmaText"] = self.figma_text
        if self.figma_placeholder:
            d["figmaPlaceholder"] = self.figma_placeholder
        return d


def scan_tree(node, root, parent=None, siblings=None):
    """Walk the Figma tree and return a list of Detection objects."""
    detections = []
    name = node.get("name", "")
    ntype = node.get("type", "")
    nid = node.get("id", "")
    children = node.get("children", [])

    already_handled = False

    # ── 1. PAGINATION (HIGH) — check first so we don't double-detect child buttons ──
    if PAGINATION_EXPLICIT.search(name) and ntype in ("FRAME", "INSTANCE"):
        det = Detection(
            node, "pagination", "HIGH",
            f"Node name '{name}' explicitly contains 'Pagination'", root,
        )
        # Collect sub-parts from Figma data
        _collect_pagination_sub_parts(node, det, root)
        detections.append(det)
        already_handled = True  # don't recurse into pagination children

    # ── 2. BUTTON — explicit (HIGH) ──
    elif BUTTON_EXPLICIT.search(name) and ntype in ("FRAME", "INSTANCE", "TEXT"):
        det = Detection(
            node, "button", "HIGH",
            f"Node name '{name}' explicitly contains a button keyword", root,
        )
        detections.append(det)
        already_handled = True

    # ── 3. BUTTON — suggestive text (MEDIUM) ──
    elif BUTTON_SUGGESTIVE.search(name) and ntype in ("FRAME", "INSTANCE", "TEXT"):
        det = Detection(
            node, "button", "MEDIUM",
            f"Node name '{name}' contains action-oriented text suggesting a button", root,
        )
        detections.append(det)
        # Don't mark handled — children might have their own detections

    # ── 4. NAV — explicit (HIGH) ──
    elif NAV_EXPLICIT.search(name) and ntype in ("FRAME", "INSTANCE"):
        texts = collect_text_descendants(node)
        if texts:
            det = Detection(
                node, "nav", "HIGH",
                f"Node name '{name}' explicitly contains 'Nav'/'Navbar' with {len(texts)} text items", root,
            )
            detections.append(det)
            # Still recurse — nav children (links, buttons) should be detected individually

    # ── 5. INPUT — explicit (HIGH) ──
    elif INPUT_EXPLICIT.search(name) and ntype in ("FRAME", "INSTANCE"):
        det = Detection(
            node, "input", "HIGH",
            f"Node name '{name}' explicitly contains an input keyword", root,
        )
        # Placeholder comes from actual child TEXT nodes
        texts = collect_text_descendants(node)
        if texts:
            det.figma_placeholder = texts[0]["characters"]
        detections.append(det)
        already_handled = True

    # ── 6. INPUT — suggestive (MEDIUM) ──
    elif SEARCH_SUGGESTIVE.search(name) and ntype in ("FRAME", "INSTANCE"):
        # "Search", "Email", "Password" in name but not explicitly "Input"
        # Only MEDIUM if the node has some text child that looks like a placeholder
        texts = collect_text_descendants(node)
        placeholder_text = texts[0]["characters"] if texts else None
        if placeholder_text:
            det = Detection(
                node, "input", "MEDIUM",
                f"Node name '{name}' suggests a search/input field (has placeholder text '{placeholder_text}')", root,
            )
            det.figma_placeholder = placeholder_text
            detections.append(det)

    # ── 7. LINK — explicit (HIGH) ──
    elif LINK_EXPLICIT.search(name) and ntype in ("FRAME", "INSTANCE"):
        det = Detection(
            node, "link", "HIGH",
            f"Node name '{name}' explicitly contains 'Link'", root,
        )
        detections.append(det)
        # Don't block recursion — link children might have sub-links

    # ── 8. CARD — name match with repeated siblings (MEDIUM) ──
    elif CARD_PATTERN.search(name) and ntype in ("FRAME", "INSTANCE"):
        if siblings:
            card_siblings = [s for s in siblings if CARD_PATTERN.search(s.get("name", ""))]
            if len(card_siblings) >= 2:
                det = Detection(
                    node, "card", "MEDIUM",
                    f"Node name '{name}' contains 'Card' with {len(card_siblings)} card siblings", root,
                )
                detections.append(det)

    # ── 9. TAB/FILTER — siblings (MEDIUM) ──
    elif TAB_PATTERNS.search(name) and ntype in ("FRAME", "INSTANCE"):
        if siblings:
            tab_siblings = [s for s in siblings if TAB_PATTERNS.search(s.get("name", ""))]
            if len(tab_siblings) >= 2:
                det = Detection(
                    node, "tab", "MEDIUM",
                    f"Node name '{name}' contains 'Tab'/'Filter' with {len(tab_siblings)} siblings", root,
                )
                detections.append(det)

    # ── 10. FOOTER — find footer link candidates, then RECURSE for buttons/inputs/etc ──
    elif FOOTER_PATTERN.search(name) and ntype in ("FRAME", "INSTANCE"):
        footer_texts = _find_footer_link_candidates(node)
        for ft_node, ft_reason in footer_texts:
            confidence = "HIGH" if "Link-named parent" in ft_reason or "Link-named ancestor" in ft_reason else "MEDIUM"
            det = Detection(
                ft_node, "footer_link", confidence,
                ft_reason, root,
            )
            detections.append(det)
        # DON'T set already_handled — still recurse to find buttons, inputs, links inside footer

    # ── 11. MENU/HEADER — structural (LOW) ──
    elif MENU_SUGGESTIVE.search(name) and ntype in ("FRAME", "INSTANCE"):
        if not NAV_EXPLICIT.search(name):  # avoid double-detect with nav
            texts = collect_text_descendants(node)
            if texts:
                det = Detection(
                    node, "nav", "LOW",
                    f"Node name '{name}' contains 'Menu'/'Header' (ambiguous — may be decorative)", root,
                )
                detections.append(det)

    # ── Recurse into children ──
    if not already_handled:
        for child in children:
            detections.extend(scan_tree(child, root, parent=node, siblings=children))

    return detections


def _collect_pagination_sub_parts(node, det, root):
    """Walk pagination tree to find the LEAF nodes actually in generated code.

    We collect:
    - TEXT nodes with numeric content or '...' → pagination_number
    - TEXT nodes with 'Previous'/'Next' text → pagination_button
    - FRAME/INSTANCE nodes named '_Pagination number base' or similar → pagination_number
    - Arrow/icon nodes near prev/next buttons
    """
    _collect_pagination_leaves(node, det, root, set())


def _collect_pagination_leaves(node, det, root, seen_ids):
    """Recursively collect leaf-level interactive pagination parts."""
    nid = node.get("id", "")
    if nid in seen_ids:
        return
    seen_ids.add(nid)

    ntype = node.get("type", "")
    nname = node.get("name", "")

    if ntype == "TEXT":
        chars = node.get("characters", "")
        if chars:
            stripped = chars.strip()
            if stripped.isdigit() or stripped == "...":
                sub = Detection(
                    node, "pagination_number", "HIGH",
                    f"Numeric text '{stripped}' inside Pagination", root,
                )
                det.sub_detections.append(sub)
            elif stripped.lower() in ("previous", "prev", "next"):
                sub = Detection(
                    node, "pagination_button", "HIGH",
                    f"Navigation text '{stripped}' inside Pagination", root,
                )
                det.sub_detections.append(sub)
        return

    # FRAME/INSTANCE named like '_Pagination number base' → the clickable wrapper
    if re.search(r'pagination.*number|number.*base', nname, re.IGNORECASE):
        sub = Detection(
            node, "pagination_number", "HIGH",
            f"Pagination number container '{nname}' (id={nid})", root,
        )
        det.sub_detections.append(sub)
        # Still recurse to find TEXT children too

    for child in node.get("children", []):
        _collect_pagination_leaves(child, det, root, seen_ids)


def _find_footer_link_candidates(node, ancestor_names=None):
    """Find TEXT nodes in footer that are actual links (not headings/inputs/descriptions).

    Uses the full ancestor chain of Figma node names to determine intent:
    - Any ancestor named 'Heading', 'Form', 'Input', 'Label' → NOT a link, skip
    - Direct parent named 'Link' or 'Link - *' → HIGH confidence link
    - Standalone short text in a non-input/heading context → MEDIUM confidence
    - Long text (>80 chars) → likely description, skip
    """
    if ancestor_names is None:
        ancestor_names = []

    results = []  # list of (node, reason_string)
    node_name = node.get("name", "")
    current_ancestors = ancestor_names + [node_name]

    # Patterns that indicate a non-link context
    non_link_context = re.compile(
        r'\b(heading|form|input|search|title|description)\b', re.IGNORECASE
    )

    # Check if ANY ancestor indicates non-link context
    in_non_link_context = any(non_link_context.search(a) for a in current_ancestors)

    for child in node.get("children", []):
        if child.get("type") == "TEXT":
            text = child.get("characters", "")
            if not text or not text.strip():
                continue
            # Skip copyright-like boilerplate
            if re.search(r'copyright|©|all rights?\s*reserved|®|™', text, re.IGNORECASE):
                continue
            # Skip if inside a heading/form/input ancestor chain
            if in_non_link_context:
                continue
            # Skip long text — likely a description, not a link
            if len(text) > 80:
                continue

            # Check if direct parent is named "Link" (the node containing this TEXT)
            if LINK_EXPLICIT.search(node_name):
                results.append((
                    child,
                    f"Footer TEXT '{text}' inside Link-named parent '{node_name}' → likely a link",
                ))
            else:
                # Check if any ancestor is Link-named
                has_link_ancestor = any(LINK_EXPLICIT.search(a) for a in current_ancestors)
                if has_link_ancestor:
                    link_ancestor = next(a for a in reversed(current_ancestors) if LINK_EXPLICIT.search(a))
                    results.append((
                        child,
                        f"Footer TEXT '{text}' inside Link-named ancestor '{link_ancestor}' → likely a link",
                    ))
                else:
                    # Short text in footer, no link ancestor — ambiguous
                    results.append((
                        child,
                        f"Footer TEXT '{text}' in footer (parent: '{node_name}') — may be a link",
                    ))
        else:
            results.extend(_find_footer_link_candidates(child, current_ancestors))

    return results


# ═══════════════════════════════════════════════════════════════════════════
# ─── File patching engine ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def find_files_with_pattern(project_dir, pattern):
    """Find all .tsx/.jsx/.html files containing a string pattern."""
    results = []
    for ext in ("*.tsx", "*.jsx", "*.html"):
        for fpath in Path(project_dir).rglob(ext):
            try:
                content = fpath.read_text()
                if pattern in content:
                    results.append(fpath)
            except Exception:
                pass
    return results


def find_node_in_files(project_dir, node):
    """Find which file(s) contain references to this node's CSS class.
    
    Uses the node ID portion of the class name for matching to avoid
    false positives when multiple nodes have similar names (e.g., many 'Link' nodes).
    """
    cls = sanitize_class(node)
    camel = to_camel(cls)
    # Extract the ID portion for more precise matching
    nid = node.get("id", "0-0").replace(":", "-").replace(";", "-")
    nid = "".join(c if c.isalnum() or c == "-" else "-" for c in nid)
    
    files = set()
    # First try matching the full class name (most precise)
    for pattern in [cls, camel]:
        files.update(find_files_with_pattern(project_dir, pattern))
    
    # If no match with full class, try matching by ID portion only
    # This handles cases where the class was truncated
    if not files and nid and nid != "0-0":
        files.update(find_files_with_pattern(project_dir, nid))
    
    return list(files), cls, camel


class FilePatcher:
    """Accumulates patches and flushes them to disk in one pass."""

    def __init__(self):
        self._file_cache = {}
        self._modified = set()
        self._needs_use_client = set()

    def read(self, fpath):
        fpath = str(fpath)
        if fpath not in self._file_cache:
            self._file_cache[fpath] = Path(fpath).read_text()
        return self._file_cache[fpath]

    def write(self, fpath, content):
        fpath = str(fpath)
        self._file_cache[fpath] = content
        self._modified.add(fpath)

    def mark_use_client(self, fpath):
        self._needs_use_client.add(str(fpath))

    def flush(self, project_dir):
        """Write all modified files, prepend 'use client' where needed."""
        modified = []
        for fpath in self._modified:
            content = self._file_cache[fpath]
            if fpath in self._needs_use_client:
                if "'use client'" not in content and '"use client"' not in content:
                    content = "'use client';\n" + content
            Path(fpath).write_text(content)
            try:
                modified.append(str(Path(fpath).relative_to(project_dir)))
            except ValueError:
                modified.append(fpath)
        return sorted(modified)


# ─── Low-level class / attribute manipulation ─────────────────────────────

def _add_tailwind_classes(content, cls, camel, new_classes):
    """Add Tailwind classes to an element identified by its CSS class name.

    Handles all three formats from generate.py:
      1. className="fig-name-id existing-classes"
      2. className={`${styles.figNameId} existing-classes`}
      3. className={styles.figNameId}
    """
    if not new_classes:
        return content

    first_new = new_classes.split()[0]

    # Pattern 1: className="...cls..."
    p1 = re.compile(r'(className="[^"]*\b' + re.escape(cls) + r'\b)([^"]*")')
    if p1.search(content):
        def r1(m):
            if first_new in m.group(2) or first_new in m.group(1):
                return m.group(0)
            return m.group(1) + m.group(2)[:-1] + " " + new_classes + '"'
        return p1.sub(r1, content)

    # Pattern 2: className={`${styles.camel} ...`}
    p2 = re.compile(r'(className=\{`\$\{styles\.' + re.escape(camel) + r'\})([^`]*`\})')
    if p2.search(content):
        def r2(m):
            if first_new in m.group(2):
                return m.group(0)
            return m.group(1) + m.group(2)[:-2] + " " + new_classes + "`}"
        return p2.sub(r2, content)

    # Pattern 3: className={styles.camel}
    p3 = re.compile(r'className=\{styles\.' + re.escape(camel) + r'\}')
    if p3.search(content):
        return p3.sub(f'className={{`${{styles.{camel}}} {new_classes}`}}', content)

    return content


def _add_onclick(content, cls, camel):
    """Add onClick={() => {}} to the element's opening tag.

    Skips <img> (self-closing) and avoids duplicate onClick.
    """
    for identifier in [cls, camel]:
        pattern = re.compile(
            r'(<(?!img\b)\w+\s+)([^>]*className=["\{][^>]*\b' + re.escape(identifier) + r'\b[^>]*?)(?<!/)( *>)'
        )

        def replacer(m):
            if "onClick" in m.group(2):
                return m.group(0)
            return m.group(1) + m.group(2) + ' onClick={() => {}}' + m.group(3)

        new_content = pattern.sub(replacer, content)
        if new_content != content:
            return new_content
    return content


def _add_todo_comment(content, cls, camel, comment_text):
    """Insert a /* TODO */ JSX comment BEFORE the element containing cls/camel."""
    for identifier in [cls, camel]:
        # Find the line that contains this identifier
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if identifier in line:
                indent = re.match(r'^(\s*)', line).group(1)
                todo_line = f"{indent}{{/* TODO: {comment_text} */}}"
                if todo_line not in content:
                    lines.insert(i, todo_line)
                    return "\n".join(lines)
                break
    return content


# ═══════════════════════════════════════════════════════════════════════════
# ─── Patch strategies (one per interaction_type) ──────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def apply_detection(det, project_dir, framework, patcher):
    """Apply a single detection. Returns action string or None.

    HIGH  → applied directly.
    MEDIUM → applied WITH a TODO comment.
    LOW   → NOT applied (report only).
    """
    if det.confidence == "LOW":
        return None  # report only

    files, cls, camel = find_node_in_files(project_dir, det.node)

    is_medium = det.confidence == "MEDIUM"
    todo_text = f"verify interaction — detected as '{det.interaction_type}' from node '{det.node_name}' (id={det.node_id})"

    handler = _APPLY_MAP.get(det.interaction_type)
    if not handler:
        return None

    # For nav/pagination, we may need to search child nodes even if parent isn't in files
    if not files and det.interaction_type in ("nav", "pagination"):
        # Pass empty files list — handler will search for children project-wide
        pass
    elif not files:
        return None

    # Store project_dir on patcher for broader searches
    patcher._project_dir = project_dir
    return handler(det, files, cls, camel, framework, patcher, is_medium, todo_text)


# ── Individual apply functions ────────────────────────────────────────────

def _apply_button(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    for fpath in files:
        content = patcher.read(fpath)
        if is_medium:
            content = _add_todo_comment(content, cls, camel, todo_text)
        content = _add_tailwind_classes(content, cls, camel,
                                        "cursor-pointer hover:opacity-80 transition-opacity")
        new_content = _add_onclick(content, cls, camel)
        if new_content != content:
            patcher.mark_use_client(str(fpath))
            content = new_content
        patcher.write(fpath, content)
    text_info = f" (text: '{det.figma_text}')" if det.figma_text else ""
    return f"Added cursor-pointer + hover + onClick{text_info}"


def _apply_link(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    for fpath in files:
        content = patcher.read(fpath)
        if is_medium:
            content = _add_todo_comment(content, cls, camel, todo_text)
        content = _add_tailwind_classes(content, cls, camel,
                                        "cursor-pointer hover:opacity-80 transition-opacity")
        new_content = _add_onclick(content, cls, camel)
        if new_content != content:
            patcher.mark_use_client(str(fpath))
            content = new_content
        patcher.write(fpath, content)
    text_info = f" (text: '{det.figma_text}')" if det.figma_text else ""
    return f"Added cursor-pointer + hover + onClick{text_info}"


def _apply_nav(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    """Add hover to text items inside the nav node."""
    texts = det.figma_children_text
    patched = 0
    project_dir = getattr(patcher, '_project_dir', None)
    for t in texts:
        tnode = t["node"]
        # Search project-wide for each text child node
        tfiles, tcls, tcamel = find_node_in_files(project_dir, tnode) if project_dir else ([], "", "")
        for fpath in tfiles:
            content = patcher.read(fpath)
            content = _add_tailwind_classes(content, tcls, tcamel,
                                            "cursor-pointer hover:opacity-70 transition-opacity")
            patcher.write(fpath, content)
            patched += 1
    if not patched:
        return None
    names = ", ".join(f"'{t['characters']}'" for t in texts[:5])
    return f"Added hover to {patched} nav items: [{names}]"


def _apply_input(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    placeholder = det.figma_placeholder  # from actual Figma TEXT node, never invented
    for fpath in files:
        content = patcher.read(fpath)
        if is_medium:
            content = _add_todo_comment(content, cls, camel, todo_text)
        content = _add_tailwind_classes(content, cls, camel,
                                        "focus-within:ring-2 focus-within:ring-blue-500 transition-shadow")
        # Also style placeholder text nodes inside as dim
        for t in det.figma_children_text:
            tcls = sanitize_class(t["node"])
            tcamel = to_camel(tcls)
            content = _add_tailwind_classes(content, tcls, tcamel, "opacity-60")
        patcher.write(fpath, content)
    ph_info = f" (placeholder from Figma: '{placeholder}')" if placeholder else ""
    return f"Added focus ring{ph_info}"


def _apply_card(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    for fpath in files:
        content = patcher.read(fpath)
        if is_medium:
            content = _add_todo_comment(content, cls, camel, todo_text)
        content = _add_tailwind_classes(content, cls, camel,
                                        "cursor-pointer hover:shadow-lg transition-shadow")
        patcher.write(fpath, content)
    return "Added hover:shadow-lg + cursor-pointer"


def _apply_tab(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    for fpath in files:
        content = patcher.read(fpath)
        if is_medium:
            content = _add_todo_comment(content, cls, camel, todo_text)
        content = _add_tailwind_classes(content, cls, camel,
                                        "cursor-pointer hover:opacity-80 transition-opacity")
        patcher.write(fpath, content)
    text_info = f" (text: '{det.figma_text}')" if det.figma_text else ""
    return f"Added cursor-pointer + hover{text_info}"


def _apply_pagination(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    """Patch pagination container and its sub-parts."""
    project_dir = getattr(patcher, '_project_dir', None)
    search_files = files
    if not search_files and project_dir:
        # Pagination parent not in files — search project-wide for sub-parts
        search_files = list(Path(project_dir).rglob("*.tsx")) + list(Path(project_dir).rglob("*.jsx"))

    patched_subs = 0
    for fpath in search_files:
        content = patcher.read(fpath)
        modified = False
        for sub in det.sub_detections:
            scls = sanitize_class(sub.node)
            scamel = to_camel(scls)
            if scls not in content and scamel not in content:
                continue
            if sub.interaction_type == "pagination_number":
                content = _add_tailwind_classes(content, scls, scamel,
                                                "cursor-pointer hover:opacity-70 transition-opacity")
                modified = True
                patched_subs += 1
            elif sub.interaction_type == "pagination_button":
                content = _add_tailwind_classes(content, scls, scamel,
                                                "cursor-pointer hover:opacity-80 transition-opacity")
                modified = True
                patched_subs += 1
        if modified:
            patcher.write(fpath, content)

    if not patched_subs and not files:
        return None
    return f"Added hover to pagination ({patched_subs} sub-elements patched)"


def _apply_footer_link(det, files, cls, camel, framework, patcher, is_medium, todo_text):
    for fpath in files:
        content = patcher.read(fpath)
        if is_medium:
            content = _add_todo_comment(content, cls, camel, todo_text)
        content = _add_tailwind_classes(content, cls, camel,
                                        "cursor-pointer hover:underline transition-all")
        patcher.write(fpath, content)
    return f"Added hover:underline (text from Figma: '{det.figma_text}')"


_APPLY_MAP = {
    "button": _apply_button,
    "link": _apply_link,
    "nav": _apply_nav,
    "input": _apply_input,
    "card": _apply_card,
    "tab": _apply_tab,
    "pagination": _apply_pagination,
    "footer_link": _apply_footer_link,
}


# ═══════════════════════════════════════════════════════════════════════════
# ─── Report ───────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def write_report(project_dir, detections, actions, modified_files):
    """Write interactivity-report.json with full traceability."""
    report_entries = []

    for det in detections:
        entry = det.to_report_dict()
        action = actions.get(det.node_id)
        if action:
            entry["action"] = action
            entry["applied"] = True
        else:
            entry["applied"] = det.confidence == "LOW"  # False for LOW (not applied)
            entry["applied"] = False
            if det.confidence == "LOW":
                entry["skippedReason"] = "LOW confidence — not auto-applied, listed for manual review"
            else:
                entry["skippedReason"] = "Could not locate node in generated files"
        report_entries.append(entry)

    report = OrderedDict()
    report["detections"] = report_entries
    report["summary"] = {
        "total_detected": len(detections),
        "high_confidence": sum(1 for d in detections if d.confidence == "HIGH"),
        "medium_confidence": sum(1 for d in detections if d.confidence == "MEDIUM"),
        "low_confidence": sum(1 for d in detections if d.confidence == "LOW"),
        "applied": sum(1 for a in actions.values() if a),
        "skipped": len(detections) - sum(1 for a in actions.values() if a),
    }
    report["modified_files"] = modified_files

    report_path = project_dir / "interactivity-report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    return report_path


# ═══════════════════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Add interactivity to generated Figma projects")
    parser.add_argument("--input", required=True, help="Input directory with design.json")
    parser.add_argument("--project", required=True, help="Generated project directory to patch")
    parser.add_argument("--framework", default="nextjs", choices=["html", "react", "nextjs"],
                        help="Framework of the generated project (default: nextjs)")
    args = parser.parse_args()

    input_dir = Path(args.input).resolve()
    project_dir = Path(args.project).resolve()

    design_path = input_dir / "design.json"
    if not design_path.exists():
        print(f"Error: {design_path} not found", file=sys.stderr)
        sys.exit(1)
    if not project_dir.exists():
        print(f"Error: {project_dir} not found", file=sys.stderr)
        sys.exit(1)

    with open(design_path) as f:
        design = json.load(f)

    root = design.get("root")
    if not root:
        print("Error: No 'root' key in design.json", file=sys.stderr)
        sys.exit(1)

    # ── Step 1: Scan ──
    print("🔍 Scanning design.json for interactive elements...")
    detections = scan_tree(root, root)

    high = [d for d in detections if d.confidence == "HIGH"]
    medium = [d for d in detections if d.confidence == "MEDIUM"]
    low = [d for d in detections if d.confidence == "LOW"]
    print(f"   Found {len(detections)} elements: {len(high)} HIGH, {len(medium)} MEDIUM, {len(low)} LOW")

    if not detections:
        print("   Nothing to patch.")
        write_report(project_dir, [], {}, [])
        return

    # ── Step 2: Apply ──
    print("\n🔧 Applying interactivity patches...")
    patcher = FilePatcher()
    actions = {}  # nodeId -> action string

    for det in detections:
        action = apply_detection(det, project_dir, args.framework, patcher)
        if action:
            actions[det.node_id] = action
            conf_badge = {"HIGH": "✅", "MEDIUM": "⚠️", "LOW": "⏭️"}[det.confidence]
            print(f"   {conf_badge} [{det.confidence}] {det.interaction_type}: '{det.node_name}' → {action}")
        elif det.confidence == "LOW":
            print(f"   ⏭️  [LOW] {det.interaction_type}: '{det.node_name}' — skipped (report only)")
        else:
            print(f"   ❌ [{det.confidence}] {det.interaction_type}: '{det.node_name}' — node not found in generated files")

    # ── Step 3: Flush ──
    modified_files = patcher.flush(project_dir)

    # ── Step 4: Report ──
    report_path = write_report(project_dir, detections, actions, modified_files)

    print(f"\n✅ Interactivity complete:")
    print(f"   Applied: {len(actions)} / {len(detections)} detections")
    print(f"   Modified files: {len(modified_files)}")
    for f in modified_files:
        print(f"     • {f}")
    print(f"   Report: {report_path}")


if __name__ == "__main__":
    main()
