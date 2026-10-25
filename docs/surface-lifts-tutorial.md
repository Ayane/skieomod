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

Keep the mapmod in its own project/package, with its default meshes, scripts
and `custom-mod.json`. The game downloads that dependency when players start
a published map. Optional replacement models belong to the map itself, as
explained in step 7.

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
| `service_width_m` | Service corridor width, 4–10 metres; default 5. |
| `service_offset_m` | Distance from the lift axis towards the ascent side, 3–10 metres; default 3.5. Leave at least 1 metre between the corridor edge and the pylons. |
| `evacuation_routes` | Optional downhill emergency paths, each an array of world `[x,y,z]` points in centimetres. |

Keep the first exercise straight. If the route has exactly `pylons + 2`
points, its interior points specify the supports; turns above 5° receive bend
supports. Otherwise supports are fitted to the route and terrain. Use surveyed
points for intended bends and inspect the result in the game. At most sixteen
configured installations are supported in one map session.

### Service corridors and stopped lifts

With **loader 1.28.0 or newer**, stopping a surface lift releases its passengers.
They ski down the closed service corridor using the game's normal simulation.
Snowcats wait before entering or continuing that corridor until the skiers have
cleared it. New grooming jobs also wait. Restarting the lift waits for clearance;
an explicit manual stop remains off afterwards. Ordinary chairlifts retain their
native behaviour. Service trails stay closed to ordinary downhill traffic.

You can add emergency exits to a lift definition without copying the mapmod:

```json
"service_width_m": 5,
"service_offset_m": 3.5,
"evacuation_routes": [
  [[-8350, 0, 0], [-10000, 2000, 0], [-12000, 5000, 0]]
]
```

These example coordinates apply to the practice line: adapt them to your terrain
and connect the last point to a safe downhill piste. Each path starts within
10 metres of the service corridor, then descends to its exit. Heights are sampled
from the map; a local rise greater than 5 metres is rejected. Keep 2–128 points per
path, at most 16 paths and 1,024 points per lift. A skier considers entries below
their current position and chooses the shortest remaining distance to a safe
exit, including the service approach. Without a shorter eligible exit, they
continue to the lower terminal. Test both sides of every entry and save/reload
during an evacuation. Use a new game to test changes to authored routes.

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

With **loader 1.27.0 or newer**, your map can replace models for each lift and
individual pylon while continuing to use the published
`community.surface-lifts` **0.1.0** dependency. Keep its ID and dependency pin;
you do not need to copy, edit or republish the mapmod.

### Try the custom-model example

Download [the custom-model practice map](https://skieomod.emillon.fr/tutorials/surface-lifts/files/surface-lift-custom-models.zip)
and extract `practice-custom-models/` beside the original `surface-lifts/`
project. It contains two native lifts: **Practice platter** has blue frames
and lower pole casings, with an orange P2 and orange P2 pulleys; **Default
platter** keeps the stock models. These cosmetic variants retain the original
geometry and attachment points. Their files belong to the map, not the mapmod.

Open `practice-custom-models/custom-map.json` in the editor, or inspect
[its complete extension settings](https://skieomod.emillon.fr/tutorials/surface-lifts/files/custom-models-options.json).
From the shared parent folder:

```sh
skieomod build surface-lifts
skieomod build practice-custom-models --dependency surface-lifts
skieomod run practice-custom-models --dependency surface-lifts
```

### Select models per lift and pylon

In your map's `custom-map.json`, add `models` and optional `pylon_models` inside
the relevant entry of `extensions["community.surface-lifts"].lifts`. This is a
fragment to add to an existing lift definition, keeping its name, route,
`kind`, speed, capacity, `pylons` and other settings:

```json
"models": {
  "drive": "Assets/blue-drive.skpm",
  "tower": "Assets/blue-tower.skpm",
  "platter_lower": "Assets/blue-platter-lower.skpm",
  "palette": "Assets/lift-palette.png"
},
"pylon_models": [{
  "index": 2,
  "models": {
    "tower": "Assets/orange-tower.skpm",
    "guide_wheel": "Assets/orange-guide-wheel.skpm"
  }
}]
```

Each model path is relative to **your map project**. Copy your replacement
meshes and PNGs there, then add every path to the map's `content.assets` array,
preserving existing entries. Unlike a mapmod manifest, a map does not need a
separate top-level `files` array. Use `/` and exact spelling/case. Reopen the
project in the editor after external edits.

The selection order is **mapmod defaults → this lift's `models` → this pylon's
`models`**. Any omitted role inherits its previous value. A lift without
`models` keeps the original appearance. A `models` object can replace only one
piece; you do not need to supply all 24 models. `drive` and `return_station`
retain their ordinary enum settings (`open`, `covered`, `modern`, etc.); the
model role replaces the mesh chosen by those settings.

`index: 1` means the first intermediate pylon from the lower station, `2` means
P2, and so on up to `pylons`. The two terminals are excluded. Each index may
appear only once. The per-pylon roles are `tower`, `angle_tower`,
`return_support`, `return_angle`, `fixed_return_support`, `guide_wheel`,
`chair_tower`, `chair_head` and `palette`. `guide_wheel` replaces that pylon's
moving pulleys, including its return-side pulleys when present. A bend uses
`angle_tower`, so override that role if the target pylon is a bend.

The same settings work for the mapmod's `chairlifts` entries. Their pylons are
numbered along the route from bottom to top using the actual native supports;
the chosen index must exist. If you change a route or support count, check the
numbering again in a new game.

### Available model roles

| `models` key | Role and selection |
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
| `palette` | PNG texture shared by this lift or pylon. |

A palette may be replaced per lift or pylon. It colours the meshes using that
bank; the generated cable and support fittings keep the lift palette. PNGs
must be square, power-of-two, 8-bit RGB/RGBA images up to 512 × 512 pixels.

The cable, wheel placement, towing poses and telescopic animation are generated
by the loader. Keep the reference origins and attachment dimensions when
replacing a mesh. Each SKPM is limited to 16 MiB, 150,000 vertices and 450,000
triangle indices. Across the session, the loader permits up to 64 custom
meshes and 32 palettes, with all meshes together capped at 32 MiB and 500,000
vertices. Assets reused by several lifts or pylons are decoded/imported once.
Keep repeated poles and wheels small.

### Create and export a model with Blender

The loader reads **`.skpm` static meshes and PNG palettes**. Keep your
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
`practice-mountain/Assets/my-tower.skpm`. This example uses the unchanged palette
shipped by the mapmod, so this mesh does not need a custom `palette` entry. The script also writes `build/surface-lifts/models.blend`
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

### Test, save and publish your map

Inspect both terminals, a straight support, bends, moving wheels and occupied
and empty poles. Test in a new game and after saving/reloading. The normal
native identities and management data remain unchanged; appearance is rebuilt
from the map's configuration on loading.

If a mesh is missing, check its path and `content.assets`; invalid paths,
unknown roles, duplicate pylon indices and malformed SKPMs stop loading with an
error. Files are read from the map's declared assets, even if the mapmod has a
file with the same name. If a model floats or misses the cable, compare its
origin and dimensions with the original.

Increase your map version, rebuild and publish it using `skieomod publish
practice-custom-models` (choose your own map ID before publishing the practice
project). Players receive your replacement assets with the map and download
the shared mapmod separately. A mapmod fork is useful only if you want to
change its behaviour rather than supply different models.

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
