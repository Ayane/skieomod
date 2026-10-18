"""Self-contained scripts and authoring guides shipped with every project."""
from __future__ import annotations


MAP_SCRIPT = '''-- Map API 1.0 entry point, shared by maps and mapmod dependencies.
-- The loader calls this function once per map session and supplies its API.
-- Register callbacks here; wait for map.ready before changing the world.
-- See docs/scripting.md for events, timers and asset declarations.
return function(api)
    -- This callback runs after the terrain is available, including on save loads.
    -- Keep it short; use API timers for work that needs to run later.
    api:on("map.ready", function()
        api:log("Welcome! Your creation is ready.")

        -- Example (uncomment to run): add starting funds to the current session.
        -- Requires the gameplay permission declared in the manifest.
        -- api.game:add_funds(1000)
    end)

    -- Release your own session resources here when the map closes.
    -- The loader automatically cancels API timers and unregisters callbacks.
    api:on("map.unloading", function()
        api:log("Your creation is unloading.")
    end)
end
'''

UE4SS_SCRIPT = '''-- UE4SS entry point: loaded when Ski-E-O! starts.
-- Close the game, edit this file, then use skieomod run to test changes.
-- Unlike a mapmod, this script uses UE4SS directly and returns no API function.
-- See docs/scripting.md before adding hooks or accessing game objects.

-- Change this prefix to distinguish your messages in the UE4SS log.
local MOD_NAME = "My Ski-E-O! mod"
print("[" .. MOD_NAME .. "] Loaded successfully\\n")

-- Add your initialization here. Game/world objects may not exist at startup;
-- register a suitable UE4SS hook before accessing them, and check validity.
-- UE4SS mod dependencies are activated at the next game startup.
'''

MAP_FOREST_SCRIPT = MAP_SCRIPT.replace(
    '        api:log("Welcome! Your creation is ready.")',
    '''        api:log("Welcome! Your creation is ready.")

        -- Edit Vegetation/forest.json; build compiles it to SKXY. Z follows terrain.
        -- The loader holds the loading screen until insertion is complete.
        -- This also rebuilds the forest when restoring a save.
        -- See docs/vegetation.md; Custom Maps 1.11 or later is required.
        api:load_forest_skxy("Vegetation/Generated/forest.skxy")''')

VEGETATION_DOC = '''# Bake trees and ground cover

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
'''


