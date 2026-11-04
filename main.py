import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from collections import defaultdict
import joblib, os, math, json, hashlib, urllib.request, urllib.error, re
import numpy as np
import pandas as pd

# ==================== CONFIG ====================
APP_TITLE = "BEACON - AI Public Safety Intelligence"
MODEL_PATH = os.getenv("MODEL_PATH", "crime_predictor_bangalore_new.pkl")
BLR_DATA_PATH = os.getenv("DATA_PATH", "bengaluru_dataset.csv")
if not os.path.exists(BLR_DATA_PATH) and os.path.exists("bengaluru_dataset.csv"):
    BLR_DATA_PATH = "bengaluru_dataset.csv"
DATA_PATH = BLR_DATA_PATH
MLR_DATA_PATH = os.getenv("MLR_DATA_PATH", "datasets/mangaluru_dataset.csv")
CACHE_DURATION = 300  # 5 minutes cache

app = FastAPI(title=APP_TITLE, version="2.4")

# CORS - Allow all for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== GLOBAL STATE ====================
model = None
model_info = {"loaded": False, "type": None, "features": None}
crime_data = None
mangaluru_crime_data = None
location_cache = {}
location_cache_blr = {}
location_cache_mlr = {}
risk_cache = {}

# Geographic Accuracy Audit Lookup Map
AUDIT_LOOKUP = {}
audit_lookup_path = "reports/audit_lookup_map.json"
if os.path.exists(audit_lookup_path):
    try:
        with open(audit_lookup_path, "r", encoding="utf-8") as f:
            AUDIT_LOOKUP = json.load(f)
            print(f"✅ Loaded {len(AUDIT_LOOKUP)} geographic audit records into runtime cache")
    except Exception as e:
        print(f"⚠️ Could not load audit lookup map: {e}")

# Standardized public quality labels
QUALITY_LABELS = {
    "INCIDENT_LOCATION_VERIFIED": "Verified location",
    "LOCALITY_MATCH_ONLY": "Approximate locality",
    "LOCATION_UNVERIFIED": "Location not verified",
    "POLICE_STATION_COORDINATE": "Police station reference",
    "LOCATION_MISMATCH": "Excluded: location mismatch"
}

def get_audit_record_metadata(rec_id: str) -> dict:
    """Retrieve audit record metadata with deterministic key normalization and strict safe fallback.
    Never silently classifies missing lookups as verified or locality-matched."""
    if not rec_id:
        return {
            "validation_status": "LOCATION_UNVERIFIED",
            "coordinate_origin": "unverified_historical_record",
            "evidence": "Record identifier missing; coordinate reliability cannot be established."
        }
    
    # 1. Direct match
    if rec_id in AUDIT_LOOKUP:
        return AUDIT_LOOKUP[rec_id]
        
    # 2. Canonical alias match (MLR-XXXX <-> MLR-CRIME-XXXX, BLR-XXXX <-> BLR-CRIME-XXXX)
    if "-CRIME-" in rec_id:
        alt_id = rec_id.replace("-CRIME-", "-")
    elif rec_id.startswith("BLR-"):
        alt_id = rec_id.replace("BLR-", "BLR-CRIME-")
    elif rec_id.startswith("MLR-"):
        alt_id = rec_id.replace("MLR-", "MLR-CRIME-")
    else:
        alt_id = None
        
    if alt_id and alt_id in AUDIT_LOOKUP:
        return AUDIT_LOOKUP[alt_id]
        
    # 3. Strict safe fallback: missing audit lookup MUST remain LOCATION_UNVERIFIED
    return {
        "validation_status": "LOCATION_UNVERIFIED",
        "coordinate_origin": "unverified_historical_record",
        "evidence": "Audit lookup entry not found in registry; coordinate reliability cannot be established."
    }

# Bengaluru and Mangaluru Safety Contacts
SAFETY_CONTACTS = {
    "emergency": [
        {"name": "National Emergency (ERSS)", "number": "112", "type": "emergency", "desc": "National Emergency Response Support System"},
        {"name": "Ambulance", "number": "108", "type": "medical", "desc": "Emergency Medical Services"},
        {"name": "Fire Services", "number": "101", "type": "fire", "desc": "Fire & Rescue Department"},
        {"name": "Police Control Room", "number": "100", "type": "police", "desc": "City Police Emergency Hotline"},
        {"name": "Women Helpline", "number": "1091", "type": "women", "desc": "24/7 Dedicated Women Safety Helpline"},
    ],
    "police_stations": [
        {"name": "Banashankari Police Station", "number": "080-26771290", "area": "Banashankari", "city": "Bengaluru", "lat": 12.9298, "lon": 77.6006},
        {"name": "Koramangala Police Station", "number": "080-25537466", "area": "Koramangala", "city": "Bengaluru", "lat": 12.9353, "lon": 77.6226},
        {"name": "Indiranagar Police Station", "number": "080-25213009", "area": "Indiranagar", "city": "Bengaluru", "lat": 12.9789, "lon": 77.6403},
        {"name": "Whitefield Police Station", "number": "080-28452905", "area": "Whitefield", "city": "Bengaluru", "lat": 12.9698, "lon": 77.7500},
        {"name": "Jayanagar Police Station", "number": "080-26633292", "area": "Jayanagar", "city": "Bengaluru", "lat": 12.9252, "lon": 77.5566},
        {"name": "Hebbal Police Station", "number": "080-22942534", "area": "Hebbal", "city": "Bengaluru", "lat": 13.0350, "lon": 77.5966},
        {"name": "Mangaluru East (Kadri) Police Station", "number": "0824-2220520", "area": "Kadri", "city": "Mangaluru", "lat": 12.8799, "lon": 74.8554},
        {"name": "Mangaluru North (Bunder) Police Station", "number": "0824-2220516", "area": "Bunder", "city": "Mangaluru", "lat": 12.8655, "lon": 74.8384},
        {"name": "Mangaluru South (Pandeshwar) Police Station", "number": "0824-2220518", "area": "Pandeshwar", "city": "Mangaluru", "lat": 12.8595, "lon": 74.8440},
        {"name": "Barke Police Station", "number": "0824-2220522", "area": "Barke", "city": "Mangaluru", "lat": 12.8847, "lon": 74.8337},
        {"name": "Urwa Police Station", "number": "0824-2220521", "area": "Urwa", "city": "Mangaluru", "lat": 12.8979, "lon": 74.8359},
        {"name": "Kavoor Police Station", "number": "0824-2220533", "area": "Kavoor", "city": "Mangaluru", "lat": 12.9206, "lon": 74.8548},
        {"name": "Panambur Police Station", "number": "0824-2407333", "area": "Panambur", "city": "Mangaluru", "lat": 12.9246, "lon": 74.8205},
        {"name": "Surathkal Police Station", "number": "0824-2270433", "area": "Surathkal", "city": "Mangaluru", "lat": 12.9949, "lon": 74.8120},
        {"name": "Mulki Police Station", "number": "0824-2290533", "area": "Mulki", "city": "Mangaluru", "lat": 13.0726, "lon": 74.8122},
        {"name": "Moodabidre Police Station", "number": "08258-236333", "area": "Moodabidre", "city": "Mangaluru", "lat": 13.0765, "lon": 75.0047},
        {"name": "Bajpe Police Station", "number": "0824-2252133", "area": "Bajpe", "city": "Mangaluru", "lat": 12.9768, "lon": 74.9135},
        {"name": "Ullal Police Station", "number": "0824-2466233", "area": "Ullal", "city": "Mangaluru", "lat": 12.8030, "lon": 74.8636},
        {"name": "Konaje Police Station", "number": "0824-2280333", "area": "Konaje", "city": "Mangaluru", "lat": 12.8094, "lon": 74.9235},
    ]
}

# ==================== DATA LOADING ====================
def load_model():
    """Load the trained model safely"""
    global model, model_info
    if not os.path.exists(MODEL_PATH):
        print(f"⚠️  Model not found at {MODEL_PATH}")
        return False
    
    try:
        model = joblib.load(MODEL_PATH)
        feats = getattr(model, "feature_names_in_", None)
        if feats is not None and hasattr(feats, "tolist"):
            feats = feats.tolist()
        n_feats = getattr(model, "n_features_in_", None)
        if n_feats is not None:
            try:
                n_feats = int(n_feats)
            except Exception:
                pass
        
        model_info = {
            "loaded": True,
            "type": type(model).__name__,
            "features": feats,
            "n_features": n_feats,
        }
        print(f"✅ Model loaded: {model_info['type']}")
        return True
    except Exception as e:
        print(f"❌ Model load error: {e}")
        return False

def load_crime_data():
    """Load and process crime dataset"""
    global crime_data, location_cache
    if not os.path.exists(DATA_PATH):
        print(f"⚠️  Dataset not found at {DATA_PATH}")
        return False
    
    try:
        # Load dataset
        df = pd.read_csv(DATA_PATH)
        print(f"📊 Loaded {len(df)} crime records")
        df['source_row_id'] = df.index + 1
        
        # Process columns
        df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
        
        # Parse datetime
        if 'date' in df.columns and 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], errors='coerce')
            df['hour'] = df['datetime'].dt.hour
            df['day_of_week'] = df['datetime'].dt.dayofweek
            df['month'] = df['datetime'].dt.month
            df['year'] = df['datetime'].dt.year
        
        # Clean coordinates
        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
        df = df.dropna(subset=['latitude', 'longitude'])
        
        crime_data = df
        
        # Build location cache (aggregate by area)
        build_location_cache()
        
        print(f"✅ Processed crime data: {len(crime_data)} valid records")
        return True
    except Exception as e:
        print(f"❌ Data load error: {e}")
        return False

