"""
coordinate_transform.py
Datum transformation between the two coordinate systems used side-by-side
in this dashboard's source data:

  - "WGS84"           EPSG:4326 — the datum the GIS shapefile package
                       (hermes_NPL_new_wgs*.shp / Protected_Area) is
                       digitised in. This is also the global web-map
                       standard (Plotly Scattermapbox, Google Maps, GPS).

  - "Everest 1830"    The Survey Department of Nepal's historical
                       trigonometric-survey datum, on the Everest 1830
                       ellipsoid. Most DoED licence-sheet Lat/Long entries
                       were originally recorded against this datum
                       (topo-sheet coordinates), NOT WGS84 — even though
                       the sheet columns are just labelled "Latitude" /
                       "Longitude" with no datum noted.

Mixing the two without conversion silently shifts points by a few hundred
metres — enough to place a plant on the wrong side of a district or
protected-area boundary. This module makes BOTH directions available and
lets the caller pick one canonical system for internal storage/GIS
overlay while still letting the UI *display* coordinates in the other.

Method: a 3-parameter geocentric (Molodensky) datum shift, which is the
standard practical approach for a datum with no officially published
7-parameter Helmert set. The (dX, dY, dZ) values below are the shift
commonly cited by the Survey Department of Nepal / Survey of India for
Everest 1830 (India & Nepal) -> WGS84, consistent with the same
approximate shift used on Indian/Nepali topographic sheets:

    dX = +295 m, dY = +736 m, dZ = +257 m   (Everest 1830 -> WGS84)

These are deliberately exposed as module-level constants (not buried
inside the function) so they can be overridden if DoED / Survey
Department supplies more precise locally-surveyed parameters later —
see EVEREST_TO_WGS84_SHIFT below. Accuracy with these approximate
parameters is on the order of a few metres to a few tens of metres,
which is more than sufficient at the scale this dashboard maps things
(district/province polygons, licence-area markers) — it is NOT
survey-grade and should not be used to fix cadastral boundaries.
"""

import math

# ── Ellipsoid parameters ────────────────────────────────────────────────────
WGS84_A, WGS84_F = 6378137.0, 1 / 298.257223563
EVEREST_A, EVEREST_F = 6377301.243, 1 / 300.8017

# ── Datum shift (Everest 1830 -> WGS84), metres, geocentric X/Y/Z ──────────
# Override these three numbers if a more precise, locally-surveyed shift
# becomes available for a specific district/project.
EVEREST_TO_WGS84_SHIFT = (295.0, 736.0, 257.0)

CRS_WGS84 = "WGS84"
CRS_EVEREST = "EVEREST1830"

CRS_LABELS = {
    CRS_WGS84: "WGS 84 (GIS / GPS standard)",
    CRS_EVEREST: "Everest 1830 (DoED survey datum)",
}


def _geodetic_to_geocentric(lat, lon, h, a, f):
    e2 = f * (2 - f)
    lat_r, lon_r = math.radians(lat), math.radians(lon)
    sin_lat, cos_lat = math.sin(lat_r), math.cos(lat_r)
    n = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
    x = (n + h) * cos_lat * math.cos(lon_r)
    y = (n + h) * cos_lat * math.sin(lon_r)
    z = (n * (1 - e2) + h) * sin_lat
    return x, y, z


def _geocentric_to_geodetic(x, y, z, a, f):
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(6):  # iterate to convergence — 4-5 passes is plenty
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
        h = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - e2 * n / (n + h)))
    sin_lat = math.sin(lat)
    n = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
    h = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), h


def everest_to_wgs84(lat, lon, h=0.0):
    """(lat, lon) on the Everest 1830 / DoED survey datum -> WGS-84 degrees."""
    if lat is None or lon is None:
        return None, None
    dx, dy, dz = EVEREST_TO_WGS84_SHIFT
    x, y, z = _geodetic_to_geocentric(lat, lon, h, EVEREST_A, EVEREST_F)
    lat2, lon2, _ = _geocentric_to_geodetic(x + dx, y + dy, z + dz, WGS84_A, WGS84_F)
    return lat2, lon2


def wgs84_to_everest(lat, lon, h=0.0):
    """(lat, lon) on WGS-84 -> Everest 1830 / DoED survey datum degrees."""
    if lat is None or lon is None:
        return None, None
    dx, dy, dz = EVEREST_TO_WGS84_SHIFT
    x, y, z = _geodetic_to_geocentric(lat, lon, h, WGS84_A, WGS84_F)
    lat2, lon2, _ = _geocentric_to_geodetic(x - dx, y - dy, z - dz, EVEREST_A, EVEREST_F)
    return lat2, lon2


def transform(lat, lon, from_crs, to_crs):
    """Generic entry point used by the UI's CRS toggle. from_crs/to_crs are
    one of CRS_WGS84 / CRS_EVEREST. No-op if they're the same system."""
    if lat is None or lon is None or from_crs == to_crs:
        return lat, lon
    if from_crs == CRS_EVEREST and to_crs == CRS_WGS84:
        return everest_to_wgs84(lat, lon)
    if from_crs == CRS_WGS84 and to_crs == CRS_EVEREST:
        return wgs84_to_everest(lat, lon)
    raise ValueError(f"Unknown CRS pair: {from_crs} -> {to_crs}")


# ── Sanity check (Kathmandu, Tribhuvan Airport reference point) ────────────
if __name__ == "__main__":
    lat, lon = 27.6966, 85.3591  # WGS-84
    e_lat, e_lon = wgs84_to_everest(lat, lon)
    back_lat, back_lon = everest_to_wgs84(e_lat, e_lon)
    print(f"WGS84        : {lat:.6f}, {lon:.6f}")
    print(f"-> Everest   : {e_lat:.6f}, {e_lon:.6f}")
    print(f"-> back WGS84: {back_lat:.6f}, {back_lon:.6f}  (round-trip check)")
