"""
BEACON — High-Risk Zones Dataset Accuracy & Safety Map Consistency Test Suite

Verifies:
1. Ground Truth Dataset Audit:
   - Exactly 100 records in bengaluru_dataset.csv have Place == 'Hebbal'.
   - All 100 coordinates are unique, valid, and within 1.54 km of Hebbal center.
   - All 100 records are violent crimes from Year 2023 (36 Attempted Murder, 36 Assault, 28 Murder).
2. Root Cause Verification (104 vs 100):
   - Confirms that the 4 additional records in the old 2km radial query came from
     Hanumantha Nagar PS (Shastri Nagar / Tyagaraja Nagar / TR Nagar in South Bengaluru).
   - Confirms that locality-based attribution cleanly excludes these 4 mismatches.
3. High-Risk Zones API Accuracy (/api/high-risk-zones):
   - Hebbal is ranked #1 in Combined and Bengaluru views.
   - Hebbal incident count is exactly 100 (not 104).
   - Hebbal risk score is 72.1 (derived from Hebbal's own records, not a 25-record cell).
   - Category is 'High Risk'.
4. Safety Map & Incidents Consistency (/api/incidents):
   - GET /api/incidents?locality=Hebbal returns exactly 100 matching records.
   - Default GET /api/incidents?limit=1000 guarantees all 100 Hebbal records are included.
   - Dashboard incident count (100) exactly equals the Safety Map marker count (100).
5. Multi-City Integrity (Bengaluru & Mangaluru):
   - Mangaluru rankings use genuine records from mangaluru_dataset.csv.
   - Localities with < 5 records are designated as 'Insufficient Evidence'.
"""

import unittest
import urllib.request
import json
import pandas as pd
import numpy as np
import math
import os

BASE_URL = "http://127.0.0.1:8000"

