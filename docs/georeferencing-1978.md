# Georeferencing 1978

1978 is the densest zero-coverage year: 118 photos catalogued, 101 downloadable
scans (now sitting in `cache/western/1978/`, ~590 MB), and not one georeferenced.
It contributes nothing to the viewer until someone pins control points.

This is the ROADMAP's "High" item for 1978. Everything below is scoped to
Ilderton village itself rather than the full AOI scope, on the theory that a
handful of frames covering the subject beats mediocre effort spread across all
101 -- doing the whole scope later is the same workflow, just longer.

## The 12 nearest to the village centre (43.0397, -81.4064)

Ranked by distance from the scan's catalogued centre point. Vertical air
photos at this era's scale (~1:20,000-1:15,840, unconfirmed per-frame) run
roughly 3-4 km across, so the first 4-5 already put Ilderton well inside the
frame with overlap to spare; the rest extend coverage outward.

| # | file (`cache/western/1978/`) | dist. from village centre |
|---|---|---|
| 1 | `4303_179_78-179-78.jpg` | 0.7 km |
| 2 | `4303_179_76-179-76.jpg` | 1.3 km |
| 3 | `4304_184_74-184-74.jpg` | 1.4 km |
| 4 | `4304_184_72-184-72.jpg` | 1.9 km |
| 5 | `L5_246-5-246.jpg` | 1.9 km |
| 6 | `4302_176_34-176-34.jpg` | 1.9 km |
| 7 | `4302_176_36-176-36.jpg` | 2.4 km |
| 8 | `4303_179_80-179-80.jpg` | 2.5 km |
| 9 | `4304_184_76-184-76.jpg` | 2.6 km |
| 10 | `4302_176_32-176-32.jpg` | 2.9 km |
| 11 | `4305_184_152-184-152.jpg` | 3.0 km |
| 12 | `L4_91-4-91.jpg` | 3.0 km |

Start with #1-4; they most likely already frame the village core.

## Workflow (QGIS Georeferencer)

1. Open QGIS. Add `https://dev.ecoworks.ca:3033` era imagery as a reference
   layer -- easiest is the `ontario_oiwms` XYZ source already in
   `sources.yaml` (current best available, ~2025), added as an XYZ tile
   layer in QGIS pointed at the same URL. Anything modern and geolocated
   works; the point is a stable reference to click control points against.
2. Raster ▸ Georeferencer. Load one of the JPGs above.
3. Add ≥4 control points, spread near the frame's corners, not clustered in
   the middle -- a 1st-order (affine) transformation is enough for a single
   vertical exposure at this scale, and needs the spread to be well-conditioned.
   **Use road intersections**, not the rail grade itself -- the grade is the
   thing this project measures, so it can't also be the ruler. Ilderton's own
   road grid (Ilderton Rd / Nairn Rd / Denfield Rd intersections) gives solid
   points that haven't moved since 1978.
4. Set output CRS to anything with a defined EPSG code (EPSG:3857 or a local
   UTM zone both work -- `harvest.py`'s `georeference()` reprojects to
   WGS84 itself via `rasterio`, whatever the source CRS is).
5. Export as GeoTIFF into `cache/manual/1978/`, keeping the same stem, e.g.
   `cache/manual/1978/4303_179_78-179-78.tif`. The directory already exists
   and is empty, waiting for output.
6. Repeat for as many of the 12 as you want covered, then:
   ```bash
   ./harvest.py adopt cache/manual --source western_madgic
   ./harvest.py manifest
   ```
   `adopt` infers the year from the `1978` path segment, reads the GeoTIFF's
   real bounds via `rasterio`, and writes the four-corner quad + a web-viewable
   PNG next to it -- same as the automated pipeline does for anything that
   ships a GeoTIFF natively. Each adopted photo gets its own `manual:<stem>`
   id, distinct from the original ungeoreferenced `western:<stem>` catalogue
   row, so nothing is overwritten if you redo one.

`--source western_madgic` (rather than the `adopt` default of `napl_eodms`)
because these are Western's own scans, just georeferenced by hand instead of
by Western -- keep the licence attribution honest (`photo.licence` still
carries Western's 50-year restriction; check before it goes anywhere public).

## Effort estimate

Realistically 5-15 minutes per photo once you have a rhythm (find 4 shared
intersections, click, export) -- so the first 4-5 covering the village core
are a single sitting, not a project.