def documentation(kind, manifest):
    """Return UTF-8 project docs without requiring access to this repository."""
    name = manifest['metadata']['name']
    identifier = manifest['id']
    source = 'custom-map.json' if kind == 'map' else 'custom-mod.json'
    suffix = '.skieomap' if kind == 'map' else '.skieomod'
    if kind == 'map':
        terrain = manifest['terrain']
        width, height = terrain['source']['vertices']
        spacing = terrain['source']['spacing_meters']
        extent = ' x '.join(f'{value:g}' for value in terrain['size_meters'])
        origin = terrain['origin_centimeters']
    runtime = {
        'map': f'An independent map with a generated {extent} metre slope.' if kind == 'map' else '',
        'mod': 'A UE4SS mod loaded when the game starts. Close the game before testing changes.',
        'mapmod': 'A Map API mod loaded as a map dependency. Local run creates a preview map automatically.',
    }[kind]
    readme = f'''# {name}

{runtime}

Package ID: `{identifier}`. Initial version: `0.1.0`.

## First steps

Run these commands from this project directory:

```sh
skieomod build
skieomod test
skieomod run
```

Creation, validation and builds need Python 3.10+ and the installed `skieomod`
command. Running needs Ski-E-O!, Steam and Custom Map/UE4SS; use `skieomod setup`
to detect the game and install the loader. For Lua syntax checks, install Lua 5.4
and run `skieomod test --check-scripts`.

## Project files

| File | Purpose |
| --- | --- |
| `{source}` | Package identity, metadata, dependencies and runtime content |
| `Scripts/main.lua` | Commented Lua entry point to customize |
| `workshop.json` | Workshop settings, initially private |
| `preview.png` | Placeholder preview; replace with your own screenshot |
| `docs/` | Manifest, scripting, development and publication guides |
| `.gitignore` | Keeps generated `bin/` and `obj/` out of source control |
'''
    if kind == 'map':
        readme += f'| `Terrain/heightmap.r16` | {width} x {height} little-endian unsigned 16-bit elevation samples |\n'
        readme += '| `Vegetation/forest.json` | Editable tree positions in world metres |\n'
        readme += '''
## Desktop workshop

Run `skieomod editor .` to open this source project in the native desktop
workshop. Import your own R16 or PNG16 heightmap, sculpt the relief, paint trees,
configure erosion and vegetation, and use Save, Build, Test and Play. The Qt
workshop includes a 3D viewport and separate trigger, resource and object
editors. Its dependencies are installed with skieomod 1.14 or later.

'''
    readme += f'''
`skieomod build` produces `bin/{identifier}-0.1.0{suffix}`. Only content referenced
by the manifest is packaged; this README and the authoring guides remain in the
source project. Share the source directory separately to include its documentation.

## Guides

- [Manifest fields and dependencies](docs/manifest.md)
- [Lua entry point and runtime](docs/scripting.md)
- [Build, test, run and troubleshooting](docs/development.md)
- [Prepare a Steam Workshop article](docs/workshop.md)
'''
    if kind == 'map':
        readme += '- [Terrain encoding and preview](docs/terrain.md)\n'
        readme += '- [Place trees with JSON](docs/vegetation.md)\n'
    elif kind == 'mapmod':
        readme += '- [Step-by-step mapmod tutorial and fox sources](https://skieomod.emillon.fr/tutorials/mapmods/)\n'
    readme += '''
Use `skieomod help`, `skieomod help create` or `skieomod COMMAND --help` for CLI
examples. `skieomod new` remains an alias for `skieomod create`.
'''
    manifest_doc = f'''# Manifest reference

Edit `{source}` as strict JSON: comments and trailing commas are not supported.
These notes explain fields outside the JSON so it stays directly installable.
Run `skieomod test` after changes.

| Field | Meaning |
| --- | --- |
| `format.name`, `format.version` | Package format; keep the template values unless migrating formats |
| `id` | Stable namespaced lowercase ID, e.g. `author.my-creation`; no spaces or filesystem paths |
| `metadata.name` | Display title |
| `metadata.version` | Package semantic version, initially `0.1.0`; increment for releases |
| `metadata.authors` | Credits; replace `Your name` if you did not pass `--author` |
| `metadata.description` | Describe the content before publication |
| `metadata.language` | Content language tag, initially `en`; e.g. `fr` |
| `metadata.license` | Initially `MIT`; choose your license and supply its terms and resource credits before sharing |
| `dependencies` | Required or optional mod dependencies; an empty list needs no other mods |

## Dependencies

Add a mod to `dependencies`, for example:

```json
{{"id": "author.snow-tools", "version": "^1.0.0", "workshop_id": "1234567890"}}
```

`id` identifies the package. `version` describes compatibility (`*`, `=1.0.0`,
`^1.0.0`, `~1.0.0` or comparison ranges). `workshop_id` is a decimal **string**
identifying its Steam article; required dependencies need it before publication.
Steam supplies the current article content, not historical package versions.
Set `optional: true` for an optional dependency. Cycles and version conflicts fail
validation. `skieomod test --check-dependencies` checks locally installed Workshop
manifests; it does not download missing dependencies.
'''
    if kind == 'mod':
        manifest_doc += '''
## UE4SS content

`runtime: "ue4ss"` loads at game startup. `install_directory` names the folder
under UE4SS/Mods; it must contain only letters, digits, `_` or `-` and must not
use a reserved loader directory. `files` lists every file to package, including
`Scripts/main.lua`. Add new scripts, data or DLL paths there before building.
Paths are relative to the project and use `/`. A UE4SS mod has no Map API
`script` declaration.
'''
    else:
        manifest_doc += '''
## Map API script

`script.language: "lua"`, `script.api: "1.0"` and `script.entry:
"Scripts/main.lua"` select the entry point. `script.permissions: ["gameplay"]`
allows documented gameplay actions. Use the supplied `api`; ordinary scripts
do not have unrestricted filesystem, process or Unreal access.
'''
        if kind == 'map':
            manifest_doc += '''
`terrain` defines the source heightmap, dimensions, elevation range and preview;
see [terrain.md](terrain.md). `content.assets` lists additional portable source
files, readable with `api:read_asset(path)`. The terrain source and script entry
are already packaged automatically: do not list them again in `content.assets`.
Maps use source data and cannot embed cooked `.pak`, `.ucas` or `.utoc` containers.
'''
        else:
            manifest_doc += '''
`runtime: "map-api"` runs in a dependent map session before the map's own script.
`files` lists every packaged file, including `script.entry`. To read additional
data with `api:read_asset(path)`, list each path in both `files` and
`content.assets`. Paths are relative to the project and use `/`.
'''
    development = '''# Development workflow

Run commands from the project directory, or pass that directory as the optional
argument: `skieomod build "path to project"`. Creation refuses to overwrite
existing files, including authoring documentation.

1. Edit the manifest and `Scripts/main.lua`.
2. Run `skieomod build` to validate and produce a reproducible ZIP in `bin/`.
3. Run `skieomod test --check-scripts` if Lua 5.4 / luac is installed.
4. Run `skieomod test --check-dependencies` to check installed Workshop mods.
5. Run `skieomod run` to rebuild, install locally and start the game via Steam.

`skieomod test` also accepts a manifest or an existing `.skieomap` / `.skieomod`.
`skieomod build --output PATH` chooses an archive path. A failed build preserves
the previous valid archive. Files absent from manifest references are excluded.
Commit your source files and docs, not generated `bin/` and `obj/` content.

## Game setup

```sh
skieomod setup
skieomod config
```

Setup detects Steam game/demo installations and remembers the game, maps and
UE4SS paths. If needed, use `skieomod setup --game-dir "PATH TO GAME"`.
Before Workshop opens, close the game and use `skieomod update --check` then
`skieomod update` to apply the latest Custom Map loader from skieomod.emillon.fr.
This preserves settings and maps and backs up replaced files. Use
`skieomod update --archive CustomMap-Mod-VERSION.zip` for a specific test release.
Windows and Linux/Proton support launching; macOS supports authoring only.
Under Proton, launch the game once from Steam and close it before setup so its
prefix exists. Setup downloads UE4SS on first installation when needed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| No unique project manifest | Run in a project directory containing one root manifest, or pass its path |
| Missing referenced file | Check its relative path and spelling in the manifest |
| Lua syntax check unavailable | Install Lua 5.4 with `luac5.4` or `luac`, or omit `--check-scripts` |
| Missing/conflicting dependency | Install the required Workshop mod and check its ID and compatible package version |
| Game installation ambiguous | Select it with `--game-dir`; inspect saved values with `skieomod config` |
| Steamworks client not connected | Use `publish --prepare` or `list --installed`; remote commands need a separate native client |

For more examples, run `skieomod help build`, `skieomod help test` and
`skieomod help run`.
'''
    if kind == 'mod':
        development += '''
## Testing this UE4SS mod

Close the game before `run`: UE4SS loads mods at startup. Local installation
enables the mod and backs up a replaced mod directory under `.skieomod-backups`
in UE4SS/Mods. Check the UE4SS log for your script's startup message and errors.
'''
    elif kind == 'mapmod':
        development += '''
## Testing this mapmod

`run` builds a private map in `obj/mapmod-preview` and adds an exact dependency
on your local mod version. Both local artifacts are installed; no Workshop
publication is needed. For another map to use this mod, add its ID and version
to that map's `dependencies`. Do not publish the generated preview map as the mod.
'''
    scripting = '''# Lua scripting

The commented entry point is `Scripts/main.lua`. Keep source in UTF-8.
`skieomod test --check-scripts` checks syntax using Lua 5.4; it does not execute
the game or validate Unreal object names. Check behavior in game with `run`.
'''
    if kind == 'mod':
        scripting += '''
## UE4SS entry point

The file runs at game startup and uses UE4SS directly. Customize `MOD_NAME`
to label log messages. It does not return `function(api)` and cannot use the
Map API's `api:on` or `api.game` directly.

Game objects may not exist when the file first loads. Add hooks suitable for
the game lifecycle and check object validity before accessing them. Close the
game before reinstalling your changes. A downloaded UE4SS mod also needs startup
registration; downloading alone does not activate it.

Consult the [UE4SS documentation](https://docs.ue4ss.com/) for its Lua API.
'''
    else:
        scripting += '''
## Entry point and events

Return `function(api)`. The loader calls it once per map session; register your
event callbacks inside it. `map.ready` is emitted after the terrain is available,
including when restoring a save. Keep callbacks short and avoid duplicating
saved objects when rebuilding your scene. `map.unloading` is the cleanup event.

```lua
return function(api)
    api:on("map.ready", function()
        api:log("Ready")
        -- With the gameplay permission declared in the manifest:
        -- api.game:add_funds(1000)
    end)
end
```

Use `api:off(event, callback)` to remove a handler. Other supported events include
`map.before_load`, `map.after_load`, `map.terrain_loaded`, `map.load_failed`,
`calendar.month_changed`, `calendar.year_changed`, `weather.changed`,
`placeable.built`, `placeable.removed`, `trail.created` and `trail.removed`.

## Timers, loading and resources

- `api:after(milliseconds, callback)` schedules a one-time callback.
- `api:every(milliseconds, callback)` repeats at intervals of at least 16 ms;
  return `false` from your callback to stop.
- `api:hold_loading()` reserves an asynchronous task **inside** `map.ready`.
  Call its returned completion function when finished, or pass an error message.
- `api:loading_progress(stage, fraction)` reports loading progress from 0 to 1.
- `api:read_asset(relative_path)` reads data declared in `content.assets`.
- `api:load_forest_skxy(relative_path, options)` reads compiled SKXY and holds
  loading until complete; call once inside `map.ready` (Custom Maps 1.11+).

The loader cancels API timers and unregisters callbacks when the session closes.
Ordinary scripts use a sandbox: do not rely on `io`, `os`, arbitrary `require`
or UE4SS globals. Declare assets in the manifest; see [manifest.md](manifest.md).
'''
    workshop = '''# Publication

## Publish to the web catalogue

Create a publishing token at https://skieomod.emillon.fr/account and set
CUSTOM_MAP_TOKEN in your terminal, then run `skieomod publish` in this project.
The map appears in New Game → Custom Map → Web. Publish dependencies first.
Increase metadata.version before releasing an update; versions are immutable.

Steam Workshop integration is in preparation; the following commands are
explicit options and do not replace web publication.


## Prepare offline

Update the manifest title, description, authors, language, license and package
version. Credit and license any imported resources. Replace `preview.png` with
your own PNG/JPG/GIF image under 1 MiB, and edit `workshop.json`:

| Field | Meaning |
| --- | --- |
| `version` | Settings format, keep `1` |
| `app_id` | Consumer Workshop AppID, initially the full game's `"4493130"` |
| `published_file_id` | `"0"` creates an article; an existing decimal-string ID updates it |
| `visibility` | Initially `private`; also `public`, `friends` or `unlisted` |
| `preview_file` | Image path relative to the project, initially `preview.png` |

```sh
skieomod publish --prepare
```

This validates and builds the project, then creates `bin/workshop/`:

- `content/`: unpacked manifest and referenced runtime files;
- `preview.png`: separate preview;
- `publish-request.json`: request for a native Steamworks client;
- `workshop.vdf`: SteamCMD test configuration.

Required mod dependencies must specify their `workshop_id` before preparation.
The local ZIP is a development artifact; Steam receives unpacked content.
Authoring docs and Workshop settings are kept in your source project.

## Publish through a native client

The native Steamworks client is not included with skieomod. When supplied by
the game integration, configure it and publish using the local Steam session:

```sh
skieomod --steam-client "PATH TO CLIENT" config
skieomod publish --steam --changenote "Initial release"
```

The returned article ID is saved in `workshop.json` for subsequent updates.
Accept the Workshop legal agreement if Steam requires it. `--item-id`,
`--app-id`, `--preview` and `--visibility` override the stored settings.
The demo AppID is `5012760`; access to another AppID's Workshop is not assumed.
The VDF is for SteamCMD testing and does not publish complete UGC metadata,
tags or dependency links. Use `skieomod help publish` for more CLI examples.
'''
    docs = {
        'README.md': readme,
        'docs/manifest.md': manifest_doc,
        'docs/development.md': development,
        'docs/scripting.md': scripting,
        'docs/workshop.md': workshop,
    }
    if kind == 'map':
        docs['docs/vegetation.md'] = VEGETATION_DOC
        docs['docs/terrain.md'] = f'''# Terrain source

The starter map is a skiable {extent} metre slope. Its heightmap contains
{width} x {height} vertices, spaced {spacing:g} metres apart.
The complete file has `{width} * {height} * 2 = {width * height * 2}` bytes.

Maps are not capped at 8 km. Choose the extent and resolution at creation:

```sh
skieomod create map --output large-map --size 16000 12000 --spacing 8
```

Both lengths must be multiples of the spacing. Creation selects a rendering
stride that keeps the starter mesh modest; increase source spacing to reduce
file size, or adjust the rendering stride to change the visible detail.
Creation allows at most 32 MiB of source samples and 16384 vertices per axis.
The native cache remains 2017 x 2017 samples resampled over the full extent;
its ground spacing grows with map size. Visible terrain and physical collision
use the portable source and the rendering stride.

`Terrain/heightmap.r16` stores row-major **unsigned 16-bit little-endian** samples,
with rows ordered north to south. There is no file header. The template uses:

```text
height_in_metres = sample * 0.01 + 0
```

These values come from `terrain.source.height_scale_meters` and
`height_offset_meters`. `terrain.source.vertices` specifies the grid size;
`spacing_meters` specifies its spacing. Keep `terrain.size_meters` consistent
with `(vertices - 1) * spacing_meters`, and `terrain.elevation_meters` equal to
the decoded minimum and maximum heights.

## Replace the heightmap

With skieomod 1.10 or later, put your original heightmap in the project and
add this top-level configuration to `custom-map.json`:

```json
"build": {{
  "heightmap": {{
    "file": "Terrain/source-heightmap.png",
    "spacing_meters": 8,
    "elevation_meters": [800, 2200]
  }}
}}
```

Then run `skieomod build`. PNG16 dimensions, terrain size, elevation encoding,
centred origin and normalized preview are calculated automatically. The build
updates derived terrain metadata and generates portable R16 only after validation;
replaced files are backed up in `.heightmap-backups/`. Keep the original file:
later builds and `run` use the stored settings again. `test` checks the same
prepared terrain without writing derived files. No separate converter is needed.

Use a non-interlaced 16-bit grayscale PNG without alpha, or headerless R16.
With skieomod 1.12 or later, `vertices` can be omitted: PNG dimensions come
from its header; raw R16 assumes a square grid when its sample count is a
perfect square, with the assumption reported by the build. Supply
`vertices: [width, height]` for rectangular raw input, or `[width, null]` /
`[null, height]` to derive the missing side. Known dimensions override the assumption.
If you omit all elevation fields, the build explicitly uses a relative
0 to 1000 m relief for testing. Pixels alone do not reveal real altitudes;
provide actual endpoints or the complete exporter scale and offset for accurate
terrain. Spacing is still required. Use `format: "r16be"` for
big-endian data. Use your actual sample spacing and elevation endpoints, or
`height_scale_meters` and `height_offset_meters` from your exporter instead.
The original input must not use the reserved output path `Terrain/heightmap.r16`.
`build.heightmap.sample_step` optionally overrides the automatic rendering stride.
See `skieomod help build` and the
[heightmap tutorial](https://skieomod.emillon.fr/tutorials/heightmap/).

For manual imports:

Export a headerless R16LE grid and update the source fields, map size and
elevation range together. `terrain.origin_centimeters` positions the grid in
game coordinates; the starter uses `{origin}` to center the slope.
The CLI does not automatically rewrite terrain metadata after binary edits.

`terrain.preview.samples` is a small rectangular height grid normalized to
0..1, currently 9 x 9. Update it to reflect your new relief. Preview dimensions
must be between 3 and 33 on each axis. For a non-flat terrain, normalize with
`(height - minimum) / (maximum - minimum)`.

`terrain.runtime.sample_step` selects the rendering sample stride;
`tile_quads` controls mesh tile size; `snow_offset_centimeters` offsets snow.
Start with the template values and validate changes with `skieomod test`.
Use `skieomod run` to inspect terrain, collision and snow in the game.

Only portable source data belongs in a `.skieomap`; cooked Unreal containers
are excluded. Keep attribution and license records for any imported terrain.
'''
    return {path: text.encode('utf-8') for path, text in docs.items()}
