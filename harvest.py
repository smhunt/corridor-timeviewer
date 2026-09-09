#!/usr/bin/env python3
"""
harvest.py -- pull the historical air photo catalogue for an area of interest
into a local cache, and keep a manifest the viewer can read.

Commands:
    survey            what exists over the AOI, by year -- no downloads
    fetch             download scans + georeferenced TIFFs into cache/
    adopt <dir>       fold manually-ordered scans (NAPL, Archives of Ontario)
                      into the manifest
    manifest          rebuild viewer/manifest.json from the cache

Everything is idempotent. Re-running fetch only pulls what is missing.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

import aoi

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
DB = CACHE / "catalogue.db"
UA = "airphoto-corridor/1.0 (local archival research cache)"
NULLS = {None, "", "None", "null", "N/A"}


# ---------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS photo (
    photo_id     TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    year         INTEGER,
    season       TEXT,
    roll         TEXT,
    line         TEXT,
    number       TEXT,
    scale        TEXT,
    focal_length TEXT,
    kind         TEXT,           -- Vertical / Oblique
    lon          REAL,
    lat          REAL,
    scan_url     TEXT,
    geotiff_url  TEXT,
    thumb_url    TEXT,
    licence      TEXT,
    notes        TEXT
);
CREATE TABLE IF NOT EXISTS asset (
    photo_id  TEXT NOT NULL,
    role      TEXT NOT NULL,     -- scan | geotiff | web
    path      TEXT NOT NULL,
    bytes     INTEGER,
    sha256    TEXT,
    fetched   REAL,
    -- geographic placement, populated for georeferenced assets
    west REAL, south REAL, east REAL, north REAL,
    corners TEXT,          -- JSON [[lon,lat] x4] tl,tr,br,bl for exact quad overlay
    PRIMARY KEY (photo_id, role)
);
CREATE INDEX IF NOT EXISTS photo_year ON photo(year);
"""


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not
# add these to a cache built by an earlier version, so apply them by hand.
MIGRATIONS = [("asset", "corners", "TEXT")]


def db():
    CACHE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()
    return conn


def config():
    with open(ROOT / "sources.yaml") as fh:
        return yaml.safe_load(fh)


def clean(v):
    return None if v in NULLS else v


# ---------------------------------------------------------------- fetching


