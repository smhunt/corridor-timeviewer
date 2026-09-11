# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Where it stands

The Ilderton spur, catalogued 4 km past the corridor: 1,070 exposures across
20 capture years, 199 of them shipping georeferenced, 80 placed and on disk
(1945, 1946, 1950, 1955, 1967, 1971, 1972, 1974) at about 3.9 GB of cache.
The current Ontario basemap joins the sequence as 2025. Nothing is placed
between 1978 and 2025 — that gap is hand work, not a bug. See `ROADMAP.md`.

## What this is

A local-first pipeline for reading how a place changed from archival aerial photography:
survey an archive over an area of interest, cache scans to disk, place the georeferenced
ones on a MapLibre map as four-corner quads, and export the year-to-year sequence as video.
Nothing is specific to the current subject (the Ilderton rail spur) — swap the AOI profile
and the same commands work anywhere the archives reach.

No git repo, no tests, no lint config, no package manifest. Dependencies are installed
directly: `pip install rasterio pillow pyyaml` (rasterio pulls numpy, which `georeference()`
also uses). Without rasterio the tool still catalogues and downloads but cannot place frames.

## Commands

```bash
./harvest.py survey                    # query the archive over the AOI, print coverage table
./harvest.py fetch --georef-only       # download only photos shipping a GeoTIFF (fast useful pass)
./harvest.py fetch --year 1955 1967    # restrict to capture years
./harvest.py adopt cache/manual --source napl_eodms   # fold in hand-ordered/QGIS-georeferenced scans
./harvest.py manifest                  # rebuild viewer/manifest.json from the cache
./harvest.py --aoi example_corridor survey            # any profile from sources.yaml
./serve.py                             # viewer + tile proxy on https://dev.ecoworks.ca:3033
./serve.py discover swoop              # list live ArcGIS layers under a raster source
python3 aoi.py [profile]               # resolve an AOI to JSON, no side effects beyond the cache
```

`fetch` and `adopt` both call `manifest` at the end. Everything is idempotent — re-running
`fetch` pulls only what is missing, and the tile proxy never re-fetches a tile on disk.

## Architecture

Four files, one direction of flow: `sources.yaml` → `aoi.py` → `harvest.py` → SQLite +
`cache/` → `viewer/manifest.json` → `index.html`, with `serve.py` as the only runtime
between the browser and the disk.

- **`sources.yaml`** is the whole configuration surface: the `active` AOI, AOI profiles,
  archive endpoints, raster tile sources, and the animation defaults the viewer opens with.
  Adding a place or a source means editing this file, not the code.
- **`aoi.py`** resolves a profile to a bbox. `kind: bbox` resolves to itself; `kind: corridor`
  posts the profile's Overpass query (with `{{bbox}}` substituted from `search_bbox`) to
  OpenStreetMap, buffers the resulting ways by `buffer_m`, and caches the centreline
  GeoJSON in `cache/aoi/<profile>.geojson`. **That cache is never invalidated** — editing
  a corridor's `overpass` or `search_bbox` has no effect until the cached geojson is deleted.
- **`harvest.py`** owns `cache/catalogue.db`. Two tables: `photo` (archive metadata, one row
  per exposure) and `asset` (one row per downloaded file, keyed `(photo_id, role)` where role
  is `scan` | `geotiff` | `web`). `CREATE TABLE IF NOT EXISTS` cannot add columns to an
  existing cache, so schema changes after first release go in the `MIGRATIONS` list as well.
- **`serve.py`** does three things: serves the viewer, serves `cache/` as static files, and
  proxies `/tiles/<source>/z/x/y` through a permanent on-disk cache. It also accepts
  `POST /frames/<take>/<n>` from the viewer's deterministic exporter and prints the ffmpeg
  commands when the frame carrying `X-Final: 1` lands.
- **`index.html`** is a single dependency-free page (MapLibre + fonts from CDN). It reads
  `manifest.json`, builds one image layer per placed photo grouped by year, and crossfades
  between years by driving `raster-opacity`.

### Things that will bite

- **The viewer must live at `viewer/index.html`.** `serve.py` rewrites `/` to
  `/viewer/index.html`; the page fetches `manifest.json` relatively and loads frames as
  `'../' + web.path`. Those three references have to agree — if the page is ever moved,
  change all of them, not one.
- **Frames are placed as four-corner quads, not lat/lon rectangles.** These exposures are
  rotated inside a north-up UTM grid and roughly a third of each TIFF is nodata. A frame is
  only drawn if its `web` asset has `corners`; nodata becomes alpha in the `.web.png`
  written beside the TIFF. A bbox rectangle would smear the image and let black wedges cover
  neighbouring frames — keep the quad path.
- **`cache/` is a superset, `manifest.json` is scoped.** The cache keeps whatever any past AOI
  pulled down; `cmd_manifest` filters photos to the active AOI's bbox (plus rows with no
  coordinates) so the viewer shows one subject at a time.
- **numpy must stay below 2.** rasterio 1.5.1 runs fine on numpy 1.26.4, but installing it
  bare pulls numpy 2.x, which breaks the globally installed matplotlib 3.8.2, shapely 2.0.3
  and scikit-learn 1.3.2. Install with `pip install rasterio pillow pyyaml "numpy<2"`.
- **Rasters split by key, not by kind.** An `xyz` raster with a `year` becomes a
  layer in the animation (Ontario Imagery 2023 is one). An `xyz` raster with
  `role: basemap` is drawn once beneath everything and never animates (OSM).
  One with neither is fetched by nothing. `format:` decides the cache extension
  and the Content-Type the proxy announces.
- **A dead tile returns a transparent pixel with HTTP 200**, not an error — a
  render walking 1300 frames must not stall on one bad tile. Failures are
  counted in `/stats` and logged, and nothing blank is written to disk.
- **Only `xyz` rasters with a `year` join the animation.** `arcgis_export` sources are tileable
  through the proxy but the viewer ignores them, and `geohub` / `arcgis_query` sources are not
  tileable at all — resolve them with `./serve.py discover` and paste back real `xyz` entries.
- **`serve.py` serves HTTPS on port 3033** (registered in `~/.claude/PORTS.md`), using the
  shared mkcert certificate at `~/Code/.traefik/certs/` and binding all interfaces so
  `https://dev.ecoworks.ca:3033` resolves. It falls back to plain HTTP if the certificate is
  missing; `--port`, `--host` and `--http` override. The viewer's `/tiles/` and `/frames/`
  paths are same-origin, so moving the port needs no other change.
- **Provincial endpoints (`status: untested`) sit behind a WAF** that blocks datacentre egress.
  403s from those are expected in some environments and are not a code bug.

### Data the pipeline cannot supply

The interesting decades are thin: the archive holds hundreds of photos but only ~22 over the
rail corridor ship georeferenced, and the years the track actually came out (1993–2001) have
no downloadable scans at all. Closing that gap is manual work in QGIS — pin control points
on raw scans against a modern orthophoto, export GeoTIFFs into `cache/manual/<year>/`, then
`adopt`. Road intersections make good control points; the grade itself does not, since it is
the thing being measured.

## Licensing

Western's collection carries a 50-year copyright restriction; the per-record
`Open_Data_Agreement` field is preserved in the `photo.licence` column — check it before
publishing frames. Ontario imagery is OGL-Ontario, OSM geometry is ODbL.
