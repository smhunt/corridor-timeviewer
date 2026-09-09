# Changelog

## [0.2.0] - 2026-09-09

Seeing past the corridor, and knowing what exists out there.

### Added
- **The catalogue reaches past the subject.** `context_m` on a profile, or
  `--expand METRES` on any command, widens what gets catalogued while the
  viewer still opens framed on the subject. `aoi.resolve()` returns both boxes:
  `bbox` is the subject, `scope` is what gets surveyed, fetched and manifested.
  Over the Ilderton spur, 4 km out is the difference between 210 photos across
  14 years and 1,063 across 20 — 1922, 1945, 1960, 1964, 1965 and 1972 exist
  only in the surroundings.
- **Holdings layer.** Every exposure the archive holds for the live year,
  drawn from the catalogue whether or not it is on disk. A ring is placeable
  today, a dot needs georeferencing first; click either for roll and status.
- **Every catalogued year on the rail**, not only years with imagery. The
  viewer already had a thin-notch style and a "catalogued, not cached" readout
  for exactly this; nothing was reaching them.
- **In-app docs** — how to read the rail, the holdings, the quads and the
  exporters, plus roadmap and changelog, behind the **Docs** button.
- `docs/README.md` (architecture and data flow) and `ROADMAP.md`.

### Changed
- Current Ontario imagery is labelled **2025**, not 2023. The service's own
  Source layer reports South Western Ontario Orthophotography 2025 behind all
  91 footprints intersecting the corridor; 2023 was the service build date.

### Notes
- Ontario publishes only "current best available" as a live service. Historical
  SWOOP years are 1 km orthophoto tiles from GeoHub — three cover the corridor —
  and join through `adopt`. Middlesex County's own server refused connection.

## [0.1.0] - 2026-09-06

First working build of the pipeline end to end: survey, fetch, place, serve.

### Added
- **OpenStreetMap under the photographs.** A `role: basemap` raster in
  `sources.yaml`, drawn beneath every year and desaturated so the imagery stays
  the subject, with a **Basemap** toggle in the bottom bar. Proxied and cached
  to disk like every other raster, so a render hits the cache, not the tile server.
- `viewer/` as the served document root. `serve.py` rewrites `/` to
  `viewer/index.html` and `harvest.py` writes `viewer/manifest.json`, so the page
  and its manifest now sit where both expect them.
- HTTPS on the dev server, using the shared mkcert certificate at
  `~/Code/.traefik/certs/`. Binds all interfaces so `https://dev.ecoworks.ca:3033`
  resolves from other devices; falls back to plain HTTP when no certificate is present.
- `--host` and `--http` flags on `serve.py`.
- `CLAUDE.md` covering the pipeline's data flow and the non-obvious constraints
  (four-corner quads, the never-invalidated AOI cache, the cache/manifest scoping split).

### Changed
- Default port 8787 → 3033, registered in `~/.claude/PORTS.md`. The old default sat
  inside the 8xxx range reserved for Docker infrastructure.
- `fetch` commits the asset ledger after every photo rather than every 25.
- Tiles are cached and served in the source's own format (`format:` in
  `sources.yaml`) instead of being labelled `image/jpeg` regardless.
- `ontario_oiwms` marked verified — it resolves from this connection and serves
  2023 orthophoto tiles, so it joins the sequence as its own capture year.

### Fixed
- **The viewer built nothing when the map won a race.** `map.on('load')` was
  registered after `await fetch('manifest.json')`. MapLibre's `load` fires once
  and does not replay for a listener added later, so whenever the map was ready
  before the manifest arrived, the handler never ran: no basemap, no centreline,
  no frames, no year rail, and no error to say why. Readiness is now captured
  synchronously at startup and awaited.
- The viewer and its manifest are served `no-store`, so a reload after a rebuild
  cannot come back stale. Tiles and scans keep their immutable caching.
- `/` now redirects to `/viewer/` instead of being rewritten server-side. The
  rewrite left the browser's base URL at `/`, so the viewer's relative
  `manifest.json` 404'd and the page reported "No manifest".
- A tile the upstream will not serve now returns the transparent pixel the code
  already described, instead of a 502 that surfaces as an error in the viewer
  and can stall a render. Three attempts before giving up, and the blank is
  neither written to disk nor cached, so the next pass retries.
- Client disconnects (a viewer scrubbing the timeline aborts tile requests by
  the dozen) no longer print a stack trace each, which was burying the ffmpeg
  command that a finished render prints.
- `stdout` is line-buffered, so that ffmpeg command appears even when the
  server is left running with output redirected to a file.
- Image layers no longer pass a `beforeId` that does not exist when the AOI is
  a plain `bbox` — a corridor has a centreline to sit under, a rectangle does not.
- An interrupted `fetch` no longer discards the whole asset ledger. With a
  batch commit every 25 photos, a georef-only run of 22 committed nothing until
  the very end — so an interrupt left gigabytes of TIFFs on disk that the next
  run could not see and re-downloaded.