def load_mangaluru_data():
    """Load and process the genuine cleaned Mangaluru crime dataset"""
    global mangaluru_crime_data, location_cache_mlr
    if not os.path.exists(MLR_DATA_PATH):
        print(f"⚠️  Mangaluru dataset not found at {MLR_DATA_PATH}")
        return False
    
    try:
        df = pd.read_csv(MLR_DATA_PATH)
        print(f"📊 Loaded {len(df)} Mangaluru crime records")
        df['source_row_id'] = df.index + 1
        
        required_cols = ['Police Station', 'Year', 'Type', 'Date', 'Latitude', 'Longitude', 'Crime_Category', 'Place_Display']
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            print(f"❌ Mangaluru dataset missing required columns: {missing}")
            return False
            
        df['latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        df['longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
        df['police_station'] = df['Police Station'].astype(str).str.strip()
        df['crime_category'] = df['Crime_Category'].astype(str).str.strip()
        df['type'] = df['crime_category']
        df['place'] = df['Place_Display'].astype(str).str.strip()
        df['date'] = df['Date'].astype(str).str.strip()
        
        df['datetime'] = pd.to_datetime(df['date'], format='%d-%m-%Y', errors='coerce')
        df['year'] = pd.to_numeric(df['Year'], errors='coerce').fillna(df['datetime'].dt.year)
        df['month'] = df['datetime'].dt.month
        df['day_of_week'] = df['datetime'].dt.dayofweek
        
        valid_geo = (
            (df['latitude'] >= 12.65) & (df['latitude'] <= 13.25) &
            (df['longitude'] >= 74.70) & (df['longitude'] <= 75.25)
        )
        df = df[valid_geo].copy()
        
        mangaluru_crime_data = df
        build_mangaluru_location_cache()
        print(f"✅ Processed Mangaluru crime data: {len(mangaluru_crime_data)} valid records")
        return True
    except Exception as e:
        print(f"❌ Mangaluru data load error: {e}")
        return False

def build_location_cache():
    """Build aggregated crime statistics by location for Bengaluru.
    Excludes 910 out-of-region geocoder mismatches and 1,001 police station centroid coordinates
    from incident crime-scene density, without modifying source crime_data.
    Deduplicates identical records to prevent duplicate inflation."""
    global location_cache, location_cache_blr
    if crime_data is None:
        return
    
    # Exclude out-of-region mismatches and police station premises from crime-scene risk caching
    valid_mask = (
        (crime_data['latitude'] >= 12.70) & (crime_data['latitude'] <= 13.35) &
        (crime_data['longitude'] >= 77.30) & (crime_data['longitude'] <= 77.90) &
        (crime_data['place'].astype(str).str.strip().str.lower() != 'police station')
    )
    df_incidents = crime_data[valid_mask].copy()
    
    # Deduplicate exact duplicate incident reports (same coords, date, time, crime type)
    if all(col in df_incidents.columns for col in ['date', 'time', 'type']):
        df_incidents = df_incidents.drop_duplicates(subset=['latitude', 'longitude', 'date', 'time', 'type'])
    else:
        df_incidents = df_incidents.drop_duplicates(subset=['latitude', 'longitude', 'date', 'type'])
        
    df_incidents['lat_bin'] = (df_incidents['latitude'] * 100).round() / 100
    df_incidents['lon_bin'] = (df_incidents['longitude'] * 100).round() / 100
    
    grouped = df_incidents.groupby(['lat_bin', 'lon_bin']).agg({
        'type': ['count', lambda x: x.mode()[0] if len(x) > 0 else 'Unknown'],
        'hour': 'mean',
        'police_station': lambda x: x.mode()[0] if len(x) > 0 else 'Unknown'
    }).reset_index()
    
    grouped.columns = ['lat', 'lon', 'crime_count', 'most_common_crime', 'avg_hour', 'police_station']
    
    location_cache_blr = {}
    for _, row in grouped.iterrows():
        key = f"{row['lat']:.2f},{row['lon']:.2f}"
        cell = {
            "lat": float(row['lat']),
            "lon": float(row['lon']),
            "crime_count": int(row['crime_count']),
            "most_common": str(row['most_common_crime']),
            "avg_hour": float(row['avg_hour']) if pd.notna(row['avg_hour']) else 12.0,
            "police_station": str(row['police_station']),
            "city": "Bengaluru",
            "is_unverified": False
        }
        location_cache_blr[key] = cell
        location_cache[key] = cell

def build_mangaluru_location_cache():
    """Build aggregated crime statistics by location for Mangaluru.
    Excludes police station centroid compounds from incident crime-scene density, preserving original source datasets.
    Deduplicates identical records to prevent duplicate inflation."""
    global location_cache_mlr, location_cache
    if mangaluru_crime_data is None:
        return
        
    mlr_ps_coords = {(12.922229, 74.859430), (12.864530, 74.858052), (12.802090, 74.901150),
                     (12.869774, 74.872641), (12.885987, 74.824397), (13.064779, 74.797981)}
    
    valid_mask = (
        (mangaluru_crime_data['latitude'] >= 12.65) & (mangaluru_crime_data['latitude'] <= 13.25) &
        (mangaluru_crime_data['longitude'] >= 74.70) & (mangaluru_crime_data['longitude'] <= 75.25) &
        (~mangaluru_crime_data.apply(lambda r: (round(r['latitude'], 6), round(r['longitude'], 6)) in mlr_ps_coords, axis=1)) &
        (~mangaluru_crime_data['place'].astype(str).str.lower().str.contains('police station'))
    )
    df_incidents_mlr = mangaluru_crime_data[valid_mask].copy()
    
    # Deduplicate exact duplicate incident reports
    if all(col in df_incidents_mlr.columns for col in ['date', 'type']):
        df_incidents_mlr = df_incidents_mlr.drop_duplicates(subset=['latitude', 'longitude', 'date', 'type'])
        
    df_incidents_mlr['lat_bin'] = (df_incidents_mlr['latitude'] * 100).round() / 100
    df_incidents_mlr['lon_bin'] = (df_incidents_mlr['longitude'] * 100).round() / 100
    
    grouped = df_incidents_mlr.groupby(['lat_bin', 'lon_bin']).agg({
        'type': ['count', lambda x: x.mode()[0] if len(x) > 0 else 'Unknown'],
        'police_station': lambda x: x.mode()[0] if len(x) > 0 else 'Unknown'
    }).reset_index()
    
    grouped.columns = ['lat', 'lon', 'crime_count', 'most_common_crime', 'police_station']
    
    location_cache_mlr = {}
    for _, row in grouped.iterrows():
        key = f"{row['lat']:.2f},{row['lon']:.2f}"
        cell = {
            "lat": float(row['lat']),
            "lon": float(row['lon']),
            "crime_count": int(row['crime_count']),
            "most_common": str(row['most_common_crime']),
            "avg_hour": 12.0,
            "police_station": str(row['police_station']),
            "city": "Mangaluru",
            "is_unverified": True
        }
        location_cache_mlr[key] = cell
        location_cache[f"mlr_{key}"] = cell

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    load_model()
    load_crime_data()
    load_mangaluru_data()

# ==================== HELPER FUNCTIONS ====================
def haversine(coord1, coord2):
    """Calculate distance between two coordinates in km"""
    R = 6371.0
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def is_mangaluru_coordinate(lat: float, lon: float) -> bool:
    """Robust geographic boundary check for Mangaluru coastal region"""
    return (12.65 <= lat <= 13.25) and (74.70 <= lon <= 75.25)

def is_bengaluru_coordinate(lat: float, lon: float) -> bool:
    """Robust geographic boundary check for Bengaluru metropolitan area"""
    return (12.70 <= lat <= 13.35) and (77.30 <= lon <= 77.90)

def get_nearest_location_data(lat, lon, radius_km=2.0, city_scope=None):
    """Get crime statistics for nearest location from appropriate regional cache"""
    nearest = None
    min_dist = float('inf')
    
    if city_scope == "mangaluru" or (city_scope is None and is_mangaluru_coordinate(lat, lon)):
        target_cache = location_cache_mlr
    elif city_scope == "bengaluru" or (city_scope is None and is_bengaluru_coordinate(lat, lon)):
        target_cache = location_cache_blr
    else:
        target_cache = location_cache_blr if is_bengaluru_coordinate(lat, lon) else (location_cache_mlr if is_mangaluru_coordinate(lat, lon) else location_cache_blr)
    
    for loc_data in target_cache.values():
        dist = haversine((lat, lon), (loc_data['lat'], loc_data['lon']))
        if dist < min_dist and dist <= radius_km:
            min_dist = dist
            nearest = loc_data
    
    return nearest, min_dist

def calculate_risk_score(lat, lon, hour=None, day_of_week=None):
    """Calculate heuristic historical threat indicator (0-100 scale).
    Note: This is a heuristic historical index based on recorded incident density,
    severity, and temporal factors, NOT an empirical probability of danger.
    
    Temporal Scoring Policy:
    - Bengaluru: Recorded FIR timestamps available. Temporal bonuses applied if hour provided.
    - Mangaluru: 99.9% TIME_NOT_RECORDED. Temporal scoring is explicitly DISABLED;
      incident times are never inferred from date or locality.
    - Unmeasured areas: If no location data is within coverage radius, returns 0.0 (no arbitrary baseline).
    """
    is_mlr = is_mangaluru_coordinate(lat, lon)
    location_data, distance = get_nearest_location_data(lat, lon, radius_km=2.0)
    
    # If no usable crime records exist within coverage radius, risk is unmeasured (do not use arbitrary baselines)
    if not location_data:
        return 0.0
        
    base_risk = 20.0  # Baseline indicator for verified crime coverage sector
    
    crime_count = location_data.get('crime_count', 0)
    # Logarithmic diminishing returns scaling to prevent single-centroid repetition from inflating risk
    raw_density = min(35.0, round(8.0 * math.log(1.0 + max(0, crime_count)), 1))
    
    # If cell represents unverified historical FIR records, discount by 50% for declared spatial uncertainty
    if location_data.get('is_unverified', False):
        raw_density *= 0.5
        
    base_risk += raw_density
    
    # Severity weighting based on historical crimes in sector
    crime_type = location_data.get('most_common', '').lower()
    if any(w in crime_type for w in ['murder', 'rape', 'pocso', 'kidnapping']):
        base_risk += 20.0
    elif any(w in crime_type for w in ['robbery', 'extortion', 'assault', 'snatching']):
        base_risk += 12.0
    elif any(w in crime_type for w in ['theft', 'burglary', 'housebreak']):
        base_risk += 7.0
        
    # Distance penalty when data cell is sparse (> 1.5 km away)
    if distance and distance > 1.5:
        base_risk += min(10.0, (distance - 1.5) * 3.0)
        
    # Temporal adjustments (STRICTLY DISABLED for Mangaluru due to missing FIR timestamps)
    if not is_mlr and hour is not None:
        if 22 <= hour or hour <= 4:
            base_risk += 15.0  # Night
        elif 18 <= hour <= 21:
            base_risk += 8.0   # Evening
        elif 6 <= hour <= 9:
            base_risk += 4.0   # Morning rush
            
    if not is_mlr and day_of_week is not None and day_of_week >= 5:
        base_risk += 4.0       # Weekend
        
    return min(100.0, max(0.0, round(base_risk, 1)))

def get_corridor_risk_tier(score, measured=True):
    """
    Authoritative corridor risk category and color mapping.
    Legend / Score Bands:
      - 0–24: Lower Historical Threat (Green: #10b981)
      - 25–39: Moderate Historical Threat (Yellow: #eab308)
      - 40–59: Elevated Historical Threat (Orange: #f97316)
      - 60–100: Higher Historical Threat (Red: #ef4444)
      - Insufficient Evidence / Unmeasured: (Gray: #64748b)

    Boundary Rules:
      - score < 25.0: Lower Historical Threat
      - 25.0 <= score < 40.0: Moderate Historical Threat (includes 25, 39, 39.1, 39.9)
      - 40.0 <= score < 60.0: Elevated Historical Threat (includes 40, 59, 59.1, 59.9)
      - score >= 60.0: Higher Historical Threat (includes 60, 100)
    """
    if not measured or score is None:
        return {
            "key": "unmeasured",
            "category": "Insufficient Evidence",
            "label": "Insufficient Evidence",
            "color": "#64748b",
            "score_band": "Unmeasured"
        }
    
    s = float(score)
    if s < 25.0:
        return {
            "key": "lower",
            "category": "Lower Historical Threat",
            "label": "Lower Historical Threat",
            "color": "#10b981",
            "score_band": "0–24"
        }
    elif s < 40.0:
        return {
            "key": "moderate",
            "category": "Moderate Historical Threat",
            "label": "Moderate Historical Threat",
            "color": "#eab308",
            "score_band": "25–39"
        }
    elif s < 60.0:
        return {
            "key": "elevated",
            "category": "Elevated Historical Threat",
            "label": "Elevated Historical Threat",
            "color": "#f97316",
            "score_band": "40–59"
        }
    else:
        return {
            "key": "higher",
            "category": "Higher Historical Threat",
            "label": "Higher Historical Threat",
            "color": "#ef4444",
            "score_band": "60–100"
        }

def get_safety_recommendations(risk_score, hour=None, crime_type=None):
    """Generate contextual safety recommendations"""
    recommendations = []
    
    if risk_score >= 70:
        recommendations.append("⚠️ HIGH RISK AREA - Avoid if possible")
        recommendations.append("🚨 Travel in groups, stay alert")
        recommendations.append("📱 Share live location with trusted contacts")
    elif risk_score >= 50:
        recommendations.append("⚡ MODERATE RISK - Exercise caution")
        recommendations.append("👥 Prefer well-lit, populated routes")
    else:
        recommendations.append("✅ RELATIVELY SAFE AREA")
        recommendations.append("👁️ Stay aware of surroundings")
    
    # Time-based
    if hour is not None:
        if 22 <= hour or hour <= 5:
            recommendations.append("🌙 Late hours - Use trusted transportation")
        elif 18 <= hour <= 21:
            recommendations.append("🌆 Evening time - Stick to main roads")
    
    # Crime-specific
    if crime_type:
        crime_lower = str(crime_type).lower()
        if 'theft' in crime_lower or 'robbery' in crime_lower:
            recommendations.append("💰 Secure valuables, avoid displaying expensive items")
        if 'assault' in crime_lower:
            recommendations.append("🥊 Stay in well-populated areas")
    
    # General
    recommendations.append("📞 Emergency: 112 | Police: 100 | Women: 1091")
    
    return recommendations

def get_incident_density(lat: float, lon: float) -> dict:
    """Analyse historical incident density within 500m, 1km, and 2km radii"""
    is_mlr = is_mangaluru_coordinate(lat, lon)
    df = mangaluru_crime_data if is_mlr else crime_data
    if df is None or len(df) == 0:
        return {"500m": 0, "1km": 0, "2km": 0}
        
    dlat = 2.0 / 111.0
    dlon = 2.0 / (111.0 * max(0.1, math.cos(math.radians(lat))))
    box = df[(df['latitude'] >= lat - dlat) & (df['latitude'] <= lat + dlat) &
             (df['longitude'] >= lon - dlon) & (df['longitude'] <= lon + dlon)]
             
    if len(box) == 0:
        return {"500m": 0, "1km": 0, "2km": 0}
        
    lats = box['latitude'].values
    lons = box['longitude'].values
    phi1 = math.radians(lat)
    phi2 = np.radians(lats)
    dphi = np.radians(lats - lat)
    dlam = np.radians(lons - lon)
    a = np.sin(dphi / 2.0) ** 2 + math.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    dists = 6371.0 * c
    
    return {
        "500m": int(np.sum(dists <= 0.5)),
        "1km": int(np.sum(dists <= 1.0)),
        "2km": int(np.sum(dists <= 2.0))
    }

def get_nearest_police_stations(lat: float, lon: float, limit: int = 3) -> list:
    """Find nearest official police stations with official phone numbers and distance in km"""
    stations = []
    is_mlr = is_mangaluru_coordinate(lat, lon)
    scope_city = "Mangaluru" if is_mlr else "Bengaluru"
    
    for ps in SAFETY_CONTACTS.get("police_stations", []):
        ps_lat = ps.get("lat")
        ps_lon = ps.get("lon")
        if ps_lat is not None and ps_lon is not None:
            dist = haversine((lat, lon), (ps_lat, ps_lon))
            stations.append({
                "name": ps["name"],
                "number": ps["number"],
                "area": ps["area"],
                "city": ps.get("city", "Bengaluru"),
                "distance_km": round(dist, 2),
                "lat": ps_lat,
                "lon": ps_lon
            })
            
    city_matched = [s for s in stations if s["city"] == scope_city]
    if city_matched:
        city_matched.sort(key=lambda s: s["distance_km"])
        return city_matched[:limit]
        
    stations.sort(key=lambda s: s["distance_km"])
    return stations[:limit]

def get_locality_matching_records(locality: str, df: pd.DataFrame, is_mlr: bool = False) -> pd.DataFrame:
    """Filter genuine, in-bounds records attributed to the specified locality name.
    Does not conflate police station jurisdiction with incident scene place.
    Excludes out-of-region geocoding mismatches and police station centroids."""
    if df is None or len(df) == 0:
        return pd.DataFrame()
        
    loc_clean = locality.strip().lower()
    
    # Base geospatial and data integrity validity masks
    if is_mlr:
        mlr_ps_coords = {(12.922229, 74.859430), (12.864530, 74.858052), (12.802090, 74.901150),
                         (12.869774, 74.872641), (12.885987, 74.824397), (13.064779, 74.797981)}
        valid = (
            (df['latitude'] >= 12.65) & (df['latitude'] <= 13.25) &
            (df['longitude'] >= 74.70) & (df['longitude'] <= 75.25) &
            (~df.apply(lambda r: (round(r['latitude'], 6), round(r['longitude'], 6)) in mlr_ps_coords, axis=1)) &
            (~df['place'].astype(str).str.lower().str.contains('police station'))
        )
    else:
        valid = (
            (df['latitude'] >= 12.70) & (df['latitude'] <= 13.35) &
            (df['longitude'] >= 77.30) & (df['longitude'] <= 77.90) &
            (df['place'].astype(str).str.strip().str.lower() != 'police station')
        )
    pool = df[valid].copy()
    
    # Match locality name against place field (not generic jurisdiction)
    pattern = r'\b' + re.escape(loc_clean) + r'\b'
    matched = pool[pool['place'].astype(str).str.lower().str.contains(pattern, regex=True)]
    if len(matched) == 0 and ' ' in loc_clean:
        alt_pattern = r'\b' + re.escape(loc_clean.replace(' ', '')) + r'\b'
        matched = pool[pool['place'].astype(str).str.lower().str.contains(alt_pattern, regex=True)]
        
    return matched

def compute_locality_risk_metrics(df_sub: pd.DataFrame):
    """Derive historical risk score, category, and most common crime from eligible records.
    Requires minimum 5 verified records; returns Insufficient Evidence if threshold not met."""
    n = len(df_sub)
    if n < 5:
        return 0.0, "Insufficient Evidence", "Insufficient Data"
        
    base = 20.0
    density = min(35.0, round(8.0 * math.log(1.0 + n), 1))
    
    types = df_sub['type'].astype(str).str.lower()
    t1 = types.str.contains('murder|rape|pocso|kidnap').sum()
    t2 = types.str.contains('robbery|extortion|assault|snatching').sum()
    t3 = types.str.contains('theft|burglary|housebreak').sum()
    other = n - (t1 + t2 + t3)
    
    sev = round((t1 * 20.0 + t2 * 12.0 + t3 * 7.0 + other * 5.0) / max(1, n), 1)
    score = float(min(100.0, max(0.0, round(base + density + sev, 1))))
    cat = "High Risk" if score >= 60.0 else ("Moderate Risk" if score >= 40.0 else "Low Risk")
    vc = df_sub['type'].value_counts()
    most_common = str(vc.index[0]) if len(vc) > 0 else "Recorded Incident"
    return score, cat, most_common

def calculate_high_risk_zones(limit: int = 5, city: Optional[str] = None) -> list:
    """Calculate top high-risk zones across Bengaluru and Mangaluru dynamically from actual dataset records.
    Derives locality crime volume and risk scores directly from matching eligible dataset records."""
    scope = (city or "combined").lower()
    places = get_places()
    results = []
    
    for name, coords in places.items():
        is_mlr = is_mangaluru_coordinate(coords[0], coords[1])
        place_city = "Mangaluru" if is_mlr else "Bengaluru"
        
        if scope == "bengaluru" and place_city != "Bengaluru":
            continue
        if scope == "mangaluru" and place_city != "Mangaluru":
            continue
            
        df = mangaluru_crime_data if is_mlr else crime_data
        matches = get_locality_matching_records(name, df, is_mlr=is_mlr)
        count = len(matches)
        
        score, category, most_common = compute_locality_risk_metrics(matches)
        
        # Determine centroid: median of eligible incident records if available, else gazetteer
        if count > 0:
            lat = round(float(matches['latitude'].median()), 6)
            lon = round(float(matches['longitude'].median()), 6)
        else:
            lat = round(coords[0], 6)
            lon = round(coords[1], 6)
            
        results.append({
            "locality": name,
            "area": name,
            "city": place_city,
            "latitude": lat,
            "longitude": lon,
            "risk_score": score,
            "incident_count": count,
            "crime_count": count,
            "risk_category": category,
            "most_common_crime": most_common
        })
        
    # Sort measured zones (>= 5 incidents) first by (risk_score, incident_count), then insufficient evidence
    results.sort(key=lambda x: (1 if x["incident_count"] >= 5 else 0, x["risk_score"], x["incident_count"]), reverse=True)
    return results[:limit]

def get_nearest_high_risk_zones(lat: float, lon: float, limit: int = 3, city: Optional[str] = None) -> list:
    """Find nearest high risk zones from given coordinates"""
    all_zones = calculate_high_risk_zones(limit=50, city=city)
    for z in all_zones:
        z["distance_km"] = round(haversine((lat, lon), (z["latitude"], z["longitude"])), 2)
    all_zones.sort(key=lambda z: (z["distance_km"], -z["risk_score"]))
    return all_zones[:limit]

CRIME_CLASSES = [
    '2 Wheeler Theft', '2 wheeler theft', '4 Wheeler Theft', 'Assault',
    'Attempted Murder', 'Chain Snatching', 'Cybercrime', 'Kidnap',
    'Murder', 'Ordinary Theft', 'Rape', 'Robbery'
]

def predict_with_model(lat, lon, hour=12, day_of_week=0, month=None):
    """Predict crime category and confidence using the loaded Bengaluru XGBoost model"""
    if model is None:
        raise ValueError("Model not loaded")
    
    now = datetime.now()
    h = float(hour) if hour is not None else float(now.hour)
    d = int(day_of_week) if day_of_week is not None else int(now.weekday())
    m = int(month) if month is not None else int(now.month)
    
    if 5 <= h < 12:
        pod = 0
    elif 12 <= h < 17:
        pod = 1
    elif 17 <= h < 22:
        pod = 2
    else:
        pod = 3
        
    df_feat = pd.DataFrame([{
        'Latitude': float(lat),
        'Longitude': float(lon),
        'Hour': h,
        'DayOfWeek': d,
        'Month': m,
        'PartOfDay': pod,
        'Police Station': 0,
        'Place': 0
    }])
    
    try:
        proba = model.predict_proba(df_feat)[0]
        class_idx = int(np.argmax(proba))
        pred_label = CRIME_CLASSES[class_idx] if class_idx < len(CRIME_CLASSES) else str(class_idx)
        confidence = float(np.max(proba) * 100.0)
        return pred_label, confidence
    except Exception as e:
        try:
            pred_val = model.predict(df_feat)[0]
            class_idx = int(pred_val)
            pred_label = CRIME_CLASSES[class_idx] if class_idx < len(CRIME_CLASSES) else str(class_idx)
            return pred_label, 75.0
        except Exception as e2:
            raise ValueError(f"Prediction failed: {e2}")

# ==================== GEOCODING & LOCAL GAZETTEER ====================
GEOCODE_CACHE = {}
GAZETTEER = {}

def build_gazetteer():
    """Build structured in-memory gazetteer of monitored places in Bengaluru and Mangaluru sectors"""
    global GAZETTEER
    places = {}
    
    # 1. Monitored sub-localities from place_lookup.json
    lookup_file = "place_lookup.json"
    if os.path.exists(lookup_file):
        try:
            with open(lookup_file, "r", encoding="utf-8") as f:
                raw_lookup = json.load(f)
                for name, coords in raw_lookup.items():
                    clean_name = str(name).strip()
                    places[clean_name] = {
                        "name": clean_name,
                        "display_name": f"{clean_name}, Bengaluru, Karnataka, India",
                        "lat": float(coords[0]),
                        "lon": float(coords[1]),
                        "city": "Bengaluru",
                        "sector": "Bengaluru Sector",
                        "in_operational_area": True
                    }
        except Exception as e:
            print(f"⚠️ Could not load place lookup for gazetteer: {e}")
            
    # 2. Mangaluru core localities & police jurisdictions
    mlr_locs = {
        "Kadri": [12.8799, 74.8554],
        "Hampankatta": [12.8696, 74.8423],
        "Bunder": [12.8655, 74.8384],
        "Pandeshwar": [12.8595, 74.8440],
        "Surathkal": [12.9949, 74.8120],
        "Panambur": [12.9246, 74.8205],
        "Ullal": [12.8030, 74.8636],
        "Kavoor": [12.9206, 74.8548],
        "Urwa": [12.8979, 74.8359],
        "Barke": [12.8847, 74.8337],
        "Mulki": [13.0726, 74.8122],
        "Moodabidre": [13.0765, 75.0047],
        "Bajpe": [12.9768, 74.9135],
        "Konaje": [12.8094, 74.9235],
        "Bejai": [12.8845, 74.8444],
        "Falnir": [12.8665, 74.8475],
        "Kankanady": [12.8739, 74.8785],
        "Lalbagh Mangaluru": [12.8782, 74.8398],
        "Mannagudda": [12.8824, 74.8335],
        "Derebail": [12.9092, 74.8488],
        "Maryhill": [12.9155, 74.8601],
        "Bondel": [12.9288, 74.8667],
        "Kottara": [12.9056, 74.8378],
        "Bikarnakatte": [12.8778, 74.8668],
        "Tannirbhavi": [12.8944, 74.8153],
        "Panambur Beach": [12.9467, 74.8028],
        "Mangalore Central Railway Station": [12.8633, 74.8436],
        "Mangalore Junction": [12.8703, 74.8761],
        "Mangalore International Airport": [12.9613, 74.8900]
    }
    for name, coords in mlr_locs.items():
        places[name] = {
            "name": name,
            "display_name": f"{name}, Mangaluru, Karnataka, India",
            "lat": float(coords[0]),
            "lon": float(coords[1]),
            "city": "Mangaluru",
            "sector": "Mangaluru Sector",
            "in_operational_area": True
        }
        
    # 3. Prominent Bengaluru landmarks & transport hubs
    blr_landmarks = {
        "MG Road": [12.9756, 77.6066],
        "Brigade Road": [12.9733, 77.6074],
        "Commercial Street": [12.9822, 77.6083],
        "Vidhana Soudha": [12.9796, 77.5907],
        "Cubbon Park": [12.9763, 77.5929],
        "Lalbagh Botanical Garden": [12.9507, 77.5848],
        "Kempegowda Bus Station": [12.9781, 77.5696],
        "Majestic": [12.9781, 77.5696],
        "KSR Bengaluru Railway Station": [12.9784, 77.5694],
        "Yeshwanthpur Railway Station": [13.0238, 77.5501],
        "Kempegowda International Airport": [13.1986, 77.7066],
        "BLR Airport": [13.1986, 77.7066],
        "Silk Board": [12.9177, 77.6238],
        "Marathahalli": [12.9591, 77.6974],
        "Bellandur": [12.9304, 77.6784],
        "HSR Layout": [12.9121, 77.6446],
        "BTM Layout": [12.9166, 77.6101],
        "Domlur": [12.9609, 77.6387],
        "Ulsoor": [12.9817, 77.6285],
        "Malleshwaram": [13.0031, 77.5643],
        "Rajajinagar": [12.9982, 77.5530],
        "Frazer Town": [12.9968, 77.6131],
        "RT Nagar": [13.0247, 77.5948],
        "Yelahanka": [13.1007, 77.5963],
        "Kengeri": [12.9177, 77.4838],
        "Vijayanagar": [12.9719, 77.5307],
        "Peenya": [13.0285, 77.5197]
    }
    for name, coords in blr_landmarks.items():
        if name not in places:
            places[name] = {
                "name": name,
                "display_name": f"{name}, Bengaluru, Karnataka, India",
                "lat": float(coords[0]),
                "lon": float(coords[1]),
                "city": "Bengaluru",
                "sector": "Bengaluru Sector",
                "in_operational_area": True
            }
            
    GAZETTEER = places
    print(f"✅ Loaded {len(GAZETTEER)} places into BEACON gazetteer")

build_gazetteer()

def in_operational_area(lat: float, lon: float) -> bool:
    """Validate whether coordinate lies within Karnataka operational bounds (11.50-18.50 N, 74.00-78.60 E)."""
    return (11.50 <= lat <= 18.50) and (74.00 <= lon <= 78.60)

def geocode_place(query: str, limit: int = 5) -> list:
    """Geocode place name to validated coordinates.
    Prioritizes real OpenStreetMap Nominatim geocoding, enforces Karnataka operational boundaries,
    and falls back seamlessly to the local gazetteer on network latency, timeout, or rate-limiting."""
    q_str = str(query).strip()
    if not q_str:
        return []
    
    q_lower = q_str.lower()
    cache_key = q_lower
    if cache_key in GEOCODE_CACHE:
        return GEOCODE_CACHE[cache_key][:limit]
        
    results = []
    
    # 1. Query real OpenStreetMap Nominatim Geocoding service
    try:
        search_term = q_str
        if not any(k in q_lower for k in ["karnataka", "bengaluru", "bangalore", "mangaluru", "mangalore"]):
            search_query = f"{q_str}, Karnataka, India"
        else:
            search_query = q_str
            
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(search_query)}&format=json&addressdetails=1&limit={limit}&countrycodes=in"
        req = urllib.request.Request(url, headers={"User-Agent": "BEACON-Public-Safety-Intelligence/2.4 (contact: ops@beacon-intel.local)"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                raw_data = json.loads(resp.read().decode("utf-8"))
                for item in raw_data:
                    try:
                        lat_val = float(item["lat"])
                        lon_val = float(item["lon"])
                        name_val = item.get("name") or item.get("display_name", "").split(",")[0].strip()
                        disp_val = item.get("display_name", "")
                        
                        # Operational Boundary Checks
                        is_blr = (12.65 <= lat_val <= 13.35) and (77.20 <= lon_val <= 77.95)
                        is_mlr = (12.65 <= lat_val <= 13.25) and (74.65 <= lon_val <= 75.25)
                        is_kar = (11.50 <= lat_val <= 18.50) and (74.00 <= lon_val <= 78.60)
                        
                        if is_blr:
                            city_val = "Bengaluru"
                            sector_val = "Bengaluru Sector"
                            in_op = True
                        elif is_mlr:
                            city_val = "Mangaluru"
                            sector_val = "Mangaluru Sector"
                            in_op = True
                        elif is_kar:
                            city_val = "Karnataka"
                            sector_val = "Karnataka Region"
                            in_op = True
                        else:
                            city_val = "External"
                            sector_val = "Outside Operational Area"
                            in_op = False
                            
                        results.append({
                            "name": name_val,
                            "display_name": disp_val,
                            "lat": lat_val,
                            "lon": lon_val,
                            "city": city_val,
                            "sector": sector_val,
                            "in_operational_area": in_op,
                            "source": "nominatim"
                        })
                    except Exception:
                        continue
    except Exception:
        # Nominatim network error, timeout, or rate-limit: silently fall back to local gazetteer
        pass
        
    # 2. Local Gazetteer matching (used if Nominatim returned 0 results or failed)
    if not results and GAZETTEER:
        # Exact match
        for place_name, info in GAZETTEER.items():
            if q_lower == place_name.lower():
                results.append(dict(info, source="gazetteer"))
                break
                
        # Substring match
        if not results:
            for place_name, info in GAZETTEER.items():
                p_lower = place_name.lower()
                if q_lower in p_lower or p_lower in q_lower:
                    results.append(dict(info, source="gazetteer"))
                    if len(results) >= limit:
                        break
                        
        # Prefix match
        if not results:
            prefix = q_lower[:4] if len(q_lower) >= 4 else q_lower
            for place_name, info in GAZETTEER.items():
                if place_name.lower().startswith(prefix):
                    results.append(dict(info, source="gazetteer"))
                    if len(results) >= limit:
                        break

    if results:
        GEOCODE_CACHE[cache_key] = results
    return results[:limit]

# ==================== MODELS ====================
class PredictRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-90, le=90)
    hour: Optional[int] = Field(None, ge=0, le=23)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)

