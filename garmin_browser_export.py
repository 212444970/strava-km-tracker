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
    """Read Garmin cookies from Firefox profile, preserving original host."""
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
    return rows  # list of (name, value, host)


def fetch_activities(cookie_rows):
    session = requests.Session()
    for name, value, host in cookie_rows:
        # Use host exactly as Firefox stored it (.garmin.com or connect.garmin.com)
        session.cookies.set(name, value, domain=host)

    session.headers.update({
        "NK": "NT",
        "X-app-ver": "4.66.1.0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://connect.garmin.com/modern/activities",
    })

    all_raw = []
    start = 0
    limit = 100

    # Web app proxies API calls through /proxy/
    # startDate/endDate are ignored by the proxy — filter by date in Python instead
    BASE_URL = "https://connect.garmin.com/proxy/activitylist-service/activities/search/activities"

    while True:
        print(f"  Stahuji aktivity {start}–{start + limit}...")
        resp = session.get(
            BASE_URL,
            params={
                "start": start,
                "limit": limit,
            },
        )
        if resp.status_code in (401, 403):
            print("CHYBA: Session vyprsela nebo nejsi prihlaseny.")
            print("Jdi v Firefoxu na connect.garmin.com, prihlas se a spust skript znovu.")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"CHYBA: HTTP {resp.status_code}")
            print(resp.text[:500])
            sys.exit(1)
        batch = resp.json()
        if not batch:
            break
        all_raw.extend(batch)
        # Stop paginating once we've gone past the cutoff date
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
    cookie_rows = get_garmin_cookies()
    print("Stahuji aktivity z Garmin Connect...")
    all_raw = fetch_activities(cookie_rows)
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