def get(url, timeout=90, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001 - surface the last failure
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


def query_arcgis(base, bbox, fields, batch=1000):
    """Page through an ArcGIS FeatureServer layer intersecting bbox."""
    out, offset = [], 0
    while True:
        params = {
            "where": "1=1",
            "geometry": ",".join(str(c) for c in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": ",".join(fields),
            "returnGeometry": "true",
            "resultOffset": offset,
            "resultRecordCount": batch,
            "f": "json",
        }
        url = f"{base}/query?{urllib.parse.urlencode(params)}"
        data = json.loads(get(url))
        if "error" in data:
            raise RuntimeError(data["error"])
        feats = data.get("features", [])
        out.extend(feats)
        if len(feats) < batch or not data.get("exceededTransferLimit"):
            break
        offset += batch
    return out


# ---------------------------------------------------------------- survey


def cmd_survey(args):
    cfg = config()
    area = aoi.resolve(args.aoi, getattr(args, "expand", None))
    bbox = area["scope"]
    src = cfg["archives"]["western_madgic"]
    fields = [
        "PhotoID", "Capture_Year", "Capture_Season", "Roll_Number",
        "Line_Number", "Photo_Number", "Photo_Scale", "Focal_Length",
        "Type__Oblique_or_Vertical_", "Download_Photo", "Download_GeoTIFF",
        "Thumbnail", "Availability", "Open_Data_Agreement", "Notes", "Source",
    ]
    feats = query_arcgis(src["url"], bbox, fields)

    conn = db()
    years = {}
    for f in feats:
        a = f["attributes"]
        geom = f.get("geometry") or {}
        year = int(a["Capture_Year"]) if str(a.get("Capture_Year", "")).isdigit() else None
        pid = f"western:{a.get('PhotoID') or a.get('Roll_Number')}-{a.get('Line_Number')}-{a.get('Photo_Number')}"
        conn.execute(
            "INSERT OR REPLACE INTO photo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid, "western_madgic", year, clean(a.get("Capture_Season")),
                clean(a.get("Roll_Number")), clean(a.get("Line_Number")),
                clean(a.get("Photo_Number")), clean(a.get("Photo_Scale")),
                clean(a.get("Focal_Length")),
                clean(a.get("Type__Oblique_or_Vertical_")),
                geom.get("x"), geom.get("y"),
                clean(a.get("Download_Photo")), clean(a.get("Download_GeoTIFF")),
                clean(a.get("Thumbnail")), clean(a.get("Open_Data_Agreement")),
                clean(a.get("Notes")),
            ),
        )
        row = years.setdefault(year, {"n": 0, "scan": 0, "geo": 0})
        row["n"] += 1
        row["scan"] += bool(clean(a.get("Download_Photo")))
        row["geo"] += bool(clean(a.get("Download_GeoTIFF")))
    conn.commit()

    extent = f"{area['length_km']} km corridor" if area["length_km"] else "rectangle"
    surround = (f", plus {area['context_m'] / 1000:g} km of surroundings"
                if area["context_m"] else "")
    print(f"\n{area['label']}  --  {extent}{surround}")
    print(f"{src['label']}  --  bbox {bbox}\n")
    print(f"  {'year':<6}{'photos':>8}{'scans':>8}{'georef':>8}   coverage")
    print("  " + "-" * 52)
    peak = max((v["n"] for v in years.values()), default=1)
    for y in sorted(k for k in years if k):
        v = years[y]
        bar = "\u2588" * max(1, round(18 * v["n"] / peak))
        print(f"  {y:<6}{v['n']:>8}{v['scan']:>8}{v['geo']:>8}   {bar}")
    tot = sum(v["n"] for v in years.values())
    print("  " + "-" * 52)
    print(f"  {'total':<6}{tot:>8}{sum(v['scan'] for v in years.values()):>8}"
          f"{sum(v['geo'] for v in years.values()):>8}\n")
    print(f"  catalogued in {DB.relative_to(ROOT)}")
    print("  next: ./harvest.py fetch --georef-only\n")


# ---------------------------------------------------------------- fetch


def store(conn, pid, role, url, dest):
    """Download url to dest unless already cached. Returns path or None."""
    row = conn.execute(
        "SELECT path FROM asset WHERE photo_id=? AND role=?", (pid, role)
    ).fetchone()
    if row and (ROOT / row[0]).exists():
        return ROOT / row[0]
    dest.parent.mkdir(parents=True, exist_ok=True)
    # the archive has spaces in filenames; quote the path segment only
    parts = urllib.parse.urlsplit(url)
    safe = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, urllib.parse.quote(parts.path), parts.query, "")
    )
    blob = get(safe)
    dest.write_bytes(blob)
    conn.execute(
        "INSERT OR REPLACE INTO asset (photo_id, role, path, bytes, sha256, fetched)"
        " VALUES (?,?,?,?,?,?)",
        (pid, role, str(dest.relative_to(ROOT)), len(blob),
         hashlib.sha256(blob).hexdigest()[:16], time.time()),
    )
    return dest