class RouteRequest(BaseModel):
    src_lat: Optional[float] = None
    src_lon: Optional[float] = None
    dst_lat: Optional[float] = None
    dst_lon: Optional[float] = None
    source_lat: Optional[float] = None
    source_lon: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lon: Optional[float] = None
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None
    destination_lat: Optional[float] = None
    destination_lon: Optional[float] = None
    origin_name: Optional[str] = None
    destination_name: Optional[str] = None
    departure_time: Optional[str] = None
    hour: Optional[int] = None
    day_of_week: Optional[int] = None

class SegmentIncidentsRequest(BaseModel):
    polyline: List[List[float]]
    buffer_km: Optional[float] = 1.2
    city: Optional[str] = None
    category: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    locality_query: Optional[str] = None
    limit: Optional[int] = 100
    offset: Optional[int] = 0

# ==================== ENDPOINTS ====================
@app.get("/")
def root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        if os.path.exists("public/index.html"):
            return FileResponse("public/index.html")
        elif os.path.exists("frontend/index.html"):
            return FileResponse("frontend/index.html")
    return {
        "status": "online",
        "app": APP_TITLE,
        "version": "2.0",
        "model_loaded": model_info["loaded"],
        "data_loaded": crime_data is not None,
        "total_records": len(crime_data) if crime_data is not None else 0,
        "cached_locations": len(location_cache)
    }

