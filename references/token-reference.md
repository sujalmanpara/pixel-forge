# Figma Node Token Reference

Quick reference for reading design tokens from Figma API node properties.

---

## Colors

Figma stores colors as RGBA with float values 0–1.

```json
{
  "fills": [
    {
      "type": "SOLID",
      "color": { "r": 0.063, "g": 0.776, "b": 0.337, "a": 1.0 },
      "opacity": 1.0
    }
  ]
}
```

**Conversion to hex:**
```python
def rgba_to_hex(color, opacity=1.0):
    r = round(color['r'] * 255)
    g = round(color['g'] * 255)
    b = round(color['b'] * 255)
    a = round((color.get('a', 1.0) * opacity) * 255)
    if a == 255:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}{a:02X}"

def rgba_to_css(color, opacity=1.0):
    r = round(color['r'] * 255)
    g = round(color['g'] * 255)
    b = round(color['b'] * 255)
    a = color.get('a', 1.0) * opacity
    if a == 1.0:
        return f"rgb({r}, {g}, {b})"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"
```

**Fill types:**
- `SOLID` — flat color fill
- `GRADIENT_LINEAR` — linear gradient
- `GRADIENT_RADIAL` — radial gradient
- `GRADIENT_ANGULAR` — conic gradient
- `GRADIENT_DIAMOND` — diamond gradient
- `IMAGE` — image fill (needs image export)
- `PATTERN` — repeating pattern

---

## Gradients

```json
{
  "fills": [
    {
      "type": "GRADIENT_LINEAR",
      "gradientHandlePositions": [
        {"x": 0.5, "y": 0.0},
        {"x": 0.5, "y": 1.0},
        {"x": 1.0, "y": 0.0}
      ],
      "gradientStops": [
        {"position": 0.0, "color": {"r": 0.1, "g": 0.1, "b": 0.1, "a": 1.0}},
        {"position": 1.0, "color": {"r": 0.9, "g": 0.9, "b": 0.9, "a": 1.0}}
      ]
    }
  ]
}
```

**Computing gradient angle:**
The `gradientHandlePositions` are normalized (0–1) relative to the bounding box.
- Handle[0] = start point
- Handle[1] = end point
- Handle[2] = width handle (perpendicular)

```python
import math

def compute_gradient_angle(handles):
    start = handles[0]
    end = handles[1]
    dx = end['x'] - start['x']
    dy = end['y'] - start['y']
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad) + 90  # CSS uses 0=top, clockwise
    return round(angle_deg % 360)

def gradient_to_css(fill):
    angle = compute_gradient_angle(fill['gradientHandlePositions'])
    stops = []
    for stop in fill['gradientStops']:
        color = rgba_to_hex(stop['color'])
        pct = round(stop['position'] * 100)
        stops.append(f"{color} {pct}%")
    return f"linear-gradient({angle}deg, {', '.join(stops)})"
```

---

## Typography

Figma text nodes have a `style` property:

```json
{
  "type": "TEXT",
  "characters": "Hello World",
  "style": {
    "fontFamily": "Inter",
    "fontPostScriptName": "Inter-Bold",
    "fontWeight": 700,
    "fontSize": 48,
    "textAlignHorizontal": "LEFT",
    "textAlignVertical": "TOP",
    "letterSpacing": -0.5,
    "lineHeightPx": 57.6,
    "lineHeightPercent": 120,
    "lineHeightUnit": "INTRINSIC_%",
    "italic": false,
    "textDecoration": "NONE",
    "textCase": "ORIGINAL"
  }
}
```

**Key properties:**
| Figma Property | CSS Equivalent |
|---|---|
| `fontFamily` | `font-family` |
| `fontSize` | `font-size` (px) |
| `fontWeight` | `font-weight` |
| `lineHeightPx` | `line-height` (px) |
| `letterSpacing` | `letter-spacing` (px, divide by fontSize for em) |
| `textAlignHorizontal` | `text-align` (LEFT/RIGHT/CENTER/JUSTIFIED) |
| `italic` | `font-style: italic` |
| `textDecoration` | `text-decoration` (NONE/UNDERLINE/STRIKETHROUGH) |
| `textCase` | `text-transform` (ORIGINAL/UPPER/LOWER/TITLE) |

