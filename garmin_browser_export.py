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
    candidates = []

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

    cookies = {name: value for name, value, host in rows}
    print(f"Nalezeno {len(cookies)} Garmin cookies.")
    if not cookies:
        print("CHYBA: Zadne Garmin cookies. Zkontroluj, ze jsi prihlaseny v Firefoxu na connect.garmin.com.")
        sys.exit(1)
    return cookies


def fetch_activities(cookies):
    session = requests.Session()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".garmin.com")

    # Garmin Connect expects this header
    session.headers.update({
        "NK": "NT",
        "X-app-ver": "4.66.1.0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
    })

    today = date.today().isoformat()
    all_raw = []
    start = 0
    limit = 100

    while True:
        print(f"  Stahuji aktivity {start}–{start + limit}...")
        resp = session.get(
            "https://connect.garmin.com/activitylist-service/activities/search/activities",
            params={
                "startDate": CUTOFF,
                "endDate": today,
                "start": start,
                "limit": limit,
            },
        )
        if resp.status_code == 401:
            print("CHYBA: Session vyprsela nebo nejsi prihlaseny. Obnov prihlaseni v Firefoxu na connect.garmin.com a zkus znovu.")
            sys.exit(1)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_raw.extend(batch)
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
        moving = int(a.get("movingDuration") or a.get("duration") or 0)
        date_str = (a.get("startTimeLocal") or "")[:10]
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
    cookies = get_garmin_cookies()
    print("Stahuji aktivity z Garmin Connect...")
    all_raw = fetch_activities(cookies)
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
