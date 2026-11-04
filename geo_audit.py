"""
BEACON — Geographic Accuracy Audit Engine
Audits the geographic accuracy of the BEACON Bengaluru and Mangaluru crime datasets.
Does NOT modify original datasets or invent replacement coordinates.

Validation Statuses:
- INCIDENT_LOCATION_VERIFIED
- LOCALITY_MATCH_ONLY
- POLICE_STATION_COORDINATE
- LOCATION_UNVERIFIED
- LOCATION_MISMATCH
"""

import os
import json
import math
import re
import pandas as pd
import numpy as np

# Bounding boxes for regional validation
BLR_BOUNDS = {
    "lat_min": 12.60,
    "lat_max": 13.40,
    "lon_min": 77.25,
    "lon_max": 77.95
}

MLR_BOUNDS = {
    "lat_min": 12.65,
    "lat_max": 13.25,
    "lon_min": 74.70,
    "lon_max": 75.25
}

# Bengaluru police stations with 100% station-centroid coordinates (no incident street recorded)
BLR_PS_CENTROID_STATIONS = {
    'Anekal', 'Attibele', 'Chandapura', 'Electronic City', 'Hebbal',
    'Indiranagar', 'Koramangala', 'Rajajinagar', 'Whitefield', 'Yelahanka'
}

# Known Police Station reference coordinates (approximate centroids of station buildings)
BLR_PS_COORDS = {
    'Anekal': (12.7092, 77.6967),
    'Attibele': (12.7772, 77.7661),
    'Banashankari': (12.9298, 77.6006),
    'Basavanagudi': (12.9614, 77.6292),
    'C K Achuktu': (12.9643, 77.6043),
    'Chandapura': (12.8095, 77.7064),
    'Electronic City': (12.8394, 77.6765),
    'Girinagar': (12.9067, 77.5779),
    'Hanumantha Nagar': (13.0978, 77.7594),
    'Hebbal': (13.0350, 77.5966),
    'Indiranagar': (12.9789, 77.6403),
    'J P Nagar': (12.9906, 77.6993),
    'Jayanagar': (12.9252, 77.5566),
    'K G Nagar': (12.8137, 77.5325),
    'K S Layout': (12.9061, 77.5590),
    'Konanakunte': (12.9742, 77.6436),
    'Koramangala': (12.9353, 77.6226),
    'Puttenahalli': (13.0101, 77.6346),
    'Rajajinagar': (12.9915, 77.5522),
    'Shankarapua': (12.9550, 77.5846),
    'Siddapura': (12.9243, 77.5738),
    'Subramanyapura': (12.9919, 77.6418),
    'Thalaghtappura': (12.9056, 77.5903),
    'V V Puram': (12.8795, 77.5219),
    'Whitefield': (12.9688, 77.7497),
    'Yelahanka': (13.1000, 77.5963)
}

MLR_PS_COORDS = {
    'Bajpe PS': (12.9525, 74.8679),
    'Barke PS': (12.8860, 74.8244),
    'Kankanady Town PS': (12.8698, 74.8726),
    'Kavoor PS': (12.9222, 74.8594),
    'Konaje PS': (12.8021, 74.9012),
    'Mangalore East PS': (12.8843, 74.8705),
    'Mangalore North PS': (12.8640, 74.8430),
    'Mangalore South PS': (12.8550, 74.8390),
    'Mangalore Women PS': (12.8645, 74.8581),
    'Moodabidre PS': (13.0710, 74.9970),
    'Mulki PS': (13.0648, 74.7980),
    'Panambur PS': (12.9467, 74.8080),
    'Surathkal PS': (13.0075, 74.7960),
    'Ullal PS': (12.8083, 74.8550),
    'Urva PS': (12.8900, 74.8300)
}

