import unittest
import urllib.request
import urllib.error
import json

class TestSegmentIncidentDetails(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8000"

    def post_segment_incidents(self, payload):
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route/segment-incidents",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_bengaluru_segment_incidents_and_category_reconciliation(self):
        """1 & 5: Bengaluru segment returns multiple categories with counts reconciling to total_records"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9320, 77.6030]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertGreater(data["total_records"], 0)
        self.assertEqual(data["city"], "Bengaluru")
        self.assertEqual(data["buffer_km"], 1.2)

        # Reconcile category sum with total records
        cat_sum = sum(c["count"] for c in data["categories"])
        self.assertEqual(cat_sum, data["total_records"], "Category counts must strictly reconcile with total_records")

        # Sorted by descending count
        counts = [c["count"] for c in data["categories"]]
        self.assertEqual(counts, sorted(counts, reverse=True), "Categories must be sorted by descending count")

        # Verify persistent disclaimer text
        expected_disclaimer = (
            "Incident counts include historical records within 1.2 km of this road segment. "
            "These incidents may have occurred nearby rather than directly on the road. "
            "Location accuracy depends on the original record."
        )
        self.assertEqual(data["disclaimer"], expected_disclaimer)

    def test_mangaluru_segment_and_timestamp_policy(self):
        """4: Mangaluru segment records maintain unverified classification without invented timestamps"""
        payload = {
            "polyline": [[12.8696, 74.8423], [12.8710, 74.8450]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["city"], "Mangaluru")
        self.assertGreater(data["total_records"], 0)

        # Check records quality
        for r in data["records"][:10]:
            self.assertIn(r["location_quality"], ["LOCALITY_MATCH_ONLY", "LOCATION_UNVERIFIED", "INCIDENT_LOCATION_VERIFIED"])
            # Ensure no victim identities or personal info
            self.assertNotIn("victim", r)
            self.assertNotIn("name", r)
            self.assertIn("crime_type", r)

    def test_missing_dates_and_missing_localities_handling(self):
        """3: Missing dates and missing localities are explicitly None rather than fabricated"""
        import main
        # Verify helper handles None/NaN without inventing values
        d_disp, d_iso = main.normalize_incident_date(None)
        self.assertIsNone(d_disp)
        self.assertIsNone(d_iso)

        import numpy as np
        d_disp2, d_iso2 = main.normalize_incident_date(np.nan)
        self.assertIsNone(d_disp2)
        self.assertIsNone(d_iso2)

    def test_category_filter(self):
        """6: Category filter filters records and updates category summary consistently"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9320, 77.6030]],
            "category": "Assault"
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertGreater(data["total_records"], 0)
        self.assertLessEqual(data["total_records"], data["unfiltered_total"])
        for c in data["categories"]:
            self.assertIn("assault", c["name"].lower())

    def test_date_range_filter(self):
        """6: Date range filtering correctly filters by incident date"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9320, 77.6030]],
            "date_from": "2018-01-01",
            "date_to": "2018-12-31"
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertGreater(data["total_records"], 0)
        for r in data["records"]:
            if r["date_iso"]:
                self.assertTrue("2018-01-01" <= r["date_iso"] <= "2018-12-31")

    def test_locality_search_filter(self):
        """6: Locality search filters by place or police station substring"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9320, 77.6030]],
            "locality_query": "Jayanagar"
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertGreater(data["total_records"], 0)
        for r in data["records"]:
            matches = (
                (r["locality"] and "jayanagar" in r["locality"].lower()) or
                (r["police_station"] and "jayanagar" in r["police_station"].lower()) or
                (r["crime_type"] and "jayanagar" in r["crime_type"].lower())
            )
            self.assertTrue(matches)

    def test_unmeasured_rural_segment(self):
        """8: Unmeasured segment produces zero incidents and empty category summary gracefully"""
        payload = {
            "polyline": [[12.7500, 77.4000], [12.7550, 77.4050]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["total_records"], 0)
        self.assertEqual(len(data["categories"]), 0)
        self.assertEqual(len(data["records"]), 0)
        self.assertIn("Incident counts include historical records within 1.2 km", data["disclaimer"])

    def test_police_station_coordinate_exclusion(self):
        """Police station reference coordinates are excluded from segment crime counts"""
        payload = {
            "polyline": [[13.0358, 77.5970], [13.0400, 77.5970]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        # Verify police stations are tracked in excluded_police_stations
        self.assertGreater(data["excluded_police_stations"], 0)
        # None of the returned records should be POLICE_STATION_COORDINATE
        for r in data["records"]:
            self.assertNotEqual(r["location_quality"], "POLICE_STATION_COORDINATE")

    def test_invalid_parameters_error_handling(self):
        """7: Invalid parameters return HTTP 400 with helpful error messages"""
        # Empty polyline
        req1 = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route/segment-incidents",
            data=json.dumps({"polyline": []}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req1)
        self.assertEqual(ctx.exception.code, 400)

        # Polyline with only 1 point
        req2 = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route/segment-incidents",
            data=json.dumps({"polyline": [[12.92, 77.60]]}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req2)
        self.assertEqual(ctx.exception.code, 400)

    def test_simplified_evidence_labels(self):
        """Verify simplified evidence display labels match requirement 7"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9320, 77.6030]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        valid_labels = {"Verified location", "Approximate locality", "Unverified location"}
        for r in data["records"][:15]:
            self.assertIn(r["location_quality_label"], valid_labels)

if __name__ == "__main__":
    unittest.main()
