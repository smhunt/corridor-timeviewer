"""
aoi.py -- resolve an area of interest from sources.yaml.

A bbox profile resolves to itself. A corridor profile resolves by asking
OpenStreetMap for the linear feature, buffering it, and caching the result so
later commands do not re-query Overpass.

Nothing here is specific to rail grades or to Ontario. Point a corridor
profile at a river, a highway, a shoreline, a pipeline right-of-way, and the
rest of the pipeline behaves identically.
"""

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
UA = "airphoto-corridor/1.0 (local archival research cache)"


def config():
    with open(ROOT / "sources.yaml") as fh:
        return yaml.safe_load(fh)


def _overpass(cfg, profile):
    """Fetch the corridor's ways, cached on disk by profile name."""
    name = profile["_name"]
    cached = CACHE / "aoi" / f"{name}.geojson"
    if cached.exists():
        return json.loads(cached.read_text())

    s, w, n, e = (profile["search_bbox"][1], profile["search_bbox"][0],
                  profile["search_bbox"][3], profile["search_bbox"][2])
    body = profile["overpass"].replace("{{bbox}}", f"{s},{w},{n},{e}")
    query = f"[out:json][timeout:90];\n({body});\nout geom;"

    req = urllib.request.Request(
        cfg.get("overpass_url", "https://overpass-api.de/api/interpreter"),
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = json.load(r)

    lines = []
    for el in raw.get("elements", []):
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        lines.append({
            "type": "Feature",
            "properties": {
                "osm_id": el["id"],
                **{k: v for k, v in (el.get("tags") or {}).items()
                   if k in {"name", "railway", "highway", "waterway", "operator"}},
            },
            "geometry": {"type": "LineString",
                         "coordinates": [[p["lon"], p["lat"]] for p in geom]},
        })
    fc = {"type": "FeatureCollection", "fetched": time.time(), "features": lines}
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(fc))
    return fc


def _buffer_bbox(fc, metres):
    """Envelope of the corridor, expanded by a buffer in metres."""
    pts = [p for f in fc["features"] for p in f["geometry"]["coordinates"]]
    if not pts:
        raise SystemExit(
            "Corridor query returned no ways. Widen search_bbox or loosen the "
            "Overpass tags in sources.yaml."
        )
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    mid = math.radians((min(lats) + max(lats)) / 2)
    dlat = metres / 111_320
    dlon = metres / (111_320 * max(math.cos(mid), 0.01))
    return [min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat]


def _expand_bbox(bbox, metres):
    """Widen a bbox by a margin in metres, for surveying the surroundings."""
    w, s, e, n = bbox
    mid = math.radians((s + n) / 2)
    dlat = metres / 111_320
    dlon = metres / (111_320 * max(math.cos(mid), 0.01))
    return [w - dlon, s - dlat, e + dlon, n + dlat]


def resolve(name=None, expand_m=None):
    """Return a dict describing the active AOI.

    Keys: name, label, bbox, centre, and for corridors also geometry (a
    GeoJSON FeatureCollection of the centreline) and length_km.

    `bbox` is the subject itself and is what the viewer frames on. `scope`
    is `bbox` widened by `expand_m` (or the profile's `context_m`), and is
    what gets catalogued, fetched and put in the manifest. Keeping them
    apart means you can survey a whole township of surrounding photography
    without the viewer opening on a township-sized rectangle.
    """
    cfg = config()
    name = name or cfg["active"]
    profiles = cfg["aoi_profiles"]
    if name not in profiles:
        raise SystemExit(
            f"Unknown AOI '{name}'. Available: {', '.join(sorted(profiles))}"
        )
    p = dict(profiles[name], _name=name)

    if p["kind"] == "bbox":
        bbox, geom, length = p["bbox"], None, None
    elif p["kind"] == "corridor":
        geom = _overpass(cfg, p)
        bbox = _buffer_bbox(geom, p.get("buffer_m", 750))
        length = round(sum(
            _haversine(c[i], c[i + 1])
            for f in geom["features"]
            for c in [f["geometry"]["coordinates"]]
            for i in range(len(c) - 1)
        ) / 1000, 2)
    else:
        raise SystemExit(f"AOI kind '{p['kind']}' not supported.")

    margin = p.get("context_m", 0) if expand_m is None else expand_m
    scope = _expand_bbox(bbox, margin) if margin else list(bbox)

    return {
        "name": name,
        "label": p.get("label", name),
        "kind": p["kind"],
        "subject": (p.get("subject") or "").strip() or None,
        "bbox": [round(v, 6) for v in bbox],
        "scope": [round(v, 6) for v in scope],
        "context_m": margin,
        "centre": [round((bbox[0] + bbox[2]) / 2, 6), round((bbox[1] + bbox[3]) / 2, 6)],
        "buffer_m": p.get("buffer_m"),
        "length_km": length,
        "geometry": geom,
    }


def _haversine(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


if __name__ == "__main__":
    import sys
    a = resolve(sys.argv[1] if len(sys.argv) > 1 else None)
    g = a.pop("geometry", None)
    print(json.dumps(a, indent=2))
    if g:
        print(f"centreline: {len(g['features'])} ways")
