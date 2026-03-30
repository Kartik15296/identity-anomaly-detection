# 4.features/geo_utils.py
# Location utilities for feature extraction.
#
# Strategy:
#   - Public IPs  → IP-API.com (cached in memory)
#   - Private IPs → fallback city coordinate dict
#   - Returns travel_speed_kmh as continuous score, not binary flag

import math
import time
import requests
# ─────────────────────────────────────────────
# IN-MEMORY CACHE
# Stores resolved IP → location results
# Avoids hitting IP-API.com for the same IP twice
# { ip_address: { "city": ..., "country": ..., "lat": ..., "lon": ..., "cached_at": ... } }
# ─────────────────────────────────────────────
_ip_cache = {}
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours — IPs don't change ownership that fast


# ─────────────────────────────────────────────
# FALLBACK — private / internal IPs
# IP-API.com can't resolve these
# Maps city name → (lat, lon)
# ─────────────────────────────────────────────
CITY_COORDINATES = {
    "Bangalore":  (12.9716,  77.5946),
    "Mumbai":     (19.0760,  72.8777),
    "Hyderabad":  (17.3850,  78.4867),
    "Delhi":      (28.6139,  77.2090),
    "London":     (51.5074,  -0.1278),
    "New York":   (40.7128, -74.0060),
    "Singapore":  (1.3521,  103.8198),
    "Dubai":      (25.2048,  55.2708),
    "Sydney":    (-33.8688, 151.2093),
    "Tokyo":      (35.6762, 139.6503),
}


def _is_private_ip(ip_address):
    """
    Returns True if IP is a private/internal range.
    These cannot be resolved by any external API.
    Private ranges: 10.x.x.x, 192.168.x.x, 172.16-31.x.x, 127.x.x.x
    """
    if ip_address.startswith("10."):
        return True
    if ip_address.startswith("192.168."):
        return True
    if ip_address.startswith("127."):
        return True
    parts = ip_address.split(".")
    if len(parts) == 4 and parts[0] == "172":
        second = int(parts[1])
        if 16 <= second <= 31:
            return True
    return False


def _is_cache_valid(cached_entry):
    """Check if a cached result is still within TTL."""
    return (time.time() - cached_entry["cached_at"]) < CACHE_TTL_SECONDS


def resolve_ip(ip_address, fallback_city=None):
    """
    Resolves an IP address to location data.
    Returns dict: { city, country, lat, lon, source }

    source tells you where the data came from:
      "cache"    — served from in-memory cache
      "api"      — fresh from IP-API.com
      "private"  — internal IP, used fallback city coordinates
      "unknown"  — could not resolve
    """

    # ── Check cache first ─────────────────────────────────────────
    if ip_address in _ip_cache and _is_cache_valid(_ip_cache[ip_address]):
        result = _ip_cache[ip_address].copy()
        result["source"] = "cache"
        return result

    # ── Private IP → use fallback city ────────────────────────────
    if _is_private_ip(ip_address):
        if fallback_city and fallback_city in CITY_COORDINATES:
            lat, lon = CITY_COORDINATES[fallback_city]
            return {
                "city":    fallback_city,
                "country": "Unknown",
                "lat":     lat,
                "lon":     lon,
                "source":  "private",
            }
        return {
            "city":    fallback_city or "Unknown",
            "country": "Unknown",
            "lat":     None,
            "lon":     None,
            "source":  "private",
        }

    # ── Public IP → call IP-API.com ───────────────────────────────
    try:
        url      = f"http://ip-api.com/json/{ip_address}?fields=status,city,country,lat,lon,query"
        response = requests.get(url, timeout=3)  # 3s timeout — don't block the pipeline
        data     = response.json()

        if data.get("status") == "success":
            result = {
                "city":       data.get("city", "Unknown"),
                "country":    data.get("country", "Unknown"),
                "lat":        data.get("lat"),
                "lon":        data.get("lon"),
                "cached_at":  time.time(),
            }
            # Store in cache
            _ip_cache[ip_address] = result

            result_copy = result.copy()
            result_copy["source"] = "api"
            return result_copy

        else:
            return {
                "city":    fallback_city or "Unknown",
                "country": "Unknown",
                "lat":     None,
                "lon":     None,
                "source":  "unknown",
            }

    except requests.exceptions.RequestException:
        # API unreachable — return fallback gracefully, don't crash pipeline
        if fallback_city and fallback_city in CITY_COORDINATES:
            lat, lon = CITY_COORDINATES[fallback_city]
            return {
                "city":    fallback_city,
                "country": "Unknown",
                "lat":     lat,
                "lon":     lon,
                "source":  "private",
            }
        return {
            "city":    fallback_city or "Unknown",
            "country": "Unknown",
            "lat":     None,
            "lon":     None,
            "source":  "unknown",
        }


def get_distance_km(lat1, lon1, lat2, lon2):
    """
    Haversine distance between two coordinate pairs.
    Returns distance in km, None if any coordinate is missing.
    """
    if None in (lat1, lon1, lat2, lon2):
        return None

    lat1, lon1 = math.radians(lat1), math.radians(lon1)
    lat2, lon2 = math.radians(lat2), math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return round(c * 6371, 2)


def get_travel_speed_kmh(distance_km, hours_apart):
    """
    Returns travel speed in km/h as a continuous score.
    Replaces the old binary impossible_travel flag.

    The risk engine decides what speed is suspicious — not this function.
    We just return the raw number.

    0.0     → same location, no movement
    ~80     → drove to office
    ~450    → domestic flight
    ~900    → international flight
    ~8000+  → physically impossible
    99999   → distance exists but zero time elapsed (clock anomaly)
    None    → distance could not be calculated
    """
    if distance_km is None:
        return None

    if distance_km == 0:
        return 0.0

    if hours_apart <= 0:
        return 99999.0

    return round(distance_km / hours_apart, 2)


def is_ip_in_known_subnets(ip_address, known_subnets):
    """
    Checks if IP starts with any known subnet prefix.
    known_subnets: list of prefixes like ["10.0.1.", "10.0.2."]
    """
    if not known_subnets:
        return False
    return any(ip_address.startswith(subnet) for subnet in known_subnets)


# ─────────────────────────────────────────────
# QUICK TEST — python geo_utils.py
# ─────────────────────────────────────────────
if __name__ == "__main__":

    print("── Private IP (internal office) ──────────────")
    result = resolve_ip("10.0.1.45", fallback_city="Bangalore")
    print(result)

    print("\n── Public IP (attack scenario) ───────────────")
    result = resolve_ip("82.45.12.99")
    print(result)

    print("\n── Same IP again (should hit cache) ──────────")
    result = resolve_ip("82.45.12.99")
    print(result)

    print("\n── Distance: Bangalore to London ─────────────")
    blr = CITY_COORDINATES["Bangalore"]
    lon = CITY_COORDINATES["London"]
    dist = get_distance_km(blr[0], blr[1], lon[0], lon[1])
    print(f"{dist} km")

    print("\n── Travel speed examples ──────────────────────")
    print(f"8035 km / 1h  = {get_travel_speed_kmh(8035, 1)} km/h  ← physically impossible")
    print(f"400  km / 1h  = {get_travel_speed_kmh(400,  1)} km/h  ← short flight")
    print(f"50   km / 1h  = {get_travel_speed_kmh(50,   1)} km/h  ← drove to office")
    print(f"0    km / 1h  = {get_travel_speed_kmh(0,    1)} km/h  ← same location")
    print(f"500  km / 0h  = {get_travel_speed_kmh(500,  0)} km/h  ← clock anomaly")
