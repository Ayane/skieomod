# Add platter surface lifts to your map

This guide uses **Surface lifts 0.1.0** (`community.surface-lifts`) and the
Custom Map loader **1.25.0 or newer**. **Help → Surface lift tutorial** opens
the illustrated guide in skieomod editor 1.26.0 or newer:
https://skieomod.emillon.fr/tutorials/surface-lifts/

The mapmod adapts existing native lifts. Their queues, tickets, employees,
maintenance and saves stay under the game's control. You place the lift in
the editor, then configure its appearance and towing route in the map manifest.

## 1. Start with the practice project

Download and extract [Surface lift practice](https://skieomod.emillon.fr/tutorials/surface-lifts/files/surface-lift-practice.zip).
The archive contains `practice-mountain/` and `surface-lifts/`: a small editable
map and the separate mapmod sources, including its original models and licence.
No Blender installation is needed for the standard models. The optional
custom-model chapter below uses Blender. Open `practice-mountain/custom-map.json`
with **Open** in the editor.

Update the tools and loader using the [installation guide](getting-started.md).
Play requires the supported Steam Windows game or demo, on Windows or
Linux/Proton. The editor and build tools can be used without running the game.

## 2. Place a native lift

On **Source terrain**, open the **Objects** panel. Search for the one-seat
chairlift (`BP_FixedChair1`, shown as **Chair lift (one seat)** or **Fixed Chair1**).
Click **Place on terrain**, click the lower terminal, then click the upper terminal.
Press Escape to finish placing. Select the lift and set its name to
**Practice platter**. Save the map.

The downloadable map already includes this lift and a nearby ticket office:

| Field | Practice value |
| --- | --- |
| Name | `Practice platter` |
| Lower X / Y | `-80 / 240` metres |
| Upper X / Y | `-80 / -240` metres |

Its source is `Scene/objects.json`, declared by `build.scene.file` in
`custom-map.json`. Keep this native lift: the mapmod attaches to it rather than
creating a replacement simulation. New lifts built later during play are not
automatically converted by this configuration.

## 3. Declare the dependency

Open `custom-map.json` in a text editor using **File → Show project folder**.
Add the following entry to its top-level `dependencies` array. Preserve any
other dependencies, terrain settings and build settings:

```json
{"id": "community.surface-lifts", "version": "=0.1.0"}
```

Keep the mapmod in its own project/package. Do not copy its meshes, scripts or
`custom-mod.json` into the map. The game downloads the declared dependency
when players start a published map.

## 4. Describe the line

Add this top-level `extensions` object, merging with any existing extensions:

```json
"extensions": {
  "community.surface-lifts": {
    "lifts": [{
      "name": "Practice platter",
      "kind": "detachable_platter",
      "route": [[-8000, 24000, 0], [-8000, 0, 0], [-8000, -24000, 0]],
      "speed_mps": 2.5,
      "capacity_per_hour": 600,
      "pylons": 4,
      "drive": "open",
      "return_station": "floating",
      "ascent_side": "left"
    }]
  }
}
```

This is a JSON fragment to merge, not a complete manifest. Reopen the project
in the editor after external edits so an older in-memory manifest cannot
overwrite the new settings when you save.

**Units matter:** the editor's scene positions use metres; `route` uses world
centimetres. On an ordinary centred editor map, multiply X and Y by 100. For
maps with a custom world origin, include that offset too. Each route point
requires three numbers. Its Z is resampled from the terrain and snow, so `0`
is a valid placeholder here. Put the lower terminal first and the upper last;
every point must lie on the map. A route has 2–128 points and is at most 3 km long.

The loader initially matches the exact name and a lower terminal within 50 m
of `route[1]`. Give every configured line a unique name. It then saves the
native lift GUID, so the attachment survives a normal save/reload.

| Setting | Meaning and accepted values |
| --- | --- |
| `kind` | `detachable_platter` (TKD, with a pole stock) or `fixed_platter` (TKF, rigid poles). |
| `speed_mps` | Cable speed, 0.5–5 m/s. |
| `capacity_per_hour` | Nominal capacity, 100–1200 people/hour. |
| `pylons` | 1–32 intermediate supports, excluding the two terminals. |
| `drive` | `open`, `covered` or `modern` station model. |
| `return_station` | `floating`, `release` or `lattice`. |
| `ascent_side` | `left` or `right`, looking from the lower terminal towards the top. |
| `max_snow_cm` | Optional maximum snow depth, 110–300 cm. Defaults: 150 for TKF, 250 for TKD. |

Keep the first exercise straight. If the route has exactly `pylons + 2`
points, its interior points specify the supports; turns above 5° receive bend
supports. Otherwise supports are fitted to the route and terrain. Use surveyed
points for intended bends and inspect the result in the game. At most sixteen
configured installations are supported in one map session.

## 5. Build and play

Open a terminal in the extracted practice folder and run:

```sh
skieomod build surface-lifts
skieomod build practice-mountain --dependency surface-lifts
skieomod run practice-mountain --dependency surface-lifts
```

The optional `--check-scripts` flag requires Lua 5.4 and `luac`. It is not needed
to use the downloaded example. The map and mapmod build into separate `bin/`
archives. `--dependency` tells the local command where to find the mod sources;
it does not embed them into the map. After the local dependency is installed,
you can also test the map using the editor's **Play** button.

In the game, inspect the lower station, poles, cable and support positions.
Use the normal construction tools to add descending trails and complete the
resort. Open the lift, assign staff and provide the normal guest access and
services. The native stop/speed controls and pause still apply.

Surface lifts require snow along their whole ascent. They close below 3 cm
and reopen once the whole line has at least 5 cm, subject to manual stop.
Too much snow also closes them: 150 cm for fixed poles and 250 cm for detachable
poles by default, with 20 cm of reopening margin. Provide a snowcat garage,
snowcats and staff for maintenance. The mapmod creates ascent maintenance
corridors; requesting work alone does not change the snow.

## 6. Check saves and share

Make a native save and reload it. The poles and models are reconstructed while
the native lift identity, assignments and management data are preserved. Test
route or name changes in a new game first: an existing save keeps its bound
lift GUID and the lift positions the player saved. A deleted lift is not recreated.

For distribution, keep the dependency version pinned, increase your map's
version after edits, rebuild and use `skieomod publish practice-mountain` or
the existing Workshop preparation workflow. The public Surface lifts 0.1.0
package is already available; you do not need to republish an unchanged copy.
If you change the mapmod itself, use your own ID and version.

## 7. Use your own models (optional)

The standard map options choose among the models shipped by the mapmod. To
supply your own geometry, make a separate version of the mapmod and change its
model table. A `drive` value such as `Assets/my-drive.skpm` is not supported:
`drive` still accepts only `open`, `covered` or `modern`.

### Make your own mapmod project

Copy the extracted `surface-lifts/` folder to `my-surface-lifts/`. In its
`custom-mod.json`, change `id` to a namespaced ID you own, for example
`yourname.surface-lifts`. Set your own `metadata.name`, `metadata.authors` and
`metadata.version` (start at `0.1.0`). Keep the `map-api` runtime, `gameplay`
permission, scripts and existing assets. Retain the original `LICENSE` and
credits, and credit your added models in `CREDITS.txt`.

The fork replaces `community.surface-lifts` for this map. Keep only one of them
in the dependency graph: the loader accepts **one `configure_surface_lifts`
call per map session**. The model table is shared by every configured line;
there is currently no separate custom model table per lift.

### Create and export a model with Blender

The loader reads **`.skpm` static meshes and one shared PNG palette**. Keep your
`.blend` files as authoring sources; FBX, OBJ and `.blend` files are not runtime
lift models. No Unreal cooking or DLL build is needed for a model replacement.

A working exporter and the original geometry definitions are in
[`tools/build_surface_lift_models.py`](https://github.com/Ayane/skieomod/blob/main/tools/build_surface_lift_models.py).
Download a [repository source checkout](https://github.com/Ayane/skieomod/archive/refs/heads/main.zip)
into a separate work folder. The generator recreates its Blender scene from
Python definitions; it does not read an edited `.blend` file. Add your geometry
before the final `# Keep an immediately usable authoring overview` block.
For example, this creates a wider blue mast while keeping the standard support
attachment positions:

```python
box('my footing', (0, 0, .12), (1.1, 1.1, .24), 2)
rod('my blue mast', (0, 0, .24), (0, 0, 6.55), .24, 3, 12)
rod('my crossarm', (0, 0, 6.8), (0, 1.65, 6.8), .09)
rod('my brace', (0, 0, 4.8), (0, 1.6, 6.5), .06)
ladder(.24, -.2, 6.6)
export('my-tower')
```

With Blender available as `blender`, run this from the repository checkout:

```sh
blender --background --threads 2 --python tools/build_surface_lift_models.py
```

Copy the generated `mod/SkiEO-SurfaceLifts/Assets/my-tower.skpm` into
`my-surface-lifts/Assets/my-tower.skpm`. This example uses the unchanged palette
already in your fork. The script also writes `build/surface-lifts/models.blend`
as a visual overview. Its collections are spread apart for inspection **after
export**; those overview offsets must not enter your runtime meshes.

The supplied exporter uses metres in Blender, bakes object transforms, then
writes centimetres with `(x, -y, z)` coordinates and reflected normals. Model
local X runs along the line, Z points up, and the loader handles rotation and
left/right mirroring. Keep the source model's local origin and attachment
positions: a tower is anchored at its foot, a station at its route-terminal
reference, a wheel at its centre and a pole at its cable clamp. Do not centre
each object independently before export.

For hand-modelled meshes, reuse the script's `export(name)` routine in your
Blender authoring script with your mesh objects in `parts`, the output folder
in `OUT`, and the palette materials in `mats`. Each object's first material
must belong to `mats`. This exporter assigns a palette colour per object; it
does not export Blender shader graphs or an existing UV unwrap. Edit `PALETTE`
and regenerate `palette.png` if you need different colours; replacing the
shared palette changes every model using those colours.

### Declare the files and select their roles

Add `Assets/my-tower.skpm` to **both** `files` and `content.assets` in
`my-surface-lifts/custom-mod.json`. Append to the existing arrays; keep the
other entries. Paths are relative to the mapmod root, use `/`, and are
case-sensitive. Every new mesh or replacement PNG needs both declarations.

In `my-surface-lifts/Scripts/main.lua`, keep the existing `local models = {...}`
table. Insert this assignment immediately after that table, before
`return function(api)`:

```lua
models.tower = 'Assets/my-tower.skpm'
```

This changes ordinary intermediate pylons. Bend pylons and the separately
assembled wheels keep their original models. Other replacement slots are:

| Model table key | Role and selection |
| --- | --- |
| `tower`, `angle_tower` | Ordinary and bend support frames. The reference mast is scaled vertically from a 6 m base height. |
| `return_support`, `return_angle`, `fixed_return_support` | Separate high-return frames and fixed-pole return arms. Preserve their reference attachment positions. |
| `drive` | Open lower station for `detachable_platter` with `drive: "open"`. |
| `covered`, `modern` | Lower stations selected by `drive: "covered"` or `drive: "modern"`. |
| `fixed` | Lower station for `fixed_platter` with `drive: "open"`. |
| `return_station`, `release`, `lattice` | Upper stations selected by `return_station: "floating"`, `"release"` or `"lattice"`. |
| `inclined_wheel`, `guide_wheel`, `motor` | Separate rotating wheels and motor. The reference wheel radii are 2 m and 0.8 m, centred at the origin in the XY plane. |
| `platter` | Complete rigid TKF pole: clamp at the origin, disc about 3 m below it. |
| `platter_upper`, `platter_shaft`, `platter_lower` | Animated TKD clamp/suspension, sliding shaft and lower spring casing with disc. Preserve all three source origins and lengths; the shaft is a 1 cm segment scaled by the animation. |
| `poles_bundle` | The passenger's carried ski poles. |
| `chair_drive`, `chair_return`, `chair_tower`, `chair_head` | Frames used by the `fixed_chair` configuration; native chairs remain native. |
| `palette` | Shared PNG texture for all models. |

All **24 mesh slots plus `palette` are required**, including slots unused by
your particular line. Keep the original files for anything you do not replace.
The cable, wheel placement, towing poses and telescopic animation are generated
by the loader; changing a mesh does not move their attachment points. Start
with cosmetic changes that preserve the reference dimensions. Each SKPM mesh
must fit the loader limits: 16 MiB, 150,000 vertices and 450,000 triangle indices
(150,000 triangles). Keep repeated poles and wheels much smaller.

### Bind the map to your fork, test and publish

In `practice-mountain/custom-map.json`, replace the dependency ID with
`yourname.surface-lifts` and pin `=0.1.0`. Rename the extension key from
`community.surface-lifts` to `yourname.surface-lifts`, keeping its `lifts`
configuration unchanged. The extension key must match the fork's ID because
`api:mapmod_options()` reads that namespace. Reopen the map in the editor after
external edits.

Run from the parent folder containing the two projects:

```sh
skieomod build my-surface-lifts
skieomod build practice-mountain --dependency my-surface-lifts
skieomod run practice-mountain --dependency my-surface-lifts
```

Inspect a straight support, a bend if used, both terminals, moving wheels and
occupied/unoccupied poles. Check a new game and a save/reload. If a model is
missing, check both manifest lists and exact path spelling; if it floats or
misses the cable, compare its origin and dimensions with the original mesh.

Give the practice map your own map ID before publishing it. Publish your
mapmod first with `skieomod publish my-surface-lifts`, then publish the map with
`skieomod publish practice-mountain`. Keep them as separate packages. For later
model edits, increase the fork's `metadata.version`, update the map's dependency
pin and version, rebuild and publish both projects.

## Troubleshooting

- **The chairlift stays visible:** check spelling/case, the dependency, the
  lower-terminal coordinates and the final loading result. Inspect UE4SS.log
  for `Surface lifts: 1 native installations adapted`.
- **Nothing attaches in an old save:** check its saved lift position and GUID.
  Try a new game after changing your authored scene.
- **The lift stops:** check snow along the entire ascent, manual stop, hours,
  staff and maintenance before changing the model configuration.
- **A bend or terminal looks wrong:** check the route order, centimetre units,
  side of ascent, support count and terrain profile. Keep all points inside the map.
- **The game build is refused:** update the tools and loader. The native
  helpers deliberately require a reviewed game build; changing the DLL filename
  or disabling the guard does not add support.

For the low-level API and rendering details, see [surface-lifts.md](surface-lifts.md).
Use the mapmod options above for ordinary maps; the dependency already calls
`api:configure_surface_lifts` after loading, once per map session.
