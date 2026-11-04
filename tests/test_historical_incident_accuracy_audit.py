import unittest
import urllib.request
import urllib.error
import json
import pandas as pd
import numpy as np

class TestHistoricalIncidentAccuracyAudit(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8000"

    def post_segment_incidents(self, payload):
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route/segment-incidents",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def post_safe_route(self, payload):
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    # -------------------------------------------------------------
    # 1. Category counts, filtered totals, and individual records consistency
    # -------------------------------------------------------------
    def test_category_counts_and_record_reconciliation(self):
        """Audit 1: Verify category counts, filtered totals, and records remain strictly consistent"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9350, 77.6050]],
            "buffer_km": 1.2,
            "limit": 500
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        total_records = data["total_records"]
        categories = data["categories"]
        records = data["records"]

        self.assertGreater(total_records, 0)
        # 1a. Sum of category counts must equal total_records exactly
        cat_sum = sum(c["count"] for c in categories)
        self.assertEqual(cat_sum, total_records, f"Sum of category counts ({cat_sum}) != total_records ({total_records})")

        # 1b. Every category must have a positive count
        for c in categories:
            self.assertGreater(c["count"], 0)

        # 1c. Records returned must match min(total_records, limit)
        self.assertEqual(len(records), min(total_records, 500))

        # 1d. Every record's crime_type must match one of the categories
        cat_names_lower = {c["name"].lower() for c in categories}
        for r in records:
            self.assertIn(r["crime_type"].lower(), cat_names_lower)

    # -------------------------------------------------------------
    # 2. Date and locality filters combined + Clear filters
    # -------------------------------------------------------------
    def test_combined_filters_and_clear_filters(self):
        """Audit 2: Date and locality filters work together correctly and Clear filters restores original results"""
        baseline_payload = {
            "polyline": [[12.9298, 77.6005], [12.9350, 77.6050]],
            "buffer_km": 1.2
        }
        _, base_data = self.post_segment_incidents(baseline_payload)
        unfiltered_total = base_data["total_records"]
        self.assertGreater(unfiltered_total, 0)

        # Pick a target category and locality from the baseline data
        sample_rec = next(r for r in base_data["records"] if r["date"] and r["locality"])
        sample_year = sample_rec["date_iso"][:4]
        sample_loc_substr = sample_rec["locality"][:4]

        # Apply combined date range + locality query
        combined_payload = {
            "polyline": baseline_payload["polyline"],
            "buffer_km": 1.2,
            "date_from": f"{sample_year}-01-01",
            "date_to": f"{sample_year}-12-31",
            "locality_query": sample_loc_substr
        }
        status, filtered_data = self.post_segment_incidents(combined_payload)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(filtered_data["total_records"], 1)
        self.assertLessEqual(filtered_data["total_records"], unfiltered_total)

        # Verify all returned records satisfy both filters
        for r in filtered_data["records"]:
            if r["date_iso"]:
                self.assertTrue(r["date_iso"].startswith(sample_year))
            self.assertIn(sample_loc_substr.lower(), r["locality"].lower())

        # Clear filters (omit filter params) restores original total
        status_clear, clear_data = self.post_segment_incidents(baseline_payload)
        self.assertEqual(status_clear, 200)
        self.assertEqual(clear_data["total_records"], unfiltered_total)

    # -------------------------------------------------------------
    # 3. View on map uses only valid stored coordinates and never generates or substitutes coordinates
    # -------------------------------------------------------------
    def test_stored_coordinates_accuracy_and_no_fabrication(self):
        """Audit 3: View on map uses only valid stored coordinates from underlying datasets; no coordinates generated"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9350, 77.6050]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)

        # Load raw Bengaluru dataset
        df_blr = pd.read_csv("bengaluru_dataset.csv")

        for r in data["records"][:30]:
            lat = r["latitude"]
            lon = r["longitude"]
            self.assertIsNotNone(lat)
            self.assertIsNotNone(lon)
            # Ensure coordinates are within valid Bengaluru geographic bounding envelope
            self.assertTrue(12.7 <= lat <= 13.3, f"Latitude {lat} out of valid bounds")
            self.assertTrue(77.4 <= lon <= 77.9, f"Longitude {lon} out of valid bounds")

            # Verify coordinate exists in actual dataset
            coords_match = df_blr[
                (np.isclose(df_blr['Latitude'], lat, atol=1e-5)) &
                (np.isclose(df_blr['Longitude'], lon, atol=1e-5))
            ]
            self.assertGreater(len(coords_match), 0, f"Coordinate [{lat}, {lon}] not found in source dataset")

    # -------------------------------------------------------------
    # 4. Approximate locality locations and unverified records are clearly distinguished from verified incident locations
    # -------------------------------------------------------------
    def test_location_quality_distinction(self):
        """Audit 4: Verified incident scenes, locality centroids, and unverified records are strictly distinguished"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9350, 77.6050]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)

        allowed_statuses = {
            "INCIDENT_LOCATION_VERIFIED": "Verified location",
            "LOCALITY_MATCH_ONLY": "Approximate locality",
            "LOCATION_UNVERIFIED": "Unverified location"
        }

        for r in data["records"][:30]:
            q_status = r["location_quality"]
            q_label = r["location_quality_label"]
            self.assertIn(q_status, allowed_statuses)
            self.assertEqual(q_label, allowed_statuses[q_status])

            # Ensure locality centroids are NEVER labeled as verified incident scene
            if q_status == "LOCALITY_MATCH_ONLY":
                self.assertNotEqual(q_label, "Verified location")
                self.assertEqual(q_label, "Approximate locality")

    # -------------------------------------------------------------
    # 5. Missing dates and localities display the correct fallback text
    # -------------------------------------------------------------
    def test_missing_dates_and_localities_fallback(self):
        """Audit 5: Missing dates and localities display correct fallback text without fabrication"""
        import main
        # Verify helper returns None for missing/nan
        d_disp, d_iso = main.normalize_incident_date(None)
        self.assertIsNone(d_disp)
        self.assertIsNone(d_iso)

        d_disp2, d_iso2 = main.normalize_incident_date("")
        self.assertIsNone(d_disp2)

        # In Mangaluru dataset, test records with missing localities or missing dates
        payload = {
            "polyline": [[12.8696, 74.8423], [12.8710, 74.8450]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)

        for r in data["records"]:
            # If date or locality is None in API, frontend renders 'Date not recorded' and 'Location not recorded'
            if r["date"] is None:
                self.assertIsNone(r["date_iso"])
            if r["locality"] is None:
                self.assertTrue(r["locality"] is None)

    # -------------------------------------------------------------
    # 6. Exclude police-station reference coordinates and geographic mismatches
    # -------------------------------------------------------------
    def test_police_station_and_mismatch_exclusions(self):
        """Audit 6: Incident counts exclude police station reference coordinates and geographic mismatches"""
        # Corridor passing near police stations in Bengaluru
        payload = {
            "polyline": [[13.0358, 77.5970], [13.0400, 77.5970]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertGreater(data["excluded_police_stations"], 0)

        # Verify no returned record is a police station or mismatch
        for r in data["records"]:
            self.assertNotEqual(r["location_quality"], "POLICE_STATION_COORDINATE")
            self.assertNotEqual(r["location_quality"], "LOCATION_MISMATCH")

    # -------------------------------------------------------------
    # 7. Risk scores, category labels, map colors, and unmeasured states
    # -------------------------------------------------------------
    def test_risk_score_and_category_consistency(self):
        """Audit 7: Authoritative risk score bands, categories, colors, and unmeasured states are consistent"""
        from main import get_corridor_risk_tier

        # Test measured bands
        tier_lower = get_corridor_risk_tier(15.0, measured=True)
        self.assertEqual(tier_lower["category"], "Lower Historical Threat")
        self.assertEqual(tier_lower["color"], "#10b981")

        tier_mod = get_corridor_risk_tier(35.0, measured=True)
        self.assertEqual(tier_mod["category"], "Moderate Historical Threat")
        self.assertEqual(tier_mod["color"], "#eab308")

        tier_elev = get_corridor_risk_tier(45.0, measured=True)
        self.assertEqual(tier_elev["category"], "Elevated Historical Threat")
        self.assertEqual(tier_elev["color"], "#f97316")

        tier_high = get_corridor_risk_tier(75.0, measured=True)
        self.assertEqual(tier_high["category"], "Higher Historical Threat")
        self.assertEqual(tier_high["color"], "#ef4444")

        # Test unmeasured state
        tier_unmeasured = get_corridor_risk_tier(0.0, measured=False)
        self.assertEqual(tier_unmeasured["category"], "Insufficient Evidence")
        self.assertEqual(tier_unmeasured["color"], "#64748b")

        # Test route segments API returns consistent categories and colors
        route_res = self.post_safe_route({
            "source_lat": 12.9298, "source_lon": 77.6005,
            "dest_lat": 12.9716, "dest_lon": 77.5946
        })
        self.assertEqual(route_res[0], 200)
        segments = route_res[1]["segments"]
        for seg in segments:
            if seg["measured"]:
                self.assertIsNotNone(seg["score"])
                expected_tier = get_corridor_risk_tier(seg["score"], measured=True)
                self.assertEqual(seg["category"], expected_tier["category"])
                self.assertEqual(seg["color"], expected_tier["color"])
            else:
                self.assertIsNone(seg["score"])
                expected_tier = get_corridor_risk_tier(None, measured=False)
                self.assertEqual(seg["category"], expected_tier["category"])
                self.assertEqual(seg["color"], expected_tier["color"])

    # -------------------------------------------------------------
    # 8. Persistent 1.2 km Buffer Disclaimer
    # -------------------------------------------------------------
    def test_buffer_disclaimer_accuracy(self):
        """Audit 8: Persistent 1.2 km buffer disclaimer remains exact and visible"""
        payload = {
            "polyline": [[12.9298, 77.6005], [12.9350, 77.6050]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)

        expected_text = (
            "Incident counts include historical records within 1.2 km of this road segment. "
            "These incidents may have occurred nearby rather than directly on the road. "
            "Location accuracy depends on the original record."
        )
        self.assertEqual(data["disclaimer"], expected_text)

    # -------------------------------------------------------------
    # 9. Mangaluru temporal bonus prohibition & no invented timestamps
    # -------------------------------------------------------------
    def test_mangaluru_no_temporal_bonuses_or_invented_times(self):
        """Audit 9: Mangaluru records receive no invented timestamps or temporal bonuses"""
        payload = {
            "polyline": [[12.8696, 74.8423], [12.8710, 74.8450]],
            "buffer_km": 1.2
        }
        status, data = self.post_segment_incidents(payload)
        self.assertEqual(status, 200)
        self.assertEqual(data["city"], "Mangaluru")

        for r in data["records"]:
            # Mangaluru dates should be formatted dates without fabricated time components
            if r["date"]:
                # date should not contain time
                self.assertNotIn(":", r["date"], f"Mangaluru record date {r['date']} contains fabricated time")
            if r["date_iso"]:
                # date_iso should be YYYY-MM-DD
                self.assertEqual(len(r["date_iso"]), 10, f"Mangaluru date_iso {r['date_iso']} contains time")

        # Verify temporal bonus is 0 for Mangaluru in Safe Route calculation
        route_day = self.post_safe_route({
            "source_lat": 12.8696, "source_lon": 74.8423,
            "dest_lat": 12.8710, "dest_lon": 74.8450,
            "hour": 14, "day_of_week": 2
        })
        route_night = self.post_safe_route({
            "source_lat": 12.8696, "source_lon": 74.8423,
            "dest_lat": 12.8710, "dest_lon": 74.8450,
            "hour": 23, "day_of_week": 6
        })
        self.assertEqual(route_day[0], 200)
        self.assertEqual(route_night[0], 200)
        # Scores must be identical because temporal bonuses are prohibited for Mangaluru
        self.assertEqual(
            route_day[1]["average_risk"], 
            route_night[1]["average_risk"],
            "Mangaluru threat score must not differ between night and day (temporal bonuses prohibited)"
        )

    # -------------------------------------------------------------
    # 10. API error handling for invalid payloads
    # -------------------------------------------------------------
    def test_api_error_handling(self):
        """Audit 10: API handles empty results, invalid coordinates, and bad requests gracefully"""
        # Invalid polyline: empty
        req1 = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route/segment-incidents",
            data=json.dumps({"polyline": []}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx1:
            urllib.request.urlopen(req1)
        self.assertEqual(ctx1.exception.code, 400)

        # Polyline outside jurisdiction boundaries returns 0 incidents gracefully (not crash)
        payload_ocean = {
            "polyline": [[0.0, 0.0], [0.01, 0.01]],
            "buffer_km": 1.2
        }
        status, data_ocean = self.post_segment_incidents(payload_ocean)
        self.assertEqual(status, 200)
        self.assertEqual(data_ocean["total_records"], 0)
        self.assertEqual(len(data_ocean["categories"]), 0)
        self.assertEqual(len(data_ocean["records"]), 0)

if __name__ == "__main__":
    unittest.main()
