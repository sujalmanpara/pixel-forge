# Figma REST API Reference

Quick reference for the endpoints used by the figma-perfect skill.

**Base URL:** `https://api.figma.com`
**Authentication:** `X-Figma-Token: {personal_access_token}` header

---

## Authentication

Get your token at: https://www.figma.com/developers/api#access-tokens

Personal access tokens never expire (until manually revoked). OAuth tokens expire after 2 weeks.

```python
headers = {
    "X-Figma-Token": "your-token-here"
}
```

---

## Endpoints

### GET /v1/files/{key}
Fetch full file metadata including the complete node tree.

**Warning:** Large files may return very large JSON. Prefer `/nodes` when you know the node ID.

```
GET https://api.figma.com/v1/files/{file_key}
```

**Query params:**
| Param | Type | Description |
|---|---|---|
| `version` | string | Specific version ID (optional) |
| `ids` | string | Comma-separated node IDs to filter |
| `depth` | int | Node tree depth limit |
| `geometry` | string | Set to `paths` to include vector paths |
| `plugin_data` | string | Plugin data to include |
| `branch_data` | boolean | Include branch metadata |

**Response:**
```json
{
  "name": "My Design File",
  "lastModified": "2024-01-01T00:00:00Z",
  "thumbnailUrl": "https://...",
  "version": "1234567890",
  "document": {
    "id": "0:0",
    "name": "Document",
    "type": "DOCUMENT",
    "children": [...]
  },
  "components": {},
  "componentSets": {},
  "schemaVersion": 0,
  "styles": {}
}
```

---

### GET /v1/files/{key}/nodes
Fetch specific nodes by ID (much faster than fetching the whole file).

```
GET https://api.figma.com/v1/files/{file_key}/nodes?ids={node_ids}
```

**Query params:**
| Param | Type | Description |
|---|---|---|
| `ids` | string | **Required.** Comma-separated node IDs (e.g. `217:3340,217:3341`) |
| `version` | string | Specific version ID |
| `depth` | int | Node tree depth limit |
| `geometry` | string | Set to `paths` for vector paths |
| `plugin_data` | string | Plugin data IDs |

**Node ID format:**
- From URL: `?node-id=217-3340` → API format: `217:3340` (replace `-` with `:`)
- Multiple: `217:3340,217:3341`
- URL-encoded: `217%3A3340`

**Response:**
```json
{
  "name": "My Design File",
  "lastModified": "2024-01-01T00:00:00Z",
  "thumbnailUrl": "https://...",
  "version": "1234567890",
  "nodes": {
    "217:3340": {
      "document": { ...node data... },
      "components": {},
      "schemaVersion": 0,
      "styles": {}
    }
  }
}
```

---

### GET /v1/images/{key}
Render nodes as images.

```
GET https://api.figma.com/v1/images/{file_key}?ids={node_ids}&format=png&scale=2
```

**Query params:**
| Param | Type | Description |
|---|---|---|
| `ids` | string | **Required.** Comma-separated node IDs |
| `scale` | float | Export scale 0.01–4 (default: 1). Use 2 for retina |
| `format` | string | `png`, `jpg`, `svg`, `pdf` (default: `png`) |
| `svg_include_id` | boolean | Include node IDs in SVG |
| `svg_simplify_stroke` | boolean | Simplify SVG strokes |
| `use_absolute_bounds` | boolean | Use absolute bounds (include clip) |
| `version` | string | Specific file version |
| `contents_only` | boolean | Render contents only (no background) |

**Response:**
```json
{
  "err": null,
  "images": {
    "217:3340": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/...",
    "217:3341": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/..."
  }
}
```

**Notes:**
- Image URLs expire after ~30 minutes — download immediately
- Batch up to ~100 nodes per request to avoid timeouts
- For huge files, process in batches of 50

---

### GET /v1/files/{key}/images
Get URLs for all image fills used in the file.

```
GET https://api.figma.com/v1/files/{file_key}/images
```

**Response:**
```json
{
  "err": null,
  "images": {
    "abc123def456": "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/..."
  }
}
```

**Note:** The keys here are `imageRef` values found in IMAGE-type fills. Use this to resolve image fill URLs without re-rendering nodes.

---

### GET /v1/files/{key}/components
List all published components in the file.

```
GET https://api.figma.com/v1/files/{file_key}/components
```

---

### GET /v1/files/{key}/styles
List all published styles in the file.

```
GET https://api.figma.com/v1/files/{file_key}/styles
```

---

## URL Parsing

Figma URLs follow this pattern:
```
https://www.figma.com/design/{file_key}/{file_name}?node-id={node_id}
https://www.figma.com/file/{file_key}/{file_name}?node-id={node_id}
https://www.figma.com/proto/{file_key}/{file_name}?node-id={node_id}
```

**Parsing logic:**
```python
import re
from urllib.parse import urlparse, parse_qs

def parse_figma_url(url):
    parsed = urlparse(url)
    # Extract file key from path: /design/{key}/ or /file/{key}/
    path_match = re.match(r'^/(design|file|proto)/([^/]+)', parsed.path)
    if not path_match:
        raise ValueError(f"Not a valid Figma URL: {url}")
    
    file_key = path_match.group(2)
    
    # Extract node ID from query string
    params = parse_qs(parsed.query)
    node_id = None
    if 'node-id' in params:
        raw_id = params['node-id'][0]
        # Convert URL format (217-3340) to API format (217:3340)
        node_id = raw_id.replace('-', ':')
    
    return file_key, node_id
```

---

## Rate Limits

- **Read API:** 300 requests/minute per token (as of 2024)
- **Images API:** 50 requests/minute per token
- On `429 Too Many Requests`: wait `Retry-After` seconds, then retry
- On `503 Service Unavailable`: exponential backoff (1s, 2s, 4s, 8s...)

**Best practices:**
- Batch node IDs in a single request instead of one request per node
- Cache responses locally — file data rarely changes mid-session
- For large files, use `/nodes` instead of full `/files` endpoint

---

## Error Codes

| Code | Meaning | Action |
|---|---|---|
| `400` | Bad request (invalid params) | Check node ID format |
| `403` | Forbidden | Check token, check file permissions |
| `404` | File/node not found | Verify file key and node ID |
| `429` | Rate limit exceeded | Backoff and retry |
| `500` | Figma server error | Retry with exponential backoff |
| `503` | Service unavailable | Retry with exponential backoff |

---

## Common Patterns

### Fetch a single frame and all its children
```python
resp = requests.get(
    f"https://api.figma.com/v1/files/{file_key}/nodes",
    headers={"X-Figma-Token": token},
    params={"ids": node_id, "depth": 100}
)
data = resp.json()
node = data["nodes"][node_id]["document"]
```

### Export multiple nodes as PNG
```python
node_ids = ["217:3340", "217:3341", "217:3342"]
resp = requests.get(
    f"https://api.figma.com/v1/images/{file_key}",
    headers={"X-Figma-Token": token},
    params={"ids": ",".join(node_ids), "format": "png", "scale": "2"}
)
images = resp.json()["images"]
# images = {"217:3340": "https://...url", ...}
```

### Download an image URL
```python
import urllib.request

def download_image(url, path):
    urllib.request.urlretrieve(url, path)
```

### Get all image fill URLs
```python
resp = requests.get(
    f"https://api.figma.com/v1/files/{file_key}/images",
    headers={"X-Figma-Token": token}
)
image_fills = resp.json()["images"]
# image_fills = {"imageRef": "https://...url", ...}
```
