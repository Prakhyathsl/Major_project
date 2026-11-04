import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import main
from main import app, geocode_place, in_operational_area, GAZETTEER

class TestPlaceNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_in_operational_area(self):
        # Bengaluru
        self.assertTrue(in_operational_area(12.9716, 77.5946))
        # Mangaluru
        self.assertTrue(in_operational_area(12.9141, 74.8560))
        # Delhi (Out of bounds)
        self.assertFalse(in_operational_area(28.6139, 77.2090))
        # London (Out of bounds)
        self.assertFalse(in_operational_area(51.5074, -0.1278))

    def test_geocode_endpoint_valid_bengaluru(self):
        resp = self.client.get("/api/geocode?q=Indiranagar")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        results = data["results"]
        self.assertGreater(len(results), 0)
        first = results[0]
        self.assertIn("Indiranagar", first["display_name"])
        self.assertAlmostEqual(first["lat"], 12.9789, delta=0.05)
        self.assertAlmostEqual(first["lon"], 77.6403, delta=0.05)
        self.assertEqual(first["sector"], "Bengaluru Sector")

    def test_geocode_endpoint_valid_mangaluru(self):
        resp = self.client.get("/api/geocode?q=Surathkal")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        results = data["results"]
        self.assertGreater(len(results), 0)
        first = results[0]
        self.assertIn("Surathkal", first["display_name"])
        self.assertAlmostEqual(first["lat"], 13.0108, delta=0.05)
        self.assertAlmostEqual(first["lon"], 74.7933, delta=0.05)
        self.assertEqual(first["sector"], "Mangaluru Sector")

    def test_geocode_endpoint_unknown_query(self):
        resp = self.client.get("/api/geocode?q=NonExistentFictionalAtlantisPlace12345")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["results"]), 0)

    def test_geocode_endpoint_short_query(self):
        resp = self.client.get("/api/geocode?q=a")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])

    @patch("urllib.request.urlopen")
    def test_geocode_fallback_on_network_failure(self, mock_urlopen):
        # Simulate network timeout / error connecting to Nominatim
        mock_urlopen.side_effect = Exception("Connection timed out")
        results = geocode_place("Koramangala")
        self.assertGreater(len(results), 0)
        self.assertIn("Koramangala", results[0]["display_name"])
        self.assertEqual(results[0]["sector"], "Bengaluru Sector")

    def test_safe_route_with_place_names_bengaluru(self):
        payload = {
            "origin_name": "Banashankari",
            "destination_name": "Indiranagar"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["origin_name"], "Banashankari")
        self.assertEqual(data["destination_name"], "Indiranagar")
        self.assertGreater(data["distance_km"], 5.0)
        self.assertGreater(data["estimated_time_min"], 10.0)
        self.assertIn("route_polyline", data)
        self.assertGreater(len(data["route_polyline"]), 10)
        self.assertIn("accuracy_summary", data)
        self.assertEqual(data["accuracy_summary"]["confidence_level"], "MODERATE")
        self.assertIsNotNone(data["average_risk"])

    def test_safe_route_with_place_names_mangaluru(self):
        payload = {
            "origin_name": "Kadri",
            "destination_name": "Surathkal"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["origin_name"], "Kadri")
        self.assertEqual(data["destination_name"], "Surathkal")
        self.assertGreater(data["distance_km"], 8.0)
        self.assertIn("route_polyline", data)

    def test_safe_route_unknown_place_returns_400(self):
        payload = {
            "origin_name": "UnknownFictionalHogwarts999",
            "destination_name": "Indiranagar"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("could not be resolved", resp.json()["detail"])

    def test_safe_route_identical_origin_destination_returns_400(self):
        # With names
        payload = {
            "origin_name": "Indiranagar",
            "destination_name": "Indiranagar"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Starting point and destination cannot be identical", resp.json()["detail"])

        # With explicit coordinates
        coord_payload = {
            "src_lat": 12.9789,
            "src_lon": 77.6403,
            "dst_lat": 12.9789,
            "dst_lon": 77.6403
        }
        resp_coord = self.client.post("/api/safe-route", json=coord_payload)
        self.assertEqual(resp_coord.status_code, 400)
        self.assertIn("Starting point and destination cannot be identical", resp_coord.json()["detail"])

    def test_safe_route_out_of_bounds_returns_400(self):
        payload = {
            "src_lat": 28.6139,  # Delhi
            "src_lon": 77.2090,
            "dst_lat": 12.9716,
            "dst_lon": 77.5946
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("supported BEACON operational area", resp.json()["detail"])

    @patch("main.fetch_road_route")
    def test_safe_route_osrm_failure_returns_503(self, mock_osrm):
        # Mock OSRM failure (returns None)
        mock_osrm.return_value = None
        payload = {
            "origin_name": "Banashankari",
            "destination_name": "Indiranagar"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Routing Unavailable", resp.json()["detail"])

    def test_safe_route_unmeasured_corridor(self):
        # A rural corridor far from any recorded incidents
        payload = {
            "src_lat": 12.7500,
            "src_lon": 77.4000,
            "origin_name": "Rural Outpost A",
            "dst_lat": 12.7800,
            "dst_lon": 77.4200,
            "destination_name": "Rural Outpost B"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        acc = data["accuracy_summary"]
        self.assertEqual(acc["confidence_level"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(data["measured_risk"])
        self.assertEqual(data["average_risk"], 0.0)
        self.assertEqual(acc["total_corridor_incidents"], 0)
        self.assertEqual(acc["usable_evidence_ratio"], 0.0)

        # Segments check on unmeasured corridor
        self.assertIn("segments", data)
        self.assertIn("segment_summary", data)
        for seg in data["segments"]:
            self.assertFalse(seg["measured"])
            self.assertIsNone(seg["score"])
            self.assertEqual(seg["color"], "#64748b")
            self.assertEqual(seg["category"], "Insufficient Evidence")
        self.assertEqual(data["segment_summary"]["measured_percent"], 0.0)
        self.assertEqual(data["segment_summary"]["unmeasured_percent"], 100.0)

    def test_safe_route_segment_structure_and_contiguity(self):
        payload = {
            "origin_name": "Banashankari",
            "destination_name": "Indiranagar"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("segments", data)
        self.assertIn("segment_summary", data)
        segments = data["segments"]
        self.assertGreater(len(segments), 5)

        # Check contiguity: end of segment i must equal start of segment i+1
        for i in range(len(segments) - 1):
            curr_end = segments[i]["end_coord"]
            next_start = segments[i + 1]["start_coord"]
            self.assertAlmostEqual(curr_end[0], next_start[0], places=5)
            self.assertAlmostEqual(curr_end[1], next_start[1], places=5)

        # Check fields and color consistency
        color_map = {
            "Lower Historical Threat": "#10b981",
            "Moderate Historical Threat": "#eab308",
            "Elevated Historical Threat": "#f97316",
            "Higher Historical Threat": "#ef4444",
            "Insufficient Evidence": "#64748b"
        }
        for seg in segments:
            self.assertIn(seg["category"], color_map)
            self.assertEqual(seg["color"], color_map[seg["category"]])
            if seg["measured"]:
                self.assertIsNotNone(seg["score"])
                self.assertGreaterEqual(seg["score"], 0)
                self.assertLessEqual(seg["score"], 100)
            if seg["measured"]:
                self.assertIsNotNone(seg["score"])
                self.assertGreaterEqual(seg["score"], 0)
                self.assertLessEqual(seg["score"], 100)
                if seg["category"] == "Lower Historical Threat":
                    self.assertTrue(0 <= seg["score"] < 25.0)
                elif seg["category"] == "Moderate Historical Threat":
                    self.assertTrue(25.0 <= seg["score"] < 40.0)
                elif seg["category"] == "Elevated Historical Threat":
                    self.assertTrue(40.0 <= seg["score"] < 60.0)
                elif seg["category"] == "Higher Historical Threat":
                    self.assertTrue(60.0 <= seg["score"] <= 100.0)
            else:
                self.assertIsNone(seg["score"])
                self.assertEqual(seg["color"], "#64748b")

        # Check summary metrics
        summary = data["segment_summary"]
        self.assertEqual(summary["total_segments"], len(segments))
        self.assertAlmostEqual(summary["measured_percent"] + summary["unmeasured_percent"], 100.0, delta=0.2)
        self.assertGreater(summary["total_distance_km"], 5.0)

    def test_corridor_risk_tier_boundary_mapping(self):
        from main import get_corridor_risk_tier
        
        # Unmeasured / Insufficient Evidence
        res_none = get_corridor_risk_tier(None, measured=False)
        self.assertEqual(res_none["category"], "Insufficient Evidence")
        self.assertEqual(res_none["color"], "#64748b")
        self.assertEqual(res_none["key"], "unmeasured")

        res_unmeasured = get_corridor_risk_tier(35.0, measured=False)
        self.assertEqual(res_unmeasured["category"], "Insufficient Evidence")
        self.assertEqual(res_unmeasured["color"], "#64748b")

        # 0–24: Lower Historical Threat (Green: #10b981)
        res_0 = get_corridor_risk_tier(0)
        self.assertEqual(res_0["category"], "Lower Historical Threat")
        self.assertEqual(res_0["color"], "#10b981")

        res_24 = get_corridor_risk_tier(24)
        self.assertEqual(res_24["category"], "Lower Historical Threat")
        self.assertEqual(res_24["color"], "#10b981")

        res_24_9 = get_corridor_risk_tier(24.9)
        self.assertEqual(res_24_9["category"], "Lower Historical Threat")
        self.assertEqual(res_24_9["color"], "#10b981")

        # 25–39: Moderate Historical Threat (Yellow: #eab308)
        res_25 = get_corridor_risk_tier(25)
        self.assertEqual(res_25["category"], "Moderate Historical Threat")
        self.assertEqual(res_25["color"], "#eab308")

        res_39 = get_corridor_risk_tier(39)
        self.assertEqual(res_39["category"], "Moderate Historical Threat")
        self.assertEqual(res_39["color"], "#eab308")

        # Fractional values: 39.1 and 39.9 MUST be Moderate Historical Threat!
        res_39_1 = get_corridor_risk_tier(39.1)
        self.assertEqual(res_39_1["category"], "Moderate Historical Threat")
        self.assertEqual(res_39_1["color"], "#eab308")

        res_39_9 = get_corridor_risk_tier(39.9)
        self.assertEqual(res_39_9["category"], "Moderate Historical Threat")
        self.assertEqual(res_39_9["color"], "#eab308")

        # 40–59: Elevated Historical Threat (Orange: #f97316)
        res_40 = get_corridor_risk_tier(40)
        self.assertEqual(res_40["category"], "Elevated Historical Threat")
        self.assertEqual(res_40["color"], "#f97316")

        res_40_1 = get_corridor_risk_tier(40.1)
        self.assertEqual(res_40_1["category"], "Elevated Historical Threat")
        self.assertEqual(res_40_1["color"], "#f97316")

        res_59 = get_corridor_risk_tier(59)
        self.assertEqual(res_59["category"], "Elevated Historical Threat")
        self.assertEqual(res_59["color"], "#f97316")

        res_59_9 = get_corridor_risk_tier(59.9)
        self.assertEqual(res_59_9["category"], "Elevated Historical Threat")
        self.assertEqual(res_59_9["color"], "#f97316")

        # 60–100: Higher Historical Threat (Red: #ef4444)
        res_60 = get_corridor_risk_tier(60)
        self.assertEqual(res_60["category"], "Higher Historical Threat")
        self.assertEqual(res_60["color"], "#ef4444")

        res_100 = get_corridor_risk_tier(100)
        self.assertEqual(res_100["category"], "Higher Historical Threat")
        self.assertEqual(res_100["color"], "#ef4444")

    def test_safe_route_mangaluru_segments(self):
        payload = {
            "origin_name": "Kadri",
            "destination_name": "Surathkal"
        }
        resp = self.client.post("/api/safe-route", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("segments", data)
        self.assertIn("segment_summary", data)
        self.assertGreater(len(data["segments"]), 5)
        # Mangaluru route has both measured and/or unmeasured segments along coastal road
        summary = data["segment_summary"]
        self.assertGreater(summary["total_segments"], 0)
        self.assertAlmostEqual(summary["measured_percent"] + summary["unmeasured_percent"], 100.0, delta=0.2)

if __name__ == "__main__":
    unittest.main()
