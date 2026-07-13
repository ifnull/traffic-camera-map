"""City of Austin adapter.

Input is the CoA map-format JSON produced by ``csv_to_cameras_json.py``
(one object per camera with ``id``, ``name``, ``status``, ``screenshot``,
``lat``, ``lon`` and assorted city fields). Feeds are JPEG snapshots.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import record

# City fields worth surfacing in the popup, carried through under ``meta``.
_META_FIELDS = [
    "turnOnDate", "manufacturer", "atdLocationId", "landmark", "signalArea",
    "councilDistrict", "jurisdiction", "locationType", "primaryStreet",
    "crossStreet", "primaryStAka", "crossStAka", "primaryStreetBlock",
    "crossStreetBlock", "coaIntersectionId", "modifiedDate", "funding",
    "recordId",
]


def load(path: Path) -> list[dict[str, Any]]:
    """Read CoA map-format JSON at ``path`` and return normalized records."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for cam in data:
        if not isinstance(cam, dict):
            continue
        cid = str(cam.get("id", "")).strip()
        lat, lon = cam.get("lat"), cam.get("lon")
        if not cid or lat is None or lon is None:
            continue
        meta = {k: cam.get(k, "") for k in _META_FIELDS if cam.get(k, "") != ""}
        out.append(record(
            source="coa",
            native_id=cid,
            name=cam.get("name", ""),
            lat=lat,
            lon=lon,
            feed_type="image",
            feed_url=cam.get("screenshot", ""),
            status=cam.get("status", ""),
            meta=meta,
        ))
    return out
