# Corridor — change over time

A local-first tool for reading how a place changed, built from archival aerial
photography. It surveys what exists over an area, caches the scans to disk,
places the georeferenced ones on a map, and exports the sequence as an
animation.

The first subject is the **Ilderton spur of the London, Huron & Bruce Railway** —
the grade running from Hyde Park north to Ilderton, abandoned around 1995 and
now the Ilderton Rail Trail. The available capture years bracket the whole
transition: active rail through 1989, track lifted somewhere between 1993 and
2001, trail surface thereafter.

Nothing in the pipeline is specific to that corridor, or to Ontario. Add an AOI
profile and the same commands work anywhere the archives reach.

---

## Setup

```bash
pip install rasterio pillow pyyaml
```

`rasterio` reads the georeferencing off each TIFF. Without it the tool still
catalogues and downloads, but cannot place frames on the map.

`serve.py` picks up the shared mkcert certificate at `~/Code/.traefik/certs/`
and serves HTTPS when it is present, plain HTTP when it is not. `--port` moves
it, `--http` forces plaintext.

## Run it

```bash
./harvest.py survey                      # what exists over the AOI, by year
./harvest.py fetch --georef-only         # cache the frames that can be placed
./serve.py                               # https://dev.ecoworks.ca:3033
```

`survey` prints a coverage table. For the rail corridor:

```
  year    photos   scans  georef   coverage
  1942         1       1       0   █
  1946         2       2       2   █
  1950        46      46       0   ██████████████████
  1955        20      20       5   ████████
  1967        11      11      11   ████
  1970         9       9       0   ████
  1971         7       7       1   ███
  1974         3       3       3   █
  1978        35      35       0   ██████████████
  1982         5       0       0   ██
  1989        14      11       0   █████
  1993        28       0       0   ███████████
  1998        21       0       0   ████████
  2001        13       0       0   █████
  total      215     145      22
```

Three columns, three different things. **photos** is what the archive holds.
**scans** is what you can download without visiting the library. **georef** is
what ships with georeferencing and can go straight onto the map. The gap
between the second and third columns is the work: everything in it needs
georeferencing by hand in QGIS before it can join the animation.

## How to read it

**The survey table has three columns because they are three different things.**
*photos* is what the archive holds. *scans* is what you can download without
visiting the library. *georef* is what ships with georeferencing and can go
straight onto the map. The gap between the second and third columns is the
work: everything in it needs georeferencing by hand before it can join the
animation.

**The year rail along the bottom is the record, not a slider.** Horizontal
position is *when*, so the eleven-year hole between 1955 and 1967 reads as a
hole. Notch height is how many frames that year holds. A thin notch is a year
the archive photographed but nobody has placed — it is on the rail because it
is part of the record, and the readout says how many are catalogued but not
cached. The red band marks the years the track came out.

**Rings and dots are holdings.** Every exposure the archive holds for the live
year, whether or not it is on disk. An amber ring is a photo that ships
georeferenced and could be placed today. A grey dot needs georeferencing first.
Faded means already placed. Click one for its roll and status. Without this the
map would say "nothing here" about ground the archive photographed forty times.

**Frames are quads, not rectangles.** Each exposure is rotated inside a
north-up grid, so about a third of every scan is black. Placing them as
four-corner quads keeps the image honest and stops the black wedges covering
the neighbouring frame.

**The corridor is drawn as a surveyor's dashed line**, from OpenStreetMap
rather than from the imagery, so you can see the grade against every year —
including the years the imagery itself has lost it.

**The map opens on the subject but is not confined to it.** The catalogue
reaches `context_m` past the corridor, so panning out finds photography the
archive flew over the surrounding townships, in years it never flew the spur.

## Areas of interest

`sources.yaml` holds AOI profiles. Two kinds:

**bbox** — a rectangle. Simple, good for a town or a site.

**corridor** — a linear feature pulled live from OpenStreetMap and buffered.
This is the more useful one for reading change, because change along a
right-of-way is legible in a way that change across a rectangle is not.

```yaml
ilderton_rail_grade:
  kind: corridor
  overpass: |
    way["railway"="abandoned"]({{bbox}});
    way["highway"~"path|cycleway"]["name"~"Rail Trail",i]({{bbox}});
  search_bbox: [-81.42, 43.00, -81.28, 43.09]
  buffer_m: 900
```

That resolves to 16 OSM ways, 11.57 km of centreline, buffered to a working
bbox. The resolved geometry is cached in `cache/aoi/` and drawn on the map as
a surveyor's dashed line, so you can see the grade against every year's
imagery even where the imagery itself has lost it.

Swap the Overpass query and the same machinery follows a river, a highway, a
shoreline, a pipeline easement:

```bash
./harvest.py --aoi example_corridor survey
```

`context_m` on a profile — or `--expand METRES` on any command — widens what
gets catalogued without moving what the viewer opens on:

```bash
./harvest.py --expand 4000 survey     # the corridor, plus 4 km around it
```

Over the Ilderton spur that is the difference between 210 photos across 14
years and 1,063 across 20 — 1922, 1945, 1960, 1964, 1965 and 1972 exist only
in the surroundings.

