"""
server_state.py
Shared, single-source-of-truth server state for the Nepal Power Plant &
Transmission Line License Status web app. Both app.py (public dashboard)
and admin.py (admin panel) import from here — this avoids a circular
import between them and means there is exactly one copy of "what data is
currently loaded" no matter which route touched it last.

STORAGE NOTE: files are written under DATA_DIR, which defaults to a local
./data folder next to this file. On Render's free/starter web service tier
this disk is EPHEMERAL — it's wiped on every redeploy and on some restarts.
For uploads to survive redeploys, attach a Render Persistent Disk and point
DATA_DIR at its mount path via the DATA_DIR environment variable. This is
called out again in the README.
"""

import os
import json
import traceback

import data_engine as de

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
GIS_DIR = os.path.join(DATA_DIR, "gis")
ASSETS_DIR = os.path.join(DATA_DIR, "assets")
for d in (DATA_DIR, GIS_DIR, ASSETS_DIR):
    os.makedirs(d, exist_ok=True)

WORKBOOK_PATH = os.path.join(DATA_DIR, "workbook.xlsx")
GIS_ZIP_PATH = os.path.join(GIS_DIR, "hermes_NPL_new_wgs.zip")
PA_ZIP_PATH = os.path.join(GIS_DIR, "Protected_Area.zip")
LOGO_PATH_JSON = os.path.join(DATA_DIR, "config.json")

STATE = {
    "loader": None,
    "gis_loaded": False,
    "pa_loaded": False,
    "error": None,
    "source_label": "No data loaded yet",
    "last_sync": None,
    "logo_filename": None,
    "flag_filename": None,
}


def _read_config_file():
    """Pure read of the on-disk config — no STATE side effects. Used both
    at startup (see _sync_state_from_config) and internally by
    _save_config when merging in a new value."""
    if os.path.exists(LOGO_PATH_JSON):
        try:
            with open(LOGO_PATH_JSON) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _sync_state_from_config():
    """Populate STATE from disk once at process startup. Deliberately NOT
    called from _save_config — doing so previously clobbered fresh
    in-memory writes with stale on-disk values (e.g. set_marquee_enabled()
    would set STATE then immediately have it overwritten back to the old
    value by _save_config's internal reload, even though the file on disk
    ended up correct). Keeping this as a separate, startup-only step fixes
    that."""
    cfg = _read_config_file()
    STATE["logo_filename"] = cfg.get("logo_filename")
    STATE["flag_filename"] = cfg.get("flag_filename")
    STATE["background_filename"] = cfg.get("background_filename")
    STATE["marquee_enabled"] = cfg.get("marquee_enabled", True)
    STATE["last_sync"] = cfg.get("last_sync")
    STATE["type_bg"] = cfg.get("type_bg", {})
    STATE["province_bg"] = cfg.get("province_bg", {})
    STATE["visitor_count"] = cfg.get("visitor_count", 0)
    return cfg


def _save_config(**updates):
    cfg = _read_config_file()
    cfg.update(updates)
    with open(LOGO_PATH_JSON, "w") as f:
        json.dump(cfg, f)


_sync_state_from_config()


def ensure_gis_loaded(force=False):
    """(Re)load the GIS district/province + protected-area polygons from
    whatever has been uploaded via the admin panel, if anything."""
    if force:
        STATE["gis_loaded"] = False
        STATE["pa_loaded"] = False
    if not STATE["gis_loaded"]:
        try:
            if os.path.exists(GIS_ZIP_PATH):
                ok = de.GIS.load_from_path(GIS_ZIP_PATH)
            else:
                ok = de.GIS.load()  # falls back to searching next to app.py
            STATE["gis_loaded"] = bool(ok)
        except Exception:
            traceback.print_exc()
            STATE["gis_loaded"] = False
    if not STATE["pa_loaded"]:
        try:
            if os.path.exists(PA_ZIP_PATH):
                ok = de.GIS.load_protected_from_path(PA_ZIP_PATH)
            else:
                ok = de.GIS.load_protected()
            STATE["pa_loaded"] = bool(ok)
        except Exception:
            traceback.print_exc()
            STATE["pa_loaded"] = False