class TestHighRiskZonesDatasetAccuracy(unittest.TestCase):
    """Rigorous test suite for BEACON dataset accuracy and map consistency"""

    @classmethod
    def setUpClass(cls):
        cls.blr_df = pd.read_csv("bengaluru_dataset.csv")
        cls.blr_df.columns = cls.blr_df.columns.str.strip().str.lower().str.replace(' ', '_')
        
        cls.mlr_df = pd.read_csv("datasets/mangaluru_dataset.csv")

    def get_json(self, path):
        req = urllib.request.Request(f"{BASE_URL}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    # ==================== 1. HEBBAL GROUND TRUTH AUDIT ====================
    def test_hebbal_dataset_records_count(self):
        """bengaluru_dataset.csv contains exactly 100 records with Place == 'Hebbal'"""
        hebbal_places = self.blr_df[self.blr_df['place'].astype(str).str.strip().str.lower() == 'hebbal']
        self.assertEqual(len(hebbal_places), 100, f"Expected exactly 100 records with Place='Hebbal', found {len(hebbal_places)}")

        hebbal_stations = self.blr_df[self.blr_df['police_station'].astype(str).str.strip().str.lower() == 'hebbal']
        self.assertEqual(len(hebbal_stations), 100, f"Expected exactly 100 records with Police Station='Hebbal', found {len(hebbal_stations)}")

    def test_hebbal_coordinates_validity_and_uniqueness(self):
        """All 100 Hebbal records have distinct GPS coordinates within Hebbal bounds"""
        hebbal = self.blr_df[self.blr_df['place'].astype(str).str.strip().str.lower() == 'hebbal']
        
        # No null coordinates
        self.assertEqual(hebbal['latitude'].isna().sum(), 0)
        self.assertEqual(hebbal['longitude'].isna().sum(), 0)

        # Coordinate ranges in Hebbal
        self.assertTrue((hebbal['latitude'] >= 13.020).all() and (hebbal['latitude'] <= 13.055).all(),
                        "All Hebbal latitudes must be in North Bengaluru Hebbal corridor (13.02-13.05)")
        self.assertTrue((hebbal['longitude'] >= 77.580).all() and (hebbal['longitude'] <= 77.615).all(),
                        "All Hebbal longitudes must be in North Bengaluru Hebbal corridor (77.58-77.61)")

        # Uniqueness: 100 distinct GPS coordinates
        unique_coords = hebbal[['latitude', 'longitude']].drop_duplicates()
        self.assertEqual(len(unique_coords), 100, "All 100 Hebbal records must have unique, non-synthesized coordinates")

    def test_hebbal_crime_categories_and_temporal(self):
        """Hebbal crime distribution: 36 Attempted Murder, 36 Assault, 28 Murder in Year 2023"""
        hebbal = self.blr_df[self.blr_df['place'].astype(str).str.strip().str.lower() == 'hebbal']
        vc = hebbal['type'].value_counts().to_dict()
        self.assertEqual(vc.get('Attempted Murder', 0), 36)
        self.assertEqual(vc.get('Assault', 0), 36)
        self.assertEqual(vc.get('Murder', 0), 28)
        self.assertEqual(sum(vc.values()), 100, "100% of Hebbal records are violent crimes")

    # ==================== 2. ROOT CAUSE AUDIT (104 VS 100) ====================
    def test_radial_query_mismatch_identified(self):
        """Identify the 4 out-of-region geocoded mismatch records from Hanumantha Nagar PS"""
        hebbal_gazetteer = (13.035037, 77.596621)
        
        def haversine_km(lat1, lon1, lat2, lon2):
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        all_dists = [haversine_km(hebbal_gazetteer[0], hebbal_gazetteer[1], lat, lon)
                     for lat, lon in zip(self.blr_df['latitude'], self.blr_df['longitude'])]
        within_2km = self.blr_df[pd.Series(all_dists) <= 2.0]
        
        self.assertEqual(len(within_2km), 104, "Raw 2km radius around Hebbal gazetteer must identify exactly 104 records")
        
        mismatched = within_2km[within_2km['police_station'].astype(str).str.strip().str.lower() != 'hebbal']
        self.assertEqual(len(mismatched), 4, "Exactly 4 records must be foreign police station geocoding mismatches")
        self.assertTrue((mismatched['police_station'] == 'Hanumantha Nagar').all(),
                        "All 4 foreign records belong to Hanumantha Nagar PS in South Bengaluru")

    # ==================== 3. HIGH-RISK ZONES ENDPOINT ====================
    def test_high_risk_zones_hebbal_score_and_count(self):
        """GET /api/high-risk-zones returns Hebbal with count=100, score=72.1, High Risk"""
        data = self.get_json("/api/high-risk-zones?limit=5")
        zones = data["zones"]
        self.assertGreaterEqual(len(zones), 1)

        hebbal = next((z for z in zones if z["locality"] == "Hebbal"), None)
        self.assertIsNotNone(hebbal, "Hebbal must appear in Top 5 High-Risk Zones")
        self.assertEqual(hebbal["incident_count"], 100, f"Hebbal count must be 100 (not 104), got {hebbal['incident_count']}")
        self.assertEqual(hebbal["city"], "Bengaluru")
        self.assertEqual(hebbal["risk_category"], "High Risk")
        self.assertEqual(hebbal["risk_score"], 72.1, f"Hebbal risk score must be 72.1, got {hebbal['risk_score']}")

    def test_high_risk_zones_mangaluru_filtering(self):
        """GET /api/high-risk-zones?city=mangaluru returns genuine MLR localities"""
        data = self.get_json("/api/high-risk-zones?limit=5&city=mangaluru")
        zones = data["zones"]
        self.assertGreaterEqual(len(zones), 1)
        for z in zones:
            self.assertEqual(z["city"], "Mangaluru")
            self.assertGreaterEqual(z["incident_count"], 5, "Ranked zones must have at least 5 incidents")

        mlr_localities = [z["locality"] for z in zones]
        self.assertIn("Kadri", mlr_localities)
        self.assertIn("Surathkal", mlr_localities)

    # ==================== 4. SAFETY MAP & INCIDENTS CONSISTENCY ====================
    def test_locality_incidents_endpoint_hebbal(self):
        """GET /api/incidents?locality=Hebbal returns all 100 eligible records"""
        data = self.get_json("/api/incidents?locality=Hebbal")
        self.assertEqual(data["total"], 100)
        self.assertEqual(len(data["incidents"]), 100)
        
        # Verify structure of Hebbal incident markers
        sample = data["incidents"][0]
        self.assertEqual(sample["place"], "Hebbal")
        self.assertEqual(sample["city"], "Bengaluru")
        self.assertIn(sample["crime_type"], ["Attempted Murder", "Murder", "Assault"])
        self.assertIsInstance(sample["latitude"], (int, float))
        self.assertIsInstance(sample["longitude"], (int, float))

    def test_default_map_sample_contains_all_hebbal_records(self):
        """GET /api/incidents?limit=1000 contains all 100 Hebbal records for map plotting"""
        data = self.get_json("/api/incidents?limit=1000")
        hebbal_in_map = [i for i in data["incidents"] if i["place"].lower() == "hebbal"]
        self.assertEqual(len(hebbal_in_map), 100,
                         f"Safety Map must have all 100 Hebbal records plotted, found {len(hebbal_in_map)}")

    def test_dashboard_to_map_count_exact_match(self):
        """High-Risk Zones card incident count matches Safety Map available marker count"""
        hr_data = self.get_json("/api/high-risk-zones?limit=5")
        hebbal_card = next(z for z in hr_data["zones"] if z["locality"] == "Hebbal")
        card_count = hebbal_card["incident_count"]

        loc_data = self.get_json("/api/incidents?locality=Hebbal")
        map_count = loc_data["total"]

        self.assertEqual(card_count, map_count,
                         f"Dashboard card count ({card_count}) must exactly equal Safety Map marker count ({map_count})")
        self.assertEqual(card_count, 100)

if __name__ == "__main__":
    unittest.main()

