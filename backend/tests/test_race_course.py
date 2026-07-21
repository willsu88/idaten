"""Race course import: KML/KMZ/GPX parsing, My Maps link guard, endpoints."""

from __future__ import annotations

import base64
import datetime as dt
import io
import zipfile

import pytest

from app.course import (COURSE_MAX_POINTS, CourseError, _downsample,
                        fetch_mymaps, parse_course)
from app.models import Race

from conftest import make_user

TODAY = dt.date.today()

# Two courses (like a real race map: half + 10K) plus marker-only placemarks.
KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>Start</name><Point><coordinates>121.539,25.075,0</coordinates></Point></Placemark>
    <Placemark>
      <name>Half</name>
      <LineString><coordinates>
        121.53943,25.07505,0 121.54100,25.07600,0 121.54300,25.07800,0
      </coordinates></LineString>
    </Placemark>
    <Placemark>
      <name>10K</name>
      <LineString><coordinates>121.5394,25.07499,7.66 121.5410,25.0760,7.0</coordinates></LineString>
    </Placemark>
  </Document>
</kml>"""

GPX = b"""<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">
  <trk><name>Course</name><trkseg>
    <trkpt lat="25.07505" lon="121.53943"/><trkpt lat="25.07600" lon="121.54100"/>
  </trkseg></trk>
</gpx>"""


def test_parse_kml_tracks_and_skips_markers():
    tracks = parse_course(KML)
    assert [t["name"] for t in tracks] == ["Half", "10K"]
    assert tracks[0]["points"][0] == [25.07505, 121.53943]  # lon,lat swapped to lat,lon
    assert tracks[0]["distance_km"] > 0


def test_parse_kmz():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", KML)
    assert [t["name"] for t in parse_course(buf.getvalue())] == ["Half", "10K"]


def test_parse_gpx():
    tracks = parse_course(GPX)
    assert tracks[0]["name"] == "Course"
    assert tracks[0]["points"] == [[25.07505, 121.53943], [25.076, 121.541]]


def test_parse_garbage_raises():
    with pytest.raises(CourseError):
        parse_course(b"not xml at all")
    with pytest.raises(CourseError):
        parse_course(b"<?xml version='1.0'?><html></html>")


def test_downsample_keeps_endpoints():
    points = [[float(i), float(i)] for i in range(1200)]
    sampled = _downsample(points)
    assert len(sampled) <= COURSE_MAX_POINTS + 1
    assert sampled[0] == [0.0, 0.0] and sampled[-1] == [1199.0, 1199.0]


def test_mymaps_rejects_non_google_urls():
    with pytest.raises(CourseError):
        fetch_mymaps("https://evil.example.com/?mid=abc")
    with pytest.raises(CourseError):
        fetch_mymaps("https://www.google.com/maps/d/viewer")  # no mid


def _race(db, user_id, **kw):
    r = Race(user_id=user_id, name="Test Half", date=TODAY + dt.timedelta(days=30),
             distance_km=21.1, **kw)
    db.add(r)
    db.commit()
    return r


def _login(client, username="will", password="secret1"):
    assert client.post("/api/auth/login",
                       json={"username": username, "password": password}).status_code == 200


def test_preview_from_uploaded_file(db, user, client):
    _login(client)
    res = client.post("/api/races/course/preview",
                      json={"content_b64": base64.b64encode(KML).decode()})
    assert res.status_code == 200
    assert [t["name"] for t in res.json()["tracks"]] == ["Half", "10K"]


def test_preview_rejects_bad_input(db, user, client):
    _login(client)
    assert client.post("/api/races/course/preview", json={}).status_code == 400
    assert client.post("/api/races/course/preview",
                       json={"content_b64": "!!!not-base64!!!"}).status_code == 400


def test_set_and_clear_course(db, user, client):
    race = _race(db, user.id)
    _login(client)
    course = [[25.07505, 121.53943], [25.076, 121.541]]
    res = client.put(f"/api/races/{race.id}/course", json={"course": course})
    assert res.status_code == 200 and res.json()["course"] == course
    assert client.get("/api/races").json()[0]["course"] == course
    res = client.delete(f"/api/races/{race.id}/course")
    assert res.status_code == 200 and res.json()["course"] is None


def test_course_validation(db, user, client):
    race = _race(db, user.id)
    _login(client)
    assert client.put(f"/api/races/{race.id}/course",
                      json={"course": [[25.0, 121.5]]}).status_code == 422  # < 2 points
    assert client.put(f"/api/races/{race.id}/course",
                      json={"course": [[95.0, 121.5], [25.0, 121.5]]}).status_code == 400


def test_course_is_tenant_scoped(db, user, client):
    other = make_user(db, "gf", "secret2")
    race = _race(db, other.id)
    _login(client)
    assert client.put(f"/api/races/{race.id}/course",
                      json={"course": [[25.0, 121.5], [25.1, 121.6]]}).status_code == 404
