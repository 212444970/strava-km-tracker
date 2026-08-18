"""
One-time script: exports all Strava activities to strava_archive.json.
Run locally while you still have Strava API access:

    python export_strava.py

The file is then committed and used as a static data source.
"""
import json
import os
from dotenv import load_dotenv
load_dotenv()

import strava_client

ARCHIVE_CUTOFF = "2026-08-16"
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strava_archive.json")


def main():
    print("Fetching all activities from Strava…")
    activities = strava_client.get_activities(force=True)
    if not activities:
        print("ERROR: no activities returned. Check your tokens / .env file.")
        return
    archived = [a for a in activities if a["date"] < ARCHIVE_CUTOFF]
    print(f"Total fetched: {len(activities)}, archived (before {ARCHIVE_CUTOFF}): {len(archived)}")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(archived, f, ensure_ascii=False, indent=2)
    print(f"Saved to {OUTPUT}")
    print("Next step: git add strava_archive.json && git commit && git push")


if __name__ == "__main__":
    main()
