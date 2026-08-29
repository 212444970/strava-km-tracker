"""
Export Garmin activities using existing Firefox browser session.
No login needed — uses cookies from your already-logged-in Firefox.

Usage:
    python garmin_browser_export.py

If cookies or CSRF token fail automatically, paste them from Firefox DevTools:
  1. Open Firefox, go to connect.garmin.com/activities
  2. Press F12 -> Network tab -> XHR filter
  3. Reload the page (Ctrl+R)
  4. Click the request "activities?limit=20&start=0"
  5. In the "Požadavek" (Request) tab:
       - Copy the Cookie header value -> paste into MANUAL_COOKIE_STRING below
       - Copy the Connect-Csrf-Token value -> paste into MANUAL_CSRF_TOKEN below

Then commit:
    git add garmin_archive.json
    git commit -m "Sync Garmin archive"
    git push
"""
import glob
import json
import os
import shutil
import sqlite3
import sys
import tempfile

import requests

CUTOFF = "2026-08-16"
OUTPUT = "garmin_archive.json"

# -----------------------------------------------------------------------
# MANUAL OVERRIDE — paste from Firefox DevTools if automatic reading fails
# Leave empty ("") to use automatic extraction
# -----------------------------------------------------------------------
MANUAL_COOKIE_STRING = ""
MANUAL_CSRF_TOKEN = ""

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


