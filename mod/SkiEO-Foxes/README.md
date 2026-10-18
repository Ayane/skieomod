# Forest foxes — standalone mapmod example

`community.foxes` 0.4.0 is a Map API dependency for SkiEO Custom Map 1.20.5+.
Veymont 0.7.6 pins this version; its `.skieomap` does not contain the fox assets.
The separate `.skieomod` contains the skin, eyes, nine animation clips,
behaviour and attribution. Rodents are simulated in galleries under the snow;
they have no visible mesh, texture or actor.

From the repository root:

```sh
skieomod build mod/SkiEO-Foxes --check-scripts
skieomod run mod/SkiEO-Foxes
skieomod run mod/SkiEO-Veymont --dependency mod/SkiEO-Foxes
```

`run` creates an ordinary private preview map for a mapmod. The default habitat
fits that map. `--dependency` builds and installs the dependency separately; it
never embeds it in the map archive. A new public version must be published with
its own immutable archive in the Featured catalogue before players can download it.

The example has idle, walk, trot, sniff, pounce, feeding, bounding, play-bow and
shake clips. Hips and spine counter-rotate, with three linked tail joints.
Veymont assigns four distant territories. Hunger and fatigue govern feeding,
listening, hunting and longer rests in shelter. Searches follow a persistent,
gently curving heading through a feeding patch, with sniffing stops. A rodent
belongs to the current habitat; the fox does not chase one across a daytime
piste. Night crossings serve feeding or return to shelter and have a cooldown.
Native visitors, workers and operating lift terminals/corridors take priority:
the fox watches from a distance, retreats when approached, then waits in a quiet
place. Candidate feeding/shelter positions and movement reject activity zones.
The camera is an observation tool and does not count as a person.
On encountering a neighbour they briefly play, then depart in opposite
directions with a cooldown. Snow accumulates on a separate coat, which the fox
sheds in visible flakes when shaking. Accumulation occurs only in a local
native blizzard with snow precipitation. Dry ground snow and light snowfall do
not coat the fur. A smooth dorsal mask is baked into sixteen fur textures,
shared by the animals; the old triangle-cut white shell remains hidden.
Foxes roam their
current forest or meadow, listen for underground prey and pounce through the
snow to catch it, and enter authored
crossing routes between 20:00 and 06:00. A fox caught on a piste at dawn continues
to its bank. Other travel checks the native piste map, terrain bounds and slope.
Population and random-generator state are checkpointed every 30 real seconds
and stored in the map's native save.
Movement, poses, eyes and snow flakes stop while time, the UI or the world is paused.

Click the visible fox to open a small inspection card: species, current activity
and habitat, with a discovery message. It closes with X, Escape, an outside
click or native guest/building selection. It also works when time is paused;
terrain/building tools and UI clicks do not select an animal.

For testing, press **F7** in the game to centre the normal movable camera on a
fox from five metres away. Press again to visit the next fox, cycling through
the population. This also works while time is paused. The shortcut is active
only after a map using this dependency has finished loading; unloading removes
its callback. It does not spawn animals or change their behaviour/save state.

The eyeballs are separate geometry; their pupils are painted in the texture.
`Scripts/gaze.lua` aims each globe at the prey while hunting, the landing/feeding
spot, the next movement target, or short idle fixations. A nearby observer gets
brief attention. `Assets/fox-eyes.json` defines the two orbit centres and axes
from animated vertices, keeping them attached even while the head bends.
Rotation is smoothed and limited to 16° horizontally and 10° vertically.
Gaze is fully active within four metres of the camera, fades to neutral between
four and twelve metres, and adds no eye deformation farther away.

`Scripts/behaviour.lua` is a deterministic state machine without engine calls.
`Scripts/main.lua` connects it to the sandboxed Map API. The loader provides
portable animation rendering, current terrain/snow/piste queries, and a bounded
pool of 256 geometric pawprints. Prints disappear after six game hours, on snow
melt, or on unloading. They are visual marks, not native snow deformation.
The four actual model soles define support, independently of the bounding box.
Two-bone leg adaptation follows longitudinal slopes while keeping the torso
upright on cross slopes. It is fully active within six metres, fades out by ten
metres, and fades out through the first three centimetres of paw burial. Hidden
or distant legs keep their baked animation; support height, pitch, penetration
and contact marks still work. Stance paws stay fixed in world space until lifted.
Hermite swing endpoints match stance velocity, with smooth takeoff/landing.
Turning corrections fade instead of teleporting planted paws; the paw centres
use 82% of the original stance width, with shorter walk/trot strides.
Native `packed_cm` and `fresh_cm` remain separate: paws sink through 85% of the
fresh layer, limited to leg height plus 8 cm, without compressing the packed base.
Ordinary travel walks or trots. Locomotion uses bounds only once penetration
reaches the model's leg height; the hunting pounce remains a separate action.
Walk/trot time comes from distance along the terrain, with 36/50 cm strides,
including acceleration, slower turns, blocked movement and powder resistance.
Short quiet runs supplement the feeding searches. Bounds and hunting pounces
use ballistic flight with gravity 980 cm/s², independently of forward speed:
roughly 0.63 seconds in deep snow and 0.73 seconds for a 65 cm hunting jump.
Flight, landing and their render interpolation continue with their own clock;
powder resistance cannot stretch a leap into slow motion.
The map's measured −12 cm visual calibration identifies the displayed surface;
there is no extra bounding-box or contact-height margin.
Each contact projects the model's sole triangles into a pawprint. Airborne feet
cannot stamp; the AI no longer emits generic marks every 32 cm.
The native `SC_WalkingInSnow` sound plays as a short, attenuated contact burst
inside nine metres of the camera. One reused audio component per fox is owned
by the animal and stops during pauses. Demo build 25808900 exposes no reflected
snow-track stamping method; this example uses the bounded visual mesh fallback
instead of writing the skiers' private snow-track pages.
Behaviour advances at 10 Hz in real simulation seconds; nearby poses are
interpolated at 30 Hz on the engine frame loop. Farther animals reduce animation
updates to 10 Hz, then 1 Hz. Adjacent frames
and vertex buffers are reused. Clip changes crossfade over 0.16 seconds, with
smooth start/end weights, matching leg anchors/contact targets and normalized
normals. Interruptions blend from the current pose. Ground and eye corrections
remain separate from the authored source poses, and pause stops the transition
clock. Cached native CPU snow data avoids GPU readback
stalls. The native clock determines night, pause and track expiry. The example uses authored routes,
not a full wildlife navigation mesh or avoidance of every tree/building.

## Rebuilding the fox asset

```sh
python3 tools/prepare_fox.py /path/to/fox-anatomy.zip
```

The conversion uses NumPy and Pillow. The downloaded Collada contains skin,
eyes, bones, muscles and organs, but no armature/controllers or animation.
The converter keeps skin/eyes, derives a removable snow coat, sets centimetre scale and adds a sixteen-joint
weighted rig. `Assets/fox-ground.json` packages sole profiles, leg bindings and
animated hip/knee anchors used for runtime support. `Assets/fox-rig.json` records pivots, weights, animation settings and
source SHA-256. Edit the rig/pose functions in the converter to refine the motion;
rerun it to regenerate the binary clips. Source anatomy and the rig description
are not included in the runtime package. The converter generates no rodent model.

The `.skan` format and configuration are described in
[the mapmod guide](../../docs/mapmods.md). The rig is an initial procedural pass;
the rendered model and native save/reload were verified in demo build 25808900.
Runtime leg adaptation and footprint profiles use the model's four soles.
See [CREDITS.txt](CREDITS.txt) for the original fox author and CC BY attribution.