# Authoritative landmarks with known GPS ground truth (< 150m radius)
AUTHORITATIVE_LANDMARKS_BLR = [
    {"name": "NIMHANS Hospital Campus", "keywords": ["nimhans"], "lat": 12.9431, "lon": 77.5960, "radius_km": 0.50},
    {"name": "Victoria Hospital Campus", "keywords": ["victoria hospital"], "lat": 12.9634, "lon": 77.5739, "radius_km": 0.40},
    {"name": "Bowring & Lady Curzon Hospital", "keywords": ["bowring hospital", "bowring & lady", "bowring"], "lat": 12.9822, "lon": 77.6042, "radius_km": 0.40},
    {"name": "Jayadeva Institute of Cardiology", "keywords": ["jayadeva hospital", "jayadeva institute", "jayadeva"], "lat": 12.9185, "lon": 77.5985, "radius_km": 0.40},
    {"name": "Banashankari Temple & Complex", "keywords": ["banashankari temple", "banashankari ammanavara"], "lat": 12.9254, "lon": 77.5778, "radius_km": 0.40},
    {"name": "National College Basavanagudi", "keywords": ["national college basavanagudi", "national college metro", "national college"], "lat": 12.9452, "lon": 77.5746, "radius_km": 0.35},
    {"name": "Kempegowda Bus Station (Majestic)", "keywords": ["kempegowda bus station", "majestic bus stand", "majestic"], "lat": 12.9778, "lon": 77.5714, "radius_km": 0.50},
    {"name": "Kidwai Memorial Institute of Oncology", "keywords": ["kidwai hospital", "kidwai"], "lat": 12.9377, "lon": 77.5925, "radius_km": 0.45},
    {"name": "Lalbagh Botanical Garden", "keywords": ["lalbagh botanical", "lalbagh garden", "lalbhagh"], "lat": 12.9507, "lon": 77.5848, "radius_km": 0.60}
]

AUTHORITATIVE_LANDMARKS_MLR = [
    {"name": "Mangalore International Airport", "keywords": ["immigration counter", "international airport", "airport terminal", "inter national airport"], "lat": 12.9613, "lon": 74.8899, "radius_km": 0.70},
    {"name": "Father Muller Medical College Hospital", "keywords": ["father muller"], "lat": 12.8596, "lon": 74.8540, "radius_km": 0.45},
    {"name": "KMC Hospital Mangaluru", "keywords": ["kmc hospital", "kmc"], "lat": 12.8715, "lon": 74.8450, "radius_km": 0.45},
    {"name": "New Mangalore Port / Panambur Port Gate", "keywords": ["panambur port", "new mangalore port"], "lat": 12.9344, "lon": 74.8150, "radius_km": 0.60},
    {"name": "Mangaluru Central Railway Station", "keywords": ["central railway station", "mangalore central"], "lat": 12.8640, "lon": 74.8430, "radius_km": 0.45},
    {"name": "Mangalore Junction Railway Station", "keywords": ["mangalore junction", "kankanady railway"], "lat": 12.8703, "lon": 74.8761, "radius_km": 0.45},
    {"name": "Mangaluru District Prison", "keywords": ["district prison", "distirict prison"], "lat": 12.8817, "lon": 74.8340, "radius_km": 0.45},
    {"name": "Wenlock District Hospital", "keywords": ["wenlock hospital", "wenlock"], "lat": 12.8660, "lon": 74.8420, "radius_km": 0.45},
    {"name": "Lady Goschen Hospital", "keywords": ["lady goschen"], "lat": 12.8648, "lon": 74.8415, "radius_km": 0.45},
    {"name": "Mangalore University Campus", "keywords": ["mangalore university", "konaje campus"], "lat": 12.8160, "lon": 74.9290, "radius_km": 0.60},
    {"name": "Panambur Beach Complex", "keywords": ["panambur beach"], "lat": 12.9467, "lon": 74.8028, "radius_km": 0.60},
    {"name": "Tannirbhavi Beach Complex", "keywords": ["tannirbhavi beach", "tannirbavi beach", "tannirbhavi"], "lat": 12.8944, "lon": 74.8153, "radius_km": 0.60},
    {"name": "Mahaveera College Campus", "keywords": ["mahaveera college"], "lat": 13.0760, "lon": 74.9920, "radius_km": 0.45},
    {"name": "Central Market Mangaluru", "keywords": ["central market"], "lat": 12.8685, "lon": 74.8410, "radius_km": 0.45},
    {"name": "Kadri Park Complex", "keywords": ["kadri park"], "lat": 12.8850, "lon": 74.8590, "radius_km": 0.45},
    {"name": "St. Aloysius College Campus", "keywords": ["aloysius college", "aloysius"], "lat": 12.8730, "lon": 74.8460, "radius_km": 0.45},
    {"name": "Kudroli Gokarnanatheshwara Temple", "keywords": ["kudroli temple", "gokarnanatha", "kudroli mandi"], "lat": 12.8750, "lon": 74.8330, "radius_km": 0.45},
    {"name": "Nanthoor Junction Hub", "keywords": ["nanthoor junction", "nanthur junction", "nanthoor", "nanthur"], "lat": 12.8780, "lon": 74.8630, "radius_km": 0.45},
    {"name": "Lalbagh Junction Hub", "keywords": ["lalbagh junction", "lalbagh circle", "lalbagh"], "lat": 12.8782, "lon": 74.8398, "radius_km": 0.45},
    {"name": "Sulthan Battery Landmark", "keywords": ["sulthan battery", "sulthan bhattery", "sultan battery"], "lat": 12.8930, "lon": 74.8250, "radius_km": 0.45},
    {"name": "Bavutagudda (Light House Hill)", "keywords": ["bavutagudda", "light house hill"], "lat": 12.8700, "lon": 74.8430, "radius_km": 0.45},
    {"name": "Indiana Hospital & Heart Institute", "keywords": ["indiana hospital"], "lat": 12.8660, "lon": 74.8720, "radius_km": 0.45}
]

