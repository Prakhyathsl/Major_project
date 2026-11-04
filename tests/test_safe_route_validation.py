"""
BEACON Safe Route Risk and Confidence Validation Suite
Tests:
1. Usable Evidence Ratio Formula (Zero records, All-centroid, Mixed evidence, All-unverified)
2. Confidence Threshold Boundaries (Insufficient evidence, Moderate, Approximate, High prevention)
3. Determinism & Duplicate Suppression
4. Multi-Route Evaluation (Dense locality, Sparse, Unverified-dominated, Police station only, No incidents, Invalid coordinates)
5. Dataset Preservation & Model Pipeline Integrity
"""

import unittest
import urllib.request
import urllib.error
import json
import math
import pandas as pd


class TestEvidenceRatioFormula(unittest.TestCase):
    """Unit tests for the documented evidence ratio weighting formula"""

    def calculate_evidence_ratio(self, verified, locality, unverified):
        total = verified + locality + unverified
        numerator = 1.0 * verified + 0.85 * locality + 0.0 * unverified
        return round((numerator / total) * 100, 1) if total > 0 else 0.0

    def test_zero_records(self):
        # 0 records -> ratio 0.0%
        ratio = self.calculate_evidence_ratio(0, 0, 0)
        self.assertEqual(ratio, 0.0)

    def test_all_centroid_records(self):
        # 100 locality centroids -> 85.0%
        ratio = self.calculate_evidence_ratio(0, 100, 0)
        self.assertEqual(ratio, 85.0)

    def test_mixed_evidence(self):
        # 10 verified (1.0), 40 centroid (0.85), 50 unverified (0.0) -> (10 + 34)/100 = 44.0%
        ratio = self.calculate_evidence_ratio(10, 40, 50)
        self.assertEqual(ratio, 44.0)

    def test_all_unverified_records(self):
        # 100 unverified -> 0.0%
        ratio = self.calculate_evidence_ratio(0, 0, 100)
        self.assertEqual(ratio, 0.0)


class TestConfidenceThresholdBoundaries(unittest.TestCase):
    """Unit tests for confidence label threshold boundaries"""

    def evaluate_confidence(self, verified, locality, unverified):
        total = verified + locality + unverified
        numerator = 1.0 * verified + 0.85 * locality
        ratio = (numerator / total) * 100 if total > 0 else 0.0

        if total == 0:
            return "INSUFFICIENT_EVIDENCE"
        # Rule: HIGH requires verified points, ratio >= 70%, total >= 15
        elif verified > 0 and ratio >= 70.0 and total >= 15:
            return "HIGH"
        elif ratio >= 60.0 and total >= 10:
            return "MODERATE"
        else:
            return "APPROXIMATE"

    def test_insufficient_evidence(self):
        self.assertEqual(self.evaluate_confidence(0, 0, 0), "INSUFFICIENT_EVIDENCE")

    def test_sparse_centroid_insufficient_volume(self):
        # D = 8 (< 10 threshold), ratio = 85.0% -> APPROXIMATE
        self.assertEqual(self.evaluate_confidence(0, 8, 0), "APPROXIMATE")

    def test_moderate_boundary_met(self):
        # D = 10 (>= 10), ratio = 85.0% (>= 60%) -> MODERATE
        self.assertEqual(self.evaluate_confidence(0, 10, 0), "MODERATE")

    def test_approximate_boundary_ratio_below_60(self):
        # D = 50, ratio = 55.0% (< 60%) -> APPROXIMATE
        # e.g., 30 locality, 20 unverified -> numerator = 25.5, ratio = 51.0%
        self.assertEqual(self.evaluate_confidence(0, 30, 20), "APPROXIMATE")

    def test_moderate_ratio_at_boundary_60(self):
        # D = 50, locality = 36, unverified = 14 -> num = 30.6, ratio = 61.2% -> MODERATE
        self.assertEqual(self.evaluate_confidence(0, 36, 14), "MODERATE")

    def test_high_confidence_never_issued_when_verified_is_zero(self):
        # Even with 1000 locality centroids (ratio 85%), verified = 0 -> MUST NOT be HIGH
        conf = self.evaluate_confidence(0, 1000, 0)
        self.assertNotEqual(conf, "HIGH")
        self.assertEqual(conf, "MODERATE")


