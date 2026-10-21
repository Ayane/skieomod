# Maps larger than 8 km

Custom Maps supports rectangular terrain beyond 8 km. Map extent and source
resolution are independent of the game's native terrain grid.

## Create a larger project

With `skieomod` 1.7 or later:

```sh
skieomod create map --output large-map --name "Large resort" --size 16000 12000 --spacing 8
skieomod build large-map
skieomod test large-map
skieomod run large-map
```

This creates a 16 × 12 km starter slope with a 2001 × 1501 R16 heightmap.
Both dimensions are in metres and must be positive multiples of `--spacing`.
Without these options, the template remains 1024 × 1024 m at 16 m spacing.
Replace the starter slope with your own elevation data to create a real map.
The generated `docs/terrain.md` describes its exact dimensions and encoding.

The template limits the source to 32 MiB and 16,384 vertices per axis. Choose
a larger spacing for a wider extent. These limits protect creation time and
match the native helper's per-axis limit; they are not an 8 km world-size limit.

## Choose the resolution

For each axis, `size_meters = (vertices - 1) × spacing_meters`.
The R16 contains `width × height × 2` bytes. Doubling both dimensions at the
same spacing quadruples source size and terrain work.

| Terrain consumer | Resolution |
| --- | --- |
| Portable source | Your declared R16 dimensions and spacing |
| Visible terrain and collision | Source sampled at `terrain.runtime.sample_step`, with bounded cliff refinement |
| Native Landscape, terrain cache and snow input | 2017 × 2017 samples rasterized from the visible triangle surface across the full extent |

Native spacing is `width_meters / 2016` in X and `length_meters / 2016` in Y.
A 16 × 12 km map therefore has about 7.94 × 5.95 m native spacing. Increasing
source resolution preserves more detail for rendering and physical collision;
it does not add pixels to the native snow grid. Since 1.24.8, native heights
follow the same simplified triangles, refined cliffs and stitched edges as
the visible ground. Snow is additionally refined near buildings and lift
stations to keep native terrain-pad deformation local; those extra vertices
still follow the original visible surface. Details omitted by that mesh no
longer put the simulated ground above or below the rendered snow. The portable
R16 is preserved.

Creation automatically chooses a rendering stride targeting roughly 262,144
base cells. For the example above, `sample_step` is 4, so its base mesh samples
the source every 32 m. Lower it for more detail or increase it for faster
loading. `tile_quads` controls the size of individual mesh sections. Steep
cells receive at most four subdivisions per axis, with a global budget of
16,384 refined cells. Tree counts and scripted objects also affect loading.
Test loading, snow tools and gameplay on the target machines before sharing
a much larger map. No maximum playable world extent has been established.

## Veymont 0.6: Mont Aiguille included

The Featured map by **Albatar (Élie Millon)** now covers
**8.064 × 12.096 km**, with a **2017 × 3025** source grid at **4 m**.
The extra terrain extends north and south around the original centre and
includes Mont Aiguille. Its native cache uses 4 × 6 m spacing; the base visible
mesh uses 16 m spacing before cliff refinement.

All elevation samples from the former 8.064 km square remain byte-identical.
The nine lift alignments, twenty trails and base-area placements remain at
the same world coordinates. The original 255,667 forest points are retained;
127,833 additional points populate only the new bands, for 383,500 trees.
Existing saves are kept; start a new Veymont session to inspect the new extent.

For users of CLI 1.6 or earlier, close the game and update the tool once:

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
skieomod update
```

The updater adds the new example beside older versions and preserves local
maps. The menu selects the newest installed Veymont version; its card shows
the 8.06 × 12.10 km extent in New Game.

Terrain: IGN LiDAR HD Isère 2021–2022, provided through
[CRAIG](https://www.craig.fr/services/donnees-altimetriques), Open Licence v2.0.
Layout and landmark coordinates: © OpenStreetMap contributors, ODbL 1.0;
[Mont Aiguille summit node](https://www.openstreetmap.org/node/410304217).
Its declared summit elevation is geographic metadata; the visible surface
comes from the sampled LiDAR terrain without an artificial height correction.

Veymont 0.6.1 replaces four defective 500 m source tiles around Les Deux
with IGN's reclassified MNT published on 20 February 2025. A 32 m margin
joins the replacement to the surrounding terrain. All changes lie in the
northern extension; the former square remains unchanged. See
[terrain repair sources and reproduction](terrain-repairs.md).
