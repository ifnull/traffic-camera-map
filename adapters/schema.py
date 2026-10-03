"""The normalized camera record every source adapter emits.

One schema for the map, so any new feed source is just another adapter:

    {
      "id":     "<source>-<native id>",     # globally unique across sources
      "source": "coa" | "txdot" | "webcam",
      "name":   "<human-readable label>",
      "lat":    float,
      "lon":    float,
      "feed":   {"type": "image" | "hls" | "iframe" | "json-image", "url": "<url>"},
      "status": "<source-specific status string>",
      "meta":   { ... extra source fields shown in the popup ... },
    }

``feed.type`` is the one field the map branches on: ``image`` renders as an
``<img>`` snapshot, ``hls`` renders as a live ``<video>`` via hls.js,
``iframe`` renders as an embedded third-party player, and ``json-image`` is
a CORS-readable URL answering ``{"snippet": "<base64 jpeg>"}`` that the map
fetches and decodes into an ``<img>``.
"""

from __future__ import annotations

from typing import Any, Iterable

FEED_TYPES = {"image", "hls", "iframe", "json-image"}
SOURCES = {"coa", "txdot", "webcam"}


def record(
    *,
    source: str,
    native_id: str,
    name: str,
    lat: Any,
    lon: Any,
    feed_type: str,
    feed_url: str,
    status: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one normalized record. Raises on an unknown feed type."""
    if feed_type not in FEED_TYPES:
        raise ValueError(f"feed_type must be one of {sorted(FEED_TYPES)}, got {feed_type!r}")
    return {
        "id": f"{source}-{native_id}",
        "source": source,
        "name": name or "",
        "lat": float(lat),
        "lon": float(lon),
        "feed": {"type": feed_type, "url": feed_url or ""},
        "status": status or "",
        "meta": meta or {},
    }


def validate(records: Iterable[dict[str, Any]]) -> list[str]:
    """Return a list of problems with the record set; empty means clean."""
    problems: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(records):
        rid = r.get("id")
        if not rid:
            problems.append(f"[{i}] missing id")
        elif rid in seen:
            problems.append(f"[{i}] duplicate id {rid}")
        else:
            seen.add(rid)

        if r.get("source") not in SOURCES:
            problems.append(f"[{rid}] unknown source {r.get('source')!r}")

        try:
            lat, lon = float(r["lat"]), float(r["lon"])
            # Generous Texas bounding box; catches null-island and swapped lat/lon.
            if not (25.0 < lat < 37.0 and -107.0 < lon < -93.0):
                problems.append(f"[{rid}] coords outside Texas: {lat},{lon}")
        except (KeyError, TypeError, ValueError):
            problems.append(f"[{rid}] bad coords")

        feed = r.get("feed", {})
        if feed.get("type") not in FEED_TYPES:
            problems.append(f"[{rid}] bad feed.type {feed.get('type')!r}")
        if not feed.get("url"):
            problems.append(f"[{rid}] empty feed.url")

    return problems