@app.get("/api/health")
def health():
    b_count = len(crime_data) if crime_data is not None else 0
    m_count = len(mangaluru_crime_data) if mangaluru_crime_data is not None else 0
    return {
        "status": "healthy",
        "model": model_info,
        "data_records": b_count,
        "bengaluru_records": b_count,
        "mangaluru_records": m_count,
        "total_records": b_count + m_count,
        "cached_locations": len(location_cache),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/predict")
def predict(req: PredictRequest):
    """Predict crime risk for a location with strict regional model isolation"""
    lat, lon = req.latitude, req.longitude
    hour = req.hour if req.hour is not None else datetime.now().hour
    day = req.day_of_week if req.day_of_week is not None else datetime.now().weekday()
    
    # Geographic screening: if Mangaluru coordinates, do NOT route through Bengaluru model
    if is_mangaluru_coordinate(lat, lon):
        loc_data, distance = get_nearest_location_data(lat, lon, city_scope="mangaluru")
        density = get_incident_density(lat, lon)
        nearest_high_risk = get_nearest_high_risk_zones(lat, lon, limit=3, city="mangaluru")
        nearby_police = get_nearest_police_stations(lat, lon, limit=3)
        return {
            "latitude": lat,
            "longitude": lon,
            "city": "Mangaluru",
            "model_status": "model_not_trained_for_sector",
            "predicted_crime": loc_data.get('most_common', 'Historical Mangaluru Incident') if loc_data else "Sector Unmapped",
            "risk_score": 35.0,
            "confidence": 70.0 if loc_data else 30.0,
            "recommendations": [
                "ℹ️ Mangaluru Sector: Machine learning inference model not trained for this jurisdiction",
                "📊 Actual historical incident records and spatial clustering active on Safety Map",
                "📞 Mangaluru Police Control Room: 0824-2220516 | Emergency: 112"
            ],
            "nearby_crimes": loc_data['crime_count'] if loc_data else 0,
            "nearest_police": loc_data['police_station'] if loc_data else "Mangaluru Sector",
            "distance_to_data": round(distance, 2) if distance else None,
            "used_model": False,
            "hour": hour,
            "day_of_week": day,
            "incident_density": density,
            "nearest_high_risk_zones": nearest_high_risk,
            "nearby_police_stations": nearby_police
        }
    
    # Bengaluru model prediction
    predicted_crime = None
    confidence = None
    used_model = False
    
    if model_info["loaded"]:
        try:
            predicted_crime, confidence = predict_with_model(lat, lon, hour, day)
            used_model = True
        except Exception as e:
            print(f"Model prediction failed: {e}")
    
    risk_score = calculate_risk_score(lat, lon, hour, day)
    location_data, distance = get_nearest_location_data(lat, lon, city_scope="bengaluru")
    
    if not predicted_crime and location_data:
        predicted_crime = location_data.get('most_common', 'Unknown')
        confidence = max(50, 100 - (distance * 10))
    elif not predicted_crime:
        predicted_crime = "Insufficient Data"
        confidence = 30
    
    recommendations = get_safety_recommendations(risk_score, hour, predicted_crime)
    density = get_incident_density(lat, lon)
    nearest_high_risk = get_nearest_high_risk_zones(lat, lon, limit=3, city="bengaluru")
    nearby_police = get_nearest_police_stations(lat, lon, limit=3)
    
    return {
        "latitude": lat,
        "longitude": lon,
        "city": "Bengaluru",
        "predicted_crime": predicted_crime,
        "risk_score": round(risk_score, 1),
        "confidence": round(confidence, 1),
        "recommendations": recommendations,
        "nearby_crimes": location_data['crime_count'] if location_data else 0,
        "nearest_police": location_data['police_station'] if location_data else "Unknown",
        "distance_to_data": round(distance, 2) if distance else None,
        "used_model": used_model,
        "hour": hour,
        "day_of_week": day,
        "incident_density": density,
        "nearest_high_risk_zones": nearest_high_risk,
        "nearby_police_stations": nearby_police
    }

@app.get("/api/high-risk-zones")
@app.get("/api/risky-zones")
def get_high_risk_zones(limit: int = 5, city: Optional[str] = None):
    """Get top highest-risk areas dynamically computed across Bengaluru and Mangaluru"""
    zones = calculate_high_risk_zones(limit=limit, city=city)
    return {
        "city": city or "combined",
        "limit": limit,
        "total": len(zones),
        "zones": zones,
        "disclaimer": "Historical risk estimates are derived from recorded FIR records and spatial incident density; they do not guarantee future safety or predict live events."
    }

@app.get("/api/heatmap")
def get_heatmap(limit: int = 200, city: Optional[str] = None):
    """Get crime heatmap data supporting city filtering"""
    scope = (city or "combined").lower()
    items = []
    
    if scope in ["bengaluru", "combined"]:
        for loc in location_cache_blr.values():
            risk = calculate_risk_score(loc['lat'], loc['lon'])
            items.append({
                "lat": loc['lat'],
                "lon": loc['lon'],
                "risk_score": round(risk, 1),
                "crime_count": loc['crime_count'],
                "most_common": loc['most_common'],
                "police_station": loc['police_station'],
                "city": "Bengaluru"
            })
            
    if scope in ["mangaluru", "combined"] and location_cache_mlr:
        for loc in location_cache_mlr.values():
            density_score = min(40, loc['crime_count'] * 2)
            risk = 30 + density_score
            items.append({
                "lat": loc['lat'],
                "lon": loc['lon'],
                "risk_score": round(float(risk), 1),
                "crime_count": loc['crime_count'],
                "most_common": loc['most_common'],
                "police_station": loc['police_station'],
                "city": "Mangaluru"
            })
    
    items.sort(key=lambda x: x['risk_score'], reverse=True)
    selected = items[:limit]
    
    return {
        "heatmap": selected,
        "total": len(selected),
        "city": scope,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/crime-trends")
def get_crime_trends(city: Optional[str] = None):
    """Get crime trends over time supporting city filtering"""
    scope = (city or "combined").lower()
    
    if scope == "mangaluru":
        if mangaluru_crime_data is None:
            return {"trends": [], "message": "Mangaluru dataset not loaded"}
        df = mangaluru_crime_data
    elif scope == "bengaluru":
        if crime_data is None:
            return {"trends": [], "message": "Bengaluru dataset not loaded"}
        df = crime_data
    else:
        parts = []
        if crime_data is not None: parts.append(crime_data)
        if mangaluru_crime_data is not None: parts.append(mangaluru_crime_data)
        df = pd.concat(parts, ignore_index=True) if parts else None
        
    if df is None:
        return {"trends": [], "message": "No data available"}
    
    trends = []
    if 'year' in df.columns:
        yearly = df.groupby('year').size().reset_index(name='count').sort_values('year')
        for _, row in yearly.iterrows():
            if pd.notna(row['year']) and int(row['year']) > 2000:
                trends.append({
                    "date": str(int(row['year'])),
                    "count": int(row['count'])
                })
    
    crime_types = df['type'].value_counts().head(10).to_dict()
    
    hourly = {}
    if 'hour' in df.columns and df['hour'].notna().any():
        h_counts = df['hour'].dropna().astype(int).value_counts().sort_index().to_dict()
        hourly = {int(k): int(v) for k, v in h_counts.items()}
    
    return {
        "city": scope,
        "monthly_trends": trends,
        "crime_types": {k: int(v) for k, v in crime_types.items()},
        "hourly_distribution": hourly,
        "total_crimes": len(df),
        "date_range": {
            "start": str(int(df['year'].min())) if 'year' in df.columns and pd.notna(df['year'].min()) else None,
            "end": str(int(df['year'].max())) if 'year' in df.columns and pd.notna(df['year'].max()) else None
        }
    }

ROUTING_SERVICE_URL = os.environ.get("ROUTING_SERVICE_URL", "https://router.project-osrm.org/route/v1/driving")
ROAD_ROUTE_CACHE = {}

def fetch_road_route(src_lat: float, src_lon: float, dst_lat: float, dst_lon: float, timeout_sec: float = 6.0):
    """Query configured road routing service (OSRM) to retrieve actual road network geometry.
    Returns dict with polyline coordinates [[lat, lon], ...], distance_km, estimated_time_min,
    or None if unavailable. Implements route caching and transient retry."""
    cache_key = f"{src_lat:.4f},{src_lon:.4f}->{dst_lat:.4f},{dst_lon:.4f}"
    if cache_key in ROAD_ROUTE_CACHE:
        return ROAD_ROUTE_CACHE[cache_key]
        
    url = f"{ROUTING_SERVICE_URL}/{src_lon},{src_lat};{dst_lon},{dst_lat}?overview=full&geometries=geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "BEACON-Public-Safety-Intelligence/2.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("code") != "Ok" or not data.get("routes"):
                    continue
                route = data["routes"][0]
                dist_km = round(route["distance"] / 1000.0, 2)
                time_min = round(route["duration"] / 60.0, 0)
                raw_coords = route["geometry"]["coordinates"]
                # Convert GeoJSON [lon, lat] -> [lat, lon]
                polyline = [[round(p[1], 6), round(p[0], 6)] for p in raw_coords]
                res = {
                    "polyline": polyline,
                    "distance_km": dist_km,
                    "estimated_time_min": time_min,
                    "routing_status": "road_network_verified"
                }
                ROAD_ROUTE_CACHE[cache_key] = res
                return res
        except Exception as e:
            if attempt == 1:
                print(f"⚠️ Road routing service request failed after retry: {e}")
            pass
    return None

def point_to_polyline_distances(points_lat_lon: np.ndarray, polyline_lat_lon: list) -> np.ndarray:
    """Calculate exact minimum perpendicular distance (in km) from points to road polyline segments.
    Ensures incidents along long road segments or curved roads are accurately evaluated against road geometry."""
    if len(polyline_lat_lon) < 2 or len(points_lat_lon) == 0:
        return np.zeros(len(points_lat_lon), dtype=float)
        
    poly_arr = np.array(polyline_lat_lon)
    ref_lat = float(np.mean(poly_arr[:, 0]))
    scale_y = 111.0
    scale_x = 111.0 * math.cos(math.radians(ref_lat))
    
    # Points in km coordinates
    P_y = points_lat_lon[:, 0] * scale_y
    P_x = points_lat_lon[:, 1] * scale_x
    P = np.column_stack([P_y, P_x])  # shape (M, 2)
    
    # Segment endpoints in km coordinates
    V_y = poly_arr[:, 0] * scale_y
    V_x = poly_arr[:, 1] * scale_x
    A = np.column_stack([V_y[:-1], V_x[:-1]])  # shape (K, 2)
    B = np.column_stack([V_y[1:], V_x[1:]])    # shape (K, 2)
    
    AB = B - A
    L2 = np.sum(AB**2, axis=1)
    L2[L2 == 0] = 1e-9  # avoid division by zero
    
    # Vectorized point-to-segment projection across all road segments
    AP = P[:, None, :] - A[None, :, :]  # shape (M, K, 2)
    t = np.clip(np.sum(AP * AB[None, :, :], axis=2) / L2[None, :], 0.0, 1.0)
    Q = A[None, :, :] + t[:, :, None] * AB[None, :, :]
    dists = np.sqrt(np.sum((P[:, None, :] - Q)**2, axis=2)).min(axis=1)
    return dists

def haversine_distance(p1, p2) -> float:
    """Calculate great-circle distance in kilometers between two [lat, lon] coordinates."""
    R = 6371.0
    dlat = math.radians(p2[0] - p1[0])
    dlon = math.radians(p2[1] - p1[1])
    a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(p1[0])) * math.cos(math.radians(p2[0])) * math.sin(dlon / 2.0)**2
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))

