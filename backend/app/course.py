"""Race course import: Google My Maps links + KML/KMZ/GPX files.

A shared race map often holds several course lines (half / 10K / 4K), so
parsing yields candidate tracks and the athlete picks one in the UI. The
chosen polyline is stored on the race as [[lat, lon], ...] — the same shape
as Activity.route, so the frontend renders both with the same map component.
"""

from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile

import httpx

COURSE_MAX_POINTS = 500
FETCH_TIMEOUT_S = 20

_MYMAPS_MID_RE = re.compile(r"[?&]mid=([\w-]+)")


class CourseError(ValueError):
    """User-correctable import problem (bad link, unparseable file, no track)."""


def fetch_mymaps(url: str) -> bytes:
    """KML bytes for a shared Google My Maps link.

    We only lift the map id out of the pasted URL and build the export URL
    ourselves — a caller-supplied URL is never fetched (SSRF guard).
    """
    m = _MYMAPS_MID_RE.search(url)
    if "google.com/maps" not in url or not m:
        raise CourseError(
            "That doesn't look like a Google My Maps link (expected google.com/maps/d/... with mid=...)")
    export = f"https://www.google.com/maps/d/kml?mid={m.group(1)}&forcekml=1"
    try:
        r = httpx.get(export, follow_redirects=True, timeout=FETCH_TIMEOUT_S)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise CourseError(f"Couldn't fetch the map from Google (is it shared publicly?): {e}") from e
    return r.content


def parse_course(data: bytes) -> list[dict]:
    """Candidate tracks from a KML/KMZ/GPX payload.

    Returns [{"name", "distance_km", "points": [[lat, lon], ...]}, ...] with
    points downsampled to COURSE_MAX_POINTS; tracks under 2 points dropped.
    """
    if data[:2] == b"PK":  # KMZ = zip with a .kml inside
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
                if not kml_names:
                    raise CourseError("KMZ file contains no KML document")
                data = z.read(kml_names[0])
        except zipfile.BadZipFile as e:
            raise CourseError("File looks like a KMZ but isn't a valid zip") from e
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise CourseError("Not a readable KML or GPX file") from e

    kind = _localname(root.tag)
    if kind == "kml":
        tracks = _kml_tracks(root)
    elif kind == "gpx":
        tracks = _gpx_tracks(root)
    else:
        raise CourseError(f"Unsupported file type <{kind}> (expected KML or GPX)")

    out = []
    for name, points in tracks:
        if len(points) < 2:
            continue
        out.append({
            "name": name or "Course",
            "distance_km": round(_track_km(points), 2),
            "points": _downsample(points),
        })
    return out


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kml_tracks(root: ET.Element) -> list[tuple[str, list[list[float]]]]:
    """One track per Placemark that carries LineStrings (MultiGeometry merged)."""
    tracks = []
    for pm in root.iter():
        if _localname(pm.tag) != "Placemark":
            continue
        name = next((el.text or "" for el in pm if _localname(el.tag) == "name"), "")
        points: list[list[float]] = []
        for el in pm.iter():
            if _localname(el.tag) != "LineString":
                continue
            for coords in el.iter():
                if _localname(coords.tag) != "coordinates":
                    continue
                for tup in (coords.text or "").split():
                    parts = tup.split(",")  # lon,lat[,alt]
                    if len(parts) >= 2:
                        points.append([round(float(parts[1]), 6), round(float(parts[0]), 6)])
        if points:
            tracks.append((name.strip(), points))
    return tracks


def _gpx_tracks(root: ET.Element) -> list[tuple[str, list[list[float]]]]:
    """One track per <trk> (segments merged) or <rte>."""
    tracks = []
    for trk in root.iter():
        if _localname(trk.tag) not in ("trk", "rte"):
            continue
        name = next((el.text or "" for el in trk if _localname(el.tag) == "name"), "")
        points = [
            [round(float(pt.attrib["lat"]), 6), round(float(pt.attrib["lon"]), 6)]
            for pt in trk.iter()
            if _localname(pt.tag) in ("trkpt", "rtept")
            and "lat" in pt.attrib and "lon" in pt.attrib
        ]
        if points:
            tracks.append((name.strip(), points))
    return tracks


def _downsample(points: list[list[float]], limit: int = COURSE_MAX_POINTS) -> list[list[float]]:
    if len(points) <= limit:
        return points
    stride = math.ceil(len(points) / limit)
    sampled = points[::stride]
    if sampled[-1] != points[-1]:  # keep the true finish
        sampled.append(points[-1])
    return sampled


def _track_km(points: list[list[float]]) -> float:
    return sum(
        _haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)
    ) / 1000


def _haversine_m(a: list[float], b: list[float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(h))
