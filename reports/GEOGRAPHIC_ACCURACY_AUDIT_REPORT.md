# BEACON — Geospatial Accuracy Audit Report
**AI Public Safety Intelligence Platform** | *Rigorous Geospatial Integrity & Risk Scoring Audit*

> **Data Integrity Notice**: The original crime datasets (`bengaluru_dataset.csv` — 9,859 records, and `datasets/mangaluru_dataset.csv` — 5,871 records) have **not** been modified, altered, or overwritten. No coordinates have been fabricated, invented, or shifted. All findings reflect the ground-truth characteristics of the source records.

---

## 1. Executive Summary

A comprehensive geospatial accuracy audit was conducted across all **15,730 records** (9,859 Bengaluru + 5,871 Mangaluru) in the BEACON platform. Every coordinate was evaluated against official geographic references (Karnataka State Police jurisdiction boundaries, BBMP ward boundaries, Survey of India gazetteers, and OpenStreetMap landmark geometries).

### Key Audit Findings & Standards:
1. **Strict Evidence Threshold for `INCIDENT_LOCATION_VERIFIED` (0 records, 0.00%)**:
   - Matching a coordinate to a public landmark within 350 metres does **not** prove that the crime occurred at that landmark. Coordinates returned for landmark queries (such as "Victoria Hospital", "Nimhans", or "Central Railway Station") are facility/landmark reference centroids.
   - Neither historical dataset possesses independent, authoritative forensic GPS dispatch logs or doorstep surveyor evidence.
   - To maintain scientific and legal integrity, **0 records** are falsely certified as verified doorstep incident scenes.
2. **Locality Centroids Predominate (`LOCALITY_MATCH_ONLY` — 8,474 records, 53.87%)**:
   - 7,945 Bengaluru records and 529 Mangaluru records represent verified sub-locality, neighborhood, or facility centroids within expected police station jurisdictions.
3. **Unsurveyed Historical FIR Address Descriptions (`LOCATION_UNVERIFIED` — 5,272 records, 33.52%)**:
   - 5,269 Mangaluru records originate from historical FIR narrative descriptions (e.g., *"Near Padmashri hotel"*, *"An empty field next to the road"*, *"Near Reyan Hall Permude"*) where the source dataset itself explicitly flags `Location_Status: LOCATION UNVERIFIED`.
   - 3 Bengaluru records have missing or null place strings.
4. **Police Station Compound Coordinates (`POLICE_STATION_COORDINATE` — 1,074 records, 6.83%)**:
   - 1,001 Bengaluru records (including 1,000 records across 10 stations with `Place == Police Station`) and 73 Mangaluru records cluster at police station headquarters.
   - **Crucial Rule**: These administrative headquarters coordinates are **excluded** from crime-scene incident risk calculations along route corridors to prevent treating police stations as danger zones.
5. **Out-of-Region Geocoder Failures (`LOCATION_MISMATCH` — 910 records, 5.79%)**:
   - 910 Bengaluru records placed crimes into neighboring states (Andhra Pradesh, Tamil Nadu) or distant districts (Mysuru, Kolar) due to automated geocoding matches on homonymous street or temple names.
   - **Crucial Rule**: These 910 coordinates are **strictly excluded** from all location-based risk models, heatmaps, and route corridor calculations, while remaining completely preserved in the raw source file.

---

## 2. Quantitative Audit Breakdown

| Validation Status | Bengaluru (9,859) | Mangaluru (5,871) | Combined Total (15,730) | Percentage | Classification Standard |
|---|:---:|:---:|:---:|:---:|---|
| **`LOCALITY_MATCH_ONLY`** | 7,945 (80.59%) | 529 (9.01%) | **8,474** | **53.87%** | Sub-locality / area centroid approximation within valid jurisdiction |
| **`LOCATION_UNVERIFIED`** | 3 (0.03%) | 5,269 (89.75%) | **5,272** | **33.52%** | Unsurveyed historical FIR text or missing place description |
| **`POLICE_STATION_COORDINATE`** | 1,001 (10.15%) | 73 (1.24%) | **1,074** | **6.83%** | Station building / jurisdiction reference centroid |
| **`LOCATION_MISMATCH`** | 910 (9.23%) | 0 (0.00%) | **910** | **5.79%** | Out-of-region coordinate geocoding failure |
| **`INCIDENT_LOCATION_VERIFIED`** | 0 (0.00%) | 0 (0.00%) | **0** | **0.00%** | Requires authoritative forensic GPS survey; not present in source datasets |
| **Total Records Audited** | **9,859** | **5,871** | **15,730** | **100.0%** | **Full Registry Coverage (100% of both datasets)** |

---

## 3. Analysis by Validation Category

