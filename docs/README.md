# Architecture

Four files, one direction of flow. Nothing here knows about railways or about
Ontario; the subject is entirely a matter of configuration.

```
sources.yaml ──► aoi.py ──► harvest.py ──► cache/catalogue.db
   (config)      (where)     (what)         cache/western/<year>/
                                                   │
                                                   ▼
                                          viewer/manifest.json
                                                   │
                              serve.py ────────────┤
                        (tiles, frames, static)    ▼
                                           viewer/index.html
```

| File | Job |
| --- | --- |
| `sources.yaml` | The whole configuration surface: active AOI, AOI profiles, archives, raster services, animation defaults. |
| `aoi.py` | Resolves a profile to geometry and two boxes: the subject, and the wider area to catalogue. |
| `harvest.py` | Owns the catalogue and the cache. Surveys, downloads, georeferences, writes the manifest. |
| `serve.py` | Serves the viewer, proxies and caches remote tiles, receives exported frames. |
| `viewer/index.html` | One dependency-free page. MapLibre, the year rail, the animation, the exporters. |

## Subject versus scope

`aoi.resolve()` returns two boxes, and the difference is the point.

- **`bbox`** — the subject. A corridor buffered by `buffer_m`, or a plain
  rectangle. The viewer opens framed on this.
- **`scope`** — `bbox` widened by `context_m` (or `--expand METRES`). This is
  what gets catalogued, fetched and written into the manifest.

Keeping them apart means you can hold a township of surrounding photography in
the catalogue without the viewer opening on a township-sized rectangle. The
archive flew the surroundings in years it never flew the subject: over the
Ilderton spur, going 4 km out adds 1922, 1945, 1960, 1964, 1965 and 1972.

## Corridors

A `kind: corridor` profile is an Overpass query plus a buffer. The query runs
once, and the resolved centreline is cached at `cache/aoi/<profile>.geojson`.

**That cache is never invalidated.** Editing a profile's `overpass` or
`search_bbox` does nothing until you delete the cached geojson. `buffer_m` and
`context_m` are applied at resolve time and take effect immediately.

## Storage

```
cache/catalogue.db          photo metadata + asset ledger
cache/aoi/<profile>.geojson resolved centreline
cache/western/<year>/       source TIFF, plus a web PNG with nodata as alpha
cache/tiles/<source>/z/x/y  proxied tiles, in the source's own format
export/<take>/              rendered frames
viewer/manifest.json        everything the viewer reads (generated)
```

Two tables. `photo` is one row per exposure from the archive. `asset` is one
row per file on disk, keyed `(photo_id, role)` where role is `scan`,
`geotiff` or `web`.

`CREATE TABLE IF NOT EXISTS` will not add a column to a cache built by an
earlier version, so any schema change after first release also goes in the
`MIGRATIONS` list.

The cache is a superset — it keeps whatever any past AOI pulled down. The
manifest is scoped to the AOI in play, so the viewer shows one subject.

## Placement

Frames go down as **four-corner quads**, never lat/lon rectangles. These
exposures are north-up in a UTM grid with the image rotated inside the frame,
so roughly a third of each TIFF is nodata. A rectangle would smear the image
and let the black wedges cover neighbouring frames. `georeference()` reads the
four pixel corners, warps them to EPSG:4326, and stores them as `corners`;
nodata becomes alpha in the `.web.png` written beside the TIFF.

A frame is drawn only if its `web` asset has `corners`.

## Rasters

Entries under `rasters:` are split by key, not by kind:

| Keys | Behaviour |
| --- | --- |
| `kind: xyz` + `year` | A layer in the animation, at that year. |
| `kind: xyz` + `role: basemap` | Drawn once beneath everything, never animated. |
| `format:` | Cache extension and the Content-Type the proxy announces. |
| `kind: arcgis_export` | Tileable through the proxy; the viewer ignores it. |
| `kind: geohub`, `arcgis_query` | Not tileable. Resolve with `./serve.py discover`. |

## The tile proxy

`/tiles/<source>/<z>/<x>/<y>` fetches once and keeps it. Nothing is ever
re-fetched unless you delete it, which is what makes a 1,300-frame render
repeatable and offline.

A tile the upstream will not serve returns a **transparent pixel with HTTP
200**, after three attempts. A render must not stall or blank on one bad tile.
Failures are counted at `/stats` and logged, and nothing blank is written to
disk, so the next pass tries again.

## Export

The browser cannot encode a high-bitrate MP4, so precise export renders one
PNG per frame, waits for the map to settle, and POSTs each to
`/frames/<take>/<n>`. The frame carrying `X-Final: 1` makes `serve.py` print
the ffmpeg commands. Stdout is line-buffered so that printout survives being
redirected to a file.

## Archives

`western_madgic` is an ArcGIS FeatureServer, queried by envelope and paged
1,000 records at a time. It is the only source here with a public per-photo
API. `napl_eodms` and `archives_ontario` are order-only: deliveries land in
`cache/manual/<year>/` and join through `./harvest.py adopt`.

Ontario's imagery service directory is behind a WAF that blocks folder
listing, but individual services answer. The `Ontario_Imagery_Web_Map_Service_Source`
layer reports the true capture date behind each pixel of the current basemap —
over this corridor, all 91 intersecting footprints are SWOOP 2025.