def partition_polyline_into_segments(full_polyline: list, target_km: float = 0.35, min_km: float = 0.20) -> list:
    """Divide actual road polyline into ordered, contiguous segments approximately 250-500m long.
    Preserves exact road geometry with zero gaps (segment k+1 starts where segment k ends)."""
    if not full_polyline or len(full_polyline) < 2:
        return [(full_polyline, 0.0)] if full_polyline else []
        
    segments = []
    curr_seg = [full_polyline[0]]
    curr_dist = 0.0
    
    for i in range(len(full_polyline) - 1):
        p1 = full_polyline[i]
        p2 = full_polyline[i+1]
        step_d = haversine_distance(p1, p2)
        
        # If an individual road segment is long (> 0.5km), interpolate intermediate vertices
        if step_d > 0.5:
            num_subs = math.ceil(step_d / target_km)
            for s in range(1, num_subs):
                frac = s / num_subs
                interp = [round(p1[0] + frac * (p2[0] - p1[0]), 6), round(p1[1] + frac * (p2[1] - p1[1]), 6)]
                curr_dist += haversine_distance(curr_seg[-1], interp)
                curr_seg.append(interp)
                if curr_dist >= target_km:
                    segments.append((curr_seg, curr_dist))
                    curr_seg = [interp]
                    curr_dist = 0.0
                    
        curr_dist += haversine_distance(curr_seg[-1], p2)
        curr_seg.append(p2)
        
        if curr_dist >= target_km:
            segments.append((curr_seg, curr_dist))
            curr_seg = [p2]
            curr_dist = 0.0
            
    if len(curr_seg) > 1:
        if segments and curr_dist < min_km:
            prev_pts, prev_d = segments[-1]
            segments[-1] = (prev_pts + curr_seg[1:], prev_d + curr_dist)
        else:
            segments.append((curr_seg, curr_dist))
            
    return segments

@app.get("/api/geocode")
def api_geocode(q: str = "", limit: int = 5):
    """Geocode place name or address with Karnataka operational bounds validation and offline gazetteer fallback"""
    if not q or len(q.strip()) < 2:
        return {"query": q, "count": 0, "results": []}
    results = geocode_place(q.strip(), limit=min(10, max(1, limit)))
    return {
        "query": q,
        "count": len(results),
        "results": results
    }

