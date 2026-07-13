# Austin Area Cameras

An interactive web map that aggregates **Austin-area public cameras into one place** — a general view of the area, traffic included. City of Austin ATD snapshots, TxDOT live traffic video, and curated public webcams (skylines, resorts, businesses) side by side, plus the tooling that builds and quality-checks the data.

The map (`index.html`) is a single static page that plots every camera, filters by source, searches, and renders each feed in its native form: a JPEG snapshot for City cameras, a live HLS video stream for TxDOT and most webcams, and an embedded player for iframe-only webcams. A small Python pipeline turns each provider's raw data into one normalized `cameras.json`.

> **Status: proof of concept.** Three sources are unified end to end (1,246 cameras). The data refresh is manual and feed-health auditing currently covers only the City JPEG feeds. See [`ASSESSMENT.md`](./ASSESSMENT.md) for the evaluation and roadmap.

## Repository layout

| Path | Purpose |
| --- | --- |
| `index.html` | The map. Static HTML/CSS/JS, no build step. Renders image and HLS feeds. Loads `cameras.json`. |
| `cameras.json` | **Generated** unified dataset the map serves. Do not edit by hand — run `build.py`. |
| `build.py` | Merges all source adapters into `cameras.json`. |
| `adapters/` | One adapter per provider, all emitting the shared schema. |
| `adapters/schema.py` | The normalized record shape + validation. |
| `adapters/coa.py` | City of Austin adapter (JPEG snapshots). |
| `adapters/txdot.py` | TxDOT adapter (HLS video, coordinates from MapLarge). |
| `adapters/curated.py` | Curated public-webcam adapter (hand-maintained list). |
| `sources/` | Per-source inputs (`coa.json`, `txdot_raw.json`, `curated.json`). |
| `csv_to_cameras_json.py` | Converts a City CSV export into `sources/coa.json`. |
| `audit_cameras.py` | Downloads and classifies City JPEG feeds (health check). |

## Architecture

```
  City CSV ──► csv_to_cameras_json.py ──► sources/coa.json ─────────┐
                                                                    │
  TxDOT MapLarge API ──► adapters/txdot.py ──► sources/txdot_raw.json ├─► build.py ──► cameras.json ──► index.html
                                                                    │
  Hand-maintained sources/curated.json ─────────────────────────────┘
```

Every source normalizes into one record shape (`adapters/schema.py`):

```json
{
  "id": "coa-229" | "txdot-TX_AUS_001" | "webcam-indeed",
  "source": "coa" | "txdot" | "webcam",
  "name": "IH-35 @ 11th",
  "lat": 30.27, "lon": -97.73,
  "feed": { "type": "image" | "hls" | "iframe", "url": "..." },
  "status": "TURNED_ON" | "ACTIVE" | ...,
  "meta": { "...source-specific fields shown in the popup..." }
}
```

`feed.type` is the field the map branches on (`image` → `<img>`, `hls` →
hls.js `<video>`, `iframe` → embedded player). Adding a new provider (Travis
County, UT, etc.) is one new file in `adapters/` plus a line in `build.py` — no
schema change.

## Building the data

```bash
python3 build.py                  # rebuild cameras.json from cached sources
python3 build.py --refresh-txdot  # re-fetch TxDOT from MapLarge first
python3 build.py --pretty         # human-readable output
```

`build.py` validates every record (unique IDs, Texas-bounded coordinates, a usable feed URL) and prints any problems before writing.

### Refreshing each source

- **City of Austin** — export the traffic-camera CSV from the city open-data portal, then:
  ```bash
  python3 csv_to_cameras_json.py Traffic_Cameras_YYYYMMDD.csv   # writes sources/coa.json
  python3 build.py
  ```
- **TxDOT** — `build.py --refresh-txdot` re-queries the MapLarge camera table for the
  Austin district and refreshes `sources/txdot_raw.json`.
- **Curated webcams** — edit `sources/curated.json` by hand: add an entry with its
  feed URL, `feed_type` (`hls` or `iframe`), and a looked-up `lat`/`lon`. Set
  `"include": false` to hold one back (e.g. missing coordinates). Then `python3 build.py`.

Current dataset: **1,004 City** + **227 TxDOT** + **15 webcams** = **1,246 total**.
Note: the map spans the wider Austin area, not just the city — TxDOT's "Austin"
jurisdiction runs up I-35 to the Bell County line, and curated webcams include
spots like Horseshoe Bay and Lockhart. The initial view frames on central Austin.

## The map (`index.html`)

- **All sources on one map** with marker clustering, colored by source (City = green, TxDOT = blue, Webcams = orange).
- **Source filter** — All / City / TxDOT / Webcams. City adds a contextual status sub-filter (On / Desired / Removed / Void) that only applies to City cameras.
- **Search** across name, ID, route, streets, landmark, category, and more.
- **Native rendering per feed:** City cameras show a JPEG snapshot; TxDOT and most
  webcams play live HLS video (via [hls.js](https://github.com/video-dev/hls.js),
  native on Safari) with a "Live" badge; iframe-only webcams embed their player.
  Streams load on popup open and are torn down when it closes.
- **"Locate me"** geolocation, responsive mobile panel, analytics.

Serve the repo root with any static server (the map fetches `cameras.json` from the same directory):

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Feed audit (`audit_cameras.py`)

Health check for the **City JPEG feeds** — downloads each snapshot and classifies it as
live, black, blank, a possible placeholder, or an HTTP/network error, with optional
frozen-frame detection. TxDOT's HLS streams are **not** covered by this tool (a
different, stream-based check would be needed).

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

python3 audit_cameras.py sources/coa.json                 # audit City feeds
python3 audit_cameras.py sources/coa.json --save-all-images
python3 audit_cameras.py sources/coa.json --second-pass-delay 60 --save-suspects
```

Output lands in `camera_audit_output/` (`camera_audit.csv`, `camera_audit.json`, and
optional `images/` / `suspect_images/`).

> **Interpretation note:** an unchanged frame is not proof a feed is broken — a quiet
> intersection or cached image can look static. Treat suspicious classifications as
> review flags, not failures.

## Data sources

- **City of Austin** Transportation & Public Works traffic-camera inventory (open-data
  portal); feeds are JPEG snapshots at `cctv.austinmobility.io`.
- **TxDOT** Austin-district ITS cameras via the MapLarge `cameraPoint` table; feeds are
  HLS video from `skyvdn.com`. Coordinates come from the table's `XY` geometry column.
- **Curated webcams** — public webcams (skylines, resorts, businesses) served as HLS
  from `brownrice.com` or as embedded players from `wetmet.net`. Hand-maintained in
  `sources/curated.json` with coordinates looked up per location.

Refreshing every source is currently a manual step.
