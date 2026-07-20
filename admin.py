"""
admin.py

Login-gated admin panel for the Nepal Power Plant & Transmission Line
License Status dashboard, mounted at /admin.

Lets an authenticated admin (only) do the things that used to be public
on the dashboard's Settings panel:
- Sync the Google Sheet data source
- Upload a replacement .xlsx workbook directly
- Upload the GIS district/province package (hermes_NPL_new_wgs.zip)
- Upload the protected-area package (Protected_Area.zip)
- Upload a logo/photo for the navbar

SECURITY
- Credentials are never hardcoded. Set these as environment variables
  on Render (or locally before running):
    ADMIN_USERNAME       e.g. "sandeep"
    ADMIN_PASSWORD_HASH  generate with:
      python -c "from werkzeug.security import generate_password_hash;
                 print(generate_password_hash('your-password-here'))"
  If ADMIN_PASSWORD_HASH is not set, the admin panel refuses to start
  (fails closed, not open) — see admin_configured().
- Flask's SECRET_KEY must also be set via env var in production
  (FLASK_SECRET_KEY) — without it, sessions reset on every worker
  restart, which is inconvenient but not by itself insecure; a
  *missing but guessable* key would be, so a random fallback is used
  only for local dev.
- A per-session CSRF token is required on every POST.
- Uploaded files are validated by extension before saving.

GIS/PA UPLOADS (updated this session): the GIS district/province zip and
the protected-area zip are parsed by pure-Python shapefile code, which is
CPU/memory-heavy for a national polygon set. The upload/sync routes below
now save the file and kick off parsing in a background thread
(server_state.start_gis_reload_async / start_pa_reload_async) instead of
blocking the request — a slow or memory-heavy parse used to be able to
exceed gunicorn's --timeout or exhaust memory, taking the single worker
(and therefore the whole site, admin panel included) down with a 502.
Now the request returns immediately and the panel polls
STATE['gis_loading']/['gis_load_error'] (and the pa_ equivalents) to show
progress instead.
"""

import os
import secrets
import functools

