import os
import time
import logging

log = logging.getLogger(__name__)

try:
    import garth
    _GARTH_AVAILABLE = True
except ImportError:
    _GARTH_AVAILABLE = False

_DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))

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
    "road": "Silniční kolo",
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


def _resume():
    try:
        garth.resume(_DATA_DIR)
        return True
    except Exception:
        return False


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
    if not _GARTH_AVAILABLE:
        return []
    if not force and _cache["activities"] is not None:
        if time.time() - _cache["fetched_at"] < CACHE_TTL:
            return _cache["activities"]
    if not _resume():
        return []
    try:
        from datetime import date
        today = date.today().isoformat()
        all_raw = []
        start = 0
        limit = 100
        while True:
            batch = garth.connectapi(
                "/activitylist-service/activities/search/activities",
                params={
                    "startDate": GARMIN_CUTOFF,
                    "endDate": today,
                    "start": start,
                    "limit": limit,
                },
            )
            if not batch:
                break
            all_raw.extend(batch)
            if len(batch) < limit:
                break
            start += limit
        activities = [m for a in all_raw for m in [_map_activity(a)] if m]
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
    """
    Returns:
      'ok'            — success
      'mfa'           — MFA code required
      ('error', msg)  — failed with reason string
    """
    if not _GARTH_AVAILABLE:
        return ("error", "Knihovna garth není nainstalována.")
    try:
        garth.login(email, password)
        os.makedirs(_DATA_DIR, exist_ok=True)
        garth.save(_DATA_DIR)
        clear_cache()
        return "ok"
    except Exception as e:
        msg = str(e)
        if "MFA" in msg or "OTP" in msg or "NEED" in msg:
            return "mfa"
        return ("error", msg)


def login_mfa(otp_code):
    """Returns 'ok' or ('error', msg)."""
    return ("error", "MFA login není podporován na serveru. Použij upload tokenů z lokálního přihlášení.")


def is_connected():
    if not _GARTH_AVAILABLE:
        return False
    return _resume()


def disconnect():
    global _cache
    for fname in ("oauth1_token.json", "oauth2_token.json", "garmin_session.json"):
        try:
            os.remove(os.path.join(_DATA_DIR, fname))
        except FileNotFoundError:
            pass
    clear_cache()