def load_from_path(path, label):
    ensure_gis_loaded()
    loader = de.DataLoader(path)
    loader.load()
    STATE["loader"] = loader
    STATE["error"] = loader.error
    STATE["source_label"] = label
    return loader


def load_from_google_sheet(url_or_id):
    de.download_google_sheet_xlsx(url_or_id, WORKBOOK_PATH)
    loader = load_from_path(WORKBOOK_PATH, "Google Sheet (live sync)")
    _save_config(last_sync=_now_str(), source="google_sheet", gs_url=url_or_id)
    STATE["last_sync"] = _now_str()
    return loader


def load_from_uploaded_workbook(saved_path, filename):
    loader = load_from_path(saved_path, f"Uploaded file: {filename}")
    _save_config(last_sync=_now_str(), source="upload")
    STATE["last_sync"] = _now_str()
    return loader


def _reparse_current_workbook_if_any():
    """After the GIS or protected-area layer changes, the district/
    province/local-body assignment on every already-loaded record is
    stale — that lookup only happens once, at workbook parse time. Re-run
    the parse against whatever workbook is currently loaded (if any) so
    it picks up the new boundaries immediately instead of waiting for the
    next scheduled sheet refresh."""
    loader = STATE.get("loader")
    if loader is not None and getattr(loader, "path", None) and os.path.exists(loader.path):
        try:
            load_from_path(loader.path, STATE.get("source_label", "Reloaded after GIS update"))
        except Exception:
            traceback.print_exc()


def load_gis_from_drive(url_or_id):
    """Fast path for the GIS district/province package: pull the zip
    directly from a Google Drive share link instead of an admin file
    upload. Lets the admin update the boundary package by just replacing
    the file in Drive — no redeploy, no re-upload through the browser."""
    _, changed = de.download_google_drive_file(url_or_id, GIS_ZIP_PATH)
    ensure_gis_loaded(force=True)
    _save_config(gis_drive_url=url_or_id, last_gis_sync=_now_str())
    if changed:
        _reparse_current_workbook_if_any()
    return changed


def load_pa_from_drive(url_or_id):
    """Same as load_gis_from_drive, for the protected-area package."""
    _, changed = de.download_google_drive_file(url_or_id, PA_ZIP_PATH)
    ensure_gis_loaded(force=True)
    _save_config(pa_drive_url=url_or_id, last_pa_sync=_now_str())
    if changed:
        _reparse_current_workbook_if_any()
    return changed


def reload_cached_on_startup():
    """Superseded by bootstrap_on_startup() below — kept as a thin alias
    so nothing that still imports the old name breaks."""
    bootstrap_on_startup()


