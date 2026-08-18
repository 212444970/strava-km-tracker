import json
import os
import time
import logging

log = logging.getLogger(__name__)

try:
    from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
    _GARMIN_AVAILABLE = True
except ImportError:
    _GARMIN_AVAILABLE = False

_DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
_SESSION_FILE = os.path.join(_DATA_DIR, "garmin_session.json")

GARMIN_CUTOFF = "2026-08-16"

CATEGORY_MAP = {
    "cycling": "road",
    "road_biking": "road",
    "gravel_cycling": "road",
    "mountain_biking": "mtb",
    "indoor_cycling": "virtual",
    "virtual_ride": "virtual",
    "alpine_skiing": "ski",
    "backcountry_skiing": "ski",
    "cross_country_skiing": "ski",
    "running": "run",
    "trail_running": "run",
    "hiking": "hike",
    "walking": "hike",
    "swimming": "swim",
    "open_water_swimming": "swim",
}

CATEGORY_LABELS = {
    "road": "Silnční kolo",
    "mtb": "Horské kolo",
    "virtual": "Virtuální",
    "ebike": "E-kolo",
    "ski": "Lyže",
    "run": "Běh",
    "hike": "Turistika",
    "swim": "Plavání",
    "other": "Ostatní",
}

_cache = {"activities": None, "fetched_at": 0}
CACHE_TTL = 300

_pending_api = None


def _session_save(api):
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        tokens = {
            "oauth1": api.garth.oauth1_token.__dict__ if api.garth.oauth1_token else None,
            "oauth2": api.garth.oauth2_token.__dict__ if api.garth.oauth2_token else None,
        }
        with open(_SESSION_FILE, "w") as f:
            json.dump(tokens, f)
    except Exception as e:
        log.warning("Could not save Garmin session: %s", e)


def _load_api():
    if not _GARMIN_AVAILABLE:
        return None
    if not os.path.exists(_SESSION_FILE):
        return None
    try:
        api = Garmin()
        api.garth.load(_DATA_DIR)
        api.display_name
        return api
    except Exception:
        return None


def _map_activity(a):
    sport = (a.get("activityType") or {}).get("typeKey", "other")
    km = round((a.get("distance") or 0) / 1000, 2)
    elev = round(a.get("elevationGain") or 0)
    if km == 0 and elev == 0:
        return None
    moving = int(a.get("movingDuration") or a.get("duration") or 0)
    date_str = (a.get("startTimeLocal") or "")[:10]
    return {
        "name": a.get("activityName") or sport,
        "date": date_str,
        "km": km,
        "elevation": elev,
        "moving_time": moving,
        "type": sport,
        "category": CATEGORY_MAP.get(sport, "other"),
        "source": "garmin",
    }


def get_activities(force=False):
    global _cache
    if not _GARMIN_AVAILABLE:
        return []
    if not force and _cache["activities"] is not None:
        if time.time() - _cache["fetched_at"] < CACHE_TTL:
            return _cache["activities"]

    api = _load_api()
    if api is None:
        return []

    try:
        from datetime import date
        today = date.today().isoformat()
        raw = api.get_activities_by_date(GARMIN_CUTOFF, today, None)
        activities = [m for a in raw for m in [_map_activity(a)] if m]
        activities.sort(key=lambda x: x["date"], reverse=True)
        _cache = {"activities": activities, "fetched_at": time.time()}
        return activities
    except Exception as e:
        log.error("Garmin fetch failed: %s", e)
        return _cache["activities"] or []


def clear_cache():
    global _cache
    _cache = {"activities": None, "fetched_at": 0}


def login(email, password):
    global _pending_api
    if not _GARMIN_AVAILABLE:
        return "error"
    try:
        api = Garmin(email=email, password=password)
        api.login()
        api.garth.dump(_DATA_DIR)
        _session_save(api)
        clear_cache()
        return "ok"
    except GarminConnectAuthenticationError as e:
        if "MFA" in str(e) or "OTP" in str(e) or "NEEDS_MFA" in str(e):
            _pending_api = api
            return "mfa"
        return "error"
    except Exception as e:
        log.error("Garmin login error: %s", e)
        return "error"


def login_mfa(otp_code):
    global _pending_api
    if not _pending_api:
        return "error"
    try:
        _pending_api.login(otp_code=otp_code)
        _pending_api.garth.dump(_DATA_DIR)
        _session_save(_pending_api)
        clear_cache()
        _pending_api = None
        return "ok"
    except Exception as e:
        log.error("Garmin MFA error: %s", e)
        _pending_api = None
        return "error"


def is_connected():
    return os.path.exists(_SESSION_FILE) and _load_api() is not None


def disconnect():
    global _cache
    try:
        os.remove(_SESSION_FILE)
    except FileNotFoundError:
        pass
    for fname in ("oauth1_token.json", "oauth2_token.json"):
        try:
            os.remove(os.path.join(_DATA_DIR, fname))
        except FileNotFoundError:
            pass
    clear_cache()
