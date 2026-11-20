"""Freight pricing. Keep in sync with CONFIG in frontend/index.html (the browser uses it for instant estimates;
the server recomputes every price and ignores the cost the browser sends)."""
import math

from .errors import ApiError

# id: (name, country, lat, lon, has_port)
HUBS = {
    'mumbai': ('Mumbai', 'IN', 19.08, 72.88, True),
    'delhi': ('Delhi', 'IN', 28.61, 77.21, False),
    'chennai': ('Chennai', 'IN', 13.08, 80.27, True),
    'kolkata': ('Kolkata', 'IN', 22.57, 88.36, True),
    'bengaluru': ('Bengaluru', 'IN', 12.97, 77.59, False),
    'hyderabad': ('Hyderabad', 'IN', 17.39, 78.49, False),
    'bhubaneswar': ('Bhubaneswar', 'IN', 20.30, 85.82, False),
    'paradeep': ('Paradeep Port', 'IN', 20.26, 86.67, True),
    'visakhapatnam': ('Visakhapatnam', 'IN', 17.69, 83.22, True),
    'kochi': ('Kochi', 'IN', 9.93, 76.27, True),
    'singapore': ('Singapore', 'SG', 1.35, 103.82, True),
    'dubai': ('Dubai', 'AE', 25.20, 55.27, True),
    'shanghai': ('Shanghai', 'CN', 31.23, 121.47, True),
    'hongkong': ('Hong Kong', 'HK', 22.32, 114.17, True),
    'rotterdam': ('Rotterdam', 'NL', 51.92, 4.48, True),
    'london': ('London', 'GB', 51.51, -0.13, True),
    'frankfurt': ('Frankfurt', 'DE', 50.11, 8.68, False),
    'losangeles': ('Los Angeles', 'US', 34.05, -118.24, True),
    'newyork': ('New York', 'US', 40.71, -74.01, True),
}

GST_PCT = 0.18
MODES = {
    'road': dict(base=1800, per_kg_1000km=5.5, min_charge=3500, fuel_pct=0.09,
                 circuity=1.25, transit_base=1, km_per_day=450, min_kg=1, max_kg=40000),
    'ocean': dict(base=9000, per_kg_1000km=2.2, min_charge=15000, fuel_pct=0.06,
                  circuity=1.35, transit_base=6, km_per_day=700, min_kg=100, max_kg=500000),
    'air': dict(base=6000, per_kg_1000km=9.0, min_charge=8000, fuel_pct=0.12,
                circuity=1.0, transit_base=2, km_per_day=7000, min_kg=1, max_kg=5000),
}


def _round(x):
    """Round half up, like Math.round in the browser."""
    return int(math.floor(x + 0.5))


def _haversine_km(a, b):
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[2], a[3], b[2], b[3]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def hub_name(hub_id):
    return HUBS[hub_id][0] if hub_id in HUBS else hub_id


def estimate(origin, destination, mode, weight_kg):
    o, d, rule = HUBS.get(origin), HUBS.get(destination), MODES.get(mode)
    if not o or not d:
        raise ApiError(400, 'Unknown origin or destination.')
    if not rule:
        raise ApiError(400, 'Transport mode must be road, ocean or air.')
    if origin == destination:
        raise ApiError(400, 'Origin and destination must be different.')
    if not (rule['min_kg'] <= weight_kg <= rule['max_kg']):
        raise ApiError(400, f"Weight for {mode} freight must be between {rule['min_kg']} and {rule['max_kg']} kg.")
    if mode == 'road' and not (o[1] == 'IN' and d[1] == 'IN'):
        raise ApiError(400, 'Road freight is available for domestic (India) lanes only.')
    if mode == 'ocean' and not (o[4] and d[4]):
        raise ApiError(400, 'Ocean freight needs a port at both ends.')
    km = _round(_haversine_km(o, d) * rule['circuity'])
    raw = rule['base'] + rule['per_kg_1000km'] * weight_kg * (km / 1000)
    freight = _round(max(rule['min_charge'], raw))
    fuel = _round(freight * rule['fuel_pct'])
    gst = _round((freight + fuel) * GST_PCT)
    return {
        'km': km, 'freight': freight, 'fuel': fuel, 'gst': gst, 'total': freight + fuel + gst,
        'transitDays': rule['transit_base'] + math.ceil(km / rule['km_per_day']),
    }
