#!/usr/bin/env python3
"""
Audit Austin traffic-camera screenshots.

Reads a cameras.json array, downloads each camera's `screenshot` URL, analyzes
the image, and writes:
  - camera_audit.csv
  - camera_audit.json
  - suspect_images/   (optional copies of suspicious frames)

Optional second-pass capture can flag unchanged/frozen-looking images.

Install:
    python3 -m pip install requests pillow numpy

Examples:
    python3 audit_cameras.py cameras.json
    python3 audit_cameras.py cameras.json --workers 20 --save-suspects
    python3 audit_cameras.py cameras.json --second-pass-delay 60 --save-suspects
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image, ImageOps, UnidentifiedImageError


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "https://austin-traffic-cams.altmake.com/"
DEFAULT_TIMEOUT = 15
DEFAULT_WORKERS = 16


@dataclass
class AuditResult:
    id: str
    name: str
    feed_status: str
    url: str
    http_status: int | None
    content_type: str
    width: int | None
    height: int | None
    mean_luma: float | None
    std_luma: float | None
    entropy: float | None
    dark_fraction: float | None
    bright_fraction: float | None
    edge_fraction: float | None
    image_sha256: str
    classification: str
    suspicious: bool
    reasons: str
    changed_second_pass: bool | None = None
    mean_abs_pixel_delta: float | None = None
    response_headers: str = ""
    response_body_preview: str = ""
    error: str = ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit traffic-camera screenshot feeds.")
    p.add_argument("json_file", type=Path, help="Path to cameras.json")
    p.add_argument("--output-dir", type=Path, default=Path("camera_audit_output"))
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument(
        "--request-delay",
        type=float,
        default=1.0,
        help="Delay in seconds before each request. Default: 1.0.",
    )
    p.add_argument(
        "--referer",
        default=DEFAULT_REFERER,
        help="Referer header sent with image requests.",
    )
    p.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retries for 429/5xx and transient network failures.",
    )
    p.add_argument(
        "--second-pass-delay",
        type=float,
        default=0,
        help="Seconds to wait before recapturing each successful feed. 0 disables.",
    )
    p.add_argument(
        "--save-suspects",
        action="store_true",
        help="Save suspicious images for manual review.",
    )
    p.add_argument(
        "--save-all-images",
        action="store_true",
        help="Save every successfully downloaded image, not just suspects.",
    )
    p.add_argument(
        "--include-non-active",
        action="store_true",
        help="Audit entries not marked TURNED_ON as well.",
    )
    p.add_argument(
        "--black-mean-threshold",
        type=float,
        default=12.0,
        help="Mean grayscale value below which an image is considered black.",
    )
    p.add_argument(
        "--blank-std-threshold",
        type=float,
        default=3.0,
        help="Grayscale standard deviation below which an image is near-uniform.",
    )
    p.add_argument(
        "--low-entropy-threshold",
        type=float,
        default=2.2,
        help="Entropy below which an image may be a logo/placeholder.",
    )
    p.add_argument(
        "--low-edge-threshold",
        type=float,
        default=0.012,
        help="Edge fraction below which an image may be a logo/placeholder.",
    )
    p.add_argument(
        "--unchanged-delta-threshold",
        type=float,
        default=0.35,
        help="Mean absolute pixel delta below which second-pass images are unchanged.",
    )
    return p.parse_args()


def load_cameras(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Expected the JSON root to be an array.")

    return [item for item in data if isinstance(item, dict)]


def fetch_image(
    session: requests.Session,
    url: str,
    timeout: float,
    *,
    referer: str,
    max_retries: int,
    request_delay: float,
) -> tuple[bytes, int, str, dict[str, str], str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        if request_delay > 0:
            time.sleep(request_delay)

        try:
            response = session.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )

            content_type = (
                response.headers.get("Content-Type", "")
                .split(";")[0]
                .strip()
                .lower()
            )
            selected_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() in {
                    "server",
                    "via",
                    "x-cache",
                    "x-cache-hits",
                    "x-akamai-transformed",
                    "cf-ray",
                    "retry-after",
                    "location",
                }
            }
            body_preview = ""
            if response.status_code >= 400:
                body_preview = response.text[:1000].replace("\x00", "")

            if response.status_code == 403:
                response.raise_for_status()

            if response.status_code == 429 or 500 <= response.status_code <= 599:
                if attempt < max_retries:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else 2 ** attempt
                    except ValueError:
                        wait = 2 ** attempt
                    time.sleep(min(wait, 30))
                    continue

            response.raise_for_status()
            return (
                response.content,
                response.status_code,
                content_type,
                selected_headers,
                body_preview,
            )

        except requests.RequestException as exc:
            last_error = exc
            if isinstance(exc, requests.HTTPError):
                response = exc.response
                if response is not None and response.status_code == 403:
                    setattr(exc, "audit_headers", selected_headers)
                    setattr(exc, "audit_body_preview", body_preview)
                    raise
            if attempt >= max_retries:
                raise
            time.sleep(min(2 ** attempt, 30))

    assert last_error is not None
    raise last_error


def grayscale_entropy(gray: np.ndarray) -> float:
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    probs = hist / hist.sum()
    probs = probs[probs > 0]
    return float(-(probs * np.log2(probs)).sum())


def edge_fraction(gray: np.ndarray) -> float:
    # Lightweight edge estimate using adjacent-pixel differences.
    gray_f = gray.astype(np.float32)
    dx = np.abs(np.diff(gray_f, axis=1))
    dy = np.abs(np.diff(gray_f, axis=0))
    threshold = 18.0
    edge_pixels = np.count_nonzero(dx > threshold) + np.count_nonzero(dy > threshold)
    possible = dx.size + dy.size
    return float(edge_pixels / possible) if possible else 0.0


def normalize_for_comparison(image: Image.Image, size: tuple[int, int] = (320, 180)) -> np.ndarray:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", size, (0, 0, 0))
    left = (size[0] - image.width) // 2
    top = (size[1] - image.height) // 2
    canvas.paste(image, (left, top))
    return np.asarray(canvas, dtype=np.float32)


def analyze_bytes(
    raw: bytes,
    *,
    black_mean_threshold: float,
    blank_std_threshold: float,
    low_entropy_threshold: float,
    low_edge_threshold: float,
) -> tuple[dict[str, Any], Image.Image]:
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Response was not a readable image: {exc}") from exc

    image = ImageOps.exif_transpose(image).convert("RGB")
    gray_image = image.convert("L")

    # Downsample for consistent, fast metrics.
    sample = gray_image.resize((320, 180), Image.Resampling.BILINEAR)
    gray = np.asarray(sample, dtype=np.uint8)

    mean_luma = float(gray.mean())
    std_luma = float(gray.std())
    entropy = grayscale_entropy(gray)
    dark_fraction = float(np.mean(gray <= 10))
    bright_fraction = float(np.mean(gray >= 245))
    edges = edge_fraction(gray)

    reasons: list[str] = []
    classification = "live_looking"

    if mean_luma <= black_mean_threshold and dark_fraction >= 0.90:
        classification = "black_screen"
        reasons.append(
            f"very dark frame (mean={mean_luma:.2f}, dark={dark_fraction:.1%})"
        )
    elif std_luma <= blank_std_threshold:
        classification = "blank_or_solid_screen"
        reasons.append(f"near-uniform frame (std={std_luma:.2f})")
    elif bright_fraction >= 0.97 and std_luma <= 8:
        classification = "blank_or_solid_screen"
        reasons.append(
            f"nearly all-white frame (bright={bright_fraction:.1%}, std={std_luma:.2f})"
        )
    elif entropy <= low_entropy_threshold and edges <= low_edge_threshold:
        classification = "possible_logo_or_placeholder"
        reasons.append(
            f"low visual complexity (entropy={entropy:.2f}, edges={edges:.3%})"
        )
    elif entropy <= 1.35:
        classification = "possible_logo_or_placeholder"
        reasons.append(f"extremely low entropy ({entropy:.2f})")

    metrics = {
        "width": image.width,
        "height": image.height,
        "mean_luma": mean_luma,
        "std_luma": std_luma,
        "entropy": entropy,
        "dark_fraction": dark_fraction,
        "bright_fraction": bright_fraction,
        "edge_fraction": edges,
        "image_sha256": hashlib.sha256(raw).hexdigest(),
        "classification": classification,
        "suspicious": classification != "live_looking",
        "reasons": "; ".join(reasons),
    }
    return metrics, image


def safe_filename(camera_id: str, name: str, suffix: str = ".jpg") -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return f"{camera_id}_{cleaned[:100]}{suffix}"


def audit_camera(
    camera: dict[str, Any],
    args: argparse.Namespace,
    suspect_dir: Path,
    image_dir: Path,
) -> tuple[AuditResult, np.ndarray | None]:
    camera_id = str(camera.get("id", ""))
    name = str(camera.get("name", ""))
    feed_status = str(camera.get("status", ""))
    url = str(camera.get("screenshot", ""))

    base = {
        "id": camera_id,
        "name": name,
        "feed_status": feed_status,
        "url": url,
        "http_status": None,
        "content_type": "",
        "width": None,
        "height": None,
        "mean_luma": None,
        "std_luma": None,
        "entropy": None,
        "dark_fraction": None,
        "bright_fraction": None,
        "edge_fraction": None,
        "image_sha256": "",
        "classification": "fetch_error",
        "suspicious": True,
        "reasons": "",
        "response_headers": "",
        "response_body_preview": "",
        "error": "",
    }

    if not url:
        base["classification"] = "missing_url"
        base["reasons"] = "No screenshot URL"
        return AuditResult(**base), None

    session = requests.Session()
    try:
        raw, status_code, content_type, response_headers, body_preview = fetch_image(
            session,
            url,
            args.timeout,
            referer=args.referer,
            max_retries=args.max_retries,
            request_delay=args.request_delay,
        )
        base["http_status"] = status_code
        base["content_type"] = content_type
        base["response_headers"] = json.dumps(response_headers, sort_keys=True)
        base["response_body_preview"] = body_preview

        metrics, image = analyze_bytes(
            raw,
            black_mean_threshold=args.black_mean_threshold,
            blank_std_threshold=args.blank_std_threshold,
            low_entropy_threshold=args.low_entropy_threshold,
            low_edge_threshold=args.low_edge_threshold,
        )
        base.update(metrics)

        if args.save_all_images:
            image_dir.mkdir(parents=True, exist_ok=True)
            out_path = image_dir / safe_filename(camera_id, name)
            image.save(out_path, format="JPEG", quality=92)

        if args.save_suspects and base["suspicious"]:
            suspect_dir.mkdir(parents=True, exist_ok=True)
            out_path = suspect_dir / safe_filename(camera_id, name)
            image.save(out_path, format="JPEG", quality=92)

        comparison = normalize_for_comparison(image)
        return AuditResult(**base), comparison

    except requests.HTTPError as exc:
        response = exc.response
        base["http_status"] = response.status_code if response is not None else None
        base["content_type"] = (
            response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if response is not None
            else ""
        )
        base["classification"] = "http_error"
        base["reasons"] = f"HTTP {base['http_status']}"
        audit_headers = getattr(exc, "audit_headers", {})
        audit_body = getattr(exc, "audit_body_preview", "")
        base["response_headers"] = json.dumps(audit_headers, sort_keys=True)
        base["response_body_preview"] = audit_body
        base["error"] = str(exc)
    except requests.RequestException as exc:
        base["classification"] = "network_error"
        base["reasons"] = "Network request failed"
        base["error"] = str(exc)
    except Exception as exc:
        base["classification"] = "invalid_image"
        base["reasons"] = "Downloaded content could not be analyzed as an image"
        base["error"] = str(exc)
    finally:
        session.close()

    return AuditResult(**base), None


def second_pass(
    camera: dict[str, Any],
    first_frame: np.ndarray,
    args: argparse.Namespace,
) -> tuple[bool | None, float | None, str]:
    url = str(camera.get("screenshot", ""))
    if not url:
        return None, None, "Missing screenshot URL on second pass"

    session = requests.Session()
    try:
        raw, _, _, _, _ = fetch_image(
            session,
            url,
            args.timeout,
            referer=args.referer,
            max_retries=args.max_retries,
            request_delay=args.request_delay,
        )
        image = Image.open(io.BytesIO(raw))
        image.load()
        second_frame = normalize_for_comparison(image)

        delta = float(np.mean(np.abs(first_frame - second_frame)))
        changed = delta > args.unchanged_delta_threshold
        return changed, delta, ""
    except Exception as exc:
        return None, None, str(exc)
    finally:
        session.close()


def write_reports(results: list[AuditResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "camera_audit.json"
    csv_path = output_dir / "camera_audit.csv"

    rows = [asdict(r) for r in results]

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def print_summary(results: list[AuditResult]) -> None:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1

    print("\nClassification summary")
    print("----------------------")
    for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{key:30s} {value:5d}")

    suspicious = sum(1 for r in results if r.suspicious)
    unchanged = sum(1 for r in results if r.changed_second_pass is False)
    print(f"\nTotal audited: {len(results)}")
    print(f"Suspicious:    {suspicious}")
    if any(r.changed_second_pass is not None for r in results):
        print(f"Unchanged:     {unchanged}")


def main() -> int:
    args = parse_args()

    if not args.json_file.exists():
        print(f"Error: file does not exist: {args.json_file}", file=sys.stderr)
        return 2

    try:
        cameras = load_cameras(args.json_file)
    except Exception as exc:
        print(f"Error reading JSON: {exc}", file=sys.stderr)
        return 2

    if not args.include_non_active:
        cameras = [c for c in cameras if str(c.get("status", "")) == "TURNED_ON"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suspect_dir = args.output_dir / "suspect_images"
    image_dir = args.output_dir / "images"

    print(f"Auditing {len(cameras)} camera entries with {args.workers} workers...")

    results_by_id: dict[str, AuditResult] = {}
    frames_by_id: dict[str, np.ndarray] = {}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(audit_camera, camera, args, suspect_dir, image_dir): camera
            for camera in cameras
        }

        completed = 0
        for future in as_completed(future_map):
            camera = future_map[future]
            camera_id = str(camera.get("id", ""))
            result, frame = future.result()
            results_by_id[camera_id] = result
            if frame is not None:
                frames_by_id[camera_id] = frame

            completed += 1
            if completed % 25 == 0 or completed == len(cameras):
                print(f"  completed {completed}/{len(cameras)}")

    if args.second_pass_delay > 0 and frames_by_id:
        print(
            f"\nWaiting {args.second_pass_delay:g} seconds before second-pass comparison..."
        )
        time.sleep(args.second_pass_delay)

        camera_by_id = {str(c.get("id", "")): c for c in cameras}
        eligible_ids = list(frames_by_id.keys())

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_map = {
                executor.submit(
                    second_pass,
                    camera_by_id[camera_id],
                    frames_by_id[camera_id],
                    args,
                ): camera_id
                for camera_id in eligible_ids
            }

            completed = 0
            for future in as_completed(future_map):
                camera_id = future_map[future]
                changed, delta, error = future.result()
                result = results_by_id[camera_id]
                result.changed_second_pass = changed
                result.mean_abs_pixel_delta = delta

                if error:
                    result.error = (
                        f"{result.error}; second pass: {error}".strip("; ")
                    )
                elif changed is False:
                    result.suspicious = True
                    if result.classification == "live_looking":
                        result.classification = "unchanged_frame"
                    frozen_reason = (
                        f"second-pass frame unchanged "
                        f"(mean pixel delta={delta:.4f})"
                    )
                    result.reasons = (
                        f"{result.reasons}; {frozen_reason}".strip("; ")
                    )

                completed += 1
                if completed % 25 == 0 or completed == len(eligible_ids):
                    print(f"  second pass {completed}/{len(eligible_ids)}")

    # Preserve original JSON order.
    ordered_results = [
        results_by_id[str(camera.get("id", ""))]
        for camera in cameras
        if str(camera.get("id", "")) in results_by_id
    ]

    write_reports(ordered_results, args.output_dir)
    print_summary(ordered_results)

    print(f"\nReports written to: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
