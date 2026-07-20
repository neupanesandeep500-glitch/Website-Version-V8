# Nepal Power Plant & Transmission Line License Status — Web Edition

## Changelog — this session (verified against the actual GitHub repo)

**Important finding first:** the repo's git history has only 2 commits —
an empty "Initial commit" and one bulk "Add files via upload" — so the
detailed fixes described in the two changelog entries below this one
(flag-in-`assets/`, the `f-year` property fix, etc.) describe work that
was done in some session, but **wasn't actually all committed here**.
Specifically confirmed still broken before this session: there is no
`assets/` folder in the repo (`nepal_flag.png` sits at the repo root),
so `/assets/nepal_flag.png` 404s — the flag-fix changelog entry was
aspirational, not real, for this repo. Worth checking whether there's a
newer version of this code somewhere else before trusting older
changelog entries at face value.

Fixes below were made against the actual current `app.py`/`admin.py` in
this repo (not a stale copy) and verified with `pytest` — 39 tests,
`tests/` folder added.

- **GIS map showing nothing**: `render_gis()` had a single gate —
  `if not de.GIS.loaded: return "map is being updated"` — that hid the
  *entire* map, including project location markers, whenever only the
  district/province boundary package hadn't been synced. Plant markers
  and license-boundary polygons come from the workbook, not from that
  package, so this was blanking useful data unnecessarily. Fixed: the
  map now always shows whatever it can (markers/boundaries), with a
  small dismissable banner only when boundary *shading* specifically
  isn't loaded. Regression-tested in `tests/test_dashboard_fixes.py`.
- **"No data" messaging made actionable**: the top-level empty-state
  alert (shown on every main tab when nothing is loaded) now names
  `/admin` directly, mentions `DEFAULT_SHEET_URL`, and surfaces the
  actual loader error if there is one — instead of a generic "check back
  shortly." This can't fix a missing Render env var from here, but it
  now tells whoever's looking exactly what to check.
- **Nepal flag made admin-uploadable**: added `set_flag_image()` /
  `get_flag_path()` (mirrors the existing logo mechanism), a new
  `/assets-flag` route, and an upload form in the admin panel. This also
  fixes the flag 404 as a side effect — the new route doesn't depend on
  Dash's `assets/`-folder convention at all, and falls back to the
  bundled `nepal_flag.png` if nothing's been uploaded, so the flag can
  never just disappear again.
