"""Per-activity chart data: downsampled time series + per-lap splits + route.

Series come from `get_activity_details` (the same payload enrichment already
uses for HR drift), stored columnar (~300 points) so a run costs a few KB:
    {"t_s": [...], "distance_m": [...], "hr": [...], "speed_mps": [...],
     "elevation_m": [...], "cadence_spm": [...]}
Splits come from `get_activity_splits` (lapDTOs — the watch's autolaps, i.e.
per-km for a standard config).
The GPS route comes from the same details payload (`geoPolylineDTO`, server-side
downsampled via maxPolylineSize), stored as [[lat, lon], ...].
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models import Activity

log = logging.getLogger(__name__)

SERIES_MAX_POINTS = 300
ROUTE_MAX_POINTS = 500  # plenty for a smooth route line, a few KB per run

# series field -> Garmin metricDescriptor key
_SERIES_KEYS = {
    "t_s": "sumDuration",
    "distance_m": "sumDistance",
    "hr": "directHeartRate",
    "speed_mps": "directSpeed",
    "elevation_m": "directElevation",
    "cadence_spm": "directDoubleCadence",
}


def parse_series(details: dict) -> dict | None:
    """Columnar series from a get_activity_details payload; None if unusable."""
    idx = {
        d.get("key"): d.get("metricsIndex")
        for d in details.get("metricDescriptors") or []
    }
    if idx.get("sumDuration") is None:
        return None

    cols: dict[str, list] = {field: [] for field in _SERIES_KEYS}
    for row in details.get("activityDetailMetrics") or []:
        m = row.get("metrics") or []

        def val(key: str):
            i = idx.get(key)
            if i is None:
                return None
            try:
                v = m[i]
            except (IndexError, TypeError):
                return None
            return round(float(v), 2) if v is not None else None

        t = val("sumDuration")
        if t is None:
            continue
        for field, key in _SERIES_KEYS.items():
            cols[field].append(t if field == "t_s" else val(key))

    if len(cols["t_s"]) < 2:
        return None
    # Drop channels the device didn't record at all
    return {f: v for f, v in cols.items() if f == "t_s" or any(x is not None for x in v)}


def parse_route(details: dict) -> list[list[float]]:
    """[[lat, lon], ...] from a get_activity_details payload; [] if no GPS.

    [] is a real answer (indoor activity) and gets cached so we never refetch;
    callers that couldn't fetch at all should leave Activity.route as None.
    """
    points = (details.get("geoPolylineDTO") or {}).get("polyline") or []
    out = []
    for p in points:
        lat, lon = p.get("lat"), p.get("lon")
        if lat is not None and lon is not None:
            out.append([round(float(lat), 6), round(float(lon), 6)])
    return out


def parse_splits(payload: dict) -> list[dict] | None:
    laps = (payload or {}).get("lapDTOs") or []
    out = []
    for lap in laps:
        out.append({
            "index": lap.get("lapIndex"),
            "distance_m": lap.get("distance"),
            "duration_s": lap.get("movingDuration") or lap.get("duration"),
            "avg_hr": lap.get("averageHR"),
            "max_hr": lap.get("maxHR"),
            "avg_speed_mps": lap.get("averageMovingSpeed") or lap.get("averageSpeed"),
            "elevation_gain_m": lap.get("elevationGain"),
            "avg_cadence": lap.get("averageRunCadence"),
            # Structured-workout linkage for execution scoring: the prescribed
            # intensity of this lap (WARMUP/INTERVAL/COOLDOWN/…) and which
            # workout step it belongs to. Present only when the run was executed
            # from a structured workout; None for a free run.
            "intensity": lap.get("intensityType"),
            "step_index": lap.get("wktStepIndex"),
        })
    return out or None


def fetch_and_cache(db: Session, garmin, a: Activity) -> None:
    """Fill in a.series / a.splits / a.route from Garmin if missing (best-effort)."""
    changed = False
    # An activity without a start fix has no GPS track — settle route without
    # a Garmin call (matters for old indoor activities whose series is cached).
    if a.route is None and a.start_lat is None:
        a.route = []
        changed = True
    if a.series is None or a.route is None:
        try:
            details = garmin.get_activity_details(
                a.id, maxchart=SERIES_MAX_POINTS, maxpoly=ROUTE_MAX_POINTS)
            if a.series is None:
                a.series = parse_series(details)
            if a.route is None:
                a.route = parse_route(details)
            changed = a.series is not None or a.route is not None
        except Exception as e:  # noqa: BLE001
            log.debug("series/route fetch failed for %s: %s", a.id, e)
    if a.splits is None:
        try:
            a.splits = parse_splits(garmin.get_activity_splits(a.id))
            changed = changed or a.splits is not None
        except Exception as e:  # noqa: BLE001
            log.debug("splits fetch failed for %s: %s", a.id, e)
    if changed:
        db.add(a)
        db.commit()
