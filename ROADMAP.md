# Roadmap

Ordered by what most limits the thing the tool exists to do: read a corridor
changing over a century.

## High — the record has holes where the story is

- **Georeference the trail-era years.** 1993, 1998 and 2001 bracket the track
  coming out, and none of them has a downloadable scan. They have to be ordered
  from NAPL or scanned at Weldon, georeferenced in QGIS against a modern
  orthophoto, and dropped into `cache/manual/<year>/` for `adopt`. Road
  intersections hold still across the century and make good control points; the
  grade itself does not, since it is what is being measured.
- **Georeference 1950 and 1978.** 215 and 118 scans over the wider area, none
  georeferenced. These are the densest years in the archive and currently
  contribute nothing to the animation.
- **Fold in SWOOP 2006 / 2010 / 2015 / 2020.** Open licence, 16-30 cm, and
  exactly the decades between the last air photo and today. Ontario publishes
  only "current best available" as a live service, so these come down as 1 km
  orthophoto tiles from GeoHub — three tiles cover the corridor — and join
  through `adopt`. This is the single biggest coverage win available without
  hand-georeferencing anything.

## Medium — the viewer strains as coverage grows

- **Load frames lazily.** Every placed frame becomes an image source at page
  load. At 22 frames that is 62 MB; at 199 it would be roughly 500 MB before
  the map draws anything. Build layers per year on demand, and drop years the
  playhead has left.
- **Fit to holdings.** "Fit corridor" frames the subject. There is no way to
  frame everything actually on disk, which now reaches well past the corridor.
- **Filter holdings by availability.** With 1,063 exposures catalogued, a year
  like 1950 covers the map in dots. Let the rings — the placeable ones — stand
  alone.
- **Per-year opacity or a swipe.** Crossfade compares two years at a time.
  Reading a specific change often wants a wipe across one frame instead.

## Low — worth doing, nothing blocked on them

- **Capture-date labels from the source layer.** Ontario's imagery service can
  report the true flight date behind each pixel, so a modern frame could be
  labelled with when it was actually flown rather than which dataset it is.
- **A second corridor.** Nothing in the pipeline is specific to this one, and
  the claim is untested until a river or a highway has been run through it.
- **Burn label and attribution into exported frames.** `animation.label` and
  `animation.attribution` are in `sources.yaml` and read by nothing.
- **`adopt` could read the sidecar metadata** that NAPL deliveries ship with,
  instead of inferring the year from the directory name.

## Not planned

- **Esri World Imagery Wayback.** Roughly a hundred dated snapshots since 2014,
  which is tempting. Caching tiles to disk for offline rendering is what this
  tool does by design, and that conflicts with Esri's terms. Live-only use
  would work but would break repeatable renders, which is the point of the
  cache.
- **Sentinel-2.** Free, open, every five days since 2015, and 10 m per pixel —
  too coarse to read a rail grade. Good for landscape change, useless for a
  trail surface.
