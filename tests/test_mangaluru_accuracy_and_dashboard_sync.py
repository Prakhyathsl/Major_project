"""
Unit and Integration Tests for:
1. Station references removal from UI and map layers
2. Mangaluru geographic accuracy and audit filtering
3. Dashboard and Safety Map count synchronization (6,538 = 5,023 + 1,515)
4. Full retrieval without truncation
"""

import unittest
import json
import os
from fastapi.testclient import TestClient
import main
from main import app, mangaluru_crime_data, crime_data, AUDIT_LOOKUP

class TestMangaluruAccuracyAndDashboardSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_ctx = TestClient(app)
        cls.client = cls.client_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)

    def test_01_station_references_ui_completely_removed(self):
        """Verify that Station References feature is completely removed from frontend and public HTML."""
        for path in ["frontend/index.html", "public/index.html"]:
            self.assertTrue(os.path.exists(path), f"{path} must exist")
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Verify UI controls and layer variables are absent
            self.assertNotIn("id=\"toggle-station-markers\"", content, f"{path} should not have toggle-station-markers")
            self.assertNotIn("id=\"strip-station-count\"", content, f"{path} should not have strip-station-count")
            self.assertNotIn("policeStationsLayer", content, f"{path} should not declare policeStationsLayer")
            self.assertNotIn("createStationMarkerIcon", content, f"{path} should not have createStationMarkerIcon")
            self.assertNotIn("toggleStationReferencesLayer", content, f"{path} should not have toggleStationReferencesLayer")
            self.assertNotIn("showStationMarkers", content, f"{path} should not have showStationMarkers in state")
            self.assertNotIn("loadedStationIds", content, f"{path} should not have loadedStationIds in state")

    def test_02_dynamic_audit_strip_counters_present(self):
        """Verify dynamic audit strip counters are present in frontend and public HTML."""
        required_strip_ids = [
            "strip-total-eligible",
            "strip-blr-approx",
            "strip-mlr-approx",
            "strip-verified-count",
            "strip-visible-count",
            "strip-plotted-count",
            "strip-unverified-count",
            "strip-mismatch-count",
            "strip-active-city"
        ]
        for path in ["frontend/index.html", "public/index.html"]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            for elem_id in required_strip_ids:
                self.assertIn(f"id=\"{elem_id}\"", content, f"{path} missing {elem_id}")

    def test_03_frontend_and_public_html_synchronized(self):
        """Verify that frontend/index.html and public/index.html are byte-for-byte synchronized."""
        with open("frontend/index.html", "rb") as f1, open("public/index.html", "rb") as f2:
            self.assertEqual(f1.read(), f2.read(), "frontend/index.html and public/index.html must be identical")

    def test_04_dashboard_counts_synchronized(self):
        """Verify /api/dashboard returns synchronized eligible counts where Total = BLR + MLR."""
        resp = self.client.get("/api/dashboard")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        total = data.get("total_eligible_incidents")
        blr = data.get("bengaluru_eligible_incidents")
        mlr = data.get("mangaluru_eligible_incidents")

        self.assertEqual(total, 6538, f"Expected 6,538 total eligible incidents, got {total}")
        self.assertEqual(blr, 5023, f"Expected 5,023 Bengaluru eligible incidents, got {blr}")
        self.assertEqual(mlr, 1515, f"Expected 1,515 Mangaluru eligible incidents, got {mlr}")
        self.assertEqual(total, blr + mlr, "Total eligible must equal Bengaluru eligible + Mangaluru eligible")

    def test_05_incident_stats_synchronized(self):
        """Verify /api/incidents/stats returns dynamic audit breakdown matching requirements."""
        # Combined stats
        resp = self.client.get("/api/incidents/stats?city=combined")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data.get("total_eligible_incidents"), 6538)
        self.assertEqual(data.get("bengaluru_approximate"), 5023)
        self.assertEqual(data.get("mangaluru_approximate"), 1515)
        self.assertEqual(data.get("verified_locations"), 0)
        self.assertEqual(data.get("unverified_excluded"), 7208)  # 2925 BLR + 4283 MLR
        self.assertEqual(data.get("mismatches_excluded"), 910)   # 910 BLR + 0 MLR

        # Bengaluru stats
        resp_blr = self.client.get("/api/incidents/stats?city=bengaluru")
        self.assertEqual(resp_blr.status_code, 200)
        data_blr = resp_blr.json()
        self.assertEqual(data_blr.get("total_eligible_incidents"), 5023)
        self.assertEqual(data_blr.get("bengaluru_approximate"), 5023)
        self.assertEqual(data_blr.get("mangaluru_approximate"), 0)
        self.assertEqual(data_blr.get("unverified_excluded"), 2925)
        self.assertEqual(data_blr.get("mismatches_excluded"), 910)

        # Mangaluru stats
        resp_mlr = self.client.get("/api/incidents/stats?city=mangaluru")
        self.assertEqual(resp_mlr.status_code, 200)
        data_mlr = resp_mlr.json()
        self.assertEqual(data_mlr.get("total_eligible_incidents"), 1515)
        self.assertEqual(data_mlr.get("mangaluru_approximate"), 1515)
        self.assertEqual(data_mlr.get("bengaluru_approximate"), 0)
        self.assertEqual(data_mlr.get("unverified_excluded"), 4283)
        self.assertEqual(data_mlr.get("mismatches_excluded"), 0)

    def test_06_mangaluru_incidents_audit_filtering_and_retrievability(self):
        """Verify /api/incidents?city=mangaluru returns all 1,515 eligible records and zero unverified/stations."""
        # Retrieve all records via pagination
        all_incidents = []
        offset = 0
        limit = 1000
        while True:
            resp = self.client.get(f"/api/incidents?city=mangaluru&limit={limit}&offset={offset}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            batch = data.get("incidents", [])
            all_incidents.extend(batch)
            offset += len(batch)
            if not data.get("has_more") or len(batch) == 0:
                break

        self.assertEqual(len(all_incidents), 1515, f"Expected 1,515 Mangaluru records, got {len(all_incidents)}")

        # Verify classifications of every returned record
        allowed_statuses = {"LOCALITY_MATCH_ONLY", "INCIDENT_LOCATION_VERIFIED"}
        for inc in all_incidents:
            status = inc.get("validation_status") or inc.get("location_quality")
            self.assertIn(status, allowed_statuses, f"Record {inc.get('id')} has unallowed status {status}")
            self.assertEqual(inc.get("city"), "Mangaluru")
            self.assertIsNotNone(inc.get("latitude"))
            self.assertIsNotNone(inc.get("longitude"))
            # Jurisdiction police station must remain intact
            self.assertTrue(inc.get("police_station"), f"Record {inc.get('id')} missing jurisdiction police station")

    def test_07_bengaluru_incidents_audit_filtering_and_retrievability(self):
        """Verify /api/incidents?city=bengaluru returns all 5,023 eligible records and excludes non-eligible."""
        all_incidents = []
        offset = 0
        limit = 2500
        while True:
            resp = self.client.get(f"/api/incidents?city=bengaluru&classification=LOCALITY_MATCH_ONLY&limit={limit}&offset={offset}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            batch = data.get("incidents", [])
            all_incidents.extend(batch)
            offset += len(batch)
            if not data.get("has_more") or len(batch) == 0:
                break

        self.assertEqual(len(all_incidents), 5023, f"Expected 5,023 Bengaluru records, got {len(all_incidents)}")
        for inc in all_incidents:
            status = inc.get("validation_status") or inc.get("location_quality")
            self.assertEqual(status, "LOCALITY_MATCH_ONLY")
            self.assertEqual(inc.get("city"), "Bengaluru")

    def test_08_deterministic_id_and_jurisdiction_preservation(self):
        """Verify deterministic IDs and preservation of jurisdiction information."""
        resp = self.client.get("/api/incidents?city=mangaluru&limit=20")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        incidents = data.get("incidents", [])
        self.assertGreater(len(incidents), 0)

        for inc in incidents:
            rec_id = inc.get("id")
            self.assertTrue(rec_id.startswith("MLR-CRIME-"), f"Expected deterministic ID MLR-CRIME-XXXX, got {rec_id}")
            self.assertIn("police_station", inc)
            self.assertNotEqual(inc["police_station"], "")

if __name__ == "__main__":
    unittest.main()
