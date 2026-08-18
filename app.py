import os
import webbrowser
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, render_template, request, session, url_for

import historical_store
import strava_archive_store
import garmin_client

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

PORT = int(os.environ.get("PORT", 5000))
APP_URL = os.environ.get("APP_URL", f"http://localhost:{PORT}")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if ADMIN_PASSWORD and not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def _load_all_activities():
    """Merge historical + Strava archive + Garmin into one sorted list."""
    historical = historical_store.load()                     # pre-2024
    archived   = strava_archive_store.load()                 # 2024-01-01 – 2026-08-15
    garmin     = garmin_client.get_activities()              # 2026-08-16+

    combined = historical + archived + garmin
    return sorted(combined, key=lambda x: x["date"], reverse=True)


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if not garmin_client.is_connected() and not strava_archive_store.load():
        return render_template("index.html", connected=False)

    activities = _load_all_activities()
    return render_template(
        "index.html",
        connected=True,
        activities=activities,
        category_labels=garmin_client.CATEGORY_LABELS,
    )


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin"))
        error = "Wrong password."
    return render_template("admin_login.html", error=error)


@app.route("/admin")
@admin_required
def admin():
    return render_template(
        "admin.html",
        garmin_connected=garmin_client.is_connected(),
        archive_count=len(strava_archive_store.load()),
    )


@app.route("/admin/garmin-login", methods=["POST"])
@admin_required
def admin_garmin_login():
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    result = garmin_client.login(email, password)
    if result == "ok":
        return redirect(url_for("admin"))
    if result == "mfa":
        return render_template("admin.html",
                               garmin_connected=False,
                               archive_count=len(strava_archive_store.load()),
                               needs_mfa=True)
    return render_template("admin.html",
                           garmin_connected=False,
                           archive_count=len(strava_archive_store.load()),
                           garmin_error="Přihlášení selhalo. Zkontroluj email a heslo.")


@app.route("/admin/garmin-mfa", methods=["POST"])
@admin_required
def admin_garmin_mfa():
    code = request.form.get("code", "").strip()
    result = garmin_client.login_mfa(code)
    if result == "ok":
        return redirect(url_for("admin"))
    return render_template("admin.html",
                           garmin_connected=False,
                           archive_count=len(strava_archive_store.load()),
                           garmin_error="Nesprávný MFA kód.")


@app.route("/admin/garmin-disconnect", methods=["POST"])
@admin_required
def admin_garmin_disconnect():
    garmin_client.disconnect()
    return redirect(url_for("admin"))


@app.route("/admin/refresh", methods=["POST"])
@admin_required
def admin_refresh():
    garmin_client.clear_cache()
    return redirect(url_for("admin"))


if __name__ == "__main__":
    webbrowser.open(f"http://localhost:{PORT}")
    app.run(port=PORT, debug=False)