def bootstrap_on_startup():
    """Runs once when the process starts (see app.py). On Render's
    ephemeral disk, WORKBOOK_PATH / GIS_ZIP_PATH / config.json are all
    wiped on every redeploy — so a cached *file* surviving is not
    something to rely on. What DOES survive a redeploy is an environment
    variable set in the Render dashboard. So the durable source of truth
    is three env vars:

        DEFAULT_SHEET_URL       — the Google Sheet to sync from
        DEFAULT_GIS_DRIVE_URL   — the GIS district/province zip's Drive link
        DEFAULT_PA_DRIVE_URL    — the protected-area zip's Drive link (optional)

    Set these once in Render -> Environment. Every time the process starts
    (including after a redeploy that wiped the disk) it re-fetches fresh
    copies of all three straight from the source, so the dashboard is
    never left showing nothing — it self-heals within seconds of booting,
    without an admin needing to click "sync now" again. If a live fetch
    fails (e.g. a momentary network hiccup), it falls back to whatever
    was already cached on disk for that item; ensure_gis_loaded() further
    falls back to searching next to app.py, as before.

    If a Render Persistent Disk IS attached (DATA_DIR pointed at its
    mount path), the values saved in config.json by previous admin syncs
    take priority over the env vars — so a more recent admin-panel change
    always wins over the original bootstrap default.
    """
    cfg = _read_config_file()
    sheet_url = cfg.get("gs_url") or os.environ.get("DEFAULT_SHEET_URL")
    gis_url = cfg.get("gis_drive_url") or os.environ.get("DEFAULT_GIS_DRIVE_URL")
    pa_url = cfg.get("pa_drive_url") or os.environ.get("DEFAULT_PA_DRIVE_URL")

    # GIS/PA polygons MUST be in place before the workbook is parsed: the
    # district/province/local-body lookup for every record happens once,
    # at parse time, in DataLoader.load() — not re-checked later. Loading
    # the workbook first (the old order) meant every project would parse
    # with an empty district/province whenever GIS hadn't finished loading
    # yet, and that emptiness was then permanent for the rest of the
    # process's life (see record_local()'s memoization) until the next
    # manual re-sync. Fetch GIS/PA first, workbook/sheet last.
    if gis_url:
        try:
            load_gis_from_drive(gis_url)
        except Exception:
            traceback.print_exc()
    if pa_url:
        try:
            load_pa_from_drive(pa_url)
        except Exception:
            traceback.print_exc()
    ensure_gis_loaded()  # fallback: cached zip on disk, or next to app.py

    if sheet_url:
        try:
            load_from_google_sheet(sheet_url)
        except Exception:
            traceback.print_exc()
            if os.path.exists(WORKBOOK_PATH):
                try:
                    load_from_path(WORKBOOK_PATH, "Cached workbook (Sheet fetch failed)")
                except Exception:
                    traceback.print_exc()
    elif os.path.exists(WORKBOOK_PATH):
        try:
            load_from_path(WORKBOOK_PATH, "Cached workbook (auto-restored)")
        except Exception:
            traceback.print_exc()


_REFRESH_INTERVAL_SECONDS = int(os.environ.get("AUTO_REFRESH_HOURS", "6")) * 3600


def start_background_refresh():
    """Keeps the live site in sync with the Google Sheet/Drive on its own,
    on a timer, so data doesn't go stale between admin visits even if the
    process itself never restarts. Defaults to every 6 hours — override
    with the AUTO_REFRESH_HOURS env var. Safe to call once per worker
    process at import time; each timer re-schedules itself."""
    import threading

    def _tick():
        try:
            cfg = _read_config_file()
            sheet_url = cfg.get("gs_url") or os.environ.get("DEFAULT_SHEET_URL")
            gis_url = cfg.get("gis_drive_url") or os.environ.get("DEFAULT_GIS_DRIVE_URL")
            pa_url = cfg.get("pa_drive_url") or os.environ.get("DEFAULT_PA_DRIVE_URL")
            if gis_url:
                load_gis_from_drive(gis_url)
            if pa_url:
                load_pa_from_drive(pa_url)
            if sheet_url:
                load_from_google_sheet(sheet_url)
        except Exception:
            traceback.print_exc()
        finally:
            t = threading.Timer(_REFRESH_INTERVAL_SECONDS, _tick)
            t.daemon = True
            t.start()

    t = threading.Timer(_REFRESH_INTERVAL_SECONDS, _tick)
    t.daemon = True
    t.start()


def _now_str():
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def get_last_sync():
    return STATE.get("last_sync")


def get_logo_path():
    fn = STATE.get("logo_filename")
    if fn and os.path.exists(os.path.join(ASSETS_DIR, fn)):
        return os.path.join(ASSETS_DIR, fn)
    return None


def set_logo(filename):
    STATE["logo_filename"] = filename
    _save_config(logo_filename=filename)


