#!/usr/bin/env python3
"""Convert Austin traffic camera CSV exports to cameras.json for the map."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

POINT_RE = re.compile(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", re.IGNORECASE)

# CSV column -> JSON field
FIELD_MAP = [
    ("Camera ID", "id"),
    ("Location Name", "name"),
    ("Camera Status", "status"),
    ("Turn on Date", "turnOnDate"),
    ("Camera Manufacturer", "manufacturer"),
    ("ATD Location ID", "atdLocationId"),
    ("Landmark", "landmark"),
    ("Signal Engineer Area", "signalArea"),
    ("Council District", "councilDistrict"),
    ("Jurisdiction", "jurisdiction"),
    ("Location Type", "locationType"),
    ("Primary St Segment ID", "primaryStSegmentId"),
    ("Cross St Segment ID", "crossStSegmentId"),
    ("Primary Street Block", "primaryStreetBlock"),
    ("Primary Street", "primaryStreet"),
    ("PRIMARY_ST_AKA", "primaryStAka"),
    ("Cross Street Block", "crossStreetBlock"),
    ("Cross Street", "crossStreet"),
    ("CROSS_ST_AKA", "crossStAka"),
    ("COA Intersection ID", "coaIntersectionId"),
    ("Modified Date", "modifiedDate"),
    ("Published Screenshots", "publishedScreenshots"),
    ("Screenshot Address", "screenshot"),
    ("Funding", "funding"),
    ("ID", "recordId"),
]


def parse_point(value: str) -> tuple[float, float] | None:
    """Parse WKT POINT (lon lat) into (lon, lat)."""
    match = POINT_RE.match((value or "").strip())
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def row_to_camera(row: dict[str, str]) -> dict | None:
    coords = parse_point(row.get("Location", ""))
    if coords is None:
        return None

    lon, lat = coords
    camera = {json_key: (row.get(csv_key) or "").strip() for csv_key, json_key in FIELD_MAP}
    camera["lat"] = lat
    camera["lon"] = lon
    return camera


def convert(csv_path: Path, json_path: Path, pretty: bool = False) -> int:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        cameras = []
        skipped = 0
        for row in reader:
            camera = row_to_camera(row)
            if camera is None:
                skipped += 1
                continue
            cameras.append(camera)

    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    json_path.write_text(
        json.dumps(cameras, indent=indent, separators=separators) + ("\n" if pretty else ""),
        encoding="utf-8",
    )
    print(f"Wrote {len(cameras)} cameras to {json_path}")
    if skipped:
        print(f"Skipped {skipped} rows without a valid Location POINT", file=sys.stderr)
    return len(cameras)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Austin traffic camera CSV to cameras.json for the map."
    )
    parser.add_argument(
        "csv",
        nargs="?",
        type=Path,
        default=Path("Traffic_Cameras_20260709.csv"),
        help="Input CSV path (default: Traffic_Cameras_20260709.csv)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("sources/coa.json"),
        help="Output JSON path (default: sources/coa.json, the CoA adapter input)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON instead of compact output",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    convert(args.csv, args.output, pretty=args.pretty)


if __name__ == "__main__":
    main()