### A. LOCALITY_MATCH_ONLY (8,474 records — 53.87%)
- **Definition**: The recorded place falls within the expected police station jurisdiction, but the coordinates represent an area or neighborhood centroid rather than surveyed crime-scene coordinates.
- **Evidence**:
  - In Bengaluru, 87 records in KS Layout share `(12.910936, 77.564670)`, 45 records in Sarakki share `(12.892813, 77.566630)`, and 42 records in Jayanagar share `(12.929845, 77.583100)`.
  - In Mangaluru, 529 records match recognized urban locality centroids (Kadri, Bejai, Surathkal, Hampankatta, Pandeshwar, Bunder, Kavoor).
  - Landmark coordinates (e.g., Victoria Hospital, Bowring Hospital, NIMHANS) where multiple unrelated crimes share the facility centroid are correctly grouped under locality/facility match because proximity to a public landmark does not establish independent doorstep verification.

### B. LOCATION_UNVERIFIED (5,272 records — 33.52%)
- **Definition**: Records lacking authoritative coordinates or containing informal street descriptions that cannot be verified without independent field survey.
- **Evidence**:
  - In Mangaluru, 5,269 records contain descriptive FIR text (e.g. *"Near Padmashri hotel"*, *"In front of Kankanady market"*). The dataset author explicitly flagged them as `Location_Status: LOCATION UNVERIFIED`.
  - In Bengaluru, 3 records have completely missing or null place strings (`BLR-0245`, `BLR-0246`, `BLR-7741`).

### C. POLICE_STATION_COORDINATE (1,074 records — 6.83%)
- **Definition**: Coordinates corresponding to the police station compound or circle rather than the crime occurrence scene.
- **Evidence**:
  - In Bengaluru, **1,000 records** across 10 police stations (Anekal, Attibele, Chandapura, Electronic City, Hebbal, Indiranagar, Koramangala, Rajajinagar, Whitefield, Yelahanka) have `Place` recorded identically to the station name.
  - In Mangaluru, **73 records** cluster at police station headquarters (e.g. Kavoor PS centroid `12.922229, 74.859430` with 27 incidents, Mangalore Women PS `12.864530, 74.858052` with 9 incidents).
- **Safe Route Handling**: These records are strictly excluded from crime-scene transit threat in Safe Route calculations.

### D. LOCATION_MISMATCH (910 records — 5.79%)
- **Definition**: Coordinates located outside the expected metropolitan district boundaries due to automated geocoding failures.
- **Evidence**:
  - 910 Bengaluru records placed into Andhra Pradesh (Chittoor, Kadapa: lon 78.3°–79.2° E, lat 13.2°–14.5° N) or distant districts (Mysuru, Tumakuru, Kolar) because common Kannada place names matched rural entries in neighboring states.
  - **Safe Route Handling**: Excluded from location caches, heatmaps, and corridor interpolation.

### E. INCIDENT_LOCATION_VERIFIED (0 records — 0.00%)
- **Definition**: Only assigned when supported by authoritative evidence (such as verified forensic GPS dispatch logs or surveyed ground truth).
- **Finding**: Neither historical police dataset contains surveyor-grade doorstep GPS coordinates. Treating automated geocoded outputs or landmark boundary checks as proof of doorstep incident scenes is scientifically invalid. Zero records are falsely certified.

---

## 4. Safe Route Risk Scoring & Confidence Engine

The Safe Route engine (`/api/safe-route`) has been upgraded to enforce strict geospatial integrity:

1. **Police Station Filtering**:
   - Police station coordinates (`POLICE_STATION_COORDINATE`) are excluded from crime-scene density. Roads passing by a police station are not artificially penalized as high-crime danger zones.
2. **Mismatch Exclusion**:
   - The 910 out-of-region geocoder mismatches are excluded from spatial location caches and corridor threat calculations.
3. **Evidence-Based Confidence Calculation**:
   - Confidence does not depend on the presence of a single point. It is calculated dynamically based on the proportion and quality of usable location evidence:
     $$\text{Usable Evidence Ratio} = \frac{\text{Verified} \times 1.0 + \text{Locality Centroids} \times 0.85}{\max(1, \text{Total Corridor Incident Scenes})}$$
   - **HIGH CONFIDENCE**: Requires verified incident points with $\ge 70\%$ usable ratio and dense corridor coverage.
   - **MODERATE CONFIDENCE**: Corridors supported by validated sub-locality centroids ($\ge 60\%$ usable ratio) with minor doorstep variance expected.
   - **APPROXIMATE CONFIDENCE**: Corridors traversing sectors with unverified historical FIR records ($< 40\%$ usable ratio) or sparse data coverage.