def find_firefox_profile():
    """Return the Firefox profile directory with the most recent cookies.sqlite."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        base = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
        candidates = glob.glob(os.path.join(base, "*.default*"))
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        candidates = glob.glob(
            os.path.join(home, "Library", "Application Support", "Firefox", "Profiles", "*.default*")
        )
    else:
        home = os.path.expanduser("~")
        candidates = glob.glob(os.path.join(home, ".mozilla", "firefox", "*.default*"))

    # Prefer the profile with the largest (most-used) cookies.sqlite
    with_cookies = [c for c in candidates if os.path.exists(os.path.join(c, "cookies.sqlite"))]
    if not with_cookies:
        return candidates[0] if candidates else None
    return max(with_cookies, key=lambda p: os.path.getsize(os.path.join(p, "cookies.sqlite")))


def parse_cookie_string(s):
    cookies = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        # Drop cookies whose values can't be sent as HTTP headers (latin-1 only)
        # DevTools truncates long values with '…' — skip those cookies entirely
        try:
            v.encode("latin-1")
            cookies[k] = v
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass  # skip truncated/non-latin-1 cookies (e.g. CONSENTMGR with '…')
    return cookies


def get_garmin_cookies():
    if MANUAL_COOKIE_STRING.strip():
        cookies = parse_cookie_string(MANUAL_COOKIE_STRING)
        print(f"Pouzivam manualni Cookie string ({len(cookies)} polozek).")
        return cookies

    profile = find_firefox_profile()
    if not profile:
        print("CHYBA: Firefox profil nenalezen.")
        sys.exit(1)

    path = os.path.join(profile, "cookies.sqlite")
    if not os.path.exists(path):
        print(f"CHYBA: cookies.sqlite nenalezeno v {profile}")
        sys.exit(1)
    print(f"Ctu cookies z: {path}")

    # On Windows, NamedTemporaryFile keeps the file open — use a plain temp path instead
    tmp_path = path + ".tmp_export"
    try:
        shutil.copy2(path, tmp_path)
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute(
            "SELECT name, value, host FROM moz_cookies WHERE host LIKE '%garmin%'"
        ).fetchall()
        conn.close()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    print(f"Nalezeno {len(rows)} Garmin cookies.")
    if not rows:
        print("CHYBA: Zadne Garmin cookies.")
        sys.exit(1)
    return {name: value for name, value, host in rows}


def get_csrf_token(profile_dir):
    """Try to read Connect-Csrf-Token from Firefox localStorage (webappsstore.sqlite)."""
    if MANUAL_CSRF_TOKEN.strip():
        return MANUAL_CSRF_TOKEN.strip()

    if not profile_dir:
        return None

    path = os.path.join(profile_dir, "webappsstore.sqlite")
    if not os.path.exists(path):
        return None

    tmp_path = path + ".tmp_export"
    try:
        shutil.copy2(path, tmp_path)
        conn = sqlite3.connect(tmp_path)
        # scope is stored as REVERSED domain: "moc.nimrag" = "garmin.com"
        rows = conn.execute(
            "SELECT scope, key, value FROM webappsstore2 WHERE scope LIKE '%nimrag%'"
        ).fetchall()
        conn.close()
        if rows:
            print(f"  LocalStorage Garmin: {len(rows)} klicu")
            for scope, key, value in rows:
                if "csrf" in key.lower() or "xsrf" in key.lower() or "token" in key.lower():
                    print(f"  Nalezen CSRF klic: {key} = {(value or '')[:60]}")
                    return value
            print(f"  LocalStorage klice: {[k for _, k, _ in rows[:20]]}")
        return None
    except Exception as e:
        print(f"  LocalStorage read: {e}")
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def test_auth(cookies_dict):
    """Quick auth test; returns (display_name) or exits."""
    resp = requests.get(
        "https://connect.garmin.com/modern/currentuser-service/user/info",
        headers={"NK": "NT", "User-Agent": "Mozilla/5.0"},
        cookies=cookies_dict,
    )
    print(f"Auth test -> HTTP {resp.status_code}")
    try:
        info = resp.json()
        display_name = info.get("username") or info.get("displayName") or ""
        print(f"  Uzivatel: {display_name}")
        return display_name
    except Exception:
        print(f"  Odpoved: {resp.text[:200]}")
        return ""


def _try_fetch_page(url, params, headers, cookies_dict):
    """Fetch one page; return (batch_list, raw_text, status_code)."""
    try:
        resp = requests.get(url, params=params, headers=headers, cookies=cookies_dict, timeout=20)
    except Exception as e:
        return None, str(e), 0
    status = resp.status_code
    if status not in (200, 404):
        return None, resp.text[:200], status
    try:
        data = resp.json()
    except Exception:
        return None, resp.text[:200], status
    if isinstance(data, list):
        return data, resp.text, status
    if isinstance(data, dict):
        batch = data.get("activityList") or data.get("activities") or data.get("data") or []
        if not batch and data:
            keys = list(data.keys())
            return [], f"dict keys: {keys}", status
        return batch, resp.text, status
    return [], resp.text, status


def fetch_activities(cookies_dict):
    display_name = test_auth(cookies_dict)
    profile = find_firefox_profile()
    csrf_token = get_csrf_token(profile)
    print(f"  CSRF token: {'nalezen (' + csrf_token[:12] + '...)' if csrf_token else 'NENALEZEN — zkousim bez nej'}")

    jwt_web = cookies_dict.get("JWT_WEB", "")

    def make_headers(with_csrf=True):
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:154.0) Gecko/20100101 Firefox/154.0",
            "Accept": "*/*",
            "Accept-Language": "cs,sk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if with_csrf and csrf_token:
            h["Connect-Csrf-Token"] = csrf_token
        return h

    # Garmin Connect React app (v5.27+) uses /gc-api/ prefix
    candidate_urls = [
        "https://connect.garmin.com/gc-api/activitylist-service/activities/search/activities",
        "https://connect.garmin.com/proxy/activitylist-service/activities/search/activities",
        "https://connect.garmin.com/api/proxy/activitylist-service/activities/search/activities",
    ]

    base_params = {"start": 0, "limit": 1}

    strategies = []
    for cu in candidate_urls:
        for hdr_label, hdr in [("csrf", make_headers(True)), ("no-csrf", make_headers(False))]:
            strategies.append((cu, base_params, hdr, f"{cu.split('garmin.com')[1][:35]} [{hdr_label}]"))

    url = candidate_urls[0]
    headers = make_headers()
    params = base_params
    for url, params, hdr, label in strategies:
        print(f"  Zkousim {label}")
        batch, raw, status = _try_fetch_page(url, params, hdr, cookies_dict)
        if batch:
            print(f"  Funguje! Pouzivam.")
            headers = hdr
            break
        print(f"  -> HTTP {status}: {str(raw)[:80]}")
    else:
        print("\nCHYBA: Zadna strategie nefunguje.")
        if not csrf_token:
            print("Nejspis chybi CSRF token. Spus znovu s MANUAL_CSRF_TOKEN:")
            print("  1. Firefox -> connect.garmin.com/activities")
            print("  2. F12 -> Network -> XHR -> nacti stranku")
            print('  3. Klikni na "activities?limit=20&start=0"')
            print("  4. V Request headers zkopiruj hodnotu Connect-Csrf-Token")
            print("  5. Vloz ji do MANUAL_CSRF_TOKEN na zacatku skriptu")
        sys.exit(1)

    # Fetch all pages with the working url/headers
    winning_extra = {k: v for k, v in params.items() if k not in ("start", "limit")}

    all_raw = []
    start = 0
    limit = 20  # match what the browser uses

    while True:
        print(f"  Stahuji aktivity {start}-{start + limit}...")
        page_params = {"start": start, "limit": limit, **winning_extra}
        batch, raw, status = _try_fetch_page(url, page_params, headers, cookies_dict)
        if not batch:
            print(f"  Konec: {str(raw)[:80]}")
            break
        all_raw.extend(batch)
        oldest = (batch[-1].get("startTimeLocal") or "")[:10]
        if oldest and oldest < CUTOFF:
            break
        if len(batch) < limit:
            break
        start += limit

    return all_raw


def map_activities(all_raw):
    activities = []
    for a in all_raw:
        sport = (a.get("activityType") or {}).get("typeKey", "other")
        km = round((a.get("distance") or 0) / 1000, 2)
        elev = round(a.get("elevationGain") or 0)
        if km == 0 and elev == 0:
            continue
        date_str = (a.get("startTimeLocal") or "")[:10]
        if not date_str or date_str < CUTOFF:
            continue
        moving = int(a.get("movingDuration") or a.get("duration") or 0)
        activities.append({
            "name": a.get("activityName") or sport,
            "date": date_str,
            "km": km,
            "elevation": elev,
            "moving_time": moving,
            "type": sport,
            "category": CATEGORY_MAP.get(sport, "other"),
            "source": "garmin",
        })
    activities.sort(key=lambda x: x["date"], reverse=True)
    return activities


def main():
    cookies_dict = get_garmin_cookies()
    print("Stahuji aktivity z Garmin Connect...")
    all_raw = fetch_activities(cookies_dict)
    print(f"Stazeno {len(all_raw)} zaznamu.")
    activities = map_activities(all_raw)
    print(f"Zpracovano {len(activities)} aktivit (bez nulovych).")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(activities, f, indent=2, ensure_ascii=False)

    print(f"\nHotovo! Ulozeno do {OUTPUT}")
    print("\nDalsi krok:")
    print(f"  git add {OUTPUT}")
    print(f'  git commit -m "Sync Garmin archive"')
    print("  git push")


if __name__ == "__main__":
    main()
