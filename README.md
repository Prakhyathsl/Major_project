# BEACON — AI Public Safety Intelligence

**BEACON** is a modern, real-time public safety analytics and risk intelligence platform engineered for urban safety monitoring, corridor route navigation, and historical crime analysis across Bengaluru and Mangaluru.

---

## Key Features

- **Executive Safety Dashboard**: Real-time aggregated statistics across Bengaluru (BLR) and Mangaluru (MLR), top 5 verified high-risk zone rankings, location-based safety diagnostics, and one-touch national emergency dispatch contacts (112, 108, 101, 100, 1091).
- **Interactive Safety Map**: High-performance Leaflet clustering for 15,000+ audited historical crime records with locality and category filtering, custom jurisdiction sector markers, and clean incident popups.
- **Audited Geographic Accuracy**: Comprehensive multi-tier validation separating verified doorstep incidents, locality/facility centroids, station reference coordinates, and unverified FIR entries.
- **Safe Route Corridor Optimizer**: Multi-segment waypoint routing with dynamic risk analysis, segment threat scoring, corridor incident density filtering, and road-level risk mitigation.
- **My Current Location Safety**: Real-time GPS-assisted threat scoring, multi-radius incident density profiling (500m, 1km, 2km), and nearest police station dispatch info.
- **Dual Theme Support**: Modern, responsive dark mode (charcoal background with tactical orange, purple, and emerald accents) and high-contrast light mode.

---

## System Architecture

- **Backend**: FastAPI (Python 3.10+ / 3.14) with asynchronous endpoint processing.
- **Machine Learning & Spatial Analysis**: XGBoost model inference, Haversine geospatial proximity math, and polyline distance algorithms.
- **Data Validation Engine**: `geo_audit.py` automated geographic accuracy auditing across Karnataka metropolitan boundaries.
- **Frontend**: Clean single-page application built with modern JavaScript, Tailwind CSS, Leaflet.js, and Chart.js.

---

## Getting Started

### 1. Prerequisites
- Python 3.10 or higher
- Git

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/Prakhyathsl/BEACON.git
cd BEACON

# Create and activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the Geographic Audit (Optional)
To verify or regenerate the geographic audit reports and runtime lookup caches:
```bash
python geo_audit.py
```

### 4. Start the Application Server
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser and navigate to `http://localhost:8000` to access the dashboard.

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/dashboard/stats` | GET | Aggregated incident counts and city metrics |
| `/api/incidents` | GET | Spatial crime records with verified location quality |
| `/api/high-risk-zones` | GET | Top high-risk localities ranked by verified density |
| `/api/safe-route` | POST | Optimal waypoint-based safe pathfinding |
| `/api/safe-route/segment-incidents` | POST | Historical incidents along a road corridor |
| `/api/safety-map/user-location-risk` | POST | Multi-radius risk assessment for GPS coordinates |
| `/api/health` | GET | System status and model health |

---

## Test Suite

Run the full automated test suite covering unit tests, geographic accuracy, and API regressions:
```bash
python -m unittest discover tests
```

---

## License

This project is developed for educational and public safety research purposes.
