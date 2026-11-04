import unittest
from fastapi.testclient import TestClient
from main import app, crime_data, mangaluru_crime_data, AUDIT_LOOKUP

class TestBengaluruLocalityMatchOnlyMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_ctx = TestClient(app)
        cls.client = cls.client_ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)

    # 1. Exact count and complete retrieval of 5,023 records
    def test_01_all_5023_approximate_records_retrievable_without_truncation(self):
        resp = self.client.get("/api/incidents?city=bengaluru&limit=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["total"], 5023, f"Expected 5,023 total approximate records, got {data['total']}")
        self.assertEqual(len(data["incidents"]), 5023, f"Expected 5,023 returned incidents, got {len(data['incidents'])}")

        # Verify no duplicate incident IDs
        incident_ids = [inc["id"] for inc in data["incidents"]]
        self.assertEqual(len(incident_ids), len(set(incident_ids)), "Duplicate incident IDs detected in payload")

    # 2. Validation status and label checks for all 5,023 records
    def test_02_all_records_labeled_approximate_location_never_exact(self):
        resp = self.client.get("/api/incidents?city=bengaluru&limit=0")
        data = resp.json()

        for inc in data["incidents"]:
            self.assertEqual(inc["validation_status"], "LOCALITY_MATCH_ONLY")
            self.assertEqual(inc["location_quality"], "LOCALITY_MATCH_ONLY")
            self.assertEqual(inc["location_quality_label"], "Approximate Location")
            self.assertIn(inc["status_badge"], ["APPROXIMATE LOCALITY", "SOURCE RECORD (PRIVACY PROTECTED)"])
            # Never labeled as verified or exact scene
            self.assertNotEqual(inc["location_quality_label"], "Verified location")
            self.assertNotEqual(inc["status_badge"], "VERIFIED INCIDENT SCENE")
            # Evidence disclaims exact crime-scene accuracy
            self.assertIn("Approximate locality centroid", inc["evidence"])

    # 3. Coordinate bounds validation for all 5,023 records
    def test_03_coordinates_fall_within_bengaluru_bounds(self):
        resp = self.client.get("/api/incidents?city=bengaluru&limit=0")
        data = resp.json()

        for inc in data["incidents"]:
            lat = inc["latitude"]
            lon = inc["longitude"]
            self.assertGreaterEqual(lat, 12.60, f"Lat {lat} out of southern bounds for {inc['id']}")
            self.assertLessEqual(lat, 13.40, f"Lat {lat} out of northern bounds for {inc['id']}")
            self.assertGreaterEqual(lon, 77.25, f"Lon {lon} out of western bounds for {inc['id']}")
            self.assertLessEqual(lon, 77.95, f"Lon {lon} out of eastern bounds for {inc['id']}")

    # 4. Strict isolation: no unverified or mismatch records in approximate layer
    def test_04_unverified_and_mismatches_strictly_excluded(self):
        resp = self.client.get("/api/incidents?city=bengaluru&limit=0")
        data = resp.json()

        unverified = [i for i in data["incidents"] if i["validation_status"] == "LOCATION_UNVERIFIED"]
        mismatches = [i for i in data["incidents"] if i["validation_status"] == "LOCATION_MISMATCH"]
        police_stations = [i for i in data["incidents"] if i["validation_status"] == "POLICE_STATION_COORDINATE"]

        self.assertEqual(len(unverified), 0, "Unverified records leaked into approximate locality layer")
        self.assertEqual(len(mismatches), 0, "Out-of-region mismatch records leaked into incident layer")
        self.assertEqual(len(police_stations), 0, "Police station coordinates leaked into approximate layer")

    # 5. Police Station Reference Layer Isolation
    def test_05_police_station_reference_layer_isolation(self):
        resp = self.client.get("/api/incidents?city=bengaluru&layer=police_stations&limit=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertEqual(data["total"], 1001, f"Expected 1,001 police station references, got {data['total']}")
        self.assertEqual(len(data["incidents"]), 1001)

        for inc in data["incidents"]:
            self.assertEqual(inc["validation_status"], "POLICE_STATION_COORDINATE")
            self.assertEqual(inc["location_quality_label"], "Police station reference")
            self.assertIn("Police Station Reference Coordinate", inc["evidence"])

    # 6. Dynamic Stats Endpoint exact counts
    def test_06_dynamic_stats_endpoint_exact_audit_counts(self):
        resp = self.client.get("/api/incidents/stats?city=bengaluru")
        self.assertEqual(resp.status_code, 200)
        stats = resp.json()

        self.assertEqual(stats["city"], "bengaluru")
        self.assertEqual(stats["total_records"], 9859)
        self.assertEqual(stats["approximate_locality"], 5023)
        self.assertEqual(stats["location_unverified"], 2925)
        self.assertEqual(stats["police_station_reference"], 1001)
        self.assertEqual(stats["location_mismatch"], 910)
        self.assertEqual(stats["verified_locations"], 0)
        self.assertEqual(stats["eligible_approximate_markers"], 5023)

        # Sum of classifications must equal total dataset
        cat_sum = (stats["approximate_locality"] + stats["location_unverified"] +
                   stats["police_station_reference"] + stats["location_mismatch"])
        self.assertEqual(cat_sum, 9859, f"Sum of audit categories ({cat_sum}) must equal 9,859")

    # 7. Pagination without omission or duplication
    def test_07_pagination_guarantees_complete_retrieval(self):
        page_size = 2000
        offset = 0
        all_retrieved = []

        while True:
            resp = self.client.get(f"/api/incidents?city=bengaluru&limit={page_size}&offset={offset}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            recs = data["incidents"]
            all_retrieved.extend(recs)
            offset += len(recs)

            if not data["has_more"] or len(recs) == 0:
                break

        self.assertEqual(len(all_retrieved), 5023, f"Paginated retrieval expected 5,023 records, got {len(all_retrieved)}")
        unique_ids = set(r["id"] for r in all_retrieved)
        self.assertEqual(len(unique_ids), 5023, "Duplicate records found across pagination boundaries")

    # 8. Viewport Bounding Box Spatial Filtering
    def test_08_viewport_bounding_box_filtering(self):
        # Central Bengaluru box (12.95 to 13.00 N, 77.55 to 77.65 E)
        resp = self.client.get("/api/incidents?city=bengaluru&min_lat=12.95&max_lat=13.00&min_lon=77.55&max_lon=77.65&limit=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertGreater(data["total"], 0, "Expected records in central Bengaluru viewport")
        self.assertEqual(len(data["incidents"]), data["total"])

        for inc in data["incidents"]:
            self.assertGreaterEqual(inc["latitude"], 12.95)
            self.assertLessEqual(inc["latitude"], 13.00)
            self.assertGreaterEqual(inc["longitude"], 77.55)
            self.assertLessEqual(inc["longitude"], 77.65)
            self.assertEqual(inc["validation_status"], "LOCALITY_MATCH_ONLY")

    # 9. Crime Category Filtering on complete 5,023 dataset
    def test_09_crime_category_filters_complete_approximate_dataset(self):
        resp = self.client.get("/api/incidents?city=bengaluru&crime_type=THEFT&limit=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertGreater(data["total"], 0)
        for inc in data["incidents"]:
            self.assertIn("theft", inc["crime_type"].lower())
            self.assertEqual(inc["validation_status"], "LOCALITY_MATCH_ONLY")

    # 10. Locality Query Mode (e.g. Hebbal returns all 100)
    def test_10_locality_query_preserves_all_records(self):
        resp = self.client.get("/api/incidents?locality=Hebbal")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 100)
        self.assertEqual(len(data["incidents"]), 100)

    # 11. Mangaluru functionality unchanged
    def test_11_mangaluru_functionality_unchanged(self):
        stats_resp = self.client.get("/api/incidents/stats?city=mangaluru")
        self.assertEqual(stats_resp.status_code, 200)
        stats = stats_resp.json()

        self.assertEqual(stats["city"], "mangaluru")
        self.assertEqual(stats["total_records"], 5871)
        self.assertEqual(stats["approximate_locality"], 1515)
        self.assertEqual(stats["location_unverified"], 4283)
        self.assertEqual(stats["police_station_reference"], 73)
        self.assertEqual(stats["location_mismatch"], 0)

        # Incidents query for Mangaluru
        mlr_resp = self.client.get("/api/incidents?city=mangaluru&limit=500")
        self.assertEqual(mlr_resp.status_code, 200)
        mlr_data = mlr_resp.json()
        self.assertEqual(mlr_data["city"], "mangaluru")
        self.assertGreater(len(mlr_data["incidents"]), 0)
        self.assertTrue(all(i["city"] == "Mangaluru" for i in mlr_data["incidents"]))

if __name__ == "__main__":
    unittest.main()
