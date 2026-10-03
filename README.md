# Austin Area Cameras

An interactive web map that aggregates **Austin-area public cameras into one place** — a general view of the area, traffic included. City of Austin ATD snapshots, TxDOT highway camera stills, and curated public webcams (skylines, resorts, businesses) side by side, plus the tooling that builds and quality-checks the data.

The map (`index.html`) is a single static page that plots every camera, filters by source, searches, and renders each feed in its native form: a JPEG snapshot for City and TxDOT cameras, a live HLS video stream for most webcams, and an embedded player for iframe-only webcams. A small Python pipeline turns each provider's raw data into one normalized `cameras.json`. The page runs no server code: it's hosted from S3, and TxDOT stills come through a CloudFront proxy that adds CORS headers (see [Hosting](#hosting)).

> **Status: proof of concept.** Three sources are unified end to end (1,287 cameras). The data refresh is manual and feed-health auditing currently covers only the City JPEG feeds. See [`ASSESSMENT.md`](./ASSESSMENT.md) for the evaluation and roadmap.

## Repository layout

| Path | Purpose |
| --- | --- |
| `index.html` | The map. Static HTML/CSS/JS, no build step. Renders image, HLS, iframe, and JSON-image feeds. Loads `cameras.json`. |
| `player.html` | Standalone hls.js player the map links to for HLS feeds (a raw `.m3u8` won't open in a browser tab). |
| `cameras.json` | **Generated** unified dataset the map serves. Do not edit by hand — run `build.py`. |
| `build.py` | Merges all source adapters into `cameras.json`. |
| `adapters/` | One adapter per provider, all emitting the shared schema. |
| `adapters/schema.py` | The normalized record shape + validation. |
| `adapters/coa.py` | City of Austin adapter (JPEG snapshots). |
| `adapters/txdot.py` | TxDOT adapter (JPEG stills from the `its.txdot.gov` district catalog). |
| `adapters/curated.py` | Curated public-webcam adapter (hand-maintained list). |
| `sources/` | Per-source inputs (`coa.json`, `txdot_raw.json`, `curated.json`). |
| `csv_to_cameras_json.py` | Converts a City CSV export into `sources/coa.json`. |
| `audit_cameras.py` | Downloads and classifies City JPEG feeds (health check). |

## Architecture

```
  City CSV ──► csv_to_cameras_json.py ──► sources/coa.json ─────────┐
                                                                    │
  TxDOT ITS catalog ──► adapters/txdot.py ──► sources/txdot_raw.json ├─► build.py ──► cameras.json ──► index.html
                                                                    │                                   ▲
  Hand-maintained sources/curated.json ─────────────────────────────┘                                   │
                                                                                                        │
                     TxDOT frames: its.txdot.gov ──► CloudFront proxy (60 s cache + CORS) ────────────┘
```

Every source normalizes into one record shape (`adapters/schema.py`):

```json
{
  "id": "coa-229" | "txdot-aus-ih-35-centerpoint-rd-448" | "webcam-indeed",
  "source": "coa" | "txdot" | "webcam",
  "name": "IH-35 @ Centerpoint Rd",
  "lat": 30.27, "lon": -97.73,
  "feed": { "type": "image" | "hls" | "iframe", "url": "..." },
  "status": "TURNED_ON" | "ONLINE" | ...,
  "meta": { "...source-specific fields shown in the popup..." }
}
```

`feed.type` is the field the map branches on (`image` → `<img>`, `hls` → hls.js `<video>`, `iframe` → embedded player). Adding a new provider (Travis County, UT, etc.) is one new file in `adapters/` plus a line in `build.py` — no schema change.

## Building the data

```bash
python3 build.py                                      # rebuild cameras.json from cached sources
python3 build.py --refresh-txdot                      # re-fetch the TxDOT catalog first
python3 build.py --refresh-txdot --txdot-districts AUS,SAT   # other TxDOT districts
python3 build.py --pretty                             # human-readable output
```

`build.py` validates every record (unique IDs, Texas-bounded coordinates, a usable feed URL) and prints any problems before writing.

### Refreshing each source

- **City of Austin** — export the traffic-camera CSV from the city open-data portal, then:
  ```bash
  python3 csv_to_cameras_json.py Traffic_Cameras_YYYYMMDD.csv   # writes sources/coa.json
  python3 build.py
  ```
- **TxDOT** — `build.py --refresh-txdot` re-fetches the keyless `GetCctvStatusListByDistrict` catalog for each district in `--txdot-districts` (default `AUS`; 25 district codes exist statewide) and refreshes `sources/txdot_raw.json`.
- **Curated webcams** — edit `sources/curated.json` by hand: add an entry with its feed URL, `feed_type` (`hls` or `iframe`), and a looked-up `lat`/`lon`. Set `"include": false` to hold one back (e.g. missing coordinates). Then `python3 build.py`.

Current dataset: **1,004 City** + **268 TxDOT** + **15 webcams** = **1,287 total**. Note: the map spans the wider Austin area, not just the city — TxDOT's Austin district runs from the Hays/Comal line up I-35 toward Bell County, and curated webcams include spots like Horseshoe Bay and Lockhart. The initial view frames on central Austin.

## The map (`index.html`)

- **All sources on one map** with marker clustering, colored by source (City = green, TxDOT = blue, Webcams = orange), over keyless OpenStreetMap tiles desaturated so the markers stand out.
- **Source filter** — All / City / TxDOT / Webcams. City adds a contextual status sub-filter (On / Desired / Removed / Void) that only applies to City cameras.
- **Search** across name, ID, route, streets, landmark, category, and more.
- **Native rendering per feed:** City and TxDOT cameras show a JPEG still; most webcams play live HLS video (via [hls.js](https://github.com/video-dev/hls.js), native on Safari) with a "Live" badge; iframe-only webcams embed their player. Streams load on popup open and are torn down when it closes.
- **"Locate me"** geolocation, responsive mobile panel, analytics.

Serve it with any static server (the map fetches `cameras.json` from the same directory). Use port 8000 or 8080 locally: those are the ports the TxDOT proxy's CORS policy allows.

```bash
python3 -m http.server 8080   # open http://localhost:8080
```

## Hosting

The site is static files in the S3 website bucket `austin-traffic-cams.altmake.com` (`index.html`, `cameras.json`, `player.html`), served through Cloudflare.

TxDOT stills go through a separate CloudFront distribution, `d13d9fsx8m033.cloudfront.net` (`E2L8EFRSPFYB5I`). TxDOT's per-camera endpoint (`GetCctvSnapshotByIcdId`) answers JSON wrapping a base64 JPEG and sends no CORS headers, so a browser on another origin can't read it. The distribution fixes that without running any code:

| Path pattern | Origin | Policies |
| --- | --- | --- |
| `/its/DistrictIts/GetCctvSnapshotByIcdId` | `https://its.txdot.gov` | cache 60 s keyed on `icdId` + `districtCode` (`austin-cams-txdot-snapshot-60s`); CORS for the site and `localhost` / `127.0.0.1` on ports 8000 and 8080 (`austin-cams-txdot-cors`) |
| everything else | the S3 website bucket | AWS managed `CachingOptimized` |

Only the snapshot endpoint is forwarded to TxDOT, so the distribution can't be used as a general proxy for its.txdot.gov. The map fetches the JSON on popup open and decodes the image in the browser. The distribution URL lives in `adapters/txdot.py` (`SNAPSHOT_PROXY`); rebuild `cameras.json` if it changes. To allow another origin (a different local port, a new domain), add it to the `austin-cams-txdot-cors` response headers policy.

## Feed audit (`audit_cameras.py`)

Health check for the **City JPEG feeds** — downloads each snapshot and classifies it as live, black, blank, a possible placeholder, or an HTTP/network error, with optional frozen-frame detection. TxDOT stills are **not** covered yet; the adapter already drops cameras TxDOT reports as offline.

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt

python3 audit_cameras.py sources/coa.json                 # audit City feeds
python3 audit_cameras.py sources/coa.json --save-all-images
python3 audit_cameras.py sources/coa.json --second-pass-delay 60 --save-suspects
```

Output lands in `camera_audit_output/` (`camera_audit.csv`, `camera_audit.json`, and optional `images/` / `suspect_images/`).

> **Interpretation note:** an unchanged frame is not proof a feed is broken — a quiet intersection or cached image can look static. Treat suspicious classifications as review flags, not failures.

## Data sources

- **City of Austin** Transportation & Public Works traffic-camera inventory (open-data portal); feeds are JPEG snapshots at `cctv.austinmobility.io`.
- **TxDOT** ITS highway cameras from `its.txdot.gov` (keyless, one catalog per district). Only cameras reporting `Device Online` are included, because offline devices keep serving a stale frame that can be months or years old and would look live. Frames carry a TxDOT watermark. The old `skyvdn.com` HLS streams now return `401`, so TxDOT is stills only.
- **Curated webcams** — public webcams (skylines, resorts, businesses) served as HLS from `brownrice.com` or as embedded players from `wetmet.net`. Hand-maintained in `sources/curated.json` with coordinates looked up per location.
- **Basemap** — © OpenStreetMap contributors via `tile.openstreetmap.org` (keyless; subject to the [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/), which is fine for light use but not for a high-traffic public deployment).

Refreshing every source is currently a manual step.
