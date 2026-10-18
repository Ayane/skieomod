# Create your first mapmod

A mapmod adds reusable behaviour and resources to a Ski-E-O! map. Each map
declares the mod's ID and a compatible version; the mod remains a separate
`.skieomod` download. One installed version can serve several maps.

This tutorial first builds **Mountain life**, a small Lua mapmod with a
configurable message and a saved field-report counter. It writes to the log;
it does not create animals. Then you will attach it to a practice map and use
the **Forest foxes** source project to explore animated wildlife.

The [web edition](https://skieomod.emillon.fr/tutorials/mapmods/) includes
downloadable source projects and an in-game fox capture made through UE4SS.
Open it from the workshop with **Help → Mapmod tutorial** (editor 1.20.8+).
The [mapmod reference](mapmods.md) documents the complete entity API and format.

## 1. Prepare the tools

Use Python 3.10+, `pipx`, Ski-E-O! or its Steam demo, and matching tools/game
loader **1.20.6 or later**. Authoring works without the game; Play needs Windows
or Linux/Proton. Install Lua 5.4 with `luac` for the optional syntax checks.

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
skieomod --version
skieomod setup
```

If setup is already complete, close the game and use `skieomod update` instead.
If the public feed is older than the version required here, use the matching
prepared wheel and `skieomod update --archive CustomMap-Mod-VERSION.zip`.

Download and extract [the practice source ZIP](https://skieomod.emillon.fr/tutorials/mapmods/files/first-mapmod-project.zip).
It contains `mountain-life/` and `practice-mountain/`, already wired together.
Run the later commands from their shared parent directory. To recreate the
projects yourself in empty folders:

```sh
skieomod create mapmod --output mountain-life --id tutorial.mountain-life --name "Mountain life" --author "Your name"
skieomod create map --output practice-mountain --id tutorial.practice-mountain --name "Practice mountain" --author "Your name"
```

Choose your own namespaced ID before publishing a derivative, such as
`yourname.mountain-life`. Keep it stable across updates and change all dependency
and extension keys to match. `create mod` produces a startup UE4SS mod;
`create mapmod` produces the map-scoped runtime used here.

## 2. Declare the mod's files

Open `mountain-life/custom-mod.json`. The following is a complete minimal
manifest. The download also includes a `LICENSE` file in `files`.

```json
{
  "format": {"name": "skieo-mod", "version": "1.0.0"},
  "id": "tutorial.mountain-life",
  "metadata": {
    "name": "Mountain life",
    "version": "0.1.0",
    "authors": ["Your name"],
    "description": "Configurable field reports for a living mountain.",
    "language": "en",
    "license": "MIT"
  },
  "runtime": "map-api",
  "dependencies": [],
  "script": {
    "language": "lua",
    "api": "1.4",
    "entry": "Scripts/main.lua",
    "permissions": ["gameplay"]
  },
  "files": ["Scripts/main.lua", "Data/welcome.txt"],
  "content": {"assets": ["Data/welcome.txt"]}
}
```

`format.version` identifies the package format, `script.api` selects the Lua API,
and `metadata.version` identifies **your release**. They are different numbers.
`files` lists everything packaged, including the entry point. `content.assets`
allows scripts to read selected files: an extra asset must be in **both** lists.
Use relative paths with `/` and exact spelling. Create `Data/welcome.txt`:

```text
The mountain is alive: listen for wildlife between the trees.
```

Only declared content enters the runtime archive. Project documentation,
editable model sources, `bin/` and the preview map remain authoring material.

## 3. Register behaviour after the map is ready

Replace `mountain-life/Scripts/main.lua` with this script. The loader calls its
returned function once per session and supplies `api`.

```lua
return function(api)
    local options = api:mapmod_options()
    if options.enabled == false then return end
    local label = type(options.label) == 'string' and options.label:sub(1, 80)
        or 'Mountain life'
    local welcome = api:read_asset('Data/welcome.txt'):gsub('%s+$', '')

    api:on('map.ready', function()
        local state = api:mod_state({reports = 0})
        api:log(label .. ': ' .. welcome)
        api:log('Saved field reports: ' .. state.reports)

        -- Timers follow the map session; explicitly respect the game's pause.
        api:every(30000, function()
            local environment = api:environment()
            if environment.paused or environment.ready == false then return end
            state.reports = state.reports + 1
            api:log(string.format('%s: field report %d, local hour %.1f',
                label, state.reports, environment.hour or 0))
        end)
    end)
end
```

`map.ready` runs after terrain/station initialization, including save restoration.
The message and counter appear in `UE4SS.log`, in the installed UE4SS directory;
they do not open a player-facing notification. After roughly 30 real seconds
with the game unpaused, the first field report appears.

`api:mod_state` stores JSON data under this mod's ID inside the map's native save.
Loading that save restores the counter; starting a new game starts at zero.
Keep functions, callbacks, actor handles and other transient objects out of it.
When your state schema changes, fill in missing fields before using them.
Use `mod_state` for dependency data; reserve the map's main `api:state` for the map.

The loader removes these callbacks and cancels the timer when the map closes.
Use `api:on('map.unloading', function() … end)` for any additional cleanup your
own resources need. Use the API rather than raw UE4SS hooks or global timers.

## 4. Attach the mod to a map

In `practice-mountain/custom-map.json`, replace the initially empty
`dependencies` array and add the following top-level `extensions` object.
These are **fragments to merge**, not a replacement for the entire manifest.
Preserve the map's terrain, scripts, build settings and other dependencies.

```json
"dependencies": [
  {"id": "tutorial.mountain-life", "version": "=0.1.0"}
],
"extensions": {
  "tutorial.mountain-life": {
    "enabled": true,
    "label": "Practice mountain"
  }
}
```

The loader registers dependency scripts before the map's own script. The mod
receives its configuration through `api:mapmod_options()`, which copies the
extension named after its package ID. A different map can use another label or
disable reports without editing the shared mod. Validate your own options and
provide defaults, since a map can omit the extension.

Do not copy the mod's Lua or assets into the map and do not list them in the
map's `content.assets`. The dependency is the connection between the packages.

## 5. Build and test the two packages

Run from the parent of the two project folders:

```sh
skieomod build mountain-life --check-scripts
skieomod build practice-mountain --dependency mountain-life --check-scripts
skieomod test practice-mountain --dependency mountain-life --check-dependencies --check-scripts
skieomod run practice-mountain --dependency mountain-life
```

Remove `--check-scripts` if `luac` is unavailable; this only removes the syntax
check. Build validates the manifests and files; Test checks packages and the
dependency closure. Neither proves runtime behaviour: use Play and inspect logs.

**Checkpoint:** `mountain-life/bin/tutorial.mountain-life-0.1.0.skieomod` and
`practice-mountain/bin/tutorial.practice-mountain-0.1.0.skieomap` exist. The map
archive contains no `Data/welcome.txt`. The game log shows:

```text
Practice mountain: The mountain is alive: listen for wildlife between the trees.
Saved field reports: 0
Practice mountain: field report 1, local hour …
```

Pause for more than 30 seconds: no new reports should be counted while paused.
Save, leave the map and reload the save: the saved count should resume.
Set `enabled` to `false`, rebuild and start a new session: no reports are registered.

`--dependency` accepts a mod project **or** a `.skieomod` archive, and can be
repeated for several mods. It resolves and installs them separately. Build/Test
dependency checks are offline; unpublished projects need explicit local paths.
To test a mapmod alone, use `skieomod run mountain-life`: the CLI creates a small
private map under `mountain-life/obj/mapmod-preview` with an exact dependency.
That preview is a test harness, not the mapmod you distribute.

## 6. Try the fox mapmod on your terrain

Download [Forest foxes 0.4.0 sources](https://skieomod.emillon.fr/tutorials/mapmods/files/foxes-0.4.0-project.zip)
and extract `foxes/` beside the practice map. Add
`{"id":"community.foxes","version":"=0.4.0"}` to the map's dependency array,
keeping Mountain life if you want both. Merge this into `extensions`:

```json
"community.foxes": {
  "count": 1,
  "seed": 7521,
  "habitats": [{
    "forest": {"x": -6000, "y": 0, "radius": 1800},
    "meadow": {"x": 6000, "y": 0, "radius": 1800},
    "crossing": [{"x": -2500, "y": 0}, {"x": 2500, "y": 0}]
  }]
}
```

```sh
skieomod build foxes --check-scripts
skieomod run practice-mountain --dependency mountain-life --dependency foxes
```

Positions and radii here are **centimetres**, unlike the editor's vegetation
JSON, which uses metres. This habitat fits the starter terrain. On your own map,
choose sheltered forest and meadow areas away from buildings, busy lifts and
cliffs. The first crossing bank is on the forest side, the second on the meadow
side; put both outside a piste. A forest circle does not create trees or a piste.

Use **F7** to centre the camera on a fox; press it again to visit the next one.
Click a fox for its small discovery panel. Check it in snow, on a slope, while
running, at night and during pause. Begin with one animal, then spread habitats
across the map instead of clustering many animals in the same place.

## 7. Read and adapt the animated example

The fox source separates three responsibilities:

| File | What to learn or change |
| --- | --- |
| `Scripts/behaviour.lua` | Habitat validation, goals, fear, hunting, play, dispersal, movement and gait timing |
| `Scripts/gaze.lua` | Nearby gaze targets and smoothly returning the eyes to neutral |
| `Scripts/main.lua` | API registration, saved checkpoints, rendering, camera shortcut and selection |
| `Assets/fox.skan` | Portable mesh sections and baked vertex-animation clips |
| `Assets/fox-ground.json` | Paw soles, leg anchors and contact/gait data |
| `Assets/fox-eyes.json` | Separate eyeball groups and aiming limits |
| `tools/prepare_fox.py` | Source geometry conversion, weighted rig, poses, snow textures and runtime rig generation |

The original Fox Anatomy model has anatomical display parts, but no usable
animation armature or clips. The converter keeps the skin and eyeballs and adds
a sixteen-joint weighted rig: hips, spine, legs, head and a segmented tail. The
pupils are texture details; gaze rotates the separate eyeball geometry.

To refine the fox's poses, obtain the original credited Collada ZIP, then run
these commands **inside the downloaded `foxes/` folder**:

```sh
python3 -m pip install numpy Pillow
python3 tools/prepare_fox.py /path/to/fox-anatomy.zip --output Assets
skieomod build . --check-scripts
```

The supplied converter expects this particular model. It is **not** a generic
FBX/GLB importer. Another species needs its own mesh conversion, rig, weights,
animations, eye/contact groups and behaviour. `Assets/fox-rig.json` records
authoring pivots, weights and source SHA-256; edit the converter's rig/pose
functions to regenerate animations. The current SKAN runtime consumes baked
poses, not an Unreal skeletal animation asset. No Unreal Editor is required.

`main.lua` spawns each animal with `api:spawn_animated`. It runs AI at 10 Hz and
interpolates nearby render poses at 30 Hz through `api:on_frame`. More distant
animals reduce animation work. Clip changes crossfade over 0.16 seconds; walk
and trot phases follow travelled distance. Jumps follow a ballistic flight,
and rodents remain invisible simulation data under the snow.

Ground support uses the actual paw soles and fresh/packed snow. `pose` produces
contact events that stamp model-shaped pawprints and play local snow crunches;
it keeps the body upright across a sideways slope. Decorative tracks use the
bounded visual fallback, because the demo exposes no reflected method to write
the skiers' private snow-track pages. Heavy snowfall builds a soft coat; shaking
removes it. The animal, transition clock, gaze, particles and sound respect pause.

For your own animated entity, declare the SKAN, textures and optional rigs in
both mod lists, wait for `map.ready` and `environment().ready`, and measure elapsed
seconds rather than assuming every callback arrives at a fixed rate. Keep expensive
AI away from per-frame mesh uploads, interpolate motion, and checkpoint serializable
behaviour state periodically. Frame callbacks do not automatically serialize state.
Use `handle:inspect` for the lightweight discovery panel and the loader's F7 API
for debug focus. See [mapmods.md](mapmods.md) for signatures and limits.

The code is MIT; the model and derived textures are **CC BY 4.0**. Preserve
`CREDITS.txt`, the original author npbehunin, the source/licence links and a
description of your changes when redistributing derivatives.

## 8. Distribute versions separately

Ship the map and each required mod as separate packages. A ZIP sent to someone
does not become discoverable automatically: the distribution catalogue must
advertise the mod's ID, version and verified download.

For the current **Featured** route, the project maintainer includes each release
in `featured-maps.json`, with its manifest, byte sizes, SHA-256 and HTTPS download
URL. The release tooling checks the dependency graph before publication. Publish
mods before dependent maps and keep earlier mod versions available for maps pinned
to them. The game resolves dependencies on Play, reuses compatible installed
versions, downloads missing ones, verifies them, then starts the map. A fully
installed map/dependency set can be played offline. The CLI currently downloads
from the project's Featured catalogue; it is not a general-purpose publisher
for arbitrary hosting services.

For **Steam Workshop**, prepare each article independently:

```sh
skieomod publish mountain-life --prepare
```

This writes unpacked content and a publication request under `bin/workshop/`;
it does not upload. Replace `preview.png` and review the private article settings.
Actual publication needs a configured native Steamworks client, which is not
included. Add the mod's real decimal-string `workshop_id` to the map dependency
before preparing that map for Workshop. Steam serves its current article content;
it does not promise arbitrary older semantic versions. See the
[Workshop contract](steam-workshop.md) for this route's limitations.

For updates, keep the package ID, increase `metadata.version`, rebuild the mod,
then update and rebuild maps that require it. `=0.1.0` pins a tested release;
`^0.1.0` permits compatible `0.1.x` releases. Test the full set before widening a
constraint. Never change a published immutable archive in place. A changed save
schema also needs an explicit migration/defaulting strategy.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Nothing happens | Confirm `runtime: "map-api"`, the returned registration function, a map dependency and the current loader; read UE4SS.log |
| Field reports appear but no animals | Mountain life is a log-only exercise; add the fox dependency and its habitat to test wildlife |
| Asset read is rejected | Add the exact relative path to both `files` and `content.assets` |
| Dependency cannot be resolved | Match ID/version and pass `--dependency` locally; remote Play needs a published compatible release |
| New script is not running | Rebuild and start/reload a map session; editing the source does not replace a running Lua closure |
| Foxes are hard to find | Use F7, begin with one fox, and check habitat coordinates, centimetres and terrain bounds |
| Movement continues in pause | Check `environment().paused` before simulation, animation, particles and audio |
| Save load resets behaviour | Use `api:mod_state`, preserve restored values and checkpoint changes outside frame callbacks |
| Workshop preparation rejects the map | Required Workshop dependencies need real `workshop_id` values; local/Featured dependencies alone are insufficient |
