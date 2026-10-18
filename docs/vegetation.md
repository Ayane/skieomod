# Bake trees and ground cover

With Custom Maps **1.11**, `skieomod build` prepares vegetation before packaging.
The game reads **SKXY binary trees only**. Editable JSON stays in the project;
there is no runtime JSON importer. Update both the tools and loader:

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
skieomod update
```

## Generate vegetation from the heightmap

Add `vegetation` alongside `heightmap` inside the top-level `build` object of
`custom-map.json`. This complete example also applies modest terrain processing:

```json
"build": {
  "heightmap": {
    "file": "Terrain/source-heightmap.png",
    "spacing_meters": 8,
    "elevation_meters": [800, 2200],
    "processing": {
      "resolution": 513,
      "smoothing": {"iterations": 2, "strength": 0.15, "max_delta_meters": 1},
      "thermal_erosion": {"iterations": 8, "talus_degrees": 35, "strength": 0.2, "max_delta_meters": 3},
      "hydraulic_erosion": {"iterations": 4, "strength": 0.06, "rainfall": 1, "max_delta_meters": 1}
    }
  },
  "vegetation": {
    "biome": {
      "tree_line_meters": 1900,
      "alpine_line_meters": 2400,
      "temperature_sea_level_celsius": 15,
      "lapse_rate_celsius_per_km": 6.5,
      "moisture": 0.65,
      "wind_strength": 0.3,
      "wind_direction_degrees": 270
    },
    "trees": {
      "seed": 42,
      "density_per_hectare": 90,
      "min_spacing_meters": 5,
      "max_slope_degrees": 32,
      "tree_line_fade_meters": 150,
      "patch_size_meters": 160,
      "patchiness": 0.6,
      "max_trees": 100000
    },
    "ground_cover": {"texture_size": 256, "max_slope_degrees": 45}
  }
}
```

Run the usual `skieomod build`. No additional conversion command or Lua edit
is needed. `build.vegetation` requires `build.heightmap`, and its defaults enable
both trees and ground cover. Omit `processing` to keep the original relief.
Omit individual processing methods to disable them. All settings are optional
inside the vegetation objects; the schema documents their defaults and limits.

Terrain processing runs in this order: smoothing, thermal erosion, hydraulic
erosion, then optional noise. Smoothing reduces local relief. Thermal erosion
moves material down slopes exceeding the talus angle. Hydraulic erosion uses
D8 steepest-descent drainage and contributing area to move material downhill.
`max_delta_meters` limits the total displacement per vertex **for each method**,
not per iteration. The perimeter is fixed. Rainfall is a dimensionless multiplier.
These are bounded authoring approximations, not the game's proprietary baking
pipeline or a physical water simulation. Depressions are not filled, and the
build does not create rivers, snow or weather schedules.

`processing.resolution` defaults to 513 and permits 33..1025 vertices along the
longest axis. For larger heightmaps, the build interpolates the corrections back
onto the original grid, retaining its fine detail. Increasing resolution costs
more time. Optional `noise` adds reproducible detail:

```json
"noise": {"amplitude_meters": 0.25, "wavelength_meters": 64, "seed": 42}
```

The wavelength must span at least two processing grid intervals. Noise also
preserves the boundary. All processing starts from the original source on every
build; effects never accumulate across builds. Height encoding, actual elevation
range and preview are recalculated from the processed terrain.

Tree candidates come from a seeded, jittered grid. The bake filters them using
the final terrain's elevation and slope, a fade below the tree line, temperature
with altitude, estimated drainage moisture, wind exposure and broad forest
patches. `density_per_hectare` is an upper candidate density; the habitat filters
and minimum spacing reduce the final count. At `max_trees`, a reproducible uniform
subset is retained across the map. The build rejects more than 2,000,000 candidates;
reduce density or split such a map. Tree positions use world metres, centred with
the heightmap: X east, Y south. Custom Maps 1.11.1 anchors each tree to the rendered terrain triangles, including
coarse mesh cells and adaptive cliff seams. This prevents roots from floating
above details that the visible mesh omits. The full rectangular heightmap is
sampled; a tree-count cap selects points across the whole eligible area.

`tree_line_meters` is the upper tree limit; `alpine_line_meters` is the upper limit
for green ground cover and must be higher. Moisture and wind strength range from
0 to 1. Wind direction names where wind **comes from**: 0 north, 90 east, 270 west.
The biome is a static bake preset; it does not replace live seasonal weather.
`analysis_resolution` defaults to 513 (33..1025), for the drainage estimate.

To reserve a clearing, add `trees.exclude`: an array of `[west, north, east, south]`
rectangles in centred world metres. For example `[[ -60, -40, 60, 40 ]]` clears a
120 by 80 m area around the origin. `min_elevation_meters` optionally bounds tree
placement from below. Trees are visual spruce instances; they have no gameplay
collision. The native tree visibility button controls them.

Ground cover is a baked **grass/rock colour texture**, not 3D grass blades.
`texture_size` accepts 16, 32, 64, 128, 256 or 512. Optional `grass_color` and
`rock_color` are three sRGB integers from 0 to 255. The build supplies the complete
mip chain, material and UV mapping, including for rectangular maps. In automatic
mode these rendering settings take precedence over authored albedo/material.
Disable a component with `trees.enabled` or `ground_cover.enabled: false`.

Generated files appear in `Terrain/Generated/` and `Vegetation/Generated/`.
`build-report.json` records processing displacement and tree counts;
`ground-cover.png` previews the growth mask. Trees are written directly as
`forest.skxy`. The package includes a generated Lua entry point beside the
original script, preserving its callbacks and loading the compiled forest once
per session, including save restoration. It overrides manual SKXY importer calls
made through this map's API while automatic trees are enabled. Authored Lua and
manual forest JSON remain unchanged. Rendering overrides live in the package;
turning off generation restores the authored settings. Generated files from an
older bake can remain locally but are not used unless referenced by the new build.
Build updates are backed up together in `.heightmap-backups/` and rolled back
if packaging fails. `skieomod test` prepares the same package without saving
those generated files.

## Compile manually placed trees

`skieomod create map` supplies an editable `Vegetation/forest.json` and this local
build setting:

```json
"build": {"forest": {"file": "Vegetation/forest.json"}}
```

Keep other existing `build` settings. The source is a UTF-8 JSON array, limited
to 32 MiB and 1,000,000 positions:

```json
[
  {"x": 10, "y": -20},
  {"x": 35.5, "y": 8},
  {"x": -12, "y": 40}
]
```

Only finite numeric `x` and `y` fields are accepted. Do not add Z, comments,
duplicate fields or trailing commas. `[]` creates an empty forest. Coordinates
are in world metres, not relative to the heightmap corner. The build converts
them to SKXY v1: a 12-byte magic/version/count header followed by float32 X/Y
pairs in centimetres. The source JSON is excluded from the package. Automatic
trees take precedence over `build.forest`; when they are disabled, `build.forest`
is used again. Remove that setting too if no manual forest is wanted.

Rebuild with `skieomod build`, then test with `skieomod run`. The build generates
the asset declaration and importer wrapper. New projects need no Lua changes.
For scripts that explicitly read an already built binary, use:

```lua
api:load_forest_skxy("Vegetation/Generated/forest.skxy", {
    minimum_scale = 0.8,
    maximum_scale = 1.2,
    batch_size = 256,
})
```

Declare the binary path in `content.assets`, use the `gameplay` permission, and
call once during `map.ready`. Binary imports work for maps and mapmods; insertion
holds the loading screen until complete. There is no `load_forest_json` API in
Custom Maps 1.11. Veymont already uses SKXY. Use `schemas/vegetation.schema.json`
to validate authoring positions and `schemas/custom-map.schema.json` for build
settings.