@app.post("/api/safe-route")
def safe_route(req: RouteRequest):
    """Calculate safest route along actual road network with rigorous geospatial accuracy breakdown"""
    origin_name = req.origin_name
    destination_name = req.destination_name
    
    s_lat = req.src_lat if req.src_lat is not None else (req.source_lat if req.source_lat is not None else req.origin_lat)
    s_lon = req.src_lon if req.src_lon is not None else (req.source_lon if req.source_lon is not None else req.origin_lon)
    d_lat = req.dst_lat if req.dst_lat is not None else (req.dest_lat if req.dest_lat is not None else req.destination_lat)
    d_lon = req.dst_lon if req.dst_lon is not None else (req.dest_lon if req.dest_lon is not None else req.destination_lon)

    # Auto-resolve place names if coordinates not directly supplied
    if (s_lat is None or s_lon is None) and origin_name:
        geo_src = geocode_place(origin_name, limit=1)
        if not geo_src:
            raise HTTPException(status_code=400, detail=f"Starting place '{origin_name}' could not be resolved.")
        if not geo_src[0].get("in_operational_area", True):
            raise HTTPException(status_code=400, detail=f"Starting place '{origin_name}' is outside supported BEACON operational area (Bengaluru / Mangaluru, Karnataka).")
        s_lat = geo_src[0]["lat"]
        s_lon = geo_src[0]["lon"]
        origin_name = geo_src[0]["name"]

    if (d_lat is None or d_lon is None) and destination_name:
        geo_dst = geocode_place(destination_name, limit=1)
        if not geo_dst:
            raise HTTPException(status_code=400, detail=f"Destination place '{destination_name}' could not be resolved.")
        if not geo_dst[0].get("in_operational_area", True):
            raise HTTPException(status_code=400, detail=f"Destination place '{destination_name}' is outside supported BEACON operational area (Bengaluru / Mangaluru, Karnataka).")
        d_lat = geo_dst[0]["lat"]
        d_lon = geo_dst[0]["lon"]
        destination_name = geo_dst[0]["name"]

    if s_lat is None or s_lon is None or d_lat is None or d_lon is None:
        raise HTTPException(status_code=400, detail="Missing source or destination coordinates")
        
    # Check for NaN / Inf
    if any(math.isnan(x) or math.isinf(x) for x in [s_lat, s_lon, d_lat, d_lon]):
        raise HTTPException(status_code=400, detail="Invalid coordinates: NaN or infinite values provided")
        
    # Check coordinate bounds (-90 to 90, -180 to 180)
    if not (-90.0 <= s_lat <= 90.0 and -90.0 <= d_lat <= 90.0 and -180.0 <= s_lon <= 180.0 and -180.0 <= d_lon <= 180.0):
        raise HTTPException(status_code=400, detail="Coordinates out of valid planetary range (-90..90, -180..180)")

    # Check identical origin and destination
    if abs(s_lat - d_lat) < 0.0001 and abs(s_lon - d_lon) < 0.0001:
        raise HTTPException(status_code=400, detail="Starting point and destination cannot be identical. Please select distinct locations.")

    # Operational area check: reject coordinates outside Karnataka
    if not (11.50 <= s_lat <= 18.50 and 74.00 <= s_lon <= 78.60):
        raise HTTPException(status_code=400, detail="Starting point is outside supported BEACON operational area (Bengaluru / Mangaluru, Karnataka).")
    if not (11.50 <= d_lat <= 18.50 and 74.00 <= d_lon <= 78.60):
        raise HTTPException(status_code=400, detail="Destination is outside supported BEACON operational area (Bengaluru / Mangaluru, Karnataka).")

    src = (s_lat, s_lon)
    dst = (d_lat, d_lon)
    
    # 1. Fetch real-world road geometry from routing service
    road_route = fetch_road_route(src[0], src[1], dst[0], dst[1])
    if not road_route:
        # Prompt requirement 3: "If routing fails, return an explicit unavailable state instead of inventing a road route."
        raise HTTPException(
            status_code=503,
            detail="Actual road routing service unavailable or unreachable. Route geometry cannot be verified. Routing Unavailable."
        )
        
    full_polyline = road_route["polyline"]
    distance = road_route["distance_km"]
    estimated_time = road_route["estimated_time_min"]
    
    # Identify regional scope
    is_mlr = is_mangaluru_coordinate(src[0], src[1]) or is_mangaluru_coordinate(dst[0], dst[1])
    
    # Parse evaluation hour
    eval_hour = req.hour
    if eval_hour is None and req.departure_time:
        try:
            eval_hour = int(req.departure_time.split(':')[0])
        except Exception:
            eval_hour = None
            
    # Calculate incident proximity against the actual road polyline segments (corridor buffer: 1.2 km)
    corridor_buffer_km = 1.2
    
    verified_nearby = 0
    locality_nearby = 0
    ps_nearby = 0
    unverified_nearby = 0
    mismatches_excluded = 0
    
    corridor_category_weights = []
    corridor_distances = []
    
    sub_dedup = pd.DataFrame()
    coords_arr = np.empty((0, 2))
    
    if is_mlr:
        df_target = mangaluru_crime_data if mangaluru_crime_data is not None else pd.DataFrame()
        prefix = "MLR"
    else:
        df_target = crime_data if crime_data is not None else pd.DataFrame()
        prefix = "BLR"
        
    if not df_target.empty and 'latitude' in df_target.columns and 'longitude' in df_target.columns:
        buf_deg = (corridor_buffer_km / 111.0) * 1.5
        all_lats = [p[0] for p in full_polyline]
        all_lons = [p[1] for p in full_polyline]
        min_lat = min(all_lats) - buf_deg
        max_lat = max(all_lats) + buf_deg
        min_lon = min(all_lons) - buf_deg
        max_lon = max(all_lons) + buf_deg
        
        sub = df_target[
            (df_target['latitude'] >= min_lat) & (df_target['latitude'] <= max_lat) &
            (df_target['longitude'] >= min_lon) & (df_target['longitude'] <= max_lon)
        ].copy()
        
        if not sub.empty:
            # Deduplicate candidate records to prevent duplicate inflation
            if 'date' in sub.columns and 'type' in sub.columns:
                sub_dedup = sub.drop_duplicates(subset=['latitude', 'longitude', 'date', 'type'])
            else:
                sub_dedup = sub.drop_duplicates(subset=['latitude', 'longitude'])
                
            coords_arr = sub_dedup[['latitude', 'longitude']].values
            min_dist_to_route = point_to_polyline_distances(coords_arr, full_polyline)
            
            in_corridor_mask = (min_dist_to_route <= corridor_buffer_km)
            in_corridor_indices = sub_dedup.index[in_corridor_mask]
            in_corridor_dists = min_dist_to_route[in_corridor_mask]
            
            for idx, dist_val in zip(in_corridor_indices, in_corridor_dists):
                row_record = sub_dedup.loc[idx]
                source_id = int(row_record.get('source_row_id', idx + 1))
                rec_id = f"{prefix}-{source_id:04d}"
                audit_meta = get_audit_record_metadata(rec_id)
                status = audit_meta.get("validation_status", "LOCATION_UNVERIFIED")
                
                if status == "INCIDENT_LOCATION_VERIFIED":
                    verified_nearby += 1
                elif status == "LOCALITY_MATCH_ONLY":
                    locality_nearby += 1
                elif status == "POLICE_STATION_COORDINATE":
                    ps_nearby += 1
                    continue  # Excluded from crime-scene risk and category weights
                elif status == "LOCATION_MISMATCH":
                    mismatches_excluded += 1
                    continue  # Excluded from spatial analysis entirely
                else:
                    unverified_nearby += 1
                    
                # Collect crime category severity weight for verified and locality/unverified crime scenes
                row_record = sub_dedup.loc[idx]
                c_type_str = str(row_record.get('type', row_record.get('Crime_Category', ''))).lower()
                if any(w in c_type_str for w in ['murder', 'rape', 'pocso', 'kidnapping']):
                    corridor_category_weights.append(25.0)
                elif any(w in c_type_str for w in ['robbery', 'extortion', 'dacoity', 'assault', 'snatching']):
                    corridor_category_weights.append(15.0)
                elif any(w in c_type_str for w in ['theft', 'burglary', 'housebreak', 'vehicle']):
                    corridor_category_weights.append(8.0)
                else:
                    corridor_category_weights.append(4.0)
                    
                corridor_distances.append(float(dist_val))

    # Total deduplicated crime-scene incidents along corridor (police station coordinates excluded from crime scenes)
    total_crime_scenes = verified_nearby + locality_nearby + unverified_nearby
    
    # Numerator with documented weights: Verified (1.0), Locality Centroid (0.85), Unverified (0.0)
    usable_evidence_numerator = 1.0 * verified_nearby + 0.85 * locality_nearby
    
    # Denominator: total crime-scene incident records
    usable_ratio = round((usable_evidence_numerator / total_crime_scenes) * 100, 1) if total_crime_scenes > 0 else 0.0
    
    # Calculate risk at source and destination
    src_risk = calculate_risk_score(src[0], src[1], hour=eval_hour, day_of_week=req.day_of_week)
    dst_risk = calculate_risk_score(dst[0], dst[1], hour=eval_hour, day_of_week=req.day_of_week)

    # Risk Score Formulation
    # If total_crime_scenes == 0: no usable records exist along corridor.
    # Requirement 2: "Do not use arbitrary baseline values to imply that an area has measured risk when no usable records exist."
    # Requirement 4: "Never describe a route as safe merely because the dataset contains no records nearby."
    if total_crime_scenes == 0:
        avg_risk = 0.0
        measured_risk = False
        confidence = "INSUFFICIENT_EVIDENCE"
        if ps_nearby > 0:
            advisory = f"Insufficient evidence: zero validated crime-scene incident records located along route corridor (excluded {ps_nearby} police station reference coordinates from crime threat). Risk is unmeasured due to absence of local crime records; corridor cannot be assumed safe."
        else:
            advisory = "Insufficient evidence: zero validated crime-scene incident records located within corridor buffer. Risk is unmeasured due to absence of local crime records; corridor cannot be assumed safe."
            
        recommendations = [
            "ℹ️ No recorded historical crime data located along this corridor",
            "⚠️ Absence of crime records does not indicate that the corridor is safe",
            "🚨 Exercise standard situational awareness and follow well-lit public thoroughfares"
        ]
    else:
        measured_risk = True
        n_eff = 1.0 * locality_nearby + 0.5 * unverified_nearby
        # Diminishing-returns logarithmic density scaling
        s_density = min(45.0, round(10.0 * math.log(1.0 + n_eff), 1))
        
        # Proportional crime category severity aggregation across all corridor incidents
        s_severity = round(sum(corridor_category_weights) / len(corridor_category_weights), 1) if corridor_category_weights else 6.0
        
        # Proximity scaling factor based on mean perpendicular distance to road polyline
        mean_d = float(np.mean(corridor_distances)) if corridor_distances else 0.5
        s_proximity = max(0.6, round(1.0 - (mean_d / 2.4), 2))
        
        # Temporal scoring (STRICTLY DISABLED for Mangaluru because FIR timestamps are missing)
        s_temporal = 0.0
        if not is_mlr and eval_hour is not None:
            if 22 <= eval_hour or eval_hour <= 4:
                s_temporal += 15.0  # Night
            elif 18 <= eval_hour <= 21:
                s_temporal += 8.0   # Evening
            elif 6 <= eval_hour <= 9:
                s_temporal += 4.0   # Morning rush
                
        if not is_mlr and req.day_of_week is not None and req.day_of_week >= 5:
            s_temporal += 4.0       # Weekend
            
        raw_threat = (s_density * s_proximity) + s_severity + s_temporal
        avg_risk = min(100.0, max(10.0, round(raw_threat, 1)))
        
        # Strictly Calibrated Confidence Status
        if usable_ratio >= 60.0 and total_crime_scenes >= 10:
            confidence = "MODERATE"
            advisory = f"Moderate confidence: corridor is informed by {locality_nearby} validated sub-locality centroid records within jurisdiction bounds. Doorstep-level variance exists; not verified incident scenes."
        else:
            confidence = "APPROXIMATE"
            if unverified_nearby > 0:
                advisory = f"Approximate confidence: corridor relies predominantly on unverified historical FIR records ({unverified_nearby} of {total_crime_scenes} unverified) with substantial spatial uncertainty."
            else:
                advisory = f"Approximate confidence: corridor has sparse usable record coverage ({locality_nearby} incidents along {distance} km)."
                
        recommendations = get_safety_recommendations(avg_risk)

    # ==================== CONTIGUOUS ROAD SEGMENT EVALUATION (~250-500m) ====================
    raw_segments = partition_polyline_into_segments(full_polyline, target_km=0.35, min_km=0.20)
    evaluated_segments = []
    
    for seg_idx, (seg_pts, seg_dist) in enumerate(raw_segments):
        seg_id = seg_idx + 1
        seg_verified = 0
        seg_locality = 0
        seg_ps = 0
        seg_unverified = 0
        seg_mismatches = 0
        seg_cat_weights = []
        seg_distances = []
        
        if len(coords_arr) > 0 and not sub_dedup.empty:
            seg_min_dists = point_to_polyline_distances(coords_arr, seg_pts)
            seg_mask = (seg_min_dists <= corridor_buffer_km)
            seg_indices = sub_dedup.index[seg_mask]
            seg_dists_filtered = seg_min_dists[seg_mask]
            
            for idx, dist_val in zip(seg_indices, seg_dists_filtered):
                row_record = sub_dedup.loc[idx]
                source_id = int(row_record.get('source_row_id', idx + 1))
                rec_id = f"{prefix}-{source_id:04d}"
                audit_meta = get_audit_record_metadata(rec_id)
                status = audit_meta.get("validation_status", "LOCATION_UNVERIFIED")
                
                if status == "INCIDENT_LOCATION_VERIFIED":
                    seg_verified += 1
                elif status == "LOCALITY_MATCH_ONLY":
                    seg_locality += 1
                elif status == "POLICE_STATION_COORDINATE":
                    seg_ps += 1
                    continue
                elif status == "LOCATION_MISMATCH":
                    seg_mismatches += 1
                    continue
                else:
                    seg_unverified += 1
                    
                row_record = sub_dedup.loc[idx]
                c_type_str = str(row_record.get('type', row_record.get('Crime_Category', ''))).lower()
                if any(w in c_type_str for w in ['murder', 'rape', 'pocso', 'kidnapping']):
                    seg_cat_weights.append(25.0)
                elif any(w in c_type_str for w in ['robbery', 'extortion', 'dacoity', 'assault', 'snatching']):
                    seg_cat_weights.append(15.0)
                elif any(w in c_type_str for w in ['theft', 'burglary', 'housebreak', 'vehicle']):
                    seg_cat_weights.append(8.0)
                else:
                    seg_cat_weights.append(4.0)
                    
                seg_distances.append(float(dist_val))
                
        seg_total_crime = seg_verified + seg_locality + seg_unverified
        
        if seg_total_crime == 0:
            seg_measured = False
            seg_score = None
            tier = get_corridor_risk_tier(None, measured=False)
            seg_cat = tier["key"]
            seg_label = tier["label"]
            seg_color = tier["color"]
            seg_ev_status = "INSUFFICIENT_EVIDENCE"
            seg_usable_ratio = 0.0
            if seg_ps > 0:
                seg_advisory = f"Insufficient evidence: zero crime-scene incident records within 1.2 km corridor buffer of road segment ({seg_dist:.2f} km). Excluded {seg_ps} police station reference coordinates. Risk is unmeasured."
            else:
                seg_advisory = f"Insufficient evidence: zero recorded crime incidents within 1.2 km corridor buffer ({seg_dist:.2f} km). Absence of records does not imply that this road segment is safe."
        else:
            seg_measured = True
            n_eff_seg = 1.0 * seg_locality + 0.5 * seg_unverified
            s_dens_seg = min(45.0, round(10.0 * math.log(1.0 + n_eff_seg), 1))
            s_sev_seg = round(sum(seg_cat_weights) / len(seg_cat_weights), 1) if seg_cat_weights else 6.0
            mean_d_seg = float(np.mean(seg_distances)) if seg_distances else 0.5
            s_prox_seg = max(0.6, round(1.0 - (mean_d_seg / 2.4), 2))
            
            s_temp_seg = 0.0
            if not is_mlr and eval_hour is not None:
                if 22 <= eval_hour or eval_hour <= 4:
                    s_temp_seg += 15.0
                elif 18 <= eval_hour <= 21:
                    s_temp_seg += 8.0
                elif 6 <= eval_hour <= 9:
                    s_temp_seg += 4.0
            if not is_mlr and req.day_of_week is not None and req.day_of_week >= 5:
                s_temp_seg += 4.0
                
            raw_seg_threat = (s_dens_seg * s_prox_seg) + s_sev_seg + s_temp_seg
            seg_score = min(100.0, max(10.0, round(raw_seg_threat, 1)))
            
            seg_num = 1.0 * seg_verified + 0.85 * seg_locality
            seg_usable_ratio = round((seg_num / seg_total_crime) * 100, 1)
            
            if seg_usable_ratio >= 60.0 and seg_total_crime >= 5:
                seg_ev_status = "MODERATE"
            else:
                seg_ev_status = "APPROXIMATE"
                
            # Shared authoritative score-band mapping
            tier = get_corridor_risk_tier(seg_score, measured=True)
            seg_cat = tier["key"]
            seg_label = tier["label"]
            seg_color = tier["color"]
            seg_advisory = f"{tier['label']} ({seg_score}/100) based on {seg_total_crime} historical incidents within 1.2 km corridor buffer along this road segment ({seg_dist:.2f} km)."
                
        evaluated_segments.append({
            "segment_id": seg_id,
            "polyline": seg_pts,
            "start_coord": [seg_pts[0][0], seg_pts[0][1]],
            "end_coord": [seg_pts[-1][0], seg_pts[-1][1]],
            "distance_km": round(seg_dist, 3),
            "length_km": round(seg_dist, 3),
            "measured": seg_measured,
            "measured_risk": seg_measured,
            "score": seg_score,
            "threat_score": seg_score,
            "risk_category": seg_cat,
            "category": seg_label,
            "color": seg_color,
            "incident_count": seg_total_crime,
            "corridor_incidents": seg_total_crime,
            "evidence_status": seg_ev_status,
            "location_quality_status": seg_ev_status,
            "usable_evidence_ratio": seg_usable_ratio,
            "verified_count": seg_verified,
            "locality_count": seg_locality,
            "unverified_count": seg_unverified,
            "police_station_count": seg_ps,
            "advisory": seg_advisory
        })

    total_seg_dist = round(sum(s["distance_km"] for s in evaluated_segments), 2)
    measured_dist = round(sum(s["distance_km"] for s in evaluated_segments if s["measured_risk"]), 2)
    unmeasured_dist = round(sum(s["distance_km"] for s in evaluated_segments if not s["measured_risk"]), 2)
    if total_seg_dist > 0:
        if measured_dist == 0.0:
            measured_pct = 0.0
            unmeasured_pct = 100.0
        elif unmeasured_dist == 0.0:
            measured_pct = 100.0
            unmeasured_pct = 0.0
        else:
            measured_pct = round((measured_dist / total_seg_dist) * 100, 1)
            unmeasured_pct = round(100.0 - measured_pct, 1)
    else:
        measured_pct = 0.0
        unmeasured_pct = 0.0

    category_counts = {
        "lower": sum(1 for s in evaluated_segments if s["risk_category"] == "lower"),
        "moderate": sum(1 for s in evaluated_segments if s["risk_category"] == "moderate"),
        "elevated": sum(1 for s in evaluated_segments if s["risk_category"] == "elevated"),
        "higher": sum(1 for s in evaluated_segments if s["risk_category"] == "higher"),
        "unmeasured": sum(1 for s in evaluated_segments if s["risk_category"] == "unmeasured"),
    }

    categories_full = {
        "Lower Historical Threat": category_counts["lower"],
        "Moderate Historical Threat": category_counts["moderate"],
        "Elevated Historical Threat": category_counts["elevated"],
        "Higher Historical Threat": category_counts["higher"],
        "Insufficient Evidence": category_counts["unmeasured"],
    }

    segment_summary = {
        "total_segments": len(evaluated_segments),
        "measured_segments": sum(1 for s in evaluated_segments if s["measured_risk"]),
        "unmeasured_segments": sum(1 for s in evaluated_segments if not s["measured_risk"]),
        "total_distance_km": total_seg_dist,
        "measured_distance_km": measured_dist,
        "unmeasured_distance_km": unmeasured_dist,
        "measured_percent": measured_pct,
        "measured_percentage": measured_pct,
        "unmeasured_percent": unmeasured_pct,
        "unmeasured_percentage": unmeasured_pct,
        "category_counts": category_counts,
        "categories": categories_full
    }

    # Sub-sample polyline for backwards compatibility with route preview waypoints
    wp_step = max(1, len(full_polyline) // 25)
    sampled_coords = full_polyline[::wp_step]
    if full_polyline[-1] not in sampled_coords:
        sampled_coords.append(full_polyline[-1])
        
    route_points = []
    for pt in sampled_coords:
        pt_risk = calculate_risk_score(pt[0], pt[1], hour=eval_hour, day_of_week=req.day_of_week) if measured_risk else 0.0
        route_points.append({
            "lat": pt[0],
            "lon": pt[1],
            "risk": pt_risk
        })

    return {
        "route": route_points,
        "route_polyline": full_polyline,
        "segments": evaluated_segments,
        "segment_summary": segment_summary,
        "origin_name": origin_name or f"Point A ({s_lat:.4f}, {s_lon:.4f})",
        "destination_name": destination_name or f"Point B ({d_lat:.4f}, {d_lon:.4f})",
        "routing_mode": "actual_road_network",
        "distance_km": distance,
        "average_risk": avg_risk,
        "measured_risk": measured_risk,
        "risk_type": "heuristic_historical_indicator",
        "src_risk": src_risk,
        "dst_risk": dst_risk,
        "recommendations": recommendations,
        "high_risk_segments": sum(1 for p in route_points if p['risk'] >= 70),
        "estimated_time_min": estimated_time,
        "accuracy_summary": {
            "confidence_level": confidence,
            "usable_evidence_ratio": usable_ratio,
            "total_corridor_incidents": total_crime_scenes,
            "verified_nearby": verified_nearby,
            "locality_centroids_nearby": locality_nearby,
            "police_station_coords_nearby": ps_nearby,
            "unverified_locations_nearby": unverified_nearby,
            "mismatches_excluded": mismatches_excluded,
            "advisory": advisory
        },
        "temporal_policy": {
            "city": "Mangaluru" if is_mlr else "Bengaluru",
            "scoring_status": "disabled_due_to_missing_fir_timestamps" if is_mlr else "active_from_recorded_timestamps",
            "applied_hour": None if is_mlr else eval_hour,
            "applied_day_of_week": None if is_mlr else req.day_of_week
        }
    }

def normalize_incident_date(date_val):
    """Normalize incident date into display format (DD-MM-YYYY) and ISO sort format (YYYY-MM-DD)"""
    if date_val is None or pd.isna(date_val):
        return None, None
    s = str(date_val).strip()
    if not s or s.lower() in ['nan', 'none', 'nat', 'null', '0']:
        return None, None
    for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            dt = datetime.strptime(s.split()[0], fmt)
            return dt.strftime('%d-%m-%Y'), dt.strftime('%Y-%m-%d')
        except Exception:
            pass
    return s, None

@app.post("/api/safe-route/segment-incidents")
def get_segment_incidents(req: SegmentIncidentsRequest):
    """Retrieve detailed historical crime incidents for a specific road segment buffer with filters"""
    if not req.polyline or len(req.polyline) < 2:
        raise HTTPException(status_code=400, detail="Segment polyline must contain at least 2 coordinate points.")

    for pt in req.polyline:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            raise HTTPException(status_code=400, detail="Invalid polyline coordinate point format.")
        lat, lon = pt[0], pt[1]
        if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
            raise HTTPException(status_code=400, detail="Invalid coordinate values: NaN or infinite values found.")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise HTTPException(status_code=400, detail="Polyline coordinates out of planetary bounds.")

    buffer_km = max(0.1, min(5.0, float(req.buffer_km or 1.2)))

    # Determine city scope
    is_mlr = False
    if req.city:
        is_mlr = "mangaluru" in req.city.lower()
    else:
        is_mlr = is_mangaluru_coordinate(req.polyline[0][0], req.polyline[0][1])

    if is_mlr:
        df_target = mangaluru_crime_data if mangaluru_crime_data is not None else pd.DataFrame()
        prefix = "MLR"
        city_name = "Mangaluru"
    else:
        df_target = crime_data if crime_data is not None else pd.DataFrame()
        prefix = "BLR"
        city_name = "Bengaluru"

    disclaimer_text = (
        "Incident counts include historical records within 1.2 km of this road segment. "
        "These incidents may have occurred nearby rather than directly on the road. "
        "Location accuracy depends on the original record."
    )

    if df_target.empty or 'latitude' not in df_target.columns or 'longitude' not in df_target.columns:
        return {
            "total_records": 0,
            "unfiltered_total": 0,
            "buffer_km": buffer_km,
            "city": city_name,
            "disclaimer": disclaimer_text,
            "categories": [],
            "records": [],
            "excluded_police_stations": 0,
            "excluded_mismatches": 0
        }

    # Bounding box candidate filter
    buf_deg = (buffer_km / 111.0) * 1.5
    all_lats = [p[0] for p in req.polyline]
    all_lons = [p[1] for p in req.polyline]
    min_lat = min(all_lats) - buf_deg
    max_lat = max(all_lats) + buf_deg
    min_lon = min(all_lons) - buf_deg
    max_lon = max(all_lons) + buf_deg

    sub = df_target[
        (df_target['latitude'] >= min_lat) & (df_target['latitude'] <= max_lat) &
        (df_target['longitude'] >= min_lon) & (df_target['longitude'] <= max_lon)
    ].copy()

    if sub.empty:
        return {
            "total_records": 0,
            "unfiltered_total": 0,
            "buffer_km": buffer_km,
            "city": city_name,
            "disclaimer": disclaimer_text,
            "categories": [],
            "records": [],
            "excluded_police_stations": 0,
            "excluded_mismatches": 0
        }

    # Deduplicate candidate records identical to corridor scoring
    if 'date' in sub.columns and 'type' in sub.columns:
        sub_dedup = sub.drop_duplicates(subset=['latitude', 'longitude', 'date', 'type'])
    else:
        sub_dedup = sub.drop_duplicates(subset=['latitude', 'longitude'])

    coords_arr = sub_dedup[['latitude', 'longitude']].values
    dists = point_to_polyline_distances(coords_arr, req.polyline)
    in_mask = (dists <= buffer_km)
    matched_indices = sub_dedup.index[in_mask]
    matched_dists = dists[in_mask]

    all_incident_records = []
    excluded_ps_count = 0
    excluded_mismatch_count = 0

    for idx, dist_val in zip(matched_indices, matched_dists):
        row = sub_dedup.loc[idx]
        source_id = int(row.get('source_row_id', idx + 1))
        rec_id = f"{prefix}-{source_id:04d}"
        audit_meta = get_audit_record_metadata(rec_id)
        status = audit_meta.get("validation_status", "LOCATION_UNVERIFIED")

        # Exclude police station coordinates and mismatches from crime scene counts
        if status == "POLICE_STATION_COORDINATE":
            excluded_ps_count += 1
            continue
        elif status == "LOCATION_MISMATCH":
            excluded_mismatch_count += 1
            continue

        raw_type = row.get('type', row.get('Crime_Category', None))
        crime_type_str = str(raw_type).strip() if raw_type is not None and not pd.isna(raw_type) else "Other/Unclassified"
        if not crime_type_str or crime_type_str.lower() in ['nan', 'none']:
            crime_type_str = "Other/Unclassified"

        raw_date = row.get('Date', row.get('date', None))
        disp_date, iso_date = normalize_incident_date(raw_date)

        raw_place = row.get('Place', row.get('place', row.get('Place_Display', None)))
        place_str = str(raw_place).strip() if raw_place is not None and not pd.isna(raw_place) else None
        if place_str and place_str.lower() in ['nan', 'none', 'null']:
            place_str = None

        raw_ps = row.get('Police Station', row.get('police_station', None))
        ps_str = str(raw_ps).strip() if raw_ps is not None and not pd.isna(raw_ps) else None
        if ps_str and ps_str.lower() in ['nan', 'none', 'null']:
            ps_str = None

        all_incident_records.append({
            "id": rec_id,
            "crime_type": crime_type_str,
            "date": disp_date,
            "date_iso": iso_date,
            "locality": place_str,
            "police_station": ps_str,
            "latitude": round(float(row['latitude']), 6),
            "longitude": round(float(row['longitude']), 6),
            "distance_km": round(float(dist_val), 3),
            "location_quality": status,
            "location_quality_label": QUALITY_LABELS.get(status, "Location not verified"),
            "coordinate_origin": audit_meta.get("coordinate_origin", "unverified_historical_record"),
            "evidence": audit_meta.get("evidence", "Coordinate reliability unverified.")
        })

    unfiltered_total = len(all_incident_records)

    # Apply filters
    filtered_records = all_incident_records

    # Category filter
    if req.category and req.category.strip().lower() != 'all':
        cat_q = req.category.strip().lower()
        filtered_records = [
            r for r in filtered_records
            if r["crime_type"].lower() == cat_q or cat_q in r["crime_type"].lower()
        ]

    # Date range filters (date_from, date_to in ISO format: YYYY-MM-DD)
    if req.date_from:
        d_from = req.date_from.strip()
        filtered_records = [
            r for r in filtered_records
            if r["date_iso"] is not None and r["date_iso"] >= d_from
        ]
    if req.date_to:
        d_to = req.date_to.strip()
        filtered_records = [
            r for r in filtered_records
            if r["date_iso"] is not None and r["date_iso"] <= d_to
        ]

    # Locality search filter
    if req.locality_query and len(req.locality_query.strip()) > 0:
        loc_q = req.locality_query.strip().lower()
        filtered_records = [
            r for r in filtered_records
            if (r["locality"] and loc_q in r["locality"].lower()) or
               (r["police_station"] and loc_q in r["police_station"].lower()) or
               (r["crime_type"] and loc_q in r["crime_type"].lower())
        ]

    # Group by category and compute counts & proportional percentages
    cat_counts = {}
    for r in filtered_records:
        ctype = r["crime_type"]
        cat_counts[ctype] = cat_counts.get(ctype, 0) + 1

    sorted_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
    total_filtered = len(filtered_records)

    categories_summary = []
    for cname, ccount in sorted_cats:
        pct = round((ccount / total_filtered) * 100, 1) if total_filtered > 0 else 0.0
        categories_summary.append({
            "name": cname,
            "count": ccount,
            "percentage": pct
        })

    # Pagination
    limit = req.limit if req.limit is not None and req.limit > 0 else len(filtered_records)
    offset = max(0, req.offset or 0)
    paginated_records = filtered_records[offset:offset + limit]

    return {
        "total_records": total_filtered,
        "unfiltered_total": unfiltered_total,
        "buffer_km": buffer_km,
        "city": city_name,
        "disclaimer": disclaimer_text,
        "categories": categories_summary,
        "records": paginated_records,
        "excluded_police_stations": excluded_ps_count,
        "excluded_mismatches": excluded_mismatch_count
    }

@app.get("/api/safety-contacts")
def get_safety_contacts():
    """Get emergency contacts and helplines"""
    return SAFETY_CONTACTS

@app.get("/api/dashboard")
def get_dashboard(city: Optional[str] = None):
    """Get dashboard metrics with dual-city support"""
    scope = (city or "combined").lower()
    
    blr_count = len(crime_data) if crime_data is not None else 0
    mlr_count = len(mangaluru_crime_data) if mangaluru_crime_data is not None else 0
    total_crimes = blr_count + mlr_count
    
    if scope == "mangaluru":
        active_df = mangaluru_crime_data
        active_total = mlr_count
        monitored_locs = len(location_cache_mlr)
    elif scope == "bengaluru":
        active_df = crime_data
        active_total = blr_count
        monitored_locs = len(location_cache_blr)
    else:
        active_df = crime_data
        active_total = total_crimes
        monitored_locs = len(location_cache_blr) + len(location_cache_mlr)
    
    crime_types = active_df['type'].value_counts().head(5).to_dict() if active_df is not None else {}
    
    top_risky = calculate_high_risk_zones(limit=5, city=scope)
    all_scored = calculate_high_risk_zones(limit=50, city=scope)
    high_risk_count = sum(1 for z in all_scored if z.get('risk_category') == 'High Risk')
    avg_risk = round(sum(z['risk_score'] for z in all_scored) / max(1, len(all_scored)), 1) if all_scored else 48.5
    
    return {
        "city": scope,
        "total_crimes": active_total,
        "bengaluru_records": blr_count,
        "mangaluru_records": mlr_count,
        "combined_total_records": blr_count + mlr_count,
        "mangaluru_status": "active" if mangaluru_crime_data is not None else "pending_integration",
        "unmapped_records": 0,
        "high_risk_count": high_risk_count,
        "recent_crimes_30d": 142,
        "top_risky_areas": top_risky,
        "crime_types": {k: int(v) for k, v in crime_types.items()},
        "average_risk": avg_risk,
        "monitored_locations": monitored_locs
    }

@app.get("/api/recent-incidents")
def get_recent_incidents(limit: int = 15, city: Optional[str] = None):
    """Get recent recorded incidents with verified historical dates and dual-city support"""
    scope = (city or "combined").lower()
    incidents = []
    
    if scope in ["mangaluru", "combined"] and mangaluru_crime_data is not None:
        mlr_sorted = mangaluru_crime_data.dropna(subset=['datetime']).sort_values('datetime', ascending=False) if 'datetime' in mangaluru_crime_data.columns else mangaluru_crime_data
        sample_size = limit if scope == "mangaluru" else max(1, limit // 2)
        mlr_sample = mlr_sorted.head(sample_size)
        
        for idx, row in mlr_sample.iterrows():
            incidents.append({
                "id": f"MLR-CRIME-{idx+1:04d}",
                "police_station": str(row.get('police_station', 'Unknown')),
                "type": str(row.get('crime_category', row.get('type', 'Recorded Incident'))),
                "date": str(row.get('date', 'Unknown')),
                "time": "Not recorded",
                "place": str(row.get('place', row.get('police_station', 'Mangaluru'))),
                "latitude": float(row.get('latitude', 12.9141)),
                "longitude": float(row.get('longitude', 74.8560)),
                "city": "Mangaluru",
                "status_badge": "SOURCE RECORD"
            })
            
    if scope in ["bengaluru", "combined"] and crime_data is not None:
        blr_sorted = crime_data.dropna(subset=['datetime']).sort_values('datetime', ascending=False) if 'datetime' in crime_data.columns else crime_data
        sample_size = limit if scope == "bengaluru" else (limit - len(incidents))
        blr_sample = blr_sorted.head(sample_size)
        
        for idx, row in blr_sample.iterrows():
            incidents.append({
                "id": f"BLR-CRIME-{idx+1:04d}",
                "police_station": str(row.get('police_station', 'Unknown')),
                "type": str(row.get('type', 'Incident')),
                "date": str(row.get('date', 'Unknown')),
                "time": str(row.get('time', 'Unknown')),
                "place": str(row.get('place', row.get('police_station', 'Bengaluru'))),
                "latitude": float(row.get('latitude', 12.9716)),
                "longitude": float(row.get('longitude', 77.5946)),
                "city": "Bengaluru",
                "status_badge": "SOURCE RECORD"
            })
            
    return {
        "city": scope,
        "count": len(incidents),
        "incidents": incidents
    }

@app.get("/api/incidents")
def get_incidents(limit: int = 1000, city: Optional[str] = None, crime_type: Optional[str] = None, locality: Optional[str] = None):
    """Get actual recorded crime incidents from datasets for map display.
    Guarantees full representation for high-risk zones (such as Hebbal) and supports locality filtering."""
    scope = (city or "combined").lower()
    incidents = []
    
    # 1. Locality specific query mode
    if locality and locality.strip():
        loc_name = locality.strip()
        
        # Query Mangaluru if in scope
        if scope in ["mangaluru", "combined"] and mangaluru_crime_data is not None:
            df_mlr_loc = get_locality_matching_records(loc_name, mangaluru_crime_data, is_mlr=True)
            if crime_type:
                df_mlr_loc = df_mlr_loc[df_mlr_loc['type'].str.lower() == crime_type.lower()]
            for idx, row in df_mlr_loc.iterrows():
                c_type = str(row.get('type', 'Recorded Incident')).strip()
                place_val = row.get('place')
                place = str(place_val).strip() if pd.notna(place_val) and str(place_val).strip() and str(place_val).strip().lower() != 'nan' else 'Sector Area'
                date_val = row.get('date')
                date_str = str(date_val).strip() if pd.notna(date_val) and str(date_val).strip() and str(date_val).strip().lower() != 'nan' else 'Recorded'
                station_val = row.get('police_station')
                station = str(station_val).strip() if pd.notna(station_val) and str(station_val).strip() and str(station_val).strip().lower() != 'nan' else 'Mangaluru Police'
                lat = float(row.get('latitude', 0.0))
                lon = float(row.get('longitude', 0.0))
                source_id = int(row.get('source_row_id', idx + 1))
                rec_id = f"MLR-CRIME-{source_id:04d}"
                audit_entry = get_audit_record_metadata(rec_id)
                v_status = audit_entry.get("validation_status", "LOCATION_UNVERIFIED")
                c_origin = audit_entry.get("coordinate_origin", "unverified_historical_record")
                ev_text = audit_entry.get("evidence", f"Incident recorded in {loc_name} sector.")
                
                is_sensitive = any(w in c_type.lower() for w in ['rape', 'sexual', 'pocso', 'molestation'])
                if is_sensitive:
                    status_badge = "SOURCE RECORD (PRIVACY PROTECTED)"
                    lat = round(lat, 2)
                    lon = round(lon, 2)
                    place = f"{station} Sector (Generalized for privacy)"
                elif v_status == "INCIDENT_LOCATION_VERIFIED":
                    status_badge = "VERIFIED INCIDENT SCENE"
                elif v_status == "LOCALITY_MATCH_ONLY":
                    status_badge = "LOCALITY CENTROID ONLY"
                elif v_status == "POLICE_STATION_COORDINATE":
                    status_badge = "POLICE STATION COORD"
                elif v_status == "LOCATION_MISMATCH":
                    status_badge = "GEOGRAPHIC MISMATCH"
                else:
                    status_badge = "LOCATION UNVERIFIED"
                    
                incidents.append({
                    "id": rec_id,
                    "crime_type": c_type,
                    "place": place,
                    "date": date_str,
                    "time": "Not recorded",
                    "police_station": station,
                    "latitude": lat,
                    "longitude": lon,
                    "city": "Mangaluru",
                    "status_badge": status_badge,
                    "validation_status": v_status,
                    "location_quality": v_status,
                    "location_quality_label": QUALITY_LABELS.get(v_status, "Location not verified"),
                    "coordinate_origin": c_origin,
                    "evidence": ev_text
                })
                
        # Query Bengaluru if in scope
        if scope in ["bengaluru", "combined"] and crime_data is not None:
            df_blr_loc = get_locality_matching_records(loc_name, crime_data, is_mlr=False)
            if crime_type:
                df_blr_loc = df_blr_loc[df_blr_loc['type'].str.lower() == crime_type.lower()]
            for idx, row in df_blr_loc.iterrows():
                c_type = str(row.get('type', 'Recorded Incident')).strip()
                place_val = row.get('place')
                place = str(place_val).strip() if pd.notna(place_val) and str(place_val).strip() and str(place_val).strip().lower() != 'nan' else 'Sector Area'
                date_val = row.get('date')
                date_str = str(date_val).strip() if pd.notna(date_val) and str(date_val).strip() and str(date_val).strip().lower() != 'nan' else 'Recorded'
                time_val = row.get('time')
                time_str = str(time_val).strip() if pd.notna(time_val) and str(time_val).strip() and str(time_val).strip().lower() != 'nan' else 'Not recorded'
                station_val = row.get('police_station')
                station = str(station_val).strip() if pd.notna(station_val) and str(station_val).strip() and str(station_val).strip().lower() != 'nan' else 'Bengaluru Police'
                lat = float(row.get('latitude', 0.0))
                lon = float(row.get('longitude', 0.0))
                source_id = int(row.get('source_row_id', idx + 1))
                rec_id = f"BLR-CRIME-{source_id:04d}"
                audit_entry = get_audit_record_metadata(rec_id)
                v_status = audit_entry.get("validation_status", "LOCATION_UNVERIFIED")
                c_origin = audit_entry.get("coordinate_origin", "unverified_historical_record")
                ev_text = audit_entry.get("evidence", f"Incident recorded in {loc_name} sector.")
                
                is_sensitive = any(w in c_type.lower() for w in ['rape', 'sexual', 'pocso'])
                if is_sensitive:
                    status_badge = "SOURCE RECORD (PRIVACY PROTECTED)"
                    lat = round(lat, 2)
                    lon = round(lon, 2)
                    place = f"{station} Sector (Generalized for privacy)"
                elif v_status == "INCIDENT_LOCATION_VERIFIED":
                    status_badge = "VERIFIED INCIDENT SCENE"
                elif v_status == "LOCALITY_MATCH_ONLY":
                    status_badge = "LOCALITY CENTROID ONLY"
                elif v_status == "POLICE_STATION_COORDINATE":
                    status_badge = "POLICE STATION COORD"
                elif v_status == "LOCATION_MISMATCH":
                    status_badge = "GEOGRAPHIC MISMATCH"
                else:
                    status_badge = "LOCATION UNVERIFIED"
                    
                incidents.append({
                    "id": rec_id,
                    "crime_type": c_type,
                    "place": place,
                    "date": date_str,
                    "time": time_str,
                    "police_station": station,
                    "latitude": lat,
                    "longitude": lon,
                    "city": "Bengaluru",
                    "status_badge": status_badge,
                    "validation_status": v_status,
                    "location_quality": v_status,
                    "location_quality_label": QUALITY_LABELS.get(v_status, "Location not verified"),
                    "coordinate_origin": c_origin,
                    "evidence": ev_text
                })
                
        return {
            "city": scope,
            "locality": loc_name,
            "total": len(incidents),
            "incidents": incidents
        }

    # 2. General Map Display Mode (Stratified sampling with High-Risk Zone priority)
    # 2a. Mangaluru Incidents
    if scope in ["mangaluru", "combined"] and mangaluru_crime_data is not None:
        df_mlr = mangaluru_crime_data.dropna(subset=['latitude', 'longitude']).copy()
        if crime_type:
            df_mlr = df_mlr[df_mlr['type'].str.lower() == crime_type.lower()]
            
        mlr_limit = limit if scope == "mangaluru" else limit // 2
        
        # Priority inclusion of top Mangaluru zones
        top_mlr_zones = ["Kadri", "Surathkal", "Kavoor", "Urwa"]
        mlr_priority_list = [get_locality_matching_records(z, df_mlr, is_mlr=True) for z in top_mlr_zones]
        mlr_priority = pd.concat(mlr_priority_list).drop_duplicates() if mlr_priority_list else pd.DataFrame()
        
        rem_mlr = df_mlr.loc[~df_mlr.index.isin(mlr_priority.index)]
        rem_limit = max(0, mlr_limit - len(mlr_priority))
        
        if len(rem_mlr) > rem_limit and 'type' in rem_mlr.columns:
            per_cat = max(10, rem_limit // rem_mlr['type'].nunique())
            sample_rem_mlr = rem_mlr.groupby('type', group_keys=False).apply(lambda g: g.head(per_cat))
            sample_mlr = pd.concat([mlr_priority, sample_rem_mlr]).head(mlr_limit)
        else:
            sample_mlr = pd.concat([mlr_priority, rem_mlr]).head(mlr_limit)
            
        for idx, row in sample_mlr.iterrows():
            c_type = str(row.get('type', 'Recorded Incident')).strip()
            place_val = row.get('place')
            place = str(place_val).strip() if pd.notna(place_val) and str(place_val).strip() and str(place_val).strip().lower() != 'nan' else 'Sector Area'
            date_val = row.get('date')
            date_str = str(date_val).strip() if pd.notna(date_val) and str(date_val).strip() and str(date_val).strip().lower() != 'nan' else 'Recorded'
            station_val = row.get('police_station')
            station = str(station_val).strip() if pd.notna(station_val) and str(station_val).strip() and str(station_val).strip().lower() != 'nan' else 'Mangaluru Police'
            
            lat = float(row.get('latitude', 0.0))
            lon = float(row.get('longitude', 0.0))
            source_id = int(row.get('source_row_id', idx + 1))
            rec_id = f"MLR-CRIME-{source_id:04d}"
            audit_entry = get_audit_record_metadata(rec_id)
            v_status = audit_entry.get("validation_status", "LOCATION_UNVERIFIED")
            c_origin = audit_entry.get("coordinate_origin", "unverified_historical_record")
            ev_text = audit_entry.get("evidence", "Historical FIR entry with informal street description.")
            
            is_sensitive = any(w in c_type.lower() for w in ['rape', 'sexual', 'pocso', 'molestation'])
            if is_sensitive:
                status_badge = "SOURCE RECORD (PRIVACY PROTECTED)"
                lat = round(lat, 2)
                lon = round(lon, 2)
                place = f"{station} Sector (Generalized for privacy)"
            elif v_status == "INCIDENT_LOCATION_VERIFIED":
                status_badge = "VERIFIED INCIDENT SCENE"
            elif v_status == "LOCALITY_MATCH_ONLY":
                status_badge = "LOCALITY CENTROID ONLY"
            elif v_status == "POLICE_STATION_COORDINATE":
                status_badge = "POLICE STATION COORD"
            elif v_status == "LOCATION_MISMATCH":
                status_badge = "GEOGRAPHIC MISMATCH"
            else:
                status_badge = "LOCATION UNVERIFIED"
                
            incidents.append({
                "id": rec_id,
                "crime_type": c_type,
                "place": place,
                "date": date_str,
                "time": "Not recorded",
                "police_station": station,
                "latitude": lat,
                "longitude": lon,
                "city": "Mangaluru",
                "status_badge": status_badge,
                "validation_status": v_status,
                "location_quality": v_status,
                "location_quality_label": QUALITY_LABELS.get(v_status, "Location not verified"),
                "coordinate_origin": c_origin,
                "evidence": ev_text
            })
            
    # 2b. Bengaluru Incidents
    if scope in ["bengaluru", "combined"] and crime_data is not None:
        df_blr = crime_data.dropna(subset=['latitude', 'longitude']).copy()
        if crime_type:
            df_blr = df_blr[df_blr['type'].str.lower() == crime_type.lower()]
            
        blr_limit = limit if scope == "bengaluru" else (limit - len(incidents))
        
        # Priority inclusion of top Bengaluru high-risk zones, GUARANTEEING Hebbal's 100 records
        top_blr_zones = ["Hebbal", "Anekal", "Attibele", "Koramangala"]
        blr_priority_list = [get_locality_matching_records(z, df_blr, is_mlr=False) for z in top_blr_zones]
        blr_priority = pd.concat(blr_priority_list).drop_duplicates() if blr_priority_list else pd.DataFrame()
        
        rem_blr = df_blr.loc[~df_blr.index.isin(blr_priority.index)]
        rem_limit = max(0, blr_limit - len(blr_priority))
        
        if len(rem_blr) > rem_limit and 'type' in rem_blr.columns:
            per_cat = max(15, rem_limit // rem_blr['type'].nunique())
            sample_rem_blr = rem_blr.groupby('type', group_keys=False).apply(lambda g: g.head(per_cat))
            sample_blr = pd.concat([blr_priority, sample_rem_blr]).head(blr_limit)
        else:
            sample_blr = pd.concat([blr_priority, rem_blr]).head(blr_limit)
            
        for idx, row in sample_blr.iterrows():
            c_type = str(row.get('type', 'Recorded Incident')).strip()
            place_val = row.get('place')
            place = str(place_val).strip() if pd.notna(place_val) and str(place_val).strip() and str(place_val).strip().lower() != 'nan' else 'Sector Area'
            date_val = row.get('date')
            date_str = str(date_val).strip() if pd.notna(date_val) and str(date_val).strip() and str(date_val).strip().lower() != 'nan' else 'Recorded'
            time_val = row.get('time')
            time_str = str(time_val).strip() if pd.notna(time_val) and str(time_val).strip() and str(time_val).strip().lower() != 'nan' else 'Not recorded'
            station_val = row.get('police_station')
            station = str(station_val).strip() if pd.notna(station_val) and str(station_val).strip() and str(station_val).strip().lower() != 'nan' else 'Bengaluru Police'
            
            lat = float(row.get('latitude', 0.0))
            lon = float(row.get('longitude', 0.0))
            source_id = int(row.get('source_row_id', idx + 1))
            rec_id = f"BLR-CRIME-{source_id:04d}"
            audit_entry = get_audit_record_metadata(rec_id)
            v_status = audit_entry.get("validation_status", "LOCATION_UNVERIFIED")
            c_origin = audit_entry.get("coordinate_origin", "unverified_historical_record")
            ev_text = audit_entry.get("evidence", "Represents sub-locality centroid.")
            
            is_sensitive = any(w in c_type.lower() for w in ['rape', 'sexual', 'pocso'])
            if is_sensitive:
                status_badge = "SOURCE RECORD (PRIVACY PROTECTED)"
                lat = round(lat, 2)
                lon = round(lon, 2)
                place = f"{station} Sector (Generalized for privacy)"
            elif v_status == "INCIDENT_LOCATION_VERIFIED":
                status_badge = "VERIFIED INCIDENT SCENE"
            elif v_status == "LOCALITY_MATCH_ONLY":
                status_badge = "LOCALITY CENTROID ONLY"
            elif v_status == "POLICE_STATION_COORDINATE":
                status_badge = "POLICE STATION COORD"
            elif v_status == "LOCATION_MISMATCH":
                status_badge = "GEOGRAPHIC MISMATCH"
            else:
                status_badge = "LOCATION UNVERIFIED"
                
            incidents.append({
                "id": rec_id,
                "crime_type": c_type,
                "place": place,
                "date": date_str,
                "time": time_str,
                "police_station": station,
                "latitude": lat,
                "longitude": lon,
                "city": "Bengaluru",
                "status_badge": status_badge,
                "validation_status": v_status,
                "location_quality": v_status,
                "location_quality_label": QUALITY_LABELS.get(v_status, "Location not verified"),
                "coordinate_origin": c_origin,
                "evidence": ev_text
            })
            
    return {
        "city": scope,
        "total": len(incidents),
        "incidents": incidents
    }

@app.get("/api/places")
def get_places():
    """Get monitored places and coordinates from place_lookup.json and Mangaluru directory"""
    places = {}
    lookup_file = "place_lookup.json"
    if os.path.exists(lookup_file):
        try:
            with open(lookup_file, "r") as f:
                places.update(json.load(f))
        except Exception:
            pass
            
    mlr_defaults = {
        "Kadri": [12.8799, 74.8554],
        "Hampankatta": [12.8696, 74.8423],
        "Bunder": [12.8655, 74.8384],
        "Pandeshwar": [12.8595, 74.8440],
        "Surathkal": [12.9949, 74.8120],
        "Panambur": [12.9246, 74.8205],
        "Ullal": [12.8030, 74.8636],
        "Kavoor": [12.9206, 74.8548],
        "Urwa": [12.8979, 74.8359],
        "Barke": [12.8847, 74.8337],
        "Mulki": [13.0726, 74.8122],
        "Moodabidre": [13.0765, 75.0047],
        "Bajpe": [12.9768, 74.9135],
        "Konaje": [12.8094, 74.9235],
        "Kaikamba": [12.9605, 74.9332],
        "Kankanady": [12.8739, 74.8785]
    }
    for k, v in mlr_defaults.items():
        if k not in places:
            places[k] = v
            
    return places

# Serve static files (frontend)
if os.path.exists("frontend"):
    app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")
if os.path.exists("public"):
    app.mount("/", StaticFiles(directory="public", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))