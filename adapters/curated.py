"""Curated / community webcam adapter.

Unlike the City and TxDOT adapters, this source is a hand-maintained list
(``sources/curated.json``) rather than an API: a person adds each camera with
a looked-up ``lat``/``lon``. Feeds are HLS (``.m3u8``) or an embeddable
third-party player (``iframe``).

Each entry:

    {
      "id": "austonian",              # slug, unique within this source
      "name": "The Austonian",
      "feed_type": "hls" | "iframe",
      "url": "...",
      "lat": 30.26, "lon": -97.74,    # null + "include": false to hold one out
      "category": "Skyline",          # optional, shown in popup
      "area": "Bee Cave",             # optional
      "note": "...",                  # optional
      "include": true                 # optional, default true
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import record

_META_FIELDS = ["category", "area", "note"]


def load(path: Path) -> list[dict[str, Any]]:
    """Read the curated list at ``path`` and return normalized records.

    Entries with ``include: false`` or missing coordinates are skipped so the
    file can keep held-back cameras (e.g. ones that still need coordinates).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for cam in data:
        if not cam.get("include", True):
            continue
        lat, lon = cam.get("lat"), cam.get("lon")
        if lat is None or lon is None:
            continue
        meta = {k: cam[k] for k in _META_FIELDS if cam.get(k)}
        out.append(record(
            source="webcam",
            native_id=cam["id"],
            name=cam["name"],
            lat=lat,
            lon=lon,
            feed_type=cam["feed_type"],
            feed_url=cam["url"],
            status=cam.get("status", ""),
            meta=meta,
        ))
    return out
