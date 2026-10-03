#!/usr/bin/env python3
"""Build the unified ``cameras.json`` the map serves, from all source adapters.

    python3 build.py                  # rebuild from cached sources
    python3 build.py --refresh-txdot  # re-fetch TxDOT from its.txdot.gov first
    python3 build.py --refresh-txdot --txdot-districts AUS,SAT

Each source has an adapter under ``adapters/`` that emits records in the
shared ``adapters.schema`` shape. This merges them, validates, and writes one
compact JSON file.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from adapters import coa, curated, schema, txdot

ROOT = Path(__file__).parent
SOURCES = ROOT / "sources"


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge all camera sources into cameras.json")
    ap.add_argument("-o", "--output", type=Path, default=ROOT / "cameras.json")
    ap.add_argument(
        "--refresh-txdot",
        action="store_true",
        help="Re-fetch TxDOT from its.txdot.gov instead of using sources/txdot_raw.json",
    )
    ap.add_argument(
        "--txdot-districts",
        default=",".join(txdot.DEFAULT_DISTRICTS),
        help="Comma-separated TxDOT district codes to fetch with --refresh-txdot (default: AUS)",
    )
    ap.add_argument("--pretty", action="store_true", help="Pretty-print the output JSON")
    args = ap.parse_args()
    districts = [d.strip().upper() for d in args.txdot_districts.split(",") if d.strip()]
    unknown = [d for d in districts if d not in txdot.DISTRICTS]
    if unknown:
        ap.error(f"unknown TxDOT district(s): {', '.join(unknown)}")

    records: list[dict] = []
    records += coa.load(SOURCES / "coa.json")
    records += txdot.load(cache=SOURCES / "txdot_raw.json", refresh=args.refresh_txdot, districts=districts)
    records += curated.load(SOURCES / "curated.json")

    problems = schema.validate(records)
    if problems:
        print(f"WARNING: {len(problems)} validation problem(s):")
        for p in problems[:20]:
            print("  ", p)
        if len(problems) > 20:
            print(f"   ...and {len(problems) - 20} more")

    if args.pretty:
        text = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    else:
        text = json.dumps(records, separators=(",", ":"), ensure_ascii=False)
    args.output.write_text(text, encoding="utf-8")

    by_source = Counter(r["source"] for r in records)
    print(f"Wrote {len(records)} cameras to {args.output}  {dict(by_source)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
