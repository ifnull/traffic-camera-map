# Austin Traffic Camera Map

An interactive web map of the City of Austin ATD traffic-camera network, plus the
tooling that builds and quality-checks its data.

The public-facing piece is a single static page (`index.html`) that plots every
camera on a Leaflet map, lets you search and filter by status, and shows a live
screenshot preview in each camera's popup. Behind it sit two Python utilities: one
that converts the city's CSV export into the map's data file, and one that audits
the camera feeds to find dead, black, or frozen images.

> **Status: proof of concept.** The map and tooling work end to end, but the data
> pipeline is manual and the feed audit is not yet wired into the map. See
> [`ASSESSMENT.md`](./ASSESSMENT.md) for a full evaluation and roadmap.

## Repository layout

| File | Purpose |
| --- | --- |
| `index.html` | The map. Self-contained HTML/CSS/JS, no build step. Loads `cameras.json` at runtime. |
| `cameras.json` | Camera dataset the map reads (1,004 records). Generated from the city CSV. |
| `csv_to_cameras_json.py` | Converts an Austin traffic-camera CSV export into `cameras.json`. |
| `audit_cameras.py` | Downloads and analyzes each camera's screenshot to classify feed health. |
| `requirements.txt` | Python dependencies for the audit and conversion tooling. |

## The map (`index.html`)

Features:

- **All cameras plotted** with marker clustering (Leaflet + markercluster).
- **Status filter** — All / Turned On / Desired / Removed / Void.
- **Search** across name, ID, landmark, streets, ATD location, signal area, and more.
- **Live screenshot preview** in each popup, with a graceful "Preview unavailable"
  fallback when a feed is down.
- **"Locate me"** geolocation with a live position marker and accuracy ring.
- **Responsive** — slide-out panel on mobile.
- **Analytics** via Google Analytics (gtag).

It is a static file. Serve the repo root with any static server:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

`index.html` fetches `cameras.json` from the same directory, so both must be served
together.

## Data pipeline

Camera data originates from the City of Austin's published traffic-camera dataset,
exported as CSV. Convert it to the map's JSON with:

```bash
python3 csv_to_cameras_json.py Traffic_Cameras_YYYYMMDD.csv -o cameras.json
```

- Rows without a valid WKT `POINT (lon lat)` location are skipped (and counted).
- Use `--pretty` for human-readable JSON; the default is compact for smaller
  page loads.

The current dataset breaks down as:

| Status | Count |
| --- | --- |
| Turned On | 817 |
| Desired | 124 |
| Void | 33 |
| Removed | 30 |
| **Total** | **1,004** |

## Feed audit (`audit_cameras.py`)

Screenshots are served from `https://cctv.austinmobility.io/image/<id>.jpg`
(CloudFront in front of S3). The audit tool downloads each one, computes image
metrics, and classifies the feed as live, black, blank/solid, a possible
logo/placeholder, or an HTTP/network error. An optional second pass re-captures
each feed after a delay to flag frozen (unchanged) frames.

Setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Basic run (audits `TURNED_ON` cameras by default):

```bash
python3 audit_cameras.py cameras.json
```

Useful options:

```bash
# Save a JPEG of every downloaded frame
python3 audit_cameras.py cameras.json --save-all-images

# Save only frames flagged as suspicious
python3 audit_cameras.py cameras.json --save-suspects

# Detect frozen feeds by re-capturing after 60 seconds
python3 audit_cameras.py cameras.json --second-pass-delay 60 --save-suspects

# Include DESIRED / VOID / REMOVED entries too
python3 audit_cameras.py cameras.json --include-non-active
```

Output is written under `camera_audit_output/`:

- `camera_audit.csv` and `camera_audit.json` — per-camera metrics and classification
- `images/` — all frames (with `--save-all-images`)
- `suspect_images/` — flagged frames (with `--save-suspects`)

A recent full run of the 817 active feeds returned **810 live** and **7 hard
`403` errors** (cameras that are forbidden on the origin for everyone, confirmed
with `curl`).

### Interpretation note

An unchanged image is **not** proof that a feed is broken. A quiet intersection, a
fixed station logo, or a cached response can all look static. Treat `unchanged_frame`
and other suspicious classifications as review flags, not definitive failures.

## Data source

City of Austin Transportation & Public Works — traffic camera inventory, published
on the city's open-data portal. Screenshots are the city's own public camera images.
Refreshing the dataset is currently a manual export-and-convert step.