# Bundled default the app ships with — used only as a fallback until an
# admin uploads a replacement, so the flag never just disappears.
_BUNDLED_FLAG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nepal_flag.png")


def get_flag_path():
    """Admin-uploaded flag image if one exists, else the bundled default
    shipped with the repo. This used to be a hardcoded path in app.py's
    navbar (`/assets/nepal_flag.png`, which also silently 404'd because
    Dash only serves that route from a folder literally named `assets/`)
    — now it's admin-replaceable the same way the org logo already is,
    and never breaks even if nothing's been uploaded."""
    fn = STATE.get("flag_filename")
    if fn and os.path.exists(os.path.join(ASSETS_DIR, fn)):
        return os.path.join(ASSETS_DIR, fn)
    if os.path.exists(_BUNDLED_FLAG_PATH):
        return _BUNDLED_FLAG_PATH
    return None


def set_flag_image(filename):
    STATE["flag_filename"] = filename
    _save_config(flag_filename=filename)


def get_background_path():
    fn = STATE.get("background_filename")
    if fn and os.path.exists(os.path.join(ASSETS_DIR, fn)):
        return os.path.join(ASSETS_DIR, fn)
    return None


def set_background(filename):
    STATE["background_filename"] = filename
    _save_config(background_filename=filename)


def get_marquee_enabled():
    return STATE.get("marquee_enabled", True)


def set_marquee_enabled(enabled):
    STATE["marquee_enabled"] = bool(enabled)
    _save_config(marquee_enabled=bool(enabled))


def bump_visitor_count():
    """Increments and returns the all-time visitor count. Called once per
    browser (gated by a session cookie in app.py, not once per page
    interaction) so repeat clicks around the dashboard don't inflate it."""
    n = int(STATE.get("visitor_count", 0)) + 1
    STATE["visitor_count"] = n
    _save_config(visitor_count=n)
    return n


def get_visitor_count():
    return int(STATE.get("visitor_count", 0))


def slugify_type(type_name):
    """Turn a project-type label ('Hydro (>1MW)') into a filesystem/URL-safe
    slug ('hydro_gt1mw') used both for the saved filename and the lookup key
    in config.json's type_bg map."""
    s = type_name.lower().strip()
    s = s.replace(">", "gt").replace("<=", "lte").replace("<", "lt")
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def get_type_bg_path(type_name):
    slug = slugify_type(type_name)
    fn = STATE.get("type_bg", {}).get(slug)
    if fn and os.path.exists(os.path.join(ASSETS_DIR, fn)):
        return os.path.join(ASSETS_DIR, fn)
    return None


def get_type_bg_url(type_name):
    """Public URL path (served by app.py's /assets-type-bg/<slug> route) if
    a background has been uploaded for this project type, else None."""
    slug = slugify_type(type_name)
    if STATE.get("type_bg", {}).get(slug):
        return f"/assets-type-bg/{slug}"
    return None


def set_type_bg(type_name, filename):
    slug = slugify_type(type_name)
    d = dict(STATE.get("type_bg") or {})
    d[slug] = filename
    STATE["type_bg"] = d
    _save_config(type_bg=d)


def get_province_bg_path(province_name):
    slug = slugify_type(province_name)
    fn = STATE.get("province_bg", {}).get(slug)
    if fn and os.path.exists(os.path.join(ASSETS_DIR, fn)):
        return os.path.join(ASSETS_DIR, fn)
    return None


def get_province_bg_url(province_name):
    slug = slugify_type(province_name)
    if STATE.get("province_bg", {}).get(slug):
        return f"/assets-province-bg/{slug}"
    return None


def set_province_bg(province_name, filename):
    slug = slugify_type(province_name)
    d = dict(STATE.get("province_bg") or {})
    d[slug] = filename
    STATE["province_bg"] = d
    _save_config(province_bg=d)
