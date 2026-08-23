"""
Export Garmin activities via browser session (bypasses rate limiting).

Usage:
    pip install playwright
    playwright install chromium
    python garmin_browser_export.py

Then commit the output file:
    git add garmin_archive.json
    git commit -m "Add Garmin archive"
    git push
"""
from playwright.sync_api import sync_playwright
import json
from datetime import date

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


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("Otevirám Garmin Connect...")
        page.goto("https://connect.garmin.com/modern/activities")

        print("\nPrihlas se ve webovém okne.")
        print("Jakmile vidis seznam aktivit (ne prihlasovaci stránku), stiskni Enter...")
        input()

        today = date.today().isoformat()
        all_raw = []
        start = 0
        limit = 100

        while True:
            print(f"  Stahuji aktivity {start}–{start + limit}...")
            batch = page.evaluate(f"""
                async () => {{
                    const url = new URL(
                        '/activitylist-service/activities/search/activities',
                        location.origin
                    );
                    url.searchParams.set('startDate', '{CUTOFF}');
                    url.searchParams.set('endDate', '{today}');
                    url.searchParams.set('start', '{start}');
                    url.searchParams.set('limit', '{limit}');
                    const r = await fetch(url, {{ credentials: 'include' }});
                    if (!r.ok) return null;
                    return r.json();
                }}
            """)
            if not batch:
                break
            all_raw.extend(batch)
            if len(batch) < limit:
                break
            start += limit

        browser.close()
        print(f"Stazeno {len(all_raw)} záznamu ze serveru.")

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

        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(activities, f, indent=2, ensure_ascii=False)

        print(f"\nHotovo! Ulozeno {len(activities)} aktivit do {OUTPUT}")
        print("\nDalsi krok:")
        print(f"  git add {OUTPUT}")
        print(f'  git commit -m "Add Garmin archive"')
        print("  git push")


if __name__ == "__main__":
    main()