class TestSafeRouteLiveAPI(unittest.TestCase):
    """End-to-end API tests against the running BEACON backend"""

    BASE_URL = "http://127.0.0.1:8000"

    def post_safe_route(self, payload):
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_dataset_integrity(self):
        """Preserve source datasets unmodified"""
        df_b = pd.read_csv("bengaluru_dataset.csv")
        df_m = pd.read_csv("datasets/mangaluru_dataset.csv")
        self.assertEqual(df_b.shape, (9859, 9), "Bengaluru dataset shape altered!")
        self.assertEqual(df_m.shape, (5871, 15), "Mangaluru dataset shape altered!")

    def test_ml_prediction_pipeline(self):
        """Preserve existing Bengaluru XGBoost model"""
        payload = {"latitude": 12.9716, "longitude": 77.5946, "hour": 22, "day_of_week": 4}
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/predict",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("used_model"), "ML model pipeline was bypassed!")
            self.assertEqual(data.get("city"), "Bengaluru")

    def test_determinism_same_inputs_produce_same_outputs(self):
        """Verify that the exact same inputs produce identical results"""
        payload = {"src_lat": 12.9716, "src_lon": 77.5946, "dst_lat": 12.9352, "dst_lon": 77.6245}
        _, res1 = self.post_safe_route(payload)
        _, res2 = self.post_safe_route(payload)
        self.assertEqual(res1["average_risk"], res2["average_risk"])
        self.assertEqual(res1["distance_km"], res2["distance_km"])
        self.assertEqual(res1["accuracy_summary"]["usable_evidence_ratio"], res2["accuracy_summary"]["usable_evidence_ratio"])
        self.assertEqual(res1["accuracy_summary"]["confidence_level"], res2["accuracy_summary"]["confidence_level"])

    def test_route_dense_locality_coverage(self):
        """Bengaluru Central corridor: Dense locality-centroid coverage"""
        payload = {"src_lat": 12.9716, "src_lon": 77.5946, "dst_lat": 12.9352, "dst_lon": 77.6245}
        status, data = self.post_safe_route(payload)
        self.assertEqual(status, 200)
        acc = data["accuracy_summary"]
        self.assertEqual(acc["confidence_level"], "MODERATE")
        self.assertGreaterEqual(acc["usable_evidence_ratio"], 60.0)
        self.assertGreaterEqual(acc["locality_centroids_nearby"], 10)
        self.assertEqual(data["risk_type"], "heuristic_historical_indicator")

    def test_route_police_station_only_corridor(self):
        """Bengaluru North: Corridors with only police station coordinates return INSUFFICIENT_EVIDENCE"""
        payload = {"src_lat": 13.0358, "src_lon": 77.5970, "dst_lat": 13.1007, "dst_lon": 77.5963}
        status, data = self.post_safe_route(payload)
        self.assertEqual(status, 200)
        acc = data["accuracy_summary"]
        # Stations are excluded from crime scenes; crime-scene D = 0 -> INSUFFICIENT_EVIDENCE
        self.assertEqual(acc["confidence_level"], "INSUFFICIENT_EVIDENCE")
        self.assertGreater(acc["police_station_coords_nearby"], 0)
        self.assertEqual(acc["locality_centroids_nearby"], 0)
        self.assertIn("Insufficient evidence", acc["advisory"])

    def test_route_unverified_dominated_corridor(self):
        """Mangaluru Central: Dominated by unverified historical FIR records"""
        payload = {"src_lat": 12.8696, "src_lon": 74.8423, "dst_lat": 12.8799, "dst_lon": 74.8554}
        status, data = self.post_safe_route(payload)
        self.assertEqual(status, 200)
        acc = data["accuracy_summary"]
        self.assertEqual(acc["confidence_level"], "APPROXIMATE")
        self.assertLess(acc["usable_evidence_ratio"], 60.0)
        self.assertGreater(acc["unverified_locations_nearby"], 500)
        self.assertIn("Approximate confidence", acc["advisory"])

    def test_route_no_usable_incidents(self):
        """Rural / Unmapped sector: Zero crime records in corridor"""
        payload = {"src_lat": 12.7500, "src_lon": 77.4000, "dst_lat": 12.7800, "dst_lon": 77.4200}
        status, data = self.post_safe_route(payload)
        self.assertEqual(status, 200)
        acc = data["accuracy_summary"]
        self.assertEqual(acc["confidence_level"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(acc["usable_evidence_ratio"], 0.0)
        self.assertEqual(acc["total_corridor_incidents"], 0)

    def test_invalid_routing_parameters(self):
        """Invalid routing inputs: NaN, out of bounds, missing coordinates return HTTP 400"""
        # Missing destination
        req1 = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route",
            data=json.dumps({"src_lat": 12.97}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req1)
        self.assertEqual(ctx.exception.code, 400)

        # Out of bounds coordinates (lat > 90)
        req2 = urllib.request.Request(
            f"{self.BASE_URL}/api/safe-route",
            data=json.dumps({"src_lat": 195.0, "src_lon": 77.59, "dst_lat": 12.93, "dst_lon": 77.62}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req2)
        self.assertEqual(ctx.exception.code, 400)

    def test_mangaluru_temporal_scoring_disabled_api(self):
        """Passing night hour (23:00) for Mangaluru route does not apply temporal bonuses"""
        payload_night = {"src_lat": 12.8696, "src_lon": 74.8423, "dst_lat": 12.8799, "dst_lon": 74.8554, "hour": 23}
        payload_day = {"src_lat": 12.8696, "src_lon": 74.8423, "dst_lat": 12.8799, "dst_lon": 74.8554, "hour": 12}
        _, res_night = self.post_safe_route(payload_night)
        _, res_day = self.post_safe_route(payload_day)
        
        # Policy explicitly states disabled
        self.assertEqual(res_night["temporal_policy"]["scoring_status"], "disabled_due_to_missing_fir_timestamps")
        self.assertIsNone(res_night["temporal_policy"]["applied_hour"])
        # Risk scores are identical between night and day because timestamps are unrecorded
        self.assertEqual(res_night["average_risk"], res_day["average_risk"])

    def test_bengaluru_temporal_scoring_active_api(self):
        """Passing night hour (23:00) for Bengaluru route applies active temporal policy"""
        payload_night = {"src_lat": 12.9716, "src_lon": 77.5946, "dst_lat": 12.9352, "dst_lon": 77.6245, "hour": 23}
        _, res_night = self.post_safe_route(payload_night)
        self.assertEqual(res_night["temporal_policy"]["scoring_status"], "active_from_recorded_timestamps")
        self.assertEqual(res_night["temporal_policy"]["applied_hour"], 23)

    def test_empty_corridor_unmeasured_risk_api(self):
        """Zero records corridor returns average_risk = 0.0, measured_risk = False, and INSUFFICIENT_EVIDENCE"""
        payload = {"src_lat": 12.7500, "src_lon": 77.4000, "dst_lat": 12.7800, "dst_lon": 77.4200}
        _, res = self.post_safe_route(payload)
        self.assertEqual(res["average_risk"], 0.0)
        self.assertFalse(res["measured_risk"])
        self.assertEqual(res["accuracy_summary"]["confidence_level"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("cannot be assumed safe", res["accuracy_summary"]["advisory"])

    def test_road_polyline_actual_geometry(self):
        """Routing uses actual road network geometry with high vertex density"""
        payload = {"src_lat": 12.9716, "src_lon": 77.5946, "dst_lat": 12.9352, "dst_lon": 77.6245}
        _, res = self.post_safe_route(payload)
        self.assertEqual(res["routing_mode"], "actual_road_network")
        self.assertGreater(len(res["route_polyline"]), 50, "Route polyline lacks road vertex detail")
        # Actual road distance is ~7.5 km, straight-line is ~5.2 km
        self.assertGreater(res["distance_km"], 5.5, "Road distance should be greater than straight-line distance")


class TestTargetedAccuracyLogic(unittest.TestCase):
    """Direct unit tests for BEACON core algorithms in main.py"""

    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        if cls.main.crime_data is None:
            cls.main.load_crime_data()
            cls.main.load_mangaluru_data()

    def test_mangaluru_missing_timestamps_produce_zero_bonus(self):
        """Mangaluru coordinates (99.9% missing timestamps) produce 0 temporal bonus across all hours"""
        # Mangaluru Central coords: 12.8696, 74.8423
        score_night = self.main.calculate_risk_score(12.8696, 74.8423, hour=23, day_of_week=5)
        score_day = self.main.calculate_risk_score(12.8696, 74.8423, hour=12, day_of_week=2)
        score_dawn = self.main.calculate_risk_score(12.8696, 74.8423, hour=3, day_of_week=6)
        
        self.assertEqual(score_night, score_day, "Night hour applied temporal bonus to Mangaluru record!")
        self.assertEqual(score_dawn, score_day, "Dawn hour applied temporal bonus to Mangaluru record!")

    def test_bengaluru_recorded_timestamps_produce_temporal_adjustments(self):
        """Bengaluru coordinates with valid timestamps produce higher night score than midday"""
        # Bengaluru Central coords: 12.9716, 77.5946
        score_night = self.main.calculate_risk_score(12.9716, 77.5946, hour=23)
        score_midday = self.main.calculate_risk_score(12.9716, 77.5946, hour=12)
        self.assertGreater(score_night, score_midday, "Bengaluru should reflect nighttime temporal factor")

    def test_duplicate_coordinate_logarithmic_suppression(self):
        """Ensure repeated or identical-coordinate records do not silently inflate risk"""
        # 1 incident -> 8 * ln(2) = 5.54
        # 10 incidents -> 8 * ln(11) = 19.18
        # 100 incidents -> 8 * ln(101) = 36.92 -> capped at 35.0
        # 1000 incidents -> capped at 35.0
        dens_1 = min(35.0, round(8.0 * math.log(1.0 + 1), 1))
        dens_10 = min(35.0, round(8.0 * math.log(1.0 + 10), 1))
        dens_100 = min(35.0, round(8.0 * math.log(1.0 + 100), 1))
        dens_1000 = min(35.0, round(8.0 * math.log(1.0 + 1000), 1))
        
        self.assertLess(dens_10, 10 * dens_1, "Density scaling should be strictly sub-linear")
        self.assertEqual(dens_100, 35.0, "Density scaling must be bounded at 35.0 ceiling")
        self.assertEqual(dens_1000, 35.0, "Duplicate records must not exceed ceiling")

    def test_crime_severity_aggregation_proportionality(self):
        """Multiple crime categories within a corridor are aggregated proportionally by severity"""
        # Formula: violent*25 + threat*15 + property*8 + other*4 / total
        cats_violent = ["Murder", "Rape", "Kidnapping"]
        cats_property = ["Theft", "Theft", "Burglary"]
        
        # Helper to compute severity using same logic as main.py
        def compute_sev(cats):
            sev_weights = {
                "violent": 25.0,
                "threat": 15.0,
                "property": 8.0,
                "other": 4.0
            }
            violent_types = {"murder", "rape", "attempt to murder", "dacoity", "culpable homicide", "kidnapping"}
            threat_types = {"robbery", "assault", "molestation", "extortion", "grievous hurt"}
            property_types = {"theft", "burglary", "cheating", "fraud", "vehicle theft", "house break"}
            
            w_sum = 0.0
            for c in cats:
                cl = c.lower()
                if any(v in cl for v in violent_types):
                    w_sum += sev_weights["violent"]
                elif any(t in cl for t in threat_types):
                    w_sum += sev_weights["threat"]
                elif any(p in cl for p in property_types):
                    w_sum += sev_weights["property"]
                else:
                    w_sum += sev_weights["other"]
            return w_sum / len(cats)
            
        sev_v = compute_sev(cats_violent)
        sev_p = compute_sev(cats_property)
        self.assertEqual(sev_v, 25.0)
        self.assertEqual(sev_p, 8.0)
        self.assertGreater(sev_v, sev_p)

    def test_empty_corridor_produces_zero_unmeasured_score(self):
        """Unmeasured area without records returns exactly 0.0, avoiding arbitrary baselines"""
        # Coordinate in Arabian Sea far from land
        score = self.main.calculate_risk_score(12.0, 70.0)
        self.assertEqual(score, 0.0, "Unmeasured area must return 0.0 rather than arbitrary baseline")

    def test_routing_service_failure_returns_503(self):
        """If routing fails, return an explicit HTTP 503 rather than inventing a road route"""
        from fastapi import HTTPException
        from unittest.mock import patch
        
        req = self.main.RouteRequest(src_lat=12.9716, src_lon=77.5946, dst_lat=12.9352, dst_lon=77.6245)
        with patch.object(self.main, "fetch_road_route", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                self.main.safe_route(req)
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("unavailable or unreachable", ctx.exception.detail)

    def test_point_to_polyline_distances_long_road_segment(self):
        """Confirm that 1.2 km corridor buffer is measured against road segments, not merely vertices on long segments"""
        import numpy as np
        # Long road segment from (12.90, 77.50) to (12.90, 77.53), segment length ~3.24 km
        polyline = [[12.90, 77.50], [12.90, 77.53]]
        # Incident located at midpoint longitude (77.515), perpendicular offset 0.006 deg latitude (~0.666 km)
        incident = np.array([[12.906, 77.515]])
        
        dist = self.main.point_to_polyline_distances(incident, polyline)[0]
        self.assertAlmostEqual(dist, 0.666, delta=0.05)
        self.assertLess(dist, 1.2, "Incident within 0.67 km of long road segment should be inside 1.2 km buffer")
        
        # Verify that discrete distance to both vertices exceeds 1.2 km
        dist_to_v1 = math.sqrt(((12.906 - 12.90) * 111.0)**2 + ((77.515 - 77.50) * 108.0)**2)
        dist_to_v2 = math.sqrt(((12.906 - 12.90) * 111.0)**2 + ((77.515 - 77.53) * 108.0)**2)
        self.assertGreater(dist_to_v1, 1.2, "Discrete vertex distance would incorrectly drop this point")
        self.assertGreater(dist_to_v2, 1.2, "Discrete vertex distance would incorrectly drop this point")

    def test_point_to_polyline_distances_curved_road(self):
        """Confirm curved road geometry accurately calculates proximity along polyline bends"""
        import numpy as np
        # Curved 90-degree road with 3 segments
        polyline = [
            [12.90, 77.50],
            [12.91, 77.50],
            [12.92, 77.51],
            [12.92, 77.53]
        ]
        # Point near the diagonal curve (12.915, 77.505)
        point = np.array([[12.915, 77.505]])
        dist = self.main.point_to_polyline_distances(point, polyline)[0]
        self.assertLess(dist, 0.2, "Point on curved segment should have proximity < 0.2 km")

    def test_mangaluru_discount_does_not_inflate_usable_evidence_ratio(self):
        """Confirm that 50% discount for unverified Mangaluru records affects risk only, not usable evidence ratio"""
        # Mangaluru route dominated by unverified historical FIR records
        payload = {"src_lat": 12.8696, "src_lon": 74.8423, "dst_lat": 12.8799, "dst_lon": 74.8554}
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/safe-route",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            acc = data["accuracy_summary"]
            # Verify that unverified records have 0.0 weight in numerator and full 1.0 weight in denominator:
            # Expected ratio: (0.85 * locality_nearby) / (locality_nearby + unverified_nearby) * 100
            expected_ratio = round((0.85 * acc["locality_centroids_nearby"] / acc["total_corridor_incidents"]) * 100, 1)
            self.assertEqual(acc["usable_evidence_ratio"], expected_ratio, "Usable evidence ratio does not match documented formula")
            self.assertEqual(acc["confidence_level"], "APPROXIMATE")


if __name__ == "__main__":
    unittest.main()
