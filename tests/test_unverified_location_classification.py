"""
BEACON — Comprehensive Verification Test Suite
Tests for Unverified Location Classification, Deterministic ID Resolution,
Public-Facing Labels, Safe Route Corridor Integrity, and Popup Consistency.
"""

import os
import json
import unittest
import pandas as pd
from fastapi.testclient import TestClient

import main
import geo_audit

class TestUnverifiedLocationClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.load_crime_data()
        main.load_mangaluru_data()
        cls.client = TestClient(main.app)
        
        # Load datasets
        cls.mlr_df = pd.read_csv("datasets/mangaluru_dataset.csv")
        cls.blr_df = pd.read_csv("bengaluru_dataset.csv")
        
        # Load audit report and lookup map
        with open("reports/geographic_accuracy_audit_report.json", "r", encoding="utf-8") as f:
            cls.audit_report = json.load(f)
        with open("reports/audit_lookup_map.json", "r", encoding="utf-8") as f:
            cls.audit_lookup = json.load(f)

    def test_01_trace_example_record(self):
        """Test 1: Trace exact example record (Row 225: Cheating, 24-02-2019, Mangaluru Distirict Prison, Barke PS)."""
        row = self.mlr_df.iloc[225]
        self.assertEqual(row['Type'], 'CHEATING')
        self.assertEqual(str(row['Date']).strip(), '24-02-2019')
        self.assertEqual(str(row['Place']).strip(), 'Mangaluru Distirict Prison')
        self.assertEqual(str(row['Police Station']).strip(), 'Barke PS')
        self.assertAlmostEqual(float(row['Latitude']), 12.881746, places=5)
        self.assertAlmostEqual(float(row['Longitude']), 74.833957, places=5)

        # Check in audit lookup map
        mlr_entry = self.audit_lookup.get("MLR-0226")
        self.assertIsNotNone(mlr_entry, "MLR-0226 should exist in audit lookup")
        self.assertEqual(mlr_entry["validation_status"], "LOCALITY_MATCH_ONLY")
        self.assertEqual(mlr_entry["coordinate_origin"], "locality_centroid")
        self.assertIn("Mangaluru District Prison", mlr_entry["evidence"])

    def test_02_audit_id_consistency_across_formats(self):
        """Test 2: Verify MLR-XXXX and MLR-CRIME-XXXX format symmetry and consistency."""
        mlr_key_short = "MLR-0226"
        mlr_key_long = "MLR-CRIME-0226"
        
        entry_short = main.get_audit_record_metadata(mlr_key_short)
        entry_long = main.get_audit_record_metadata(mlr_key_long)
        
        self.assertEqual(entry_short["validation_status"], entry_long["validation_status"])
        self.assertEqual(entry_short["coordinate_origin"], entry_long["coordinate_origin"])
        self.assertEqual(entry_short["evidence"], entry_long["evidence"])

        # Also test Bengaluru format symmetry
        blr_key_short = "BLR-0001"
        blr_key_long = "BLR-CRIME-0001"
        blr_short = main.get_audit_record_metadata(blr_key_short)
        blr_long = main.get_audit_record_metadata(blr_key_long)
        self.assertEqual(blr_short["validation_status"], blr_long["validation_status"])

    def test_03_deterministic_id_resolution(self):
        """Test 3: Test that source row IDs remain immutable across filtering and sampling."""
        res = self.client.get("/api/incidents?city=mangaluru&limit=2000")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Check target record
        found = [inc for inc in data["incidents"] if inc["id"] == "MLR-CRIME-0226"]
        self.assertEqual(len(found), 1)
        target = found[0]
        self.assertEqual(target["crime_type"], "CHEATING")
        self.assertEqual(target["place"], "Mangaluru Distirict Prison")
        self.assertEqual(target["validation_status"], "LOCALITY_MATCH_ONLY")
        self.assertEqual(target["location_quality"], "LOCALITY_MATCH_ONLY")
        self.assertEqual(target["location_quality_label"], "Approximate locality")

    def test_04_missing_audit_lookup_safe_fallback(self):
        """Test 4: Missing audit keys must strictly and safely default to LOCATION_UNVERIFIED."""
        missing_res = main.get_audit_record_metadata("MLR-99999")
        self.assertEqual(missing_res["validation_status"], "LOCATION_UNVERIFIED")
        self.assertEqual(missing_res["coordinate_origin"], "unverified_historical_record")
        self.assertIn("not found", missing_res["evidence"].lower())

        # Test empty/None id
        none_res = main.get_audit_record_metadata(None)
        self.assertEqual(none_res["validation_status"], "LOCATION_UNVERIFIED")

    def test_05_classification_categories_integrity(self):
        """Test 5: Verify all standard classification categories and label mappings."""
        expected_labels = {
            "INCIDENT_LOCATION_VERIFIED": "Verified location",
            "LOCALITY_MATCH_ONLY": "Approximate locality",
            "LOCATION_UNVERIFIED": "Location not verified",
            "POLICE_STATION_COORDINATE": "Police station reference",
            "LOCATION_MISMATCH": "Excluded: location mismatch"
        }
        for status, label in expected_labels.items():
            self.assertEqual(main.QUALITY_LABELS[status], label)

        # Check audit breakdown totals exist in audit metadata
        meta = self.audit_report["metadata"]
        self.assertEqual(meta["total_records_checked"], 15730)
        self.assertEqual(meta["bengaluru_records"], 9859)
        self.assertEqual(meta["mangaluru_records"], 5871)

        # Ensure genuine uncertainty is preserved
        self.assertGreater(meta["mangaluru_breakdown"]["LOCATION_UNVERIFIED"], 3000)
        self.assertGreater(meta["bengaluru_breakdown"]["LOCATION_UNVERIFIED"], 2000)

    def test_06_safe_route_segment_incidents_consistency(self):
        """Test 6: Safe Route segment incidents API consistency and exclusion of PS centroids."""
        payload = {
            "polyline": [
                [12.8800, 74.8300],
                [12.8820, 74.8340],
                [12.8850, 74.8360]
            ],
            "corridor_buffer_km": 0.5
        }
        res = self.client.post("/api/safe-route/segment-incidents", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIn("records", data)
        self.assertIn("excluded_police_stations", data)
        self.assertIn("excluded_mismatches", data)

        # Target record MLR-0226 must be present and labeled as Approximate locality
        matches = [r for r in data["records"] if r["id"] == "MLR-0226"]
        self.assertEqual(len(matches), 1)
        r = matches[0]
        self.assertEqual(r["location_quality"], "LOCALITY_MATCH_ONLY")
        self.assertEqual(r["location_quality_label"], "Approximate locality")
        self.assertIn("Mangaluru District Prison", r["evidence"])

    def test_07_frontend_quality_labels_synchronization(self):
        """Test 7: Verify frontend index.html has matching labels and popup badge."""
        with open("frontend/index.html", "r", encoding="utf-8") as f:
            fe_content = f.read()

        # Check getSimplifiedQualityLabel mappings
        self.assertIn("if (status === 'INCIDENT_LOCATION_VERIFIED') return 'Verified location';", fe_content)
        self.assertIn("if (status === 'LOCALITY_MATCH_ONLY') return 'Approximate locality';", fe_content)
        self.assertIn("if (status === 'LOCATION_UNVERIFIED') return 'Location not verified';", fe_content)
        self.assertIn("if (status === 'POLICE_STATION_COORDINATE') return 'Police station reference';", fe_content)
        self.assertIn("if (status === 'LOCATION_MISMATCH') return 'Excluded: location mismatch';", fe_content)

        # Check that popup renders quality badge
        self.assertIn("qStatus = record.location_quality || record.validation_status", fe_content)
        self.assertIn("qLabel = record.location_quality_label || getSimplifiedQualityLabel(qStatus)", fe_content)

if __name__ == "__main__":
    unittest.main()
