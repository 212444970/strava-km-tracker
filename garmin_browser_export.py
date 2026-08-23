"""
Export Garmin activities using existing Firefox browser session.
No login needed — uses cookies from your already-logged-in Firefox.

Usage:
    python garmin_browser_export.py

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
from datetime import date

import requests

CUTOFF = "2026-08-16"
OUTPUT = "garmin_archive.json"

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


def find_firefox_cookies():
    """Return path to Firefox cookies.sqlite (Windows/Mac/Linux)."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        candidates = glob.glob(
            os.path.join(appdata, "Mozilla", "Firefox", "Profiles", "*.default*", "cookies.sqlite")
        )
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        candidates = glob.glob(
            os.path.join(home, "Library", "Application Support", "Firefox", "Profiles", "*.default*", "cookies.sqlite")
        )
    else:
        home = os.path.expanduser("~")
        candidates = glob.glob(
            os.path.join(home, ".mozilla", "firefox", "*.default*", "cookies.sqlite")
        )
    return candidates[0] if candidates else None


def get_garmin_cookies():
    """Read Garmin cookies from Firefox profile."""
    path = find_firefox_cookies()
    if not path:
        print("CHYBA: Firefox profil nenalezen.")
        sys.exit(1)

    print(f"Ctu cookies z: {path}")

    # Firefox locks the file — copy it first
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        shutil.copy2(path, tmp.name)
        tmp_path = tmp.name

    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute(
            "SELECT name, value, host FROM moz_cookies WHERE host LIKE '%garmin%'"
        ).fetchall()
        conn.close()
    finally:
        os.unlink(tmp_path)

    print(f"Nalezeno {len(rows)} Garmin cookies.")
    if not rows:
        print("CHYBA: Zadne Garmin cookies.")
        print("Jdi v Firefoxu na connect.garmin.com, prihlas se a zkus znovu.")
        sys.exit(1)
    print(f"  Jmena cookies: {[name for name, value, host in rows]}")
    # Return as simple dict — pass directly to requests to avoid domain-matching issues
    return {name: value for name, value, host in rows}


def test_auth(cookies_dict):
    """Quick auth test; returns display_name for use in activity queries."""
    resp = requests.get(
        "https://connect.garmin.com/modern/currentuser-service/user/info",
        headers={"NK": "NT", "User-Agent": "Mozilla/5.0"},
        cookies=cookies_dict,
    )
    print(f"Auth test -> HTTP {resp.status_code}, prvnich 200 znaku: {resp.text[:200]}")
    try:
        info = resp.json()
        display_name = info.get("username") or info.get("displayName") or ""
        print(f"  displayName: {display_name}")
        return display_name
    except Exception:
        return ""


def _try_fetch_page(url, params, headers, cookies_dict):
    """Fetch one page; return (batch_list, raw_text) or sys.exit on error."""
    resp = requests.get(url, params=params, headers=headers, cookies=cookies_dict)
    if resp.status_code in (401, 403):
        print("CHYBA: Session vyprsela nebo nejsi prihlaseny.")
        sys.exit(1)
    if resp.status_code != 200:
        print(f"CHYBA: HTTP {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)
    try:
        data = resp.json()
    except Exception:
        print(f"  Odpoved neni JSON: {resp.text[:300]}")
        return None, resp.text
    if isinstance(data, list):
        return data, resp.text
    if isinstance(data, dict):
        batch = data.get("activityList") or data.get("activities") or data.get("data") or []
        if not batch and data:
            print(f"  JSON objekt s klici: {list(data.keys())}")
        return batch, resp.text
    return [], resp.text


def fetch_activities(cookies_dict):
    display_name = test_auth(cookies_dict)

    jwt_web = cookies_dict.get("JWT_WEB", "")
    print(f"  JWT_WEB: {'nalezen, zacina ' + jwt_web[:10] + '...' if jwt_web else 'CHYBI'}")

    PROXY = "https://connect.garmin.com/proxy/activitylist-service/activities/search/activities"

    base_headers = {
        "NK": "NT",
        "X-app-ver": "4.66.1.0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://connect.garmin.com/modern/activities",
        "Origin": "https://connect.garmin.com",
    }
    headers_bearer = {**base_headers, "Authorization": f"Bearer {jwt_web}"} if jwt_web else None
    headers_plain = base_headers
    headers_no_nk = {k: v for k, v in base_headers.items() if k != "NK"}

    base_params = {"start": 0, "limit": 1}
    params_with_user = {**base_params, "displayName": display_name} if display_name else None

    # Try strategies in order — first one that returns data wins
    strategies = []
    if params_with_user:
        strategies += [
            (PROXY, params_with_user, headers_plain,  "cookies + displayName"),
            (PROXY, params_with_user, headers_bearer, "Bearer + displayName") if headers_bearer else None,
            (PROXY, params_with_user, headers_no_nk,  "no-NK + displayName"),
        ]
    strategies += [
        (PROXY, base_params, headers_plain,  "cookies only"),
        (PROXY, base_params, headers_bearer, "Bearer only") if headers_bearer else None,
        (PROXY, base_params, headers_no_nk,  "no-NK"),
    ]
    strategies = [s for s in strategies if s is not None]

    url = PROXY
    headers = headers_plain
    for url, params, hdr, label in strategies:
        print(f"  Zkousim [{label}]: {url}")
        batch, raw = _try_fetch_page(url, params, hdr, cookies_dict)
        if batch:
            print(f"  Funguje! Pouzivam [{label}].")
            headers = hdr
            break
        print(f"  -> {raw[:120]}")
    else:
        print("CHYBA: Zadna strategie nefunguje.")
        print("Postup: otevri Firefox, jdi na connect.garmin.com/modern/activities,")
        print("stiskni F12 -> Network -> filtr 'activitylist' -> zkopiruj URL a headers.")
        sys.exit(1)

    # Build base params for the working strategy (keep displayName if it was part of it)
    winning_extra = {k: v for k, v in params.items() if k not in ("start", "limit")}

    # Now fetch all pages with the working url/headers
    all_raw = []
    start = 0
    limit = 100

    while True:
        print(f"  Stahuji aktivity {start}-{start + limit}...")
        page_params = {"start": start, "limit": limit, **winning_extra}
        batch, raw = _try_fetch_page(url, page_params, headers, cookies_dict)
        if not batch:
            print(f"  Prazdna odpoved: {raw[:100]}")
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
        if date_str < CUTOFF:
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
