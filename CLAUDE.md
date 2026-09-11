# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Where it stands

The Ilderton spur, catalogued 4 km past the corridor: 1,070 exposures across
20 capture years, 199 of them shipping georeferenced, 80 placed and on disk
(1945, 1946, 1950, 1955, 1967, 1971, 1972, 1974) at about 3.9 GB of cache.
The current Ontario basemap joins the sequence as 2025. Nothing is placed
between 1978 and 2025 — that gap is hand work, not a bug. See `ROADMAP.md`.

Viewer: https://dev.ecoworks.ca:3033. Repo: github.com/smhunt/corridor-timeviewer
(public — see Licensing before committing anything rendered).

## What this is

A local-first pipeline for reading how a place changed from archival aerial photography:
survey an archive over an area of interest, cache scans to disk, place the georeferenced
ones on a MapLibre map as four-corner quads, and export the year-to-year sequence as video.
Nothing is specific to the current subject — swap the AOI profile and the same commands
work anywhere the archives reach.

No tests, no lint config, no package manifest. Dependencies are installed directly, and
numpy must stay below 2 (see below):

```bash
pip install rasterio pillow pyyaml "numpy<2"
```

Without rasterio the tool still catalogues and downloads but cannot place frames.

## Commands

```bash
./harvest.py survey                    # query the archive over the scope, print coverage table
./harvest.py fetch --georef-only       # download only photos shipping a GeoTIFF
./harvest.py --expand 2000 fetch --georef-only   # download a narrower ring than was catalogued
./harvest.py fetch --year 1955 1967    # restrict to capture years
./harvest.py adopt cache/manual --source napl_eodms   # fold in ordered / QGIS-georeferenced scans
./harvest.py manifest                  # rebuild viewer/manifest.json from the cache
./harvest.py --aoi example_corridor survey            # any profile from sources.yaml
./serve.py                             # viewer + tile proxy on https://dev.ecoworks.ca:3033
./serve.py discover <raster-source>    # list layers under an ArcGIS services root
python3 aoi.py [profile]               # resolve an AOI to JSON
```

`fetch` and `adopt` both call `manifest` at the end — **using their own `--expand`**, so a
narrow fetch leaves a narrow manifest. Run `./harvest.py manifest` afterwards to restore
the profile's full `context_m`. Everything is idempotent: `fetch` pulls only what is
missing, and the tile proxy never re-fetches a tile on disk.

## Architecture

Four files, one direction of flow: `sources.yaml` → `aoi.py` → `harvest.py` → SQLite +
`cache/` → `viewer/manifest.json` → `viewer/index.html`, with `serve.py` as the only
runtime between the browser and the disk. `docs/README.md` has the long version.

- **`sources.yaml`** is the whole configuration surface: the `active` AOI, AOI profiles,
  archive endpoints, raster tile sources, and the animation defaults. Adding a place or a
  source means editing this file, not the code.
- **`aoi.py`** resolves a profile to geometry and **two boxes**. `bbox` is the subject (a
  corridor buffered by `buffer_m`, or a rectangle) and is what the viewer frames on.
  `scope` is `bbox` widened by `context_m` or `--expand`, and is what `survey`, `fetch` and
  `manifest` all use. A corridor's Overpass result is cached at
  `cache/aoi/<profile>.geojson` and **never invalidated** — editing `overpass` or
  `search_bbox` does nothing until that file is deleted. `buffer_m` and `context_m` apply at
  resolve time and take effect immediately.
- **`harvest.py`** owns `cache/catalogue.db`. `photo` is one row per exposure; `asset` is one
  row per file on disk, keyed `(photo_id, role)` with role `scan` | `geotiff` | `web`.
  `CREATE TABLE IF NOT EXISTS` cannot add columns to an existing cache, so schema changes
  also go in `MIGRATIONS`. `fetch` commits per photo so an interrupt keeps the ledger.
- **`serve.py`** serves the viewer and `cache/` as static files, proxies
  `/tiles/<source>/z/x/y` through a permanent on-disk cache, and accepts
  `POST /frames/<take>/<n>` from the exporter, printing ffmpeg commands when the frame
  carrying `X-Final: 1` lands.