- **Footer**: removed the "Data Source" status card from the public
  sidebar (it's still visible to admins at `/admin`); added a
  "🕒 Last Update: <date>" line next to the visitor counter instead.
- **Marquee format standardized**: every category segment now reads
  `{MW} MW • {N} Projects` consistently (some previously said `12 •`,
  others `12 projects`); the Transmission Line segment additionally
  shows `{KM} KM`.
- **Test suite added** (`tests/`, 39 tests): B.S. date parsing, sheet
  classification / category-separation invariant, coordinate-transform
  round trip, a synthetic-workbook `DataLoader` test, plus the two
  regression tests above for the GIS and marquee fixes, and Flask
  test-client smoke tests for the new flag route/admin upload/footer.

**Still needs a human check, not fixable from here:** whether
`DEFAULT_SHEET_URL` / `DEFAULT_GIS_DRIVE_URL` / `DEFAULT_PA_DRIVE_URL`
are actually set in Render's Environment tab — that's the most likely
reason the live site shows no data at all, and it's a secret value this
session has no access to. If they're set and it's still empty, check
that the Sheet/Drive links are shared as "Anyone with the link" and do
a manual "Sync now" from `/admin` to see the actual error message.

## Changelog — previous session (debugging pass on the live deployment)

Reproduced and fixed every regression reported against the deployed site:

- **Main tabs disappearing**: caused by `dbc.Tab(label=[html.I(...), "text"])` —
  a list of components as the `label` prop is unreliable on the pinned
  `dash-bootstrap-components==1.6.0`. Reverted to plain emoji-prefixed
  string labels (still visually distinct, but safe).
- **A crash bug of my own making, caught before shipping**: while wiring the
  marquee to the sidebar filters, I referenced `f-year`'s Dash property as
  `"value"` — but it's a `dcc.Store` here (property `"data"`), not a
  slider. That mismatch would have broken callback registration for the
  whole app. Fixed, and verified the callback runs end-to-end.
- **Admin login**: the fail-closed behavior (refuses to show a login form
  without `ADMIN_PASSWORD_HASH` set) was correct and intentional — but
  `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` / `FLASK_SECRET_KEY` were never
  actually documented in `render.yaml`. Added all three, with the exact
  command to generate the password hash in the comment.
- **Nepal flag not showing**: `nepal_flag.png` was sitting at the repo
  root, not inside a folder literally named `assets/` — Dash's static-file
  route requires that exact folder name. Created `assets/nepal_flag.png`;
  confirmed it now serves with a 200.
- **Marquee "largest"/"latest" looking like duplicates**: with few plants
  connecting per year, showing the top-3 of each list made unrelated
  projects look like they'd been double-counted between categories.
  Reduced both to a single entry each ("the largest", "the latest").
- **Marquee showing a constant total regardless of filters**: it was wired
  only to the data-load status and a 60-second timer. Now takes every
  sidebar filter as an Input and recomputes from the currently filtered
  record set.
- **Confirmed already working** (found, didn't need to (re)build): the
  capacity-range dropdown buckets (Below 1 MW → Above 100 MW), the
  date-slider removal (free YYYY / YYYY-MM / YYYY-MM-DD boxes only), the
  GIS map's rich hover detail (`data_engine.full_rec_tip` — province %,
  district %, rural municipality/municipality %, protected-area name + %,
  license number, dates) and its side detail panel, and the GIS tab's own
  Map / Protected-Areas-List sub-tabs were all already implemented in this
  repo. Verified each end-to-end with a synthetic workbook + a synthetic
  GIS/protected-area package rather than re-building any of it.

Tested this round: the full Flask test client against the homepage, the
admin panel, and the flag asset; every major tab renderer
(`render_overview`, `render_plants_tab`, `render_gis_tab`,
`render_side_category_tab`); the ticker builder and its callback with the
`f-year` fix in place; the GIS hover-detail callback with a simulated
hover payload; and the tab-aware filter-tree callback. Real Google
Sheet/Drive files still aren't available from here — do a spot-check on
staging after deploying, particularly the marquee's largest/latest picks
and the flag rendering.

## Changelog — previous session (marquee dedup, flag fix, filter UI, footer)

- **Marquee duplicate bug fixed**: "Largest connected this year" and "Latest
  connected" were computed from two different pools — Largest from this
  year's plants, Latest from *all-time* plants sorted by COD date — so a
  project (e.g. this year's biggest COD) could legitimately appear in both.
  Both segments are now scoped to the *same* pool (connected this year), and
  Latest explicitly excludes whatever Largest already picked, so no project
  is ever listed twice across the two segments. Verified with a synthetic
  dataset reproducing the Mewa Khola / Hidi Khola / Siddhi Khola overlap.
- **Nepal flag now actually renders**: `nepal_flag.png` shipped at the repo
  root, but the navbar pointed at `/assets/nepal_flag.png` — the one path
  Dash serves as static files is the `assets/` folder, which didn't exist,
  so the flag 404'd silently. Added `assets/nepal_flag.png`; the flag is
  the leftmost element in the navbar, before the admin logo and title.
- **Capacity filter → dropdown bins**: replaced the 0–100 MW range slider
  (which had no way to reach real >100 MW projects) with a dropdown: All /
  Below 1 MW / 1–10 MW / 10–25 MW / 25–50 MW / 50–100 MW / Above 100 MW.
- **Date filter → text inputs only**: removed the B.S. year range slider.
  The YYYY / YYYY-MM / YYYY-MM-DD text boxes (License Date + COD Date) are
  now the sole date control, any range works.
- **Footer visitor counter**: now shows a placeholder immediately and a
  fallback if the count fetch fails, instead of a blank div while loading.
- Confirmed already working (tested against synthetic data covering every
  tab): all 9 main tabs render; KPI cards (Total Projects/Capacity/
  Operating/Transmission) recompute per filter, not fixed values; GIS map
  hover panel surfaces province/district/rural-municipality/protected-area
  overlap; admin login succeeds end-to-end once `ADMIN_USERNAME`,
  `ADMIN_PASSWORD_HASH`, and `FLASK_SECRET_KEY` are set on Render (if
  `/admin/login` is failing on your live site, it's almost certainly one of
  these three env vars missing — the app fails closed with a 503 explaining
  exactly that, by design, rather than falling back to a guessable default).

## Changelog — previous session (reliability + marquee + UI)

**⚠️ Action needed on Render:** set these in Render → your service →
Environment, then redeploy once:

- `DEFAULT_SHEET_URL` — your Google Sheet URL
- `DEFAULT_GIS_DRIVE_URL` — the GIS zip's Drive share link
- `DEFAULT_PA_DRIVE_URL` — the protected-area zip's Drive share link (optional)
- `AUTO_REFRESH_HOURS` — how often to auto re-sync in the background (default 6)

Without these, the dashboard still works exactly as before (admin can
sync by hand from the panel) — it just won't self-heal after a redeploy
wipes the disk, which is the "loads for a while, then reverts" symptom
this was meant to fix.

- **Found and fixed the likely cause of the intermittent data loss**:
  `Procfile`/`render.yaml` ran 2 gunicorn workers, each holding its own
  independent in-memory copy of the loaded data (workbook, GIS engine,
  visitor count) — requests bouncing between the two workers could show
  stale state. Reduced to `--workers 1 --threads 4`: one consistent
  in-memory copy, concurrency handled via threads instead.
- **Bootstrap ordering bug fixed**: the workbook was being parsed *before*
  the GIS package finished loading, so every project's district/province/
  local-body came back empty for that run (and, for local body, got
  permanently cached empty — see `data_engine.record_local`'s memoization
  fix). GIS/PA now load first on every startup, workbook last; and a GIS/
  PA Drive re-sync now automatically re-parses the current workbook too
  (`server_state._reparse_current_workbook_if_any`).
- **`server_state.bootstrap_on_startup()`** (replaces
  `reload_cached_on_startup`): pulls fresh Sheet/GIS/PA data from the
  `DEFAULT_*` env vars above at every process start, falling back to
  on-disk cache if a fetch fails. **`start_background_refresh()`** repeats
  this every `AUTO_REFRESH_HOURS` so the site stays current between admin
  visits too.
- **Marquee speed**: was a fixed 55s scroll regardless of how much text
  was in it, so a long ticker whipped by. Now scales to a steady ~9
  characters/second reading pace.
- **Marquee content**: added a placeholder-text filter
  (`_looks_like_place`) so stray sheet text ("loading", "TBD", "N/A")
  can't surface as a district/province name. Rewrote the connected-plant
  segments — "Largest connected this year" and "Latest connected" now
  list every Province/District/Local Body the project touches (not just
  one district), and added a plain "connected last year (full year)"
  total alongside the existing year-to-date-vs-same-period-last-year
  comparison.
- **Footer**: kept the visitor counter; copyright trimmed to "© 2026 Er.
  Sandeep Neupane. All rights reserved." (DoED/GoN line removed). Public
  "Admin login" link removed from the sidebar — `/admin/login` still
  works by URL, it's just not advertised on the public page.
- **Sidebar**: restructured into a collapsible tree
  (Location/Coordinate System → Project → Dates → Search) that
  auto-expands the group most relevant to whichever main tab is active —
  every filter still works from any tab, this only changes which group
  starts open.
- **Main tabs**: added icons and a gradient/pill active-tab style.

Tested this round: every render_* function, the ticker builder +
render_ticker_bar, the new sidebar accordion callback, and both the
public homepage and admin panel via Flask's test client — all against a
synthetic workbook + a synthetic GIS/protected-area package (real Sheet/
Drive files not available from here). Do a spot-check after deploying,
especially the district/province/local-body values on a few known
projects, since the bootstrap-ordering fix changes *when* those get
computed.

## Changelog — previous session

- **New file `coordinate_transform.py`**: proper Everest 1830 (DoED survey
  datum) ↔ WGS-84 conversion (3-parameter Molodensky shift). Applied
  automatically at ingestion in `data_engine.py` to every DoED "Latitude"/
  "Longitude" plain-pair and DMS-triplet coordinate (and the licence-area
  bounding box), so everything lines up with the WGS-84 GIS layer. UTM
  Easting/Northing values are left alone (already WGS-84 by construction).
  A sidebar toggle (**Coordinate System**) lets a visitor flip the *display*
  between the two systems on the GIS map hover text and the Data Table's
  Latitude/Longitude columns — the underlying WGS-84 storage never changes.
  See the constants at the top of `coordinate_transform.py` if DoED / Survey
  Department later supplies a more precise locally-surveyed shift.
- **Fast Google Drive sync** for the GIS package and the protected-area
  package (`data_engine.download_google_drive_file`, wired into
  `server_state.py` and the admin panel): paste a Drive share link once
  (file shared "Anyone with the link"), hit "Sync now" — no redeploy, no
  browser upload. Manual upload is still there as a fallback. The Google
  Sheet sync already worked this way; it's untouched.
- **Live clock** (top navbar + footer), ticking client-side in JS — no
  server round-trip — matching the desktop app's header clock style
  (`WEEKDAY, DD MONTH YYYY` / `🕐 hh:mm:ss AM/PM`).
- **Footer**: useful links (MoEWRI, ERC, WECS, DoED, NEA — verified current
  URLs), a persistent visitor counter (`server_state.bump_visitor_count`,
  gated by session cookie so repeat page loads in one visit don't inflate
  it), and the copyright line.
- **Two new dedicated tabs**: *GoN Studied Projects* and *License Cancelled*
  (`render_side_category_tab`). Previously these statuses could leak into
  the Power Plants / Transmission / Growth / Compare views because those
  only excluded `type == "Transmission Line"`, not the "side" statuses.
  `render_tab` now builds an `active_recs` list (pipeline statuses only)
  for the core views and a separate unfiltered `recs` list for the two new
  tabs, so the categories never mix.
- **Exact-date filters**: License Date and COD Date now each have a free
  YYYY-MM-DD (or YYYY, or YYYY-MM) from/to text box in the sidebar, on top
  of the existing year slider — wired straight into `loader.filter()`'s
  existing `year_from/year_to`/`cod_from/cod_to` params via
  `de.parse_bs_input`, which already supported this; only the UI was
  missing.
- **Public-page message cleanup**: removed internal/dev-facing text from
  visitor-facing alerts (missing-data, missing-GIS-package) and moved the
  "unresolved district text" diagnostic off the public Overview tab into
  the admin panel, where it belongs.

Everything above was tested with a synthetic workbook and the Flask test
client (import, admin panel render, public homepage render, visitor-counter
session-gating, datum round-trip) — see the session's tool transcript for
details. It has **not** been tested against the real, live DoED workbook,
Google Sheet, or a real Drive-hosted GIS zip — do a sync + spot-check on
staging before relying on it.

This is a **Dash/Plotly web port** of `Power_Plant_Status_Dashboard.py`. It keeps
the original data engine intact and rebuilds the interface for the browser.

## Why the old file couldn't deploy on Render as-is

`Power_Plant_Status_Dashboard.py` is a **desktop GUI app** — `tkinter` +
`matplotlib.use("TkAgg")` — which needs a real display to draw windows.
Render's servers are headless (no screen), so the import fails immediately.
That's the "could not load the website module" error. There's no config fix
for this — the UI layer has to be a real web framework, which is what this
does.

## What changed vs. what's identical

**Identical (ported as-is, unchanged logic):**
- `DataLoader` — Excel workbook parsing, sheet classification (survey /
  construction / operating / cancelled / GoN study), BS date parsing,
  district/province resolution, KPI + yearly-series aggregation.
- `GISEngine` — district/province point-in-polygon engine, protected-area
  overlap checks, coordinate parsing (decimal / DMS / UTM).
- Google Sheets live-sync download.
- All colour palettes / status / type constants.

All of this lives in **`data_engine.py`**, with only the `tkinter` import
and `matplotlib.use("TkAgg")` removed (`Agg` instead — headless-safe).

**Rebuilt for the web (in `app.py`):**
- Tabs: **Overview** (KPI cards, capacity-by-type, stage breakdown, projects
  by province), **Growth Trends** (yearly capacity/count lines), **GIS Map**
  (interactive Plotly map — district choropleth + project markers, replacing
  the Tk canvas map), **Comparative Charts** (plants vs. transmission lines,
  kept on separate axes as in the original), **Data Table** (sortable/
  filterable/exportable).
- Filters sidebar (type, stage, province, capacity, license year, search) —
  same fields as the desktop filters, now live-updating Plotly charts.
- Read-only Data Source status card (what's loaded, when it last synced) —
  actual syncing/uploading now lives behind the login-gated **`/admin`**
  panel, described below.
- **Real Nepal flag** in the navbar — the exact PNG artwork embedded in the
  original desktop app, extracted byte-for-byte and shipped as
  `assets/nepal_flag.png` (no re-drawing, no external asset link to break).
- **Live KPI ticker (marquee)** — the same scrolling news-style strip as the
  desktop app's canvas ticker: active plant totals, per-stage breakdown,
  transmission summary, GoN/cancelled counts, top hydro/solar province,
  year-over-year capacity growth, latest connected projects. Built with a
  pure CSS animation (`assets/ticker.css`) instead of a canvas loop — same
  content, no extra JS dependency. Admin can turn it on/off from `/admin`.
- **Hero/background photo** — optional banner behind the dashboard title,
  admin-uploadable, auto-dimmed with a gradient overlay so text stays
  readable; the section simply hides itself if nothing's been uploaded.
- "Download PDF Report" button — server-side matplotlib (`Agg` backend)
  report generation, same technique the desktop app already used for its
  PDF export, just triggered from the browser instead of a Tk button.

**Not yet ported (flag if you want these added next):**
- The full multi-page PDF report (`_rpt_*` methods) — the button currently
  builds a 2-page summary PDF as a working example; the original's full
  report (period stats, monthly series, choropleth page, licence-map page,
  protected-area page) can be added the same way.
- Persistent per-user `settings.json` (chart style/palette/interval) — the
  desktop app saved this to disk; a shared web server needs this in
  browser storage or a per-session cookie instead, worth a design chat if
  you want it.
- Protected-area map overlay tab (data + logic are ported in `GISEngine`,
  just needs a map trace like the district choropleth).

## Files you still need to add before deploying

The uploaded files didn't include your data — copy these into this folder:

1. **`License Dashboard .xlsx`** — not required if you're using the Google
   Sheet sync exclusively, but useful as a local fallback.
2. **`hermes_NPL_new_wgs.zip`** — the district/province polygon package.
   Without it, GIS features fall back gracefully (a warning banner shows on
   the GIS Map tab instead of crashing) but the map/choropleth won't render.
3. **`Protected_Area.zip`** — optional, only needed if/when the protected-area
   overlay tab is added.

## Admin panel (`/admin`)

Uploading the workbook, GIS package, protected-area package, and logo is now
**login-gated** — the public dashboard is read-only with respect to data
sources (faster to load for visitors, and no one else can overwrite your
live data).

**Before first deploy, set these environment variables** (Render → your
service → Environment):

| Variable | Value |
|---|---|
| `ADMIN_USERNAME` | whatever username you want to log in with |
| `ADMIN_PASSWORD_HASH` | a hashed password — generate it locally with the command below, **never put the plain password itself in an env var** |
| `FLASK_SECRET_KEY` | any long random string (used to sign login sessions) |
| `DATA_DIR` | optional — see storage note below |

Generate the password hash:
```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password-here'))"
```
Paste the printed hash (starts with `pbkdf2:sha256:...` or `scrypt:...`) as
`ADMIN_PASSWORD_HASH`. If this variable isn't set, `/admin` refuses to serve
logins at all (fails closed) rather than falling back to a default password.

Once deployed, go to `yoursite.onrender.com/admin/login` and you'll get forms
to: sync the Google Sheet, upload a replacement `.xlsx`, upload the GIS zip,
upload the protected-area zip, upload a navbar logo, upload a background/hero
photo, and turn the KPI ticker/marquee on or off. Every POST is
CSRF-protected and requires the session cookie set at login.

**Storage note:** uploaded files are written to `./data` next to `app.py` by
default. Render's free/starter web-service disk is **ephemeral** — it's
wiped on redeploys and some restarts. For uploads to survive a redeploy,
either:
- attach a [Render Persistent Disk](https://render.com/docs/disks) to the
  service and set `DATA_DIR` to its mount path, or
- keep syncing from the Google Sheet after each redeploy (quick, and it's
  already the "live" source of truth anyway), or
- re-upload the GIS/PA zips again after a redeploy if you're not using a
  persistent disk (the app runs fine without them, just without the map).

## Deploy to Render

1. Push this folder to a GitHub repo (root should contain `app.py`,
   `data_engine.py`, `requirements.txt`, `Procfile`, `render.yaml`, and your
   GIS/data files from above).
2. On Render: **New → Blueprint** and point it at the repo (it will read
   `render.yaml` automatically), or **New → Web Service** and set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:server --workers 2 --timeout 120 --bind 0.0.0.0:$PORT`
3. Set the `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, and `FLASK_SECRET_KEY`
   environment variables described above, before or right after first
   deploy.
4. First load: go to `yoursite.onrender.com/admin/login`, log in, and sync
   the Google Sheet or upload the workbook/GIS files. The public dashboard
   picks up the change automatically within about a minute (it polls
   `server_state` every 60s) — no redeploy needed.

## Run locally

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:8050
```

## Known limitation on Render's free/starter tier

The loaded workbook is cached in server memory (one process). If you deploy
with more than 1 worker (`--workers` > 1 in the Procfile), each worker loads
its own copy independently until someone syncs on that worker — fine for a
small internal tool, but worth moving to Redis or a shared file if usage
grows. Flagging this rather than silently letting it surprise you.