def georeference(conn, pid, path):
    """Read bounds from a GeoTIFF and write a web-viewable JPEG beside it."""
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
    except ImportError:
        print("    ! rasterio not installed -- bounds unknown, skipping web render")
        return
    try:
        import numpy as np
        from PIL import Image
        from rasterio.warp import transform as warp_pts

        with rasterio.open(path) as ds:
            if not ds.crs:
                return
            w, s, e, n = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)

            # Exact corner quad. These frames are north-up in UTM but the
            # exposure inside is rotated, so a lat/lon bbox would smear the
            # image; a four-corner quad places it honestly.
            px = [(0, 0), (ds.width, 0), (ds.width, ds.height), (0, ds.height)]
            xs, ys = zip(*[ds.transform * p for p in px])
            lons, lats = warp_pts(ds.crs, "EPSG:4326", list(xs), list(ys))
            corners = json.dumps([[round(a, 7), round(b, 7)]
                                  for a, b in zip(lons, lats)])

            conn.execute(
                "UPDATE asset SET west=?, south=?, east=?, north=?, corners=?"
                " WHERE photo_id=? AND role='geotiff'",
                (w, s, e, n, corners, pid),
            )

            web = path.with_suffix(".web.png")
            if not web.exists():
                scale = 2048 / max(ds.width, ds.height, 1)
                shape = (max(1, int(ds.height * scale)), max(1, int(ds.width * scale)))
                arr = ds.read(1, out_shape=shape, resampling=Resampling.average)
                mask = ds.read_masks(1, out_shape=shape, resampling=Resampling.nearest)
                rgba = np.dstack([arr, arr, arr, mask]).astype("uint8")
                Image.fromarray(rgba, "RGBA").save(web, optimize=True)

            conn.execute(
                "INSERT OR REPLACE INTO asset (photo_id, role, path, bytes, fetched,"
                " west, south, east, north, corners) VALUES (?,'web',?,?,?,?,?,?,?,?)",
                (pid, str(web.relative_to(ROOT)), web.stat().st_size,
                 time.time(), w, s, e, n, corners),
            )
    except Exception as exc:  # noqa: BLE001
        print(f"    ! {pid}: {exc}")


def cmd_fetch(args):
    conn = db()
    where = "geotiff_url IS NOT NULL" if args.georef_only else "scan_url IS NOT NULL"
    if args.year:
        where += f" AND year IN ({','.join(str(int(y)) for y in args.year)})"
    rows = conn.execute(
        f"SELECT photo_id, year, scan_url, geotiff_url FROM photo WHERE {where}"
        " ORDER BY year, roll, line, number"
    ).fetchall()
    if not rows:
        print("Nothing matches. Run `./harvest.py survey` first.")
        return

    print(f"{len(rows)} photos queued ({'georeferenced only' if args.georef_only else 'all scans'})")
    for i, (pid, year, scan, geo) in enumerate(rows, 1):
        base = CACHE / "western" / str(year or "unknown")
        stem = pid.split(":", 1)[1].replace("/", "_")
        print(f"  [{i}/{len(rows)}] {year} {stem}")
        try:
            if geo:
                p = store(conn, pid, "geotiff", geo, base / f"{stem}.tif")
                if p:
                    georeference(conn, pid, p)
            elif scan:
                ext = Path(urllib.parse.urlsplit(scan).path).suffix or ".jpg"
                store(conn, pid, "scan", scan, base / f"{stem}{ext}")
        except Exception as exc:  # noqa: BLE001
            print(f"    ! {exc}")
        # Commit per photo, not per batch. A download is orders of magnitude
        # more expensive than a commit, and an interrupted run that loses the
        # ledger re-fetches gigabytes it already has on disk.
        conn.commit()
    conn.commit()
    cmd_manifest(args)


# ---------------------------------------------------------------- adopt


def cmd_adopt(args):
    """Fold manually-ordered scans into the catalogue.

    Expects cache/manual/<year>/<anything>.tif -- NAPL and Archives of Ontario
    deliveries drop in unchanged.
    """
    conn = db()
    root = Path(args.directory)
    found = 0
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".tif", ".tiff", ".jpg", ".jpeg", ".png"}:
            continue
        year = next((int(p) for p in path.parts if p.isdigit() and 1900 < int(p) < 2100), None)
        pid = f"manual:{path.stem}"
        conn.execute(
            "INSERT OR REPLACE INTO photo (photo_id, source, year, notes)"
            " VALUES (?,?,?,?)",
            (pid, args.source, year, f"adopted from {path}"),
        )
        role = "geotiff" if path.suffix.lower().startswith(".tif") else "scan"
        conn.execute(
            "INSERT OR REPLACE INTO asset (photo_id, role, path, bytes, fetched)"
            " VALUES (?,?,?,?,?)",
            (pid, role, str(path.resolve()), path.stat().st_size, time.time()),
        )
        if role == "geotiff":
            georeference(conn, pid, path)
        found += 1
    conn.commit()
    print(f"Adopted {found} files from {root} as source '{args.source}'")
    cmd_manifest(args)


