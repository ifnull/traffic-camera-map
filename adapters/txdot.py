"""TxDOT adapter.

TxDOT's Austin-district cameras live in a MapLarge point table. The table has
a geometry column ``XY`` that a plain ``*`` select hides, but MapLarge evaluates
functions in ``sqlselect``, so ``Longitude(XY)`` / ``Latitude(XY)`` return the
coordinates (as ``Expression1`` / ``Expression2`` in the response). Feeds are
HLS video (``.m3u8``), not snapshots.

A cached raw response lives at ``sources/txdot_raw.json`` so builds are
reproducible and offline-friendly; pass ``refresh=True`` to re-fetch.
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .schema import record

ENDPOINT = "https://dtx-e-cdn.maplarge.com/Api/ProcessDirect"
TABLE = "appgeo/cameraPoint/639193392549115356"
SELECT = [
    "name", "route", "direction", "description", "jurisdiction",
    "httpsurl", "iosurl", "imageurl", "active", "problemstream",
    "Longitude(XY)", "Latitude(XY)",
]


def fetch_raw(jurisdiction: str = "Austin", take: int = 5000, timeout: int = 40) -> dict[str, Any]:
    """Query MapLarge for all cameras in a TxDOT jurisdiction (district)."""
    req = {
        "action": "table/query",
        "query": {
            "sqlselect": SELECT,
            "start": 0,
            "take": take,
            "table": TABLE,
            "where": [{"col": "jurisdiction", "test": "Equal", "value": jurisdiction}],
        },
    }
    url = f"{ENDPOINT}?request=" + urllib.parse.quote(json.dumps(req))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read())


def _status(active: Any, problem: Any) -> str:
    if str(problem) == "1":
        return "PROBLEM"
    return "ACTIVE" if str(active) == "1" else "INACTIVE"


def normalize(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a MapLarge columnar response into normalized records."""
    cols = raw["data"]["data"]
    n = len(cols.get("name", []))
    lon_key = "Longitude(XY)" if "Longitude(XY)" in cols else "Expression1"
    lat_key = "Latitude(XY)" if "Latitude(XY)" in cols else "Expression2"

    def col(name: str) -> list:
        return cols.get(name, [None] * n)

    out: list[dict[str, Any]] = []
    for i in range(n):
        lat, lon = col(lat_key)[i], col(lon_key)[i]
        if lat is None or lon is None:
            continue
        code = cols["name"][i]                    # e.g. TX_AUS_116
        desc = col("description")[i] or code      # human label
        meta = {
            "code": code,
            "route": col("route")[i],
            "direction": col("direction")[i],
            "jurisdiction": col("jurisdiction")[i],
            "iosUrl": col("iosurl")[i],
            "thumbUrl": col("imageurl")[i],
        }
        out.append(record(
            source="txdot",
            native_id=code,
            name=desc,
            lat=lat,
            lon=lon,
            feed_type="hls",
            feed_url=col("httpsurl")[i],
            status=_status(col("active")[i], col("problemstream")[i]),
            meta={k: v for k, v in meta.items() if v not in (None, "")},
        ))
    return out


def load(cache: Path | None = None, refresh: bool = False) -> list[dict[str, Any]]:
    """Return normalized TxDOT records, using ``cache`` unless ``refresh``."""
    if cache and Path(cache).exists() and not refresh:
        raw = json.loads(Path(cache).read_text(encoding="utf-8"))
    else:
        raw = fetch_raw()
        if cache:
            Path(cache).write_text(json.dumps(raw), encoding="utf-8")
    return normalize(raw)