---

## Layout (Auto Layout)

Auto Layout maps directly to CSS Flexbox:

```json
{
  "layoutMode": "HORIZONTAL",
  "primaryAxisAlignItems": "SPACE_BETWEEN",
  "counterAxisAlignItems": "CENTER",
  "paddingLeft": 24,
  "paddingRight": 24,
  "paddingTop": 16,
  "paddingBottom": 16,
  "itemSpacing": 12,
  "layoutSizingHorizontal": "FILL",
  "layoutSizingVertical": "HUG"
}
```

**Mapping:**
| Figma | CSS |
|---|---|
| `layoutMode: HORIZONTAL` | `flex-direction: row` |
| `layoutMode: VERTICAL` | `flex-direction: column` |
| `layoutMode: NONE` | no flex |
| `primaryAxisAlignItems: MIN` | `justify-content: flex-start` |
| `primaryAxisAlignItems: CENTER` | `justify-content: center` |
| `primaryAxisAlignItems: MAX` | `justify-content: flex-end` |
| `primaryAxisAlignItems: SPACE_BETWEEN` | `justify-content: space-between` |
| `counterAxisAlignItems: MIN` | `align-items: flex-start` |
| `counterAxisAlignItems: CENTER` | `align-items: center` |
| `counterAxisAlignItems: MAX` | `align-items: flex-end` |
| `counterAxisAlignItems: BASELINE` | `align-items: baseline` |
| `layoutSizingHorizontal: FILL` | `width: 100%` or `flex: 1` |
| `layoutSizingHorizontal: HUG` | `width: fit-content` |
| `layoutSizingHorizontal: FIXED` | `width: {absoluteBoundingBox.width}px` |
| `itemSpacing` | `gap` |
| `padding*` | `padding` |

**Wrap:**
```json
"layoutWrap": "WRAP"   →   flex-wrap: wrap
"layoutWrap": "NO_WRAP" →  flex-wrap: nowrap
```

---

## Effects (Shadows & Blur)

```json
{
  "effects": [
    {
      "type": "DROP_SHADOW",
      "visible": true,
      "color": {"r": 0, "g": 0, "b": 0, "a": 0.15},
      "offset": {"x": 0, "y": 4},
      "radius": 20,
      "spread": 0,
      "blendMode": "NORMAL"
    },
    {
      "type": "INNER_SHADOW",
      "visible": true,
      "color": {"r": 0, "g": 0, "b": 0, "a": 0.1},
      "offset": {"x": 0, "y": 2},
      "radius": 8,
      "spread": 0
    },
    {
      "type": "LAYER_BLUR",
      "visible": true,
      "radius": 10
    },
    {
      "type": "BACKGROUND_BLUR",
      "visible": true,
      "radius": 20
    }
  ]
}
```

**CSS mapping:**
```python
def shadow_to_css(effect):
    c = effect['color']
    x = effect['offset']['x']
    y = effect['offset']['y']
    blur = effect['radius']
    spread = effect.get('spread', 0)
    color = rgba_to_css(c)
    inset = "inset " if effect['type'] == 'INNER_SHADOW' else ""
    return f"{inset}{x}px {y}px {blur}px {spread}px {color}"

# LAYER_BLUR → filter: blur(10px)
# BACKGROUND_BLUR → backdrop-filter: blur(20px)
```

---

## Borders & Corner Radius

```json
{
  "cornerRadius": 12,
  "rectangleCornerRadii": [12, 12, 0, 0],
  "strokes": [
    {
      "type": "SOLID",
      "color": {"r": 0.8, "g": 0.8, "b": 0.8, "a": 1.0},
      "opacity": 1.0
    }
  ],
  "strokeWeight": 1,
  "strokeAlign": "INSIDE",
  "dashPattern": []
}
```

