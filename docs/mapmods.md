# Standalone mapmods and the fox example

New to mapmods? Follow the [step-by-step tutorial](mapmod-tutorial.md), also
available as an [illustrated web guide](https://skieomod.emillon.fr/tutorials/mapmods/)
with downloadable source projects. This page is the API and format reference.

A mapmod is a `custom-mod.json` project with `runtime: "map-api"`. It is executed
inside the map session. It owns its scripts and assets, while the map owns the
lifetime of its callbacks, timers, actors and save state. Custom Map 1.20.5 adds
portable animated entities and automatic Featured dependency downloads.

## Declare a dependency without embedding it

Add this to the map's `custom-map.json`:

```json
"dependencies": [{"id": "community.foxes", "version": "=0.4.0"}]
```

Do not add the mod's files to the map's `content.assets`. Build and publish the
map and mod as two archives. The static `featured-maps.json` catalogue lists both
releases, with their manifests, sizes and SHA-256 digests. It can retain multiple
versions of one mod. The release builder verifies the complete dependency graph
before producing the catalogue. Publication retains earlier mod versions in the
server catalogue. Required missing versions, conflicts and cycles
fail before any package download; optional dependencies are omitted.

On Play, the loader resolves the requested versions and downloads missing
mapmods before starting the map. A compatible installed dependency is reused.
Old versions remain available to maps that still require them. A downloaded map
with all of its dependencies starts without contacting the server, including
during a catalogue refresh. Downloading missing packages and verifying their
contents happen inside the loading screen. Refreshing maps and accepting a
Featured update are explicit menu actions. A local map can resolve its
missing dependencies from the configured catalogue too. Workshop dependencies
retain their separate `workshop_id` identity and are handled by Steam.

`skieomod run` also resolves local packages and downloads missing mapmods from
the project Featured catalogue. During development, before publication:

```sh
skieomod build mod/SkiEO-Foxes --check-scripts
skieomod build mod/SkiEO-Veymont --dependency mod/SkiEO-Foxes --check-scripts
skieomod run mod/SkiEO-Veymont --dependency mod/SkiEO-Foxes
```

`--dependency` accepts a local mod project or `.skieomod` archive and can be
repeated. `build/test --check-dependencies` remain offline. Tools and loader
release archives contain code and documentation; the fox payload is a separate
download. The examples live in `mod/SkiEO-Foxes` and `mod/SkiEO-Veymont` in the
source repository.

## Author a habitat

The map sets the dependency's configuration under its namespaced extension:

```json
"extensions": {
  "community.foxes": {
    "count": 4,
    "seed": 7521,
    "habitats": [{
      "forest": {"x": -6000, "y": 0, "radius": 1800},
      "meadow": {"x": 6000, "y": 0, "radius": 1800},
      "crossing": [{"x": -2500, "y": 0}, {"x": 2500, "y": 0}]
    }]
  }
}
```

Coordinates and radii are centimetres in map space. Ground height is sampled
at runtime. The first crossing bank belongs to the forest side, the second to
the meadow side. Place both outside the piste, with a clear corridor between
them. Keep habitat circles within the map and away from cliffs/buildings.
There may be 1–8 habitats and 1–8 foxes. Rodents remain simulation data for
underground galleries: no rodent asset or actor is created. Each fox uses one
of the loader's 16 animated entities per session. Veymont includes four widely separated authored territories, each with forest,
meadow and night crossing banks. Habitat placement is separate from tree
placement; a circle named `forest` does not create trees.

## Map API additions

Use script API `1.4` and the `gameplay` permission. Package modules such as
`Scripts/behaviour.lua` must be declared in `content.assets` and `files`.
No unrestricted UE4SS access is needed.

| Call | Behaviour |
| --- | --- |
| `api:mapmod_options()` | Copy of the map's extension named after this package ID |
| `api:mod_state(defaults)` | Persistent JSON table scoped to this package under `__mapmods` |
| `api:bind_key('F7', callback)` | Attach the current map to the loader's F7 debug shortcut; callback runs on the game thread after loading; returns a release function and is removed on unload |
| `api:focus_camera(x, y, z, distance)` | Centre the normal movable camera on a map position, with distance 100–5000 cm (default 500); remains usable while time is paused |
| `api:environment()` | Native hour, elapsed game hours, real `seconds`, loading `ready`, time rate, time/UI/world pause state and optional `camera = {x,y,z}` |
| `api:environment(x, y)` | Also map bounds, rendered ground/snow surface, `snow_cm`, separate `packed_cm`/`fresh_cm`, piste presence and optional nearby native `disturbance={kind,x,y,distance,radius}` (`person` or operating `lift`) |
| `api:spawn_animated(path, textures, options)` | Declared SKAN asset and one declared PNG per section; optional declared `aim_rig`/`ground_rig` JSONs; `snow_coat=true` enables the final snow section; `paw_texture` and `snow_sound=true` enable contact marks/native snow crunch; `blend_duration=0..1` sets clip crossfade duration in seconds (default 0.24; zero disables it) |
| `handle:pose(clip, seconds, x, y, z, yaw, pitch, roll, support)` | Interpolates frames and clip changes; optional `support.dt=0..1` advances the transition clock (otherwise native real seconds); a ground rig solves Z/pitch, keeps roll zero and adapts visible nearby legs; `support={jump=0,emit=true,dt=elapsed}` enables contact events; optional `adapt=0..1` overrides the visibility weight; returns resolved Z/pitch/roll and contacts |
| `handle:place(x, y, z, yaw, pitch, roll)` | Update the transform without decoding or uploading animation vertices |
| `handle:snow(amount, shake_time)` | Snow coat 0–1; optional shake time emits falling flakes |
| `handle:pause()` | Immediately silence the entity's contact audio during time/UI/world pause |
| `handle:inspect(provider)` | Make the visible mesh selectable with the mouse; provider returns `title`, optional `subtitle`/`note` and at most four `{label,value}` text properties; one lightweight card per map session, refreshed while selected and removed on unload |
| `api:configure_surface_lifts(definitions, assets)` | Adapts existing native lifts to standing, terrain-following platter lifts; requires `gameplay`, the reviewed game build and this loader. See [surface lifts](surface-lifts.md) for assets, configuration and limitations. |
| `api:on_frame(callback)` | Map-owned callback on each engine frame, falling back to a 16 ms game-thread timer |
| `handle:look_at(x, y, z, weight, dt)` | World-space target for aim groups; weight 0–1 and timestep 0–0.25 s; weight zero smoothly returns to neutral |
| `api:footprint(x, y, yaw, texture)` | A visual pawprint on snow, with an optional declared PNG; returns false on dry/outside terrain |
| `api:expire_footprints()` | Removes old or melted prints; call periodically |

Callbacks use `api:on`, `api:every`, `api:after` and `api:on_frame`.
The fox example simulates behaviour at 10 Hz, interpolates nearby poses at 30 Hz,
and reduces animation work with camera distance. The initial placement waits for
`environment().ready`, including when the map starts paused. Frame callbacks
do not serialize save state; use a periodic timer or a map event for checkpoints.
Every movement, pose, gaze and snow particle stops during time, menu or world pause. Cached CPU snow samples
avoid synchronous GPU reads; surface height includes packed and fresh snow plus the map’s visual contact
calibration (`terrain.runtime.snow_surface_bias_centimeters`, default 0,
range −100..100 cm). Veymont uses −12 cm, measured on the native rendered
surface in all four territories at several snow depths. This affects animals
and tracks; it changes neither the snow simulation nor the terrain mesh. Each dependency uses its own asset allowlist; session timers and cleanup stay with the map. `map.unloading`
and failed loading release transient actors. Map code should reserve `__mapmods`
in its saved state. Decorative footprints are intentionally transient across a
save/reload; the animals and their behaviour resume from the latest saved checkpoint (updated
every 30 real seconds, so at most 30 seconds of wildlife movement can be replayed).

## Portable animation format

SKAN v1 is little endian. The header is `SKAN`, uint32 version `1`, section count
and clip count. Each section contains uint32 vertex/index counts, interleaved
float32 XYZ/normal XYZ/UV vertices, clockwise uint32 triangle indices, then its clips.
Each clip contains a NUL-padded 16-byte name, float32 duration, uint32 frame count
and uint32 loop flag, followed by frame-major float32 XYZ/normal XYZ samples.
The loader interpolates adjacent frames, normalizes normals, wraps loops and
clamps one-shot clips. All sections of a character share its ground correction.
Clip changes blend from the current authored pose over 0.24 seconds by default,
using a smooth weight with zero endpoint velocity/acceleration. An interrupted
transition starts from its current blended pose. Body, eyes, snow coat and
ground-rig hip/knee anchors and contact targets use the same weight. Ground and
eye corrections do not contaminate the source pose. Stop calling `pose` while
paused; use `support.dt` for a simulation-owned transition clock. The initial
placement is immediate, even on a map loaded paused.

Limits: 32 MiB per model, 8 sections, 12,000 total vertices, 72,000 indices per
section, 16 clips and 120 frames per clip. Non-finite values, invalid indices,
truncation and trailing data are rejected. Textures are RGB/RGBA power-of-two
PNGs up to 512 pixels. The renderer uses procedural meshes, so no Unreal editor
or cooked skeleton is required. This CPU path suits a small tutorial population;
it is not a crowd animation system.

An optional `skieo-aim-rig` v1 JSON file supplies up to eight disjoint groups
(4,096 total vertices). Each group names its 1-based `section`, `vertices`,
`x_pair` and `z_pair` anchor indices, plus `yaw_limit` and `pitch_limit` in degrees
(at most 45°). The midpoint of the X pair is the pivot. Both axes follow the
sampled clip; the selected vertices and normals rotate rigidly around that
pivot, with a damped transition toward the target. Overlapping groups,
undeclared assets and degenerate axes are rejected.

The fox keeps its two eyeballs in section two. Pupils are in the texture;
rotating each globe changes the gaze without moving its orbit. The example
tracks prey, feeding spots and travel targets, alternates idle fixations, and
briefly notices a close observer. Its 16°/10° eye motion is fully active inside
four metres, fades between four and twelve metres, and is neutral farther away.
This detail does not alter the deterministic hunting simulation or saved state.

The fox conversion is reproducible from the external archive with
`python3 tools/prepare_fox.py /path/to/fox-anatomy.zip` (NumPy and Pillow).
Original model: [Fox Anatomy by npbehunin](https://sketchfab.com/3d-models/fox-anatomy-bc5e3b0399784323a161005c74109578),
CC Attribution. The packaged `CREDITS.txt` names the author, source, license and
modifications. Anatomical bones, organs and muscles are omitted from the game
payload. Rendering, bounded snow tracks and native save/reload were verified in
demo build 25808900. Four model-derived soles and animated hip/knee anchors
drive two-bone leg adaptation. The torso follows pitch while retaining zero
roll across slopes; stance paws stay planted in world space. Fresh snow
penetration is 85% of `fresh_cm`, capped at leg height plus 8 cm. Bounds replace
ordinary walking only when this penetration reaches leg height. Locomotion
walk/trot animation time advances by terrain distance divided by the clip's stride,
so turning, slowing and blocked motion cannot advance those feet independently.
Bounds and hunting jumps use a separate ballistic clock (980 cm/s² gravity),
with a finite landing phase. Slower forward motion in powder cannot slow gravity.
Contact events project the actual sole triangles and play a brief native,
attenuated snow crunch from a reused entity-owned audio component. Call
`handle:pause()` when suspending animation to silence it. There is no reflected
skier snow-track stamping method in this demo; marks use bounded visual meshes,
not private snow-track page writes. Authored routes do not provide general
obstacle avoidance.

In foxes 0.4.0, leg correction is fully active within 6 m and fades out by 10 m,
and through the first 3 cm of burial in fresh snow. Baked legs remain intact
when correction is disabled, while height/pitch and sole contact events remain
active. Shorter strides, Hermite swing endpoints and gradual turn corrections
avoid snap-back and excessively spread legs. Hunger/fatigue drive patch searches,
listening, hunts and rests. Human proximity or an operating lift interrupts
these actions and selects a quiet escape. The native disturbance sampler caches
queries, uses the nearest guest and worker positions plus operating terminals/
corridors, and never treats the camera as a visitor. Save JSON retains full
floating-point precision so these steering/fear states survive reload unchanged.

`environment(x,y).heavy_snow` requires both native Blizzard weather and snow
precipitation at that elevation; `temperature_c` is the local native temperature.
The fox starts with dry fur, coats gradually only in heavy snowfall, and loses
snow through running, warmer air and shaking. `snow_textures` in the animated
entity options is an array of 2–16 declared PNG variants, applied to the body by
`handle:snow(amount)`. Textures/materials are shared and loaded once; no texture
imports occur during rendering. The old white shell is hidden in this mode.

The inspection picker tests current mesh triangles and terrain/snow occlusion.
Animals remain physically nonblocking. Native tools
and hovered UI keep their input; the card closes on outside click, Escape or
native guest/building selection. Providers receive no Unreal object references.

Native QA can run through UE4SS with the game's `-RenderOffscreen -unattended`
arguments, without activating a desktop window or sending mouse/keyboard input.
Custom Map 1.20.6 consumes F7, click and Escape flags in one retained game-thread
loop. Native key callbacks never queue Lua functions across threads, avoiding
UE4SS's shared callback-registry race during animation. The console command
`custommap_test_hotkey F7` exercises this same input path.
The console commands `custommap_test_entity focus 2`,
`custommap_test_entity select <screen-x> <screen-y>` and
`custommap_test_entity close` exercise the displayed pose and the same inspection
picker. Use Unreal's `HighResShot` for captures. Freeze both the time subsystem
and the engine world for a stable capture: calendar pause alone does not stop
GPU snow evolution. Let the camera update before freezing the engine world.