from flask import (
    Blueprint, request, session, redirect, url_for,
    render_template_string, flash, abort
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

import data_engine as de
import server_state as ss

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")


def admin_configured():
    return bool(ADMIN_PASSWORD_HASH)


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def _check_csrf():
    token = request.form.get("csrf_token", "")
    if not token or token != session.get("csrf_token"):
        abort(400, "Invalid or missing CSRF token — please retry from the form.")


BASE_STYLE = """
<style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; background:#f4f6f8; margin:0; }
  .wrap { max-width:880px; margin:40px auto; padding:0 16px; }
  .card { background:#fff; border-radius:10px; padding:24px 28px; margin-bottom:20px;
          box-shadow:0 1px 4px rgba(0,0,0,0.08); }
  h1 { font-size:22px; margin:0 0 4px; }
  h2 { font-size:16px; color:#1565c0; margin:0 0 12px; }
  label { display:block; font-size:13px; font-weight:600; color:#455a64; margin:10px 0 4px; }
  input[type=text], input[type=password], input[type=file] {
    width:100%; padding:8px 10px; border:1px solid #cfd8dc; border-radius:6px; font-size:14px;
    box-sizing:border-box;
  }
  button { background:#1565c0; color:#fff; border:none; padding:9px 18px; border-radius:6px;
           font-size:14px; cursor:pointer; margin-top:12px; }
  button.secondary { background:#607d8b; }
  button:hover { opacity:0.92; }
  .msg { padding:10px 14px; border-radius:6px; margin-bottom:14px; font-size:13px; }
  .msg.ok { background:#e8f5e9; color:#2e7d32; }
  .msg.err { background:#ffebee; color:#c62828; }
  .status { font-size:13px; color:#607d8b; margin-bottom:6px; }
  .status .loading { color:#b8790a; font-weight:600; }
  .status .failed { color:#c62828; font-weight:600; }
  a.logout { float:right; font-size:13px; color:#c62828; text-decoration:none; }
  a.back { font-size:13px; color:#1565c0; }
  .upload-row { display:flex; gap:18px; align-items:flex-start; }
  .upload-row .upload-form { flex:1 1 auto; min-width:0; }
  .upload-preview { flex:0 0 150px; text-align:center; }
  .upload-preview img { max-width:150px; max-height:110px; object-fit:cover;
    border:1px solid #cfd8dc; border-radius:6px; padding:3px; background:#fafafa; display:block; margin:0 auto; }
  .upload-preview .fname { font-size:11px; color:#607d8b; margin-top:5px; word-break:break-all; }
  .upload-preview .none-yet { font-size:12px; color:#90a4ae; font-style:italic; padding-top:30px; }
</style>
"""

LOGIN_TEMPLATE = BASE_STYLE + """
<div class="wrap">
  <div class="card">
    <h1>Admin Login</h1>
    <p class="status">Nepal Power Plant &amp; Transmission Line License Status — Dashboard</p>
    {% if error %}<div class="msg err">{{ error }}</div>{% endif %}
    <form method="post">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>Username</label>
      <input type="text" name="username" autofocus required>
      <label>Password</label>
      <input type="password" name="password" required>
      <button type="submit">Log in</button>
    </form>
  </div>
  <p><a class="back" href="/">&larr; Back to dashboard</a></p>
</div>
"""

PANEL_TEMPLATE = BASE_STYLE + """
<div class="wrap">
  <div class="card">
    <a class="logout" href="{{ url_for('admin.logout') }}">Log out</a>
    <h1>Admin Panel</h1>
    <p class="status">
      Logged in as <b>{{ username }}</b> &middot;
      {{ n_records }} records loaded &middot;
      Source: {{ source_label }} &middot;
      Last sync: {{ last_sync or "never" }} &middot;
      GIS package:
      {% if gis_loading %}<span class="loading">loading&hellip;</span>
      {% elif gis_load_error %}<span class="failed">failed</span>
      {% else %}{{ "loaded" if gis_loaded else "not loaded" }}{% endif %} &middot;
      Protected areas:
      {% if pa_loading %}<span class="loading">loading&hellip;</span>
      {% elif pa_load_error %}<span class="failed">failed</span>
      {% else %}{{ "loaded" if pa_loaded else "not loaded" }}{% endif %}
    </p>
    {% if gis_load_error %}<p class="status failed">GIS error: {{ gis_load_error }}</p>{% endif %}
    {% if pa_load_error %}<p class="status failed">Protected-area error: {{ pa_load_error }}</p>{% endif %}
  </div>

  {% if message %}<div class="msg {{ 'ok' if ok else 'err' }}">{{ message }}</div>{% endif %}

  <div class="card">
    <h2>1. Google Sheet live sync</h2>
    <form method="post" action="{{ url_for('admin.sync_sheet') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>Google Sheet URL (must be shared "Anyone with the link: Viewer")</label>
      <input type="text" name="gs_url" placeholder="https://docs.google.com/spreadsheets/d/&hellip;"
             value="{{ gs_url or '' }}">
      <button type="submit">Sync now</button>
    </form>
  </div>

  <div class="card">
    <h2>2. Upload workbook (.xlsx)</h2>
    <form method="post" action="{{ url_for('admin.upload_workbook') }}" enctype="multipart/form-data">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>DoED licence workbook</label>
      <input type="file" name="workbook" accept=".xlsx">
      <button type="submit">Upload &amp; load</button>
    </form>
  </div>

  <div class="card">
    <h2>3. GIS district/province package (hermes_NPL_new_wgs.zip)</h2>
    <p class="status">Fastest option: keep the zip in Google Drive, shared "Anyone with
      the link: Viewer", and paste the link below — updating it in Drive later needs
      no re-upload here, just hit "Sync now" again. Last Drive sync:
      {{ last_gis_sync or "never" }}. Parsing now runs in the background — this page
      returns immediately after you submit; refresh it to check progress, the site
      stays up the whole time.</p>
    <form method="post" action="{{ url_for('admin.sync_gis_drive') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>Google Drive link</label>
      <input type="text" name="gis_drive_url" placeholder="https://drive.google.com/file/d/&hellip;/view"
             value="{{ gis_drive_url or '' }}">
      <button type="submit">Sync now</button>
    </form>
    <p class="status" style="margin-top:14px;">Or upload the zip directly (max {{ max_gis_mb }} MB):</p>
    <form method="post" action="{{ url_for('admin.upload_gis') }}" enctype="multipart/form-data">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <input type="file" name="gis_zip" accept=".zip">
      <button type="submit" class="secondary">Upload &amp; reload GIS</button>
    </form>
  </div>

  <div class="card">
    <h2>4. Protected-area package (optional)</h2>
    <p class="status">Same fast path as above, via Google Drive. Last Drive sync:
      {{ last_pa_sync or "never" }}.</p>
    <form method="post" action="{{ url_for('admin.sync_pa_drive') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>Google Drive link</label>
      <input type="text" name="pa_drive_url" placeholder="https://drive.google.com/file/d/&hellip;/view"
             value="{{ pa_drive_url or '' }}">
      <button type="submit">Sync now</button>
    </form>
    <p class="status" style="margin-top:14px;">Or upload the zip directly (max {{ max_gis_mb }} MB):</p>
    <form method="post" action="{{ url_for('admin.upload_pa') }}" enctype="multipart/form-data">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <input type="file" name="pa_zip" accept=".zip">
      <button type="submit" class="secondary">Upload &amp; reload</button>
    </form>
  </div>

  {% if unmapped_districts %}
  <div class="card">
    <h2>District text not resolved to a GIS polygon</h2>
    <p class="status">Admin-only diagnostic — not shown to public visitors. These district
      names in the workbook didn't match the GIS district layer, so those records fall
      back to the province-level view only.</p>
    <p>{% for d, n in unmapped_districts %}{{ d }} ({{ n }}){% if not loop.last %}, {% endif %}{% endfor %}</p>
  </div>
  {% endif %}

  <div class="card">
    <h2>4b. Upload Nepal flag image</h2>
    <p class="status">Shown in the top-left of the navbar. Ships with a default
      flag image, but can be replaced here without touching any code — e.g.
      to swap in a higher-resolution version.</p>
    <div class="upload-row">
      <div class="upload-form">
        <form method="post" action="{{ url_for('admin.upload_flag') }}" enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <label>Flag image (PNG/JPG)</label>
          <input type="file" name="flag" accept=".png,.jpg,.jpeg">
          <button type="submit">Upload</button>
        </form>
      </div>
      <div class="upload-preview">
        <img src="/assets-flag?_={{ range(1,99999)|random }}" alt="Current flag">
        <div class="fname">{{ flag_filename or "bundled default" }}</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>5. Upload logo / photo</h2>
    <div class="upload-row">
      <div class="upload-form">
        <form method="post" action="{{ url_for('admin.upload_logo') }}" enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <label>Navbar logo (PNG/JPG)</label>
          <input type="file" name="logo" accept=".png,.jpg,.jpeg">
          <button type="submit">Upload</button>
        </form>
      </div>
      <div class="upload-preview">
        {% if logo_filename %}
        <img src="/assets-logo?_={{ range(1,99999)|random }}" alt="Current logo">
        <div class="fname">{{ logo_filename }}</div>
        {% else %}
        <div class="none-yet">No logo uploaded yet</div>
        {% endif %}
      </div>
    </div>
  </div>

  <div class="card">
    <h2>6. Upload background / hero photo</h2>
    <p class="status">Shown as a banner image behind the dashboard title — a wide,
      landscape photo (e.g. a hydropower dam, transmission towers, or the Nepal
      hills) works best. It's automatically dimmed with an overlay so page text
      stays readable.</p>
    <div class="upload-row">
      <div class="upload-form">
        <form method="post" action="{{ url_for('admin.upload_background') }}" enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <label>Background / hero photo (PNG/JPG)</label>
          <input type="file" name="background" accept=".png,.jpg,.jpeg">
          <button type="submit">Upload</button>
        </form>
      </div>
      <div class="upload-preview">
        {% if background_filename %}
        <img src="/assets-background?_={{ range(1,99999)|random }}" alt="Current background">
        <div class="fname">{{ background_filename }}</div>
        {% else %}
        <div class="none-yet">No background uploaded yet</div>
        {% endif %}
      </div>
    </div>
  </div>

  <div class="card">
    <h2>7. Live KPI ticker (marquee)</h2>
    <p class="status">Scrolling news-style strip on the Overview tab — active plant
      totals, per-stage breakdown, transmission summary, top hydro/solar
      province, capacity added this year vs. last, latest connected projects.
      Currently <b>{{ "ON" if marquee_enabled else "OFF" }}</b>.</p>
    <form method="post" action="{{ url_for('admin.toggle_marquee') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <input type="hidden" name="enable" value="{{ '0' if marquee_enabled else '1' }}">
      <button type="submit" class="{{ '' if marquee_enabled else 'secondary' }}">
        {{ "Turn marquee OFF" if marquee_enabled else "Turn marquee ON" }}
      </button>
    </form>
  </div>

  <div class="card">
    <h2>8. Project-type background images (Overview tab)</h2>
    <p class="status">Optional photo shown behind each project-type card in the
      Overview tab (e.g. a dam for Hydro, panels for Solar, turbines for Wind,
      towers for Transmission Line). Falls back to a plain colour card if none
      is uploaded for a type.</p>
    {% for t in project_types %}
    <div class="upload-row" style="margin-bottom:14px;">
      <div class="upload-form">
        <form method="post" action="{{ url_for('admin.upload_type_bg', slug=t.slug) }}"
              enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <label>{{ t.name }} {{ "(image set)" if t.has_bg else "(no image yet)" }}</label>
          <input type="file" name="type_bg" accept=".png,.jpg,.jpeg">
          <button type="submit">Upload</button>
        </form>
      </div>
      <div class="upload-preview">
        {% if t.has_bg %}
        <img src="{{ t.bg_url }}?_={{ range(1,99999)|random }}" alt="{{ t.name }} background">
        {% else %}
        <div class="none-yet">No image yet</div>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="card">
    <h2>9. Province background images (Power Plants tab)</h2>
    <p class="status">Optional photo shown behind each province card on the
      Power Plants tab's province breakdown.</p>
    {% for p in provinces %}
    <div class="upload-row" style="margin-bottom:14px;">
      <div class="upload-form">
        <form method="post" action="{{ url_for('admin.upload_province_bg', slug=p.slug) }}"
              enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
          <label>{{ p.name }} {{ "(image set)" if p.has_bg else "(no image yet)" }}</label>
          <input type="file" name="province_bg" accept=".png,.jpg,.jpeg">
          <button type="submit">Upload</button>
        </form>
      </div>
      <div class="upload-preview">
        {% if p.has_bg %}
        <img src="{{ p.bg_url }}?_={{ range(1,99999)|random }}" alt="{{ p.name }} background">
        {% else %}
        <div class="none-yet">No image yet</div>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <p><a class="back" href="/">&larr; Back to dashboard</a></p>
</div>
"""


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if not admin_configured():
        return ("Admin panel is not configured: set ADMIN_USERNAME and "
                "ADMIN_PASSWORD_HASH environment variables on the server "
                "before this page can be used."), 503

    error = None
    if request.method == "POST":
        _check_csrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session["is_admin"] = True
            session["username"] = username
            next_url = request.args.get("next") or url_for("admin.panel")
            return redirect(next_url)
        error = "Incorrect username or password."

    return render_template_string(LOGIN_TEMPLATE, error=error, csrf_token=_csrf_token())


@admin_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/", methods=["GET"])
@login_required
def panel(message=None, ok=True):
    loader = ss.STATE.get("loader")
    unmapped_districts = loader.get_unmapped_districts()[:20] if loader else []

    project_types = [
        {"name": t, "slug": ss.slugify_type(t), "has_bg": bool(ss.get_type_bg_path(t)),
         "bg_url": ss.get_type_bg_url(t)}
        for t in de.TYPE_ORDER
    ]
    provinces = [
        {"name": p, "slug": ss.slugify_type(p), "has_bg": bool(ss.get_province_bg_path(p)),
         "bg_url": ss.get_province_bg_url(p)}
        for p in de.PROVINCE_ORDER
    ]

    return render_template_string(
        PANEL_TEMPLATE,
        username=session.get("username"),
        n_records=len(loader.records) if loader else 0,
        source_label=ss.STATE.get("source_label"),
        last_sync=ss.get_last_sync(),
        gis_loaded=ss.STATE.get("gis_loaded"),
        pa_loaded=ss.STATE.get("pa_loaded"),
        gis_loading=ss.STATE.get("gis_loading"),
        pa_loading=ss.STATE.get("pa_loading"),
        gis_load_error=ss.STATE.get("gis_load_error"),
        pa_load_error=ss.STATE.get("pa_load_error"),
        max_gis_mb=ss.MAX_GIS_ZIP_MB,
        marquee_enabled=ss.get_marquee_enabled(),
        project_types=project_types,
        provinces=provinces,
        message=message, ok=ok,
        csrf_token=_csrf_token(),
        gs_url=None,
        gis_drive_url=ss.STATE.get("gis_drive_url"),
        pa_drive_url=ss.STATE.get("pa_drive_url"),
        last_gis_sync=ss.STATE.get("last_gis_sync"),
        last_pa_sync=ss.STATE.get("last_pa_sync"),
        unmapped_districts=unmapped_districts,
        flag_filename=ss.STATE.get("flag_filename") if ss.get_flag_path() else None,
        logo_filename=ss.STATE.get("logo_filename") if ss.get_logo_path() else None,
        background_filename=ss.STATE.get("background_filename") if ss.get_background_path() else None,
    )


@admin_bp.route("/sync-sheet", methods=["POST"])
@login_required
def sync_sheet():
    _check_csrf()
    gs_url = request.form.get("gs_url", "").strip()
    if not gs_url:
        return panel(message="Please paste a Google Sheet URL.", ok=False)
    try:
        loader = ss.load_from_google_sheet(gs_url)
        if loader.error:
            return panel(message=f"Loaded, but with a parse error: {loader.error}", ok=False)
        return panel(message=f"Synced successfully — {len(loader.records)} records loaded.", ok=True)
    except Exception as exc:
        return panel(message=f"Sync failed: {exc}", ok=False)


@admin_bp.route("/sync-gis-drive", methods=["POST"])
@login_required
def sync_gis_drive():
    _check_csrf()
    url = request.form.get("gis_drive_url", "").strip()
    if not url:
        return panel(message="Please paste a Google Drive link.", ok=False)
    # Both the download and the parse happen in the background now — a
    # large file's download alone used to be able to block this request
    # past gunicorn's timeout and take the whole site (admin panel
    # included) down with a 502. This route just kicks the job off.
    ss.start_gis_drive_sync_async(url)
    return panel(message="Sync started in the background (download + parse). "
                          "Refresh this page in ~30-90s for status; the "
                          "site and admin panel stay up the whole time.", ok=True)


@admin_bp.route("/sync-pa-drive", methods=["POST"])
@login_required
def sync_pa_drive():
    _check_csrf()
    url = request.form.get("pa_drive_url", "").strip()
    if not url:
        return panel(message="Please paste a Google Drive link.", ok=False)
    ss.start_pa_drive_sync_async(url)
    return panel(message="Sync started in the background (download + parse). "
                          "Refresh this page in ~30-90s for status.", ok=True)


@admin_bp.route("/upload-workbook", methods=["POST"])
@login_required
def upload_workbook():
    _check_csrf()
    file = request.files.get("workbook")
    if not file or not file.filename.lower().endswith(".xlsx"):
        return panel(message="Please choose a valid .xlsx file.", ok=False)
    file.save(ss.WORKBOOK_PATH)
    try:
        loader = ss.load_from_uploaded_workbook(ss.WORKBOOK_PATH, secure_filename(file.filename))
        if loader.error:
            return panel(message=f"Loaded, but with a parse error: {loader.error}", ok=False)
        return panel(message=f"Workbook uploaded — {len(loader.records)} records loaded.", ok=True)
    except Exception as exc:
        return panel(message=f"Upload failed: {exc}", ok=False)


@admin_bp.route("/upload-gis", methods=["POST"])
@login_required
def upload_gis():
    _check_csrf()
    file = request.files.get("gis_zip")
    if not file or not file.filename.lower().endswith(".zip"):
        return panel(message="Please choose a valid .zip file.", ok=False)
    file.save(ss.GIS_ZIP_PATH)
    try:
        ss._check_zip_size(ss.GIS_ZIP_PATH, "GIS package")
    except ValueError as exc:
        os.remove(ss.GIS_ZIP_PATH)
        return panel(message=str(exc), ok=False)
    ss.start_gis_reload_async()
    return panel(message="File saved — parsing in the background now "
                          "(can take a minute or two for a large "
                          "shapefile). Refresh this page for status; the "
                          "admin panel and public site stay responsive "
                          "the whole time.", ok=True)


@admin_bp.route("/upload-pa", methods=["POST"])
@login_required
def upload_pa():
    _check_csrf()
    file = request.files.get("pa_zip")
    if not file or not file.filename.lower().endswith(".zip"):
        return panel(message="Please choose a valid .zip file.", ok=False)
    file.save(ss.PA_ZIP_PATH)
    try:
        ss._check_zip_size(ss.PA_ZIP_PATH, "Protected-area package")
    except ValueError as exc:
        os.remove(ss.PA_ZIP_PATH)
        return panel(message=str(exc), ok=False)
    ss.start_pa_reload_async()
    return panel(message="File saved — parsing in the background now. "
                          "Refresh this page for status.", ok=True)


@admin_bp.route("/upload-flag", methods=["POST"])
@login_required
def upload_flag():
    _check_csrf()
    file = request.files.get("flag")
    if not file or not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return panel(message="Please choose a PNG or JPG file.", ok=False)
    filename = "flag_" + secure_filename(file.filename)
    file.save(os.path.join(ss.ASSETS_DIR, filename))
    ss.set_flag_image(filename)
    return panel(message="Flag image uploaded.", ok=True)


@admin_bp.route("/upload-logo", methods=["POST"])
@login_required
def upload_logo():
    _check_csrf()
    file = request.files.get("logo")
    if not file or not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return panel(message="Please choose a PNG or JPG file.", ok=False)
    filename = secure_filename(file.filename)
    file.save(os.path.join(ss.ASSETS_DIR, filename))
    ss.set_logo(filename)
    return panel(message="Logo uploaded.", ok=True)


@admin_bp.route("/upload-background", methods=["POST"])
@login_required
def upload_background():
    _check_csrf()
    file = request.files.get("background")
    if not file or not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return panel(message="Please choose a PNG or JPG file.", ok=False)
    filename = "bg_" + secure_filename(file.filename)
    file.save(os.path.join(ss.ASSETS_DIR, filename))
    ss.set_background(filename)
    return panel(message="Background photo uploaded.", ok=True)


@admin_bp.route("/toggle-marquee", methods=["POST"])
@login_required
def toggle_marquee():
    _check_csrf()
    enable = request.form.get("enable") == "1"
    ss.set_marquee_enabled(enable)
    return panel(message=f"Marquee turned {'ON' if enable else 'OFF'}.", ok=True)


@admin_bp.route("/upload-type-bg/<slug>", methods=["POST"])
@login_required
def upload_type_bg(slug):
    _check_csrf()
    # Recover the display name for the message; fall back to the slug itself
    # if someone hand-edits the form (defensive, not security-critical here).
    type_name = next((t for t in de.TYPE_ORDER if ss.slugify_type(t) == slug), slug)
    file = request.files.get("type_bg")
    if not file or not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return panel(message="Please choose a PNG or JPG file.", ok=False)
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    filename = f"typebg_{slug}{ext}"
    file.save(os.path.join(ss.ASSETS_DIR, filename))
    ss.set_type_bg(type_name, filename)
    return panel(message=f"Background uploaded for {type_name}.", ok=True)


@admin_bp.route("/upload-province-bg/<slug>", methods=["POST"])
@login_required
def upload_province_bg(slug):
    _check_csrf()
    province_name = next((p for p in de.PROVINCE_ORDER if ss.slugify_type(p) == slug), slug)
    file = request.files.get("province_bg")
    if not file or not file.filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return panel(message="Please choose a PNG or JPG file.", ok=False)
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    filename = f"provbg_{slug}{ext}"
    file.save(os.path.join(ss.ASSETS_DIR, filename))
    ss.set_province_bg(province_name, filename)
    return panel(message=f"Background uploaded for {province_name}.", ok=True)