# ---------------------------------------------------------------- manifest


def cmd_manifest(args):
    conn = db()
    conn.row_factory = sqlite3.Row
    cfg = config()
    area = aoi.resolve(getattr(args, "aoi", None), getattr(args, "expand", None))
    w, s_, e, n = area["scope"]
    # The cache is a superset -- it keeps whatever any past AOI pulled down.
    # The manifest is scoped to the AOI in play so the viewer shows one subject.
    photos = []
    for p in conn.execute(
        "SELECT * FROM photo WHERE lon IS NULL OR (lon BETWEEN ? AND ?"
        " AND lat BETWEEN ? AND ?) ORDER BY year", (w, e, s_, n)
    ):
        assets = {
            a["role"]: {
                "path": a["path"],
                "bounds": [a["west"], a["south"], a["east"], a["north"]]
                if a["west"] is not None else None,
                "corners": json.loads(a["corners"]) if a["corners"] else None,
                "bytes": a["bytes"],
            }
            for a in conn.execute(
                "SELECT * FROM asset WHERE photo_id=?", (p["photo_id"],)
            )
        }
        photos.append({
            "id": p["photo_id"], "source": p["source"], "year": p["year"],
            "roll": p["roll"], "line": p["line"], "number": p["number"],
            "scale": p["scale"], "kind": p["kind"],
            "lon": p["lon"], "lat": p["lat"],
            "scan_url": p["scan_url"], "geotiff_url": p["geotiff_url"],
            "cached": assets,
        })

    years = {}
    for p in photos:
        y = p["year"]
        if not y:
            continue
        row = years.setdefault(y, {"year": y, "photos": 0, "georeferenced": 0, "cached": 0})
        row["photos"] += 1
        row["georeferenced"] += bool(p["geotiff_url"])
        row["cached"] += bool(p["cached"])

    manifest = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "aoi": area,
        "animation": cfg.get("animation", {}),
        "rasters": [
            {"id": k, **{kk: vv for kk, vv in v.items() if kk != "note"}}
            for k, v in cfg["rasters"].items()
        ],
        "years": [years[y] for y in sorted(years)],
        "photos": photos,
    }
    out = ROOT / "viewer" / "manifest.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1))
    print(f"manifest: {len(photos)} photos, {len(years)} years -> {out.relative_to(ROOT)}")


# ---------------------------------------------------------------- cli


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", help="AOI profile from sources.yaml (default: the active one)")
    ap.add_argument("--expand", type=float, metavar="METRES",
                    help="widen the catalogued area around the subject, so the"
                         " surroundings come along. The viewer still opens on"
                         " the subject. Default: the profile's context_m.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("survey", help="list what exists over the AOI").set_defaults(fn=cmd_survey)

    f = sub.add_parser("fetch", help="download scans into cache/")
    f.add_argument("--georef-only", action="store_true",
                   help="only photos that ship a georeferenced TIFF (fastest useful pass)")
    f.add_argument("--year", nargs="*", type=int, help="restrict to these capture years")
    f.set_defaults(fn=cmd_fetch)

    a = sub.add_parser("adopt", help="fold in manually-ordered scans")
    a.add_argument("directory")
    a.add_argument("--source", default="napl_eodms")
    a.set_defaults(fn=cmd_adopt)

    sub.add_parser("manifest", help="rebuild viewer/manifest.json").set_defaults(fn=cmd_manifest)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