**CSS mapping:**
- `cornerRadius` → `border-radius: {value}px`
- `rectangleCornerRadii` → `border-radius: {tl}px {tr}px {br}px {bl}px` (top-left, top-right, bottom-right, bottom-left)
- `strokeWeight` + `strokes[0].color` → `border: {weight}px solid {color}`
- `strokeAlign: INSIDE` → use `outline` or `box-shadow: inset` to avoid layout shift
- `strokeAlign: OUTSIDE` → `outline: {weight}px solid {color}; outline-offset: {weight}px`
- `dashPattern: [5, 3]` → `border-style: dashed`

---

## Constraints

```json
{
  "constraints": {
    "horizontal": "LEFT_RIGHT",
    "vertical": "TOP"
  }
}
```

**Types:**
| Value | Meaning |
|---|---|
| `LEFT` | Anchored to left |
| `RIGHT` | Anchored to right |
| `LEFT_RIGHT` | Stretches horizontally |
| `CENTER` | Centered horizontally |
| `SCALE` | Scales proportionally |
| `TOP` | Anchored to top |
| `BOTTOM` | Anchored to bottom |
| `TOP_BOTTOM` | Stretches vertically |

In Auto Layout frames, constraints are overridden by the layout.
In absolute-positioned frames, use `position: absolute` with matching offsets.

---

## Dimensions

```json
{
  "absoluteBoundingBox": {
    "x": 0,
    "y": 0,
    "width": 1440,
    "height": 900
  }
}
```

- `x`, `y` — position relative to the canvas (NOT the parent)
- `width`, `height` — actual rendered dimensions in pixels
- For relative positioning, subtract parent's `absoluteBoundingBox.x/y`

---

## Node Types

| Type | Description | Key Properties |
|---|---|---|
| `DOCUMENT` | Root document | `children[]` |
| `CANVAS` | A page | `children[]`, `backgroundColor` |
| `FRAME` | Container (div) | layout props, fills, effects |
| `GROUP` | Logical grouping | `children[]` |
| `COMPONENT` | Reusable master | Same as FRAME |
| `COMPONENT_SET` | Component variants | `children[]` of COMPONENTs |
| `INSTANCE` | Component instance | `componentId`, overrides |
| `TEXT` | Text node | `characters`, `style` |
| `RECTANGLE` | Rectangle shape | fills, cornerRadius |
| `ELLIPSE` | Circle/ellipse | fills, `arcData` |
| `VECTOR` | Vector path | fills, strokes |
| `BOOLEAN_OPERATION` | Path boolean | `booleanOperation`, `children[]` |
| `STAR` | Star shape | fills, strokes |
| `LINE` | Line | strokes |
| `SECTION` | Section grouping | `children[]` |

---

## Image Fills

When a node has an IMAGE fill:
```json
{
  "fills": [
    {
      "type": "IMAGE",
      "imageRef": "abc123def456...",
      "scaleMode": "FILL",
      "imageTransform": [[1,0,0],[0,1,0]]
    }
  ]
}
```

- `imageRef` — key to look up in `/v1/files/{key}/images` response
- `scaleMode`: `FILL` → `object-fit: cover`, `FIT` → `object-fit: contain`, `CROP` → `object-fit: cover` with transform, `TILE` → `background-repeat: repeat`
- Export the image via `/v1/images/{file_key}?ids={node_id}&format=png`

---

## Opacity & Blend Mode

```json
{
  "opacity": 0.8,
  "blendMode": "MULTIPLY"
}
```

- `opacity` → CSS `opacity`
- Common `blendMode` values → CSS `mix-blend-mode`:
  - `NORMAL` → `normal`
  - `MULTIPLY` → `multiply`
  - `SCREEN` → `screen`
  - `OVERLAY` → `overlay`
  - `DARKEN` → `darken`
  - `LIGHTEN` → `lighten`
  - `COLOR_DODGE` → `color-dodge`
  - `COLOR_BURN` → `color-burn`
  - `HARD_LIGHT` → `hard-light`
  - `SOFT_LIGHT` → `soft-light`
  - `DIFFERENCE` → `difference`
  - `EXCLUSION` → `exclusion`
  - `HUE` → `hue`
  - `SATURATION` → `saturation`
  - `COLOR` → `color`
  - `LUMINOSITY` → `luminosity`