# Clean normalization helper for place strings
def normalize_place_name(text):
    if not text or pd.isna(text):
        return ""
    t = str(text).lower()
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    return ' '.join(t.split())

# Recognized Mangaluru Localities, Towns, Villages, and Wards
MANGALURU_LOCALITIES = [
    'kadri', 'hampankatta', 'hampanakatte', 'bunder', 'pandeshwar', 'surathkal',
    'panambur', 'ullal', 'kavoor', 'urva', 'barke', 'mulki', 'moodabidre', 'moodbidre',
    'moodbidri', 'bajpe', 'konaje', 'bejai', 'bijai', 'falnir', 'kankanady', 'lalbagh',
    'mannagudda', 'derebail', 'maryhill', 'bondel', 'kottara', 'bikarnakatte',
    'tannirbhavi', 'tannirbavi', 'kodialbail', 'kodialbayal', 'ashoknagar', 'chilimbi',
    'jeppu', 'boloor', 'attavar', 'attavara', 'valencia', 'morgansgate', 'bolar',
    'mangaladevi', 'car street', 'kudroli', 'alake', 'hoige bazar', 'bajal', 'padil',
    'naguri', 'pumpwell', 'kulashekar', 'kulshekar', 'vamanjoor', 'gurunagar',
    'gurupura', 'kaikamba', 'ganjimatta', 'ganjimutt', 'kinnigoli', 'kateel',
    'deralakatte', 'deralakattte', 'natekal', 'thokkottu', 'tokkottu', 'kotekar',
    'someshwar', 'someshwara', 'talapady', 'mijar', 'beluvai', 'alangar', 'kinnipadavu',
    'adyapady', 'permude', 'kenjar', 'kenjaru', 'baikampady', 'jokatte', 'kuppepadavu',
    'marnamikatte', 'nanthoor', 'mallikatte', 'nandigudda', 'nandigudde', 'gorigudda',
    'yeyyadi', 'shaktinagar', 'pachhanady', 'kuloor', 'kulur', 'mukka', 'sasihithlu',
    'haleangadi', 'hejamadi', 'karnad', 'bappanadu', 'adyar', 'balmatta', 'bavutagudda',
    'kunjathbail', 'kulai', 'hosabettu', 'chitrapura', 'idya', 'katipalla',
    'krishnapura', 'meenakaliya', 'bengre', 'kasaba', 'alape', 'kannur', 'jappinamogaru',
    'permannur', 'munnur', 'kinya', 'belma', 'harekala', 'pavoor', 'mudipu', 'kurnad',
    'pajeer', 'swaraj maidan', 'angaragudde', 'bolpugudde', 'lingappayyakadu',
    'janatha colony', 'porkodi', 'mura', 'ekkur', 'kodikal', 'valachil', 'maroli',
    'kamblapadavu', 'kenchanakere', 'adyar katte', 'adyar padavu'
]

