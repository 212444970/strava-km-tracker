import unittest
from unittest.mock import patch

import app


class MixedSourceTests(unittest.TestCase):
    def test_live_garmin_activities_replace_archive_duplicates(self):
        strava_before_cutoff = {
            "date": "2026-08-15",
            "name": "Strava activity",
            "km": 10.0,
            "type": "Ride",
        }
        strava_on_cutoff = {
            "date": "2026-08-16",
            "name": "Strava duplicate",
            "km": 20.0,
            "type": "Ride",
        }
        live_garmin = {
            "date": "2026-08-16",
            "name": "Garmin activity",
            "km": 20.0,
            "type": "cycling",
            "moving_time": 3600,
            "source": "garmin",
        }
        archived_garmin_duplicate = dict(live_garmin)
        archived_garmin_unique = {
            "date": "2026-08-17",
            "name": "Archived-only Garmin activity",
            "km": 5.0,
            "type": "cycling",
            "moving_time": 900,
            "source": "garmin",
        }

        with (
            patch.object(app.historical_store, "load", return_value=[]),
            patch.object(
                app.strava_archive_store,
                "load",
                return_value=[strava_before_cutoff, strava_on_cutoff],
            ),
            patch.object(
                app.garmin_archive_store,
                "load",
                return_value=[archived_garmin_duplicate, archived_garmin_unique],
            ),
            patch.object(app.garmin_client, "get_activities", return_value=[live_garmin]),
        ):
            activities = app._load_all_activities()

        self.assertEqual(
            {activity["name"] for activity in activities},
            {"Strava activity", "Garmin activity", "Archived-only Garmin activity"},
        )


if __name__ == "__main__":
    unittest.main()