- **`viewer/index.html`** is one page: MapLibre and fonts from CDN, no build. It reads
  `manifest.json`, builds image layers per year **lazily**, and crossfades by driving
  `raster-opacity`. `APP_VERSION`, `CHANGELOG` and `ROADMAP` constants near the top feed
  the in-app Docs overlay — keep them in step with `CHANGELOG.md` and `ROADMAP.md`.

### Things that will bite

- **The viewer's paths have to agree.** `serve.py` answers `/` with a 302 to `/viewer/`
  (a rewrite would leave the browser's base at `/`), and the page fetches `manifest.json`
  relatively and loads frames as `'../' + web.path`. Move one, move all three.
- **Map readiness is a promise created before any `await`.** MapLibre's `load` fires once
  and does not replay for a listener added later. `init()` awaits `mapReady`; never go back
  to `map.on('load')` after the manifest fetch, or the viewer silently builds nothing
  whenever the map wins the race.
- **MapLibre does nothing in a hidden tab.** No rAF, so no first render and no `load`.
  Browser-automation checks of the map come back blank unless the tab is foregrounded; DOM
  state (the Docs overlay, button presence) can still be checked.
- **Frames are four-corner quads, not lat/lon rectangles.** The exposures are rotated in a
  north-up UTM grid and about a third of each TIFF is nodata. A frame draws only if its
  `web` asset has `corners`; nodata becomes alpha in the `.web.png` beside the TIFF.
- **Lazy loading is held during export.** Scrubbing keeps a six-year window, building the
  pair in play plus one ahead. Both exporters call `buildEverything()` and set `holdAll`,
  because a year still decoding when its frame is captured is a frame of nothing. Any new
  export path must do the same and clear `holdAll` on every exit.
- **Every catalogued year is on the rail**, including years with nothing placed (thin
  notch). The holdings layer draws every exposure for the live year, placed or not.
- **`cache/` is a superset, `manifest.json` is scoped** to the AOI's `scope`.
- **numpy must stay below 2.** rasterio 1.5.1 runs on numpy 1.26.4, but installing it bare
  pulls numpy 2.x, which breaks the globally installed matplotlib 3.8.2, shapely 2.0.3 and
  scikit-learn 1.3.2.
- **Rasters split by key, not by kind.** `kind: xyz` with a `year` is an animation layer
  (Ontario Imagery, as 2025 — confirmed from its Source layer, not the service build date).
  `kind: xyz` with `role: basemap` is drawn once beneath everything (OSM). `format:` sets the
  cache extension and Content-Type; `max_zoom:` stops the viewer requesting tiles past the
  source's deepest zoom. `arcgis_export` is tileable but ignored by the viewer; `geohub` and
  `arcgis_query` are not tileable.
- **A dead tile returns a transparent pixel with HTTP 200**, so a long render never stalls.
  Transient failures get three attempts; a 4xx is final. Failures count at `/stats`, and
  nothing blank is written to disk.
- **`serve.py` serves HTTPS on 3033** (registered in `~/.claude/PORTS.md`) using the mkcert
  cert at `~/Code/.traefik/certs/`, binding all interfaces. Falls back to plain HTTP without
  the cert; `--port`, `--host`, `--http` override. HTML and the manifest are `no-store`.
- **Ontario's WAF blocks directory listing, not services.** `…/rest/services/LIO_Imagery?f=json`
  is 403 but named services answer, which is why `discover` fails there. Find endpoints
  through ArcGIS Online search instead. Middlesex County's server refused connection.

### Data the pipeline cannot supply

The gap is concentrated where the story is. 1950 has 215 scans and 16 georeferenced; 1978
has 118 and none; 1989 through 2001 — the years the track came out — has 309 photos, 35
downloadable scans, and nothing georeferenced. Closing it is manual: order or scan, pin
control points in QGIS against a modern orthophoto, export GeoTIFFs into
`cache/manual/<year>/`, then `adopt`. Road intersections make good control points; the grade
itself does not, since it is the thing being measured.

SWOOP 2006/2010/2015/2020 are open-licenced but not served live — Ontario publishes only
"current best available". They come as 1 km orthophoto tiles from GeoHub (three cover the
corridor) and join through `adopt`.

## Licensing

Western's collection carries a 50-year copyright restriction; the per-record
`Open_Data_Agreement` is preserved in `photo.licence`. **The repo is public**, so `cache/`,
`export/` and `examples/` are gitignored — rendered frames stay out until the licence is
checked. Ontario imagery is OGL-Ontario; OSM is ODbL.