# Recognized Bengaluru Localities, Towns, Villages, Wards, and Layouts
BENGALURU_LOCALITIES = [
    'hebbal', 'rajajinagar', 'indiranagar', 'yelahanka', 'anekal', 'attibele',
    'chandapura', 'whitefield', 'electronic city', 'koramangala', 'basavanagudi',
    'basvanagudi', 'jayanagar', 'jayanagara', 'jp nagar', 'jp nagara', 'j p nagar',
    'j p nagara', 'banashankari', 'btm layout', 'hsr layout', 'marathahalli',
    'bellandur', 'malleshwaram', 'malleswaram', 'frazer town', 'ulsoor', 'halasuru',
    'domlur', 'rt nagar', 'kengeri', 'vijayanagar', 'peenya', 'girinagar', 'siddapura',
    'ks layout', 'k s layout', 'subramanyapura', 'thalaghattapura', 'thalaghtappura',
    'konanakunte', 'konannakute', 'konanukunte', 'v v puram', 'vv puram', 'srinagar',
    'srinivasanagar', 'chikkalasandra', 'chikalasandra', 'uttarahalli', 'arehalli',
    'shankarapura', 'shankarapua', 'kg nagar', 'k g nagar', 'hanumantha nagar',
    'c k achukattu', 'ck achukattu', 'puttenahalli', 'madiwala', 'madivala',
    'kalyan nagar', 'kammanahalli', 'hennur', 'banaswadi', 'kasturi nagar',
    'mahadevapura', 'hoodi', 'kr puram', 'k r puram', 'varthur', 'sarjapur',
    'bannerghatta', 'bommanahalli', 'begur', 'hulimavu', 'gottigere',
    'kumaraswamy layout', 'kumarswami layout', 'basaveshwaranagar', 'mahalakshmi layout',
    'nandhini layout', 'yeshwanthpur', 'mathikere', 'sanjaynagar', 'sahakarnagar',
    'vidyaranyapura', 'jalahalli', 'kempapura', 'nagavara', 'thanisandra', 'hbr layout',
    'hrbr layout', 'cox town', 'cooke town', 'richards town', 'richmond town',
    'shanthi nagar', 'austin town', 'neelasandra', 'ejipura', 'adugodi', 'wilson garden',
    'chamrajpet', 'chamarajpet', 'chickpet', 'cottonpet', 'majestic', 'gandhi nagar',
    'seshadripuram', 'vasanth nagar', 'shivajinagar', 'commercial street', 'mg road',
    'brigade road', 'cantonment', 'gandhi bazar', 'padmanabha nagara',
    'padmanabhanagar', 'sarakki', 'shakambari nagar', 'vasanthpura', 'vasanthapura',
    'chunchaghta', 'chunchagatta', 'chuchagta', 'ittumadu', 'doddakalasandra',
    'doddakasandra', 'vaddarapally', 'kottanuru dinne', 'bireshwaranagara',
    'bireshwra nagar', 'beereshwaranagara', 'ags layout', 'kr layout', 'isro layout',
    'gowdanapalya', 'gowdanaplya', 'anjanapura', 'lakkasandra', 'sajjan rao circle',
    'kanaka nagar', 'dayananda nagar', 'daynanda nagar', 'arekempanahalli', 'chandra nagar'
]

