import os
import webbrowser
from functools import wraps

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import strava_client
import token_store
import historical_store

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
PORT = int(os.environ.get("PORT", 5000))

# In production set APP_URL=https://your-app.railway.app (no trailing slash)
APP_URL = os.environ.get("APP_URL", f"http://localhost:{PORT}")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _auth_url():
    redirect_uri = f"{APP_URL}/callback"
    return (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={os.environ['STRAVA_CLIENT_ID']}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&approval_prompt=auto"
        f"&scope=activity:read_all"
    )


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if ADMIN_PASSWORD and not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    tokens = token_store.load()
    if not tokens:
        return render_template("index.html", connected=False)

    activities = strava_client.get_activities()
    if activities is None:
        return render_template("index.html", connected=False)

    # Merge: historical data covers pre-2024, Strava covers 2024+
    historical = historical_store.load()
    if historical:
        strava_recent = [a for a in activities if a["date"] >= historical_store.HISTORICAL_CUTOFF]
        all_activities = sorted(historical + strava_recent, key=lambda x: x["date"], reverse=True)
    else:
        all_activities = activities

    return render_template(
        "index.html",
        connected=True,
        activities=all_activities,
        category_labels=strava_client.CATEGORY_LABELS,
    )


@app.route("/api/stats")
def api_stats():
    """JSON endpoint — useful for embedding stats elsewhere."""
    from flask import jsonify
    tokens = token_store.load()
    if not tokens:
        return jsonify({"error": "not connected"}), 503
    activities = strava_client.get_activities()
    if activities is None:
        return jsonify({"error": "failed to fetch activities"}), 503
    return jsonify(strava_client.compute_stats(activities))


# ---------------------------------------------------------------------------
# Admin routes (password-protected when ADMIN_PASSWORD is set)
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
    connected = token_store.load() is not None
    return render_template("admin.html", connected=connected, auth_url=_auth_url())


@app.route("/admin/refresh", methods=["POST"])
@admin_required
def admin_refresh():
    strava_client.clear_cache()
    return redirect(url_for("admin"))


@app.route("/admin/logout-strava", methods=["POST"])
@admin_required
def admin_logout_strava():
    token_store.delete()
    strava_client.clear_cache()
    return redirect(url_for("admin"))


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Authorization failed — no code returned.", 400
    strava_client.exchange_code(code)
    return redirect(url_for("index"))


if __name__ == "__main__":
    webbrowser.open(f"http://localhost:{PORT}")
    app.run(port=PORT, debug=False)
