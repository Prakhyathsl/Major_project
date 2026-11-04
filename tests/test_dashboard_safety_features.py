"""
Unit and Integration Tests for BEACON Dashboard Public Safety Features
Covers:
1. High-Risk Zones dynamic rankings, score bands, multi-city filtering, and disclaimers.
2. Emergency Contacts verification: 112, 108, 101, 100, 1091 and official police directories.
3. My Current Location Safety: concentric incident density (500m, 1km, 2km), nearest high-risk areas, and nearest police stations.
4. Dashboard integration metrics consistency across Bengaluru and Mangaluru.
"""

import unittest
import urllib.request
import urllib.error
import json

BASE_URL = "http://127.0.0.1:8000"

class TestDashboardSafetyBackend(unittest.TestCase):
    """Backend test suite for BEACON dashboard public safety features"""

    def get_json(self, path):
        req = urllib.request.Request(f"{BASE_URL}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def post_json(self, path, payload):
        req = urllib.request.Request(
            f"{BASE_URL}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    # ==================== 1. HIGH-RISK ZONES ====================
    def test_high_risk_zones_structure_and_limits(self):
        """Top 5 highest-risk zones returned dynamically across sectors"""
        data = self.get_json("/api/high-risk-zones?limit=5")
        self.assertIn("zones", data)
        self.assertIn("disclaimer", data)
        self.assertIn("do not guarantee future safety", data["disclaimer"])
        zones = data["zones"]
        self.assertLessEqual(len(zones), 5)
        self.assertGreaterEqual(len(zones), 1)

        # Check required fields
        for z in zones:
            self.assertIn("locality", z)
            self.assertIn("city", z)
            self.assertIn("risk_score", z)
            self.assertIn("incident_count", z)
            self.assertIn("risk_category", z)
            self.assertIn(z["city"], ["Bengaluru", "Mangaluru"])
            self.assertIn(z["risk_category"], ["High Risk", "Moderate Risk", "Low Risk"])
            self.assertIsInstance(z["risk_score"], (int, float))
            self.assertIsInstance(z["incident_count"], int)

        # Check sorting: highest risk first
        scores = [z["risk_score"] for z in zones]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_high_risk_zones_city_filtering(self):
        """High-Risk Zones respect city filter queries"""
        blr_data = self.get_json("/api/high-risk-zones?limit=5&city=bengaluru")
        for z in blr_data["zones"]:
            self.assertEqual(z["city"], "Bengaluru")

        mlr_data = self.get_json("/api/high-risk-zones?limit=5&city=mangaluru")
        for z in mlr_data["zones"]:
            self.assertEqual(z["city"], "Mangaluru")

    def test_risky_zones_alias_compatibility(self):
        """Backward-compatibility endpoint /api/risky-zones returns same schema"""
        data = self.get_json("/api/risky-zones?limit=5")
        self.assertIn("zones", data)
        self.assertGreaterEqual(len(data["zones"]), 1)

    # ==================== 2. EMERGENCY CONTACTS ====================
    def test_emergency_hotlines_present(self):
        """Official national emergency numbers: 112, 108, 101, 100, 1091"""
        contacts = self.get_json("/api/safety-contacts")
        self.assertIn("emergency", contacts)
        self.assertIn("police_stations", contacts)

        emergency_numbers = {e["number"]: e["name"] for e in contacts["emergency"]}
        self.assertIn("112", emergency_numbers)
        self.assertIn("108", emergency_numbers)
        self.assertIn("101", emergency_numbers)
        self.assertIn("100", emergency_numbers)
        self.assertIn("1091", emergency_numbers)

    def test_police_stations_verified_directory(self):
        """Police stations have verified official numbers and coordinates"""
        contacts = self.get_json("/api/safety-contacts")
        stations = contacts["police_stations"]
        self.assertGreaterEqual(len(stations), 10)

        for ps in stations:
            self.assertIn("name", ps)
            self.assertIn("number", ps)
            self.assertIn("area", ps)
            self.assertIn("city", ps)
            self.assertIn(ps["city"], ["Bengaluru", "Mangaluru"])
            # Ensure number is formatted official landline (080- for BLR, 0824- or 08258- for MLR)
            if ps["city"] == "Bengaluru":
                self.assertTrue(ps["number"].startswith("080-"), f"Unexpected BLR number {ps['number']}")
            elif ps["city"] == "Mangaluru":
                self.assertTrue(ps["number"].startswith("0824-") or ps["number"].startswith("08258-"), f"Unexpected MLR number {ps['number']}")

    # ==================== 3. MY CURRENT LOCATION SAFETY ====================
    def test_predict_incident_density_analysis_bengaluru(self):
        """POST /api/predict calculates multi-radius density (500m, 1km, 2km) for Bengaluru"""
        payload = {"latitude": 12.9716, "longitude": 77.5946}
        res = self.post_json("/api/predict", payload)
        self.assertEqual(res["city"], "Bengaluru")
        self.assertIn("incident_density", res)
        density = res["incident_density"]
        self.assertIn("500m", density)
        self.assertIn("1km", density)
        self.assertIn("2km", density)
        self.assertLessEqual(density["500m"], density["1km"])
        self.assertLessEqual(density["1km"], density["2km"])

        # Check nearest police stations
        self.assertIn("nearby_police_stations", res)
        self.assertGreater(len(res["nearby_police_stations"]), 0)
        first_ps = res["nearby_police_stations"][0]
        self.assertIn("distance_km", first_ps)
        self.assertIn("number", first_ps)

        # Check nearest high-risk areas
        self.assertIn("nearest_high_risk_zones", res)
        self.assertGreater(len(res["nearest_high_risk_zones"]), 0)

    def test_predict_incident_density_analysis_mangaluru(self):
        """POST /api/predict calculates multi-radius density for Mangaluru coordinates"""
        payload = {"latitude": 12.8799, "longitude": 74.8554}
        res = self.post_json("/api/predict", payload)
        self.assertEqual(res["city"], "Mangaluru")
        self.assertIn("incident_density", res)
        density = res["incident_density"]
        self.assertIn("500m", density)
        self.assertIn("1km", density)
        self.assertIn("2km", density)
        self.assertLessEqual(density["500m"], density["1km"])
        self.assertLessEqual(density["1km"], density["2km"])

        # Mangaluru nearest police station check
        self.assertIn("nearby_police_stations", res)
        self.assertGreater(len(res["nearby_police_stations"]), 0)
        self.assertEqual(res["nearby_police_stations"][0]["city"], "Mangaluru")

    # ==================== 4. DASHBOARD INTEGRATION METRICS ====================
    def test_dashboard_metrics_dynamic_high_risk(self):
        """GET /api/dashboard returns dynamically calculated top_risky_areas"""
        dash = self.get_json("/api/dashboard")
        self.assertIn("top_risky_areas", dash)
        self.assertIn("high_risk_count", dash)
        self.assertIn("average_risk", dash)
        self.assertGreater(len(dash["top_risky_areas"]), 0)
        first = dash["top_risky_areas"][0]
        self.assertIn("locality", first)
        self.assertIn("risk_score", first)
        self.assertIn("incident_count", first)


if __name__ == "__main__":
    unittest.main()