def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate Great Circle distance between two points in km"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def audit_record_blr(idx, row, coord_frequency):
    """Audit single Bengaluru record"""
    rec_id = f"BLR-{idx+1:04d}"
    lat = float(row.get('Latitude', 0.0))
    lon = float(row.get('Longitude', 0.0))
    place = str(row.get('Place', '')).strip() if pd.notna(row.get('Place')) else ''
    ps = str(row.get('Police Station', '')).strip() if pd.notna(row.get('Police Station')) else ''
    crime_type = str(row.get('Type', 'Recorded Incident')).strip()
    date_str = str(row.get('Date', '')).strip()

    rep_count = coord_frequency.get((lat, lon), 1)

    # 1. Missing Place Check
    if not place or place.lower() in ['nan', 'none', 'null', 'unknown']:
        return {
            "record_id": rec_id,
            "city": "Bengaluru",
            "police_station": ps,
            "place": place or "Not recorded",
            "latitude": lat,
            "longitude": lon,
            "validation_status": "LOCATION_UNVERIFIED",
            "coordinate_origin": "unverified_historical_record",
            "evidence": "Place field is completely missing or null in the source criminal registry.",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # 2. Out of Region (Mismatch) Check
    if (lat < BLR_BOUNDS["lat_min"] or lat > BLR_BOUNDS["lat_max"] or
        lon < BLR_BOUNDS["lon_min"] or lon > BLR_BOUNDS["lon_max"]):
        
        # Determine mismatch destination region
        if lon > 78.0:
            dest_info = f"Andhra Pradesh / Eastern border ({lon:.2f}° E)"
        elif lon < 77.25:
            dest_info = f"Mysuru / Mandya / Western region ({lon:.2f}° E)"
        elif lat > 13.40:
            dest_info = f"Chikkaballapur / Northern region ({lat:.2f}° N)"
        else:
            dest_info = f"Kanakapura / Southern rural region ({lat:.2f}° N)"

        return {
            "record_id": rec_id,
            "city": "Bengaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "LOCATION_MISMATCH",
            "coordinate_origin": "out_of_region_geocoder_mismatch",
            "evidence": f"Coordinate falls outside Bengaluru metropolitan boundaries ({dest_info}). Automated geocoding matched locality name to a distant district.",
            "is_outlier": True,
            "repetition_count": rep_count
        }

    # 3. Police Station Coordinate Check
    if ps in BLR_PS_CENTROID_STATIONS and (place == ps or place == ''):
        return {
            "record_id": rec_id,
            "city": "Bengaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "POLICE_STATION_COORDINATE",
            "coordinate_origin": "police_station_reference",
            "evidence": f"Place is listed identical to police station name '{ps}'. Coordinate represents the police station jurisdiction centroid rather than the actual incident scene.",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # Check if place explicitly references police station premises
    if any(k in place.lower() for k in ['police station', 'ps premises', 'infront of ps', 'near ps']):
        return {
            "record_id": rec_id,
            "city": "Bengaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "POLICE_STATION_COORDINATE",
            "coordinate_origin": "police_station_reference",
            "evidence": f"Incident location description explicitly references police station premises ('{place}').",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # 4. Landmark Proximity Check (Locality / Facility Centroid)
    for lm in AUTHORITATIVE_LANDMARKS_BLR:
        if any(kw in place.lower() for kw in lm["keywords"]):
            dist = haversine_km(lat, lon, lm["lat"], lm["lon"])
            if dist <= lm["radius_km"]:
                return {
                    "record_id": rec_id,
                    "city": "Bengaluru",
                    "police_station": ps,
                    "place": place,
                    "latitude": lat,
                    "longitude": lon,
                    "validation_status": "LOCALITY_MATCH_ONLY",
                    "coordinate_origin": "locality_centroid",
                    "evidence": f"Coordinate corresponds to public facility centroid for '{lm['name']}' (delta {dist*1000:.0f}m). Matching a coordinate to a public landmark does not prove the incident occurred at that landmark without independent authoritative forensic GPS verification.",
                    "is_outlier": False,
                    "repetition_count": rep_count
                }

    # 5. Locality Centroid Check (Requires genuine locality/ward/layout match)
    p_norm = normalize_place_name(place)
    p_lower = place.lower()
    matched_blr_loc = None
    for loc in BENGALURU_LOCALITIES:
        if loc in p_lower or loc in p_norm:
            matched_blr_loc = loc
            break

    if matched_blr_loc:
        rep_text = f" Coordinate shared across {rep_count} distinct recorded incidents." if rep_count >= 5 else ""
        return {
            "record_id": rec_id,
            "city": "Bengaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "LOCALITY_MATCH_ONLY",
            "coordinate_origin": "locality_centroid",
            "evidence": f"Coordinate corresponds to recognized Bengaluru locality centroid for '{matched_blr_loc.title()}'.{rep_text} Represents sub-locality centroid rather than surveyed doorstep GPS.",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # 6. Location Unverified (Preserve genuine uncertainty for informal/unverified FIR descriptions)
    return {
        "record_id": rec_id,
        "city": "Bengaluru",
        "police_station": ps,
        "place": place,
        "latitude": lat,
        "longitude": lon,
        "validation_status": "LOCATION_UNVERIFIED",
        "coordinate_origin": "unverified_historical_record",
        "evidence": f"Historical FIR entry with informal or unverified street description ('{place}'). No authoritative surveyor GPS or ground-truth verification consulted.",
        "is_outlier": False,
        "repetition_count": rep_count
    }

def audit_record_mlr(idx, row, coord_frequency):
    """Audit single Mangaluru record"""
    rec_id = f"MLR-{idx+1:04d}"
    lat = float(row.get('Latitude', 0.0))
    lon = float(row.get('Longitude', 0.0))
    place = str(row.get('Place', '')).strip() if pd.notna(row.get('Place')) else ''
    ps = str(row.get('Police Station', '')).strip() if pd.notna(row.get('Police Station')) else ''
    crime_type = str(row.get('Crime_Category', row.get('Type', 'Recorded Incident'))).strip()

    rep_count = coord_frequency.get((lat, lon), 1)

    # 1. Missing Place Check
    if not place or place.lower() in ['nan', 'none', 'null', 'unknown']:
        return {
            "record_id": rec_id,
            "city": "Mangaluru",
            "police_station": ps,
            "place": "Not recorded",
            "latitude": lat,
            "longitude": lon,
            "validation_status": "LOCATION_UNVERIFIED",
            "coordinate_origin": "unverified_historical_record",
            "evidence": "Place field is completely missing in Mangaluru source record (flagged as PLACE_MISSING).",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # 2. Out of Region (Mismatch) Check
    if (lat < MLR_BOUNDS["lat_min"] or lat > MLR_BOUNDS["lat_max"] or
        lon < MLR_BOUNDS["lon_min"] or lon > MLR_BOUNDS["lon_max"]):
        return {
            "record_id": rec_id,
            "city": "Mangaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "LOCATION_MISMATCH",
            "coordinate_origin": "out_of_region_geocoder_mismatch",
            "evidence": "Coordinate falls outside Dakshina Kannada / Mangaluru coastal limits.",
            "is_outlier": True,
            "repetition_count": rep_count
        }

    # 3. Police Station Coordinate Check
    if any(k in place.lower() for k in ['police station', 'ps limits', 'ps premises', 'ps jurisdiction']):
        return {
            "record_id": rec_id,
            "city": "Mangaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "POLICE_STATION_COORDINATE",
            "coordinate_origin": "police_station_reference",
            "evidence": f"Place explicitly references police station limits ('{place}'). Coordinate reflects jurisdiction reference point.",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # Check proximity to known Mangaluru station coordinates
    for ps_name, ps_pt in MLR_PS_COORDS.items():
        if haversine_km(lat, lon, ps_pt[0], ps_pt[1]) < 0.08 and rep_count >= 5:
            return {
                "record_id": rec_id,
                "city": "Mangaluru",
                "police_station": ps,
                "place": place,
                "latitude": lat,
                "longitude": lon,
                "validation_status": "POLICE_STATION_COORDINATE",
                "coordinate_origin": "police_station_reference",
                "evidence": f"Repeated coordinate ({rep_count} incidents) matches {ps_name} police station compound (< 80m). Represents station reference coordinate.",
                "is_outlier": False,
                "repetition_count": rep_count
            }

    # 4. Landmark Proximity Check (Locality / Facility Centroid)
    for lm in AUTHORITATIVE_LANDMARKS_MLR:
        if any(kw in place.lower() for kw in lm["keywords"]):
            dist = haversine_km(lat, lon, lm["lat"], lm["lon"])
            if dist <= lm["radius_km"]:
                return {
                    "record_id": rec_id,
                    "city": "Mangaluru",
                    "police_station": ps,
                    "place": place,
                    "latitude": lat,
                    "longitude": lon,
                    "validation_status": "LOCALITY_MATCH_ONLY",
                    "coordinate_origin": "locality_centroid",
                    "evidence": f"Coordinate corresponds to public facility centroid for '{lm['name']}' (delta {dist*1000:.0f}m). Matching a coordinate to a public landmark does not prove the incident occurred at that landmark without independent authoritative forensic GPS verification.",
                    "is_outlier": False,
                    "repetition_count": rep_count
                }

    # 5. Locality Match Check (Requires genuine locality/town/village/ward match)
    p_norm = normalize_place_name(place)
    p_lower = place.lower()
    matched_mlr_loc = None
    for loc in MANGALURU_LOCALITIES:
        if loc in p_lower or loc in p_norm:
            matched_mlr_loc = loc
            break

    if matched_mlr_loc:
        return {
            "record_id": rec_id,
            "city": "Mangaluru",
            "police_station": ps,
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "validation_status": "LOCALITY_MATCH_ONLY",
            "coordinate_origin": "locality_centroid",
            "evidence": f"Coordinate corresponds to recognized Mangaluru locality centroid for '{matched_mlr_loc.title()}'. Specific doorstep location unverified in historical FIR.",
            "is_outlier": False,
            "repetition_count": rep_count
        }

    # 6. Location Unverified (Preserve genuine uncertainty for informal/unverified FIR descriptions)
    return {
        "record_id": rec_id,
        "city": "Mangaluru",
        "police_station": ps,
        "place": place,
        "latitude": lat,
        "longitude": lon,
        "validation_status": "LOCATION_UNVERIFIED",
        "coordinate_origin": "unverified_historical_record",
        "evidence": f"Historical FIR entry with informal street description ('{place}'). No authoritative surveyor GPS or ground-truth verification consulted.",
        "is_outlier": False,
        "repetition_count": rep_count
    }

def run_geographic_audit():
    """Run full geographic accuracy audit across all datasets"""
    print("=" * 70)
    print("STARTING BEACON GEOGRAPHIC ACCURACY AUDIT")
    print("=" * 70)

    # 1. Load Bengaluru
    blr_path = "bengaluru_dataset.csv"
    if not os.path.exists(blr_path):
        raise FileNotFoundError(f"Bengaluru dataset not found at {blr_path}")
    blr_df = pd.read_csv(blr_path)
    print(f"Loaded Bengaluru dataset: {len(blr_df)} records (preserved as-is)")

    # 2. Load Mangaluru
    mlr_path = "datasets/mangaluru_dataset.csv"
    if not os.path.exists(mlr_path):
        raise FileNotFoundError(f"Mangaluru dataset not found at {mlr_path}")
    mlr_df = pd.read_csv(mlr_path)
    print(f"Loaded Mangaluru dataset: {len(mlr_df)} records (preserved as-is)")

    # Compute coordinate frequency maps
    blr_coords_freq = blr_df.groupby(['Latitude', 'Longitude']).size().to_dict()
    mlr_coords_freq = mlr_df.groupby(['Latitude', 'Longitude']).size().to_dict()

    audit_records = []

    # Audit Bengaluru
    print("Auditing Bengaluru records...")
    for idx, row in blr_df.iterrows():
        res = audit_record_blr(idx, row, blr_coords_freq)
        audit_records.append(res)

    # Audit Mangaluru
    print("Auditing Mangaluru records...")
    for idx, row in mlr_df.iterrows():
        res = audit_record_mlr(idx, row, mlr_coords_freq)
        audit_records.append(res)

    total_audited = len(audit_records)
    print(f"Total audited records: {total_audited}")

    # Summary statistics
    audit_df = pd.DataFrame(audit_records)
    status_summary = audit_df.groupby(['city', 'validation_status']).size().unstack(fill_value=0)
    total_by_status = audit_df['validation_status'].value_counts().to_dict()

    print("\n" + "=" * 50)
    print("AUDIT RESULTS SUMMARY")
    print("=" * 50)
    print(status_summary)
    print("-" * 50)
    for st, count in total_by_status.items():
        pct = (count / total_audited) * 100
        print(f"{st:30s}: {count:6d} ({pct:5.2f}%)")
    print("=" * 50)

    # Export machine-readable JSON
    os.makedirs("reports", exist_ok=True)
    report_json_path = "reports/geographic_accuracy_audit_report.json"
    
    summary_data = {
        "metadata": {
            "title": "BEACON Geographic Accuracy Audit",
            "total_records_checked": total_audited,
            "bengaluru_records": len(blr_df),
            "mangaluru_records": len(mlr_df),
            "status_totals": total_by_status,
            "bengaluru_breakdown": audit_df[audit_df['city'] == 'Bengaluru']['validation_status'].value_counts().to_dict(),
            "mangaluru_breakdown": audit_df[audit_df['city'] == 'Mangaluru']['validation_status'].value_counts().to_dict(),
        },
        "records": audit_records
    }

    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"Exported JSON report to {report_json_path}")

    # Export lookup map for fast backend API queries
    lookup_map = {}
    for r in audit_records:
        rec_id = r["record_id"]
        entry = {
            "validation_status": r["validation_status"],
            "coordinate_origin": r["coordinate_origin"],
            "evidence": r["evidence"]
        }
        lookup_map[rec_id] = entry
        if rec_id.startswith("BLR-"):
            lookup_map[rec_id.replace("BLR-", "BLR-CRIME-")] = entry
        elif rec_id.startswith("MLR-"):
            lookup_map[rec_id.replace("MLR-", "MLR-CRIME-")] = entry
    with open("reports/audit_lookup_map.json", "w", encoding="utf-8") as f:
        json.dump(lookup_map, f)
    print("Exported audit lookup map to reports/audit_lookup_map.json")

    return summary_data

if __name__ == "__main__":
    run_geographic_audit()
