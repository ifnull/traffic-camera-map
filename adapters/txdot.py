"""TxDOT adapter.

TxDOT's ITS site publishes one keyless JSON camera catalog per district
(``GetCctvStatusListByDistrict``). Feeds are still images, not video: the old
``skyvdn.com`` HLS streams now answer ``401``.

Frames come from the per-camera ``GetCctvSnapshotByIcdId`` endpoint, which
answers JSON ``{"snippet": "<base64 jpeg>", "timestampFormatted": ...}`` rather
than an image body, and sends no CORS headers. So each record's ``feed.url``
(a ``json-image`` feed) goes through ``SNAPSHOT_PROXY``, a CloudFront
distribution that forwards only that endpoint to its.txdot.gov, caches it 60s,
and adds CORS headers for the map's origin; the map decodes the base64 itself.
The upstream URL is kept in ``meta.snapshotUrl``.

Only cameras reporting ``Device Online`` are kept: offline devices still return
a stale frame (sometimes years old) that would otherwise look live.

The payload's ``dirDescription`` / ``equipLoc.direction`` is the ROADWAY's
direction, not the camera's facing (it reads "North" for nearly every Austin
camera), so it is deliberately not surfaced.

A cached raw response lives at ``sources/txdot_raw.json`` (``{district:
payload}``) so builds are reproducible and offline-friendly; pass
``refresh=True`` to re-fetch.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from .schema import record

ORIGIN = "https://its.txdot.gov"
# CloudFront distribution E2L8EFRSPFYB5I: GetCctvSnapshotByIcdId -> ORIGIN, plus CORS.
SNAPSHOT_PROXY = "https://d13d9fsx8m033.cloudfront.net"

# Valid district codes (the ITS map's own list). Austin is the default.
DISTRICTS = frozenset({
    "ABL", "AMA", "ATL", "AUS", "BMT", "BWD", "BRY", "CHS", "CRP", "DAL", "ELP", "FTW", "HOU",
    "LRD", "LBB", "LFK", "ODA", "PAR", "PHR", "SJT", "SAT", "TYL", "WAC", "WFS", "YKM",
})
DEFAULT_DISTRICTS = ("AUS",)


def status_url(district: str) -> str:
    return (f"{ORIGIN}/its/DistrictIts/GetCctvStatusListByDistrict"
            f"?districtCode={urllib.parse.quote(district)}")


SNAPSHOT_PATH = "/its/DistrictIts/GetCctvSnapshotByIcdId"


def snapshot_path(icd_id: str, district: str) -> str:
    """Root-relative path of the per-camera frame endpoint (JSON-wrapped base64 JPEG)."""
    return (f"{SNAPSHOT_PATH}"
            f"?icdId={urllib.parse.quote(icd_id)}&districtCode={urllib.parse.quote(district)}")


def snapshot_url(icd_id: str, district: str) -> str:
    """The official per-camera frame endpoint on its.txdot.gov."""
    return ORIGIN + snapshot_path(icd_id, district)


def fetch_raw(districts: Iterable[str] = DEFAULT_DISTRICTS, timeout: int = 40) -> dict[str, Any]:
    """Fetch each district's catalog. Returns ``{district: payload}``."""
    out: dict[str, Any] = {}
    for district in districts:
        req = urllib.request.Request(status_url(district), headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out[district] = json.loads(resp.read())
    return out


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def normalize(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn ``{district: GetCctvStatusListByDistrict payload}`` into records."""
    out: list[dict[str, Any]] = []
    for district, payload in raw.items():
        by_roadway = (payload or {}).get("roadwayCctvStatuses") or {}
        seen: set[str] = set()
        for rows in by_roadway.values():
            for row in rows or []:
                if row.get("statusDescription") != "Device Online":
                    continue
                lat, lon = row.get("latitude"), row.get("longitude")
                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    continue
                # icd_Id is the snapshot key. An interchange camera can appear
                # under more than one roadway grouping, so dedupe on it.
                icd_id = str(row.get("icd_Id") or "").strip()
                if not icd_id or icd_id in seen:
                    continue
                seen.add(icd_id)
                roadway = (row.get("equipLoc") or {}).get("roadway")
                meta = {
                    "code": icd_id,
                    "route": roadway,
                    "district": district,
                    "snapshotUrl": snapshot_url(icd_id, district),
                }
                out.append(record(
                    source="txdot",
                    native_id=f"{district.lower()}-{_slug(icd_id)}",
                    name=str(row.get("name") or icd_id).strip(),
                    lat=lat,
                    lon=lon,
                    feed_type="json-image",
                    feed_url=SNAPSHOT_PROXY + snapshot_path(icd_id, district),
                    status="ONLINE",
                    meta={k: v for k, v in meta.items() if v not in (None, "")},
                ))
    return out


def load(
    cache: Path | None = None,
    refresh: bool = False,
    districts: Iterable[str] = DEFAULT_DISTRICTS,
) -> list[dict[str, Any]]:
    """Return normalized TxDOT records, using ``cache`` unless ``refresh``."""
    if cache and Path(cache).exists() and not refresh:
        raw = json.loads(Path(cache).read_text(encoding="utf-8"))
        if not all(isinstance(v, dict) and "roadwayCctvStatuses" in v for v in raw.values()):
            raise SystemExit(f"{cache} is not a TxDOT ITS catalog cache; rerun with --refresh-txdot")
    else:
        raw = fetch_raw(districts)
        if cache:
            Path(cache).write_text(json.dumps(raw), encoding="utf-8")
    return normalize(raw)