## Sources

| Source | Status | What it gives |
| --- | --- | --- |
| Western Libraries Air Photo Collection | working | 1922–2001, direct scan URLs, some georeferenced. London, Elgin, Middlesex, Oxford, Perth. |
| Ontario Imagery / SWOOP | endpoints listed | 2006, 2010, 2015, 2020 orthophoto, Open Government Licence |
| Middlesex County | endpoints listed | 1999–2003, 2006, 2010 |
| NAPL / NRCan EODMS | order by hand | Canada-wide, 1920s onward — the main option outside southwestern Ontario |
| Archives of Ontario | order by hand | MNR forestry flights 1946–1999, province-wide |

Western's collection is the only one with a public per-photo API, and it is
the backbone here. The provincial endpoints in `sources.yaml` returned 403 from
the machine this was built on — that WAF blocks datacentre ranges, not people.
From a home connection they resolve: Ontario Imagery serves 2023 tiles through
the proxy, and it joins the sequence as its own capture year. The SWOOP years
still need resolving — `./serve.py discover swoop` lists what is actually live
so you can fill in the per-year tile URLs.

Ordered scans fold in with:

```bash
./harvest.py adopt cache/manual --source napl_eodms
```

Drop deliveries in `cache/manual/<year>/`. Anything with a CRS gets placed
automatically.

## Caching

Everything lands on disk and stays there.

```
cache/catalogue.db          photo metadata + asset ledger
cache/aoi/<profile>.geojson resolved corridor centreline
cache/western/<year>/       source TIFF, plus a web PNG with nodata as alpha
cache/tiles/<source>/z/x/y  provincial tiles, fetched once
```

Re-running `fetch` only pulls what is missing. The tile proxy in `serve.py`
never re-fetches a tile it already has, which matters when you are rendering a
900-frame animation against a rate-limited provincial service.

Frames are placed as **four-corner quads**, not lat/lon rectangles. These
exposures are rotated inside a north-up UTM grid — roughly a third of each
TIFF's bounding box is nodata — so a rectangle would smear the image and the
black wedges would cover the neighbouring frames.

## Under the photographs

OpenStreetMap is drawn beneath every year, desaturated hard so the imagery
stays the subject. Coverage is partial in most years, so the basemap gives the
uncovered ground somewhere to be and keeps each frame reading as an overlay
rather than floating in black. It also carries the road names, which is what
you navigate by when the photograph is seventy years old.

Tiles are proxied through `serve.py` and cached to disk like every other
raster, so a long render hits the cache instead of the tile server. **Basemap**
in the bottom bar toggles it off.

## The animation

The year rail along the bottom is the main control. Notch height is how many
frames that year holds; horizontal position is **when**, so the eleven-year
hole between 1955 and 1967 reads as a hole rather than as one more step. Drag
to scrub, arrow keys to step capture to capture, space to play.

Controls:

- **Pacing** — *chronological* spaces years by elapsed time. *Even* gives every
  capture equal screen time. Chronological is more honest about the record;
  even is easier to watch.
- **Speed** — seconds per year.
- **Interpolation** — *cut* holds each year and snaps. *Crossfade* blends
  linearly. *Ease* blends on a cubic curve, which reads as more deliberate.
- **Blend length** — how much of each gap the transition occupies. The rest of
  the gap holds still, so a year is legible before it hands over.
- **Camera drift** — a slow push in across the run. Keep it small.

Two ways out:

**WebM** records the canvas in real time and downloads. Fast, fine for sharing,
drops frames if the browser does.

**Frames → ffmpeg** renders each frame deterministically, waits for the map to
settle, and posts it to `export/<take>/`. Nothing is dropped. When the last
frame lands, `serve.py` prints the command:

```
  mp4    ffmpeg -framerate 30 -i export/corridor/frame_%05d.png \
           -c:v libx264 -pix_fmt yuv420p -crf 16 corridor.mp4
  prores ffmpeg -framerate 30 -i export/corridor/frame_%05d.png \
           -c:v prores_ks -profile:v 3 corridor.mov
  gif    ffmpeg -framerate 30 -i export/corridor/frame_%05d.png \
           -vf scale=1000:-1:flags=lanczos corridor.gif
```

## Where this needs hand work

The 22 georeferenced frames over the rail corridor are enough to see the
sequence, but they are thin in exactly the interesting decades. 1950 has 46
scans and none georeferenced; 1978 has 35 and none; 1993 through 2001 — the
years the track actually came out — have no downloadable scans at all and have
to be ordered or scanned at Weldon.

The path forward is QGIS's georeferencer: pin control points on the raw scans
against a modern orthophoto, export as GeoTIFF into `cache/manual/<year>/`, and
`adopt` them. Road intersections along the corridor hold still across the whole
century and make good control points. The grade itself does not — that is the
thing you are measuring.

## Licensing

Western's collection carries a 50-year copyright restriction and a per-record
open data agreement; the `Open_Data_Agreement` field is preserved in the
catalogue. Check it before publishing frames. Ontario imagery is Open
Government Licence – Ontario. OSM geometry is ODbL.
