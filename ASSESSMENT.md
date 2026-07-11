# Project Assessment — Austin Traffic Camera Map

_Prepared 2026-07-10. A snapshot of the proof of concept and a starting point for
planning where it goes next._

## 1. What this project is

A public, interactive map of Austin's ~1,000 traffic cameras with live screenshot
previews, backed by two small Python tools:

- **`csv_to_cameras_json.py`** — turns the city's CSV export into `cameras.json`.
- **`audit_cameras.py`** — downloads every camera image and grades feed health
  (live / black / blank / frozen / error).

The three pieces form a rough pipeline: **city CSV → `cameras.json` → map**, with the
audit tool sitting off to the side as an independent quality check that nothing yet
consumes.

## 2. Current state — what works

- **The map is genuinely usable.** Clustering, status filtering, full-text search,
  geolocation, mobile layout, and per-camera popups with live previews all work in a
  single dependency-light static file.
- **The data conversion is clean and correct.** 1,004 records, all with unique IDs,
  valid Austin coordinates, and a screenshot URL. No duplicates, no malformed rows in
  the current dataset.
- **The audit tool is solid.** A recent full run downloaded 810 of 817 active feeds
  successfully; the 7 failures are genuinely `403` on the origin (confirmed with
  `curl`), not tool bugs. It has retries, concurrency, header/error capture for
  debugging, frozen-frame detection, and image-saving modes.
- **Frontend hygiene is good.** HTML is escaped everywhere, image requests use
  `referrerpolicy="no-referrer"`, broken previews fall back gracefully, and CDN
  dependencies are version-pinned.

This is a working proof of concept, not a sketch.

## 3. Gaps and risks

### Product / direction
- **The value proposition isn't stated.** Is this a public utility ("find a working
  camera near me"), an accountability tool ("which taxpayer-funded cameras are dark?"),
  or a data/archival project? Each implies a different roadmap. This is the most
  important open question.
- **The audit is disconnected from the map.** The most obvious differentiator —
  showing which feeds are actually alive — exists in the tooling but never reaches the
  user. Right now a dead camera just shows "Preview unavailable."

### Data pipeline
- **Refresh is fully manual.** Someone has to export a CSV, run the converter, and
  commit the result. There's no scheduled or automated update, so the map drifts out
  of date silently.
- **`cameras.json` is committed and regenerated wholesale (~720 KB).** Every refresh
  rewrites the whole file, which will bloat git history over time. Fine for now; worth
  a strategy before it accumulates.
- **Non-active cameras carry screenshot URLs.** All 187 DESIRED/VOID/REMOVED records
  have image URLs that will generally `403`. Their popups show broken previews.

### Operations / hardening
- **No automation or CI.** No build, test, deploy, or scheduled-audit workflow.
- **No `LICENSE`, `.gitignore` was missing** (added in this pass).
- **Analytics without consent.** A hardcoded Google Analytics ID runs on every load
  with no consent banner — a legal/privacy consideration for a public site.
- **No Subresource Integrity (SRI)** on the unpkg CDN scripts; a compromised CDN could
  inject code. Low probability, easy to mitigate.
- **The map hammers the city's origin directly.** Every open popup pulls from
  `cctv.austinmobility.io`. At low traffic this is fine; at scale it means no caching,
  no control over rate, and reliance on the city's CORS/referrer policy staying
  permissive.

### Engineering details (minor)
- `audit_cameras.py` opens a new `requests.Session` per camera, losing connection
  pooling. A shared/thread-local session would be faster.
- The audit's image classification heuristics (thresholds for black/blank/low-entropy)
  are reasonable but unvalidated against labeled ground truth.
- `csv_to_cameras_json.py` trusts the CSV's status/field values without normalization
  and has a date-stamped default input filename.

## 4. Three possible directions

These aren't mutually exclusive, but leading with one clarifies everything else.

### A. Public utility — "working cameras near you"
Lean into the map as a citizen tool. Integrate audit results so users see feed
health at a glance, emphasize "locate me" + nearby live cameras, add deep links and
shareable views. **Next steps:** publish `audit.json`, badge markers by health, run
the audit on a schedule.

### B. Accountability / transparency — "which cameras are dark?"
Frame it around civic oversight: track how many cameras are down, for how long, by
council district. This turns the audit from a background check into the product.
**Next steps:** persist audit history over time, add uptime stats and per-district
rollups, expose a "problem feeds" view.

### C. Data / archive — "a record over time"
Capture and store camera imagery on a schedule to build a historical archive
(traffic patterns, construction, incidents). **Next steps:** scheduled capture to
object storage, retention policy, and a bigger conversation about storage cost,
bandwidth on the city's origin, and terms-of-use for rehosting images.

## 5. Recommended near-term path

Regardless of direction, these unlock the others and are low-risk:

1. **Automate the data refresh.** Pull directly from the city's open-data API
   (Socrata) on a schedule instead of manual CSV export, and regenerate `cameras.json`
   in CI. Removes the biggest source of staleness.
2. **Wire the audit into the map.** Publish the audit's JSON as an artifact the map
   reads, and reflect feed health on markers/popups. This is the single highest-value,
   lowest-effort feature and it's already 80% built.
3. **Schedule the audit.** A recurring job (GitHub Actions or similar) that runs the
   audit and commits/publishes results makes health data live rather than a one-off.
4. **Basic hardening.** Add a `LICENSE`, add SRI hashes to CDN scripts, and decide on
   an analytics-consent posture before promoting the site.

Then pick a direction (Section 4) and let it drive the deeper roadmap.

## 6. Open questions for planning

- Who is the primary user, and what do they come here to do?
- Is refreshing the data and re-running the audit something you want to happen
  automatically, and how fresh does it need to be (hourly, daily, weekly)?
- Where is (or will) this be hosted, and is there a budget for compute/storage if we
  add scheduled audits or image archiving?
- Are there terms-of-use constraints on rehosting or caching the city's camera images?
- Is the Google Analytics tracking intentional and cleared for a public launch?
