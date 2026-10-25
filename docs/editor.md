# SkiEO Map Workshop

**skieomod 1.17** includes a Qt desktop workshop with a 3D terrain viewport.

For a first map, follow the illustrated
[editor tutorial](https://skieomod.emillon.fr/tutorials/editor/): start from
the base terrain or import a heightmap, sculpt, add a forest, place a resort,
then Build, Test and Play. It includes an editable practice project and an
[offline guide](editor-tutorial.md).

The per-object property panel described below requires 1.16 or newer.
The Python package installs its Qt and OpenGL dependencies automatically.
Run it in a graphical desktop session with an OpenGL-capable driver:

```sh
skieomod editor
skieomod editor my-mountain
skieomod editor my-mountain/custom-map.json
```

Opening the workshop reopens the **last opened map** by default. Choose
**Preferences → Settings… → At startup** to open the last map, create a new
map or leave no map open. An explicit project on the command line takes
precedence. If no recent project is available, the welcome panel stays open.
**File → Recent maps** opens saved source projects in most recently opened
order. With no map open, the main panel shows the same list; select a map and
click **Open selected map**, or double-click it. Missing projects are marked
unavailable. **File → Close map** returns to that panel.

**New** creates an empty map with the base terrain immediately. Sculpt the terrain, place objects or import a
heightmap whenever you want. No name, author or source folder is required to
start editing; those details have defaults and can be changed in the Map panel.
**Open** selects an existing source project. The standalone HTML editor is retired.

![A new empty map opens immediately in the workshop](https://skieomod.emillon.fr/tutorials/heightmap/images/native-empty.png)

## Create a map from your heightmap

1. Run **skieomod editor**, then click **New**. The new map is ready to edit immediately.
2. Click **Import** and browse to your own R16/RAW or 16-bit grayscale PNG.
   Import stays disabled until the file and its settings are valid; the dialog
   shows the decoded dimensions and size before you accept.
3. Set **Sample spacing** in metres. PNG dimensions come from its header.
   Square R16 can omit dimensions; rectangular raw data needs at least one
   side in **File encoding • advanced**. Select big-endian only for that export.
4. Use **Relative test range** for an immediate test, or enter actual lowest /
   highest elevations or the exporter's scale and offset. Pixels alone cannot
   recover real altitudes. Import preserves your original file.
5. **Save** asks only for an empty source folder the first time. You can create
   that folder in the chooser. Later saves use the same folder automatically.
6. **Build → Test → Play**. Build derives metadata, applies treatments and
   compiles trees, triggers, resources and object changes into `bin/*.skieomap`.
   You can also sculpt the base terrain and build without importing a heightmap.

Unavailable actions are grey. Brush settings appear only for the active brush,
object properties appear after selecting an object, and automatic forest
settings appear only when you enable that generation mode. Invalid settings
show an inline explanation and disable the affected validation/build actions.

**Play / F5** starts a separate editor test instance. Pressing Play again reloads
that same test with your rebuilt map, once loading has finished. Your ordinary
game session is left alone. New tests start with a fresh resort containing the
objects authored in your source, rather than automatically resuming an older
resort. Existing saved games retain their own objects when loaded normally.

Use **Game → Configure Steam installation…** or `skieomod setup` if Play is
unavailable. On Linux, launch the game through Steam once to prepare Proton.
The workshop uses the installed Proton compatibility tool for its test process,
including Proton's DXVK/VKD3D initialization, as a normal Steam launch does.
If Steam is closed, Play opens it first and waits for initialization; sign in if
Steam prompts you. Failed new tests are stopped and their pending map requests
are removed. The editor's output gives the launch log path under the skieomod
configuration folder (`logs/editor-<session>.log`).
Versions before 1.17 used `runinprefix`, which could select WineD3D instead and
cause a test to use a different renderer.

The workshop checks for updates in the background once a day and when Steam's
game revision changes. **Game → Check for updates** checks immediately.
The status bar reports available updates or an unverified game revision;
**Game → Update Custom Map loader** installs the loader update. Upgrade the
Python package separately using the link in that menu.

The [heightmap tutorial](https://skieomod.emillon.fr/tutorials/heightmap/)
includes format-specific questions and command-line instructions.
**Help → Mapmod tutorial** opens the
[mapmod guide](https://skieomod.emillon.fr/tutorials/mapmods/), with downloadable
practice projects, the animated fox example and separate versioned dependencies.
**Help → Surface lift tutorial** opens the
[platter lift guide](https://skieomod.emillon.fr/tutorials/surface-lifts/), with an
editable map, the separate mapmod sources, route settings and save checks.

## Navigate and sculpt in 3D

| Control | Behaviour |
| --- | --- |
| Left click / drag | Select a terrain point, or paint with the active brush |
| Middle drag | Grab the terrain: the selected point follows the cursor until release |
| Right drag | Rotate the camera around its current centre |
| Mouse wheel | Zoom the camera; over a form or list, scroll that panel |
| Fit map | Restore the full terrain view |
| Overview | Click to move to a part of the map |

The icon palette offers **Select, Place object, Raise, Lower, Level, Smooth, Plant trees and
Erase trees**. Radius and spacing are in metres; height strength is metres per
dab. Level uses the entered elevation or the point picked at stroke start.
Shortcuts **1–7** select tools when the viewport has focus. **Ctrl+Z / Ctrl+Y**
undo and redo complete brush strokes; **Escape** cancels a stroke. **P** opens
the placement palette. Selecting another tool cancels placement.

**Source terrain** is editable. **Last built terrain** displays the generated
R16 and compiled forest; build first to see erosion and automatic vegetation.
Brushes are disabled in that view. Preview trees stand on the displayed mesh.
Large forests use a uniform subset for the viewport, with its count labelled;
the package retains every compiled tree. Terrain is sampled uniformly for a
responsive preview, including the full edges of rectangular maps. The game
uses the build's terrain resolution and rendering settings.

![Processed terrain and a compiled forest in the Qt workshop](https://skieomod.emillon.fr/tutorials/heightmap/images/native-forest.png)

The preview uses elevation colours and simple tree geometry. It does not render
the game's complete materials, weather or resort buildings.

## Terrain, nature and source files

The **Terrain** panel controls the heightmap and build-time smoothing, thermal
erosion, drainage erosion and fine detail. The **Nature** panel selects None,
Manual or Automatic forest, tree line, density, patches, exclusion rectangles
and grass/rock ground colour. These are deterministic authoring approximations;
ground colour does not create 3D grass blades. Automatic forest appears after
Build. Planting manually switches to Manual; automatic clearings use exclusions.

Use **Apply settings**, then **Save** and **Build** to preview the treatments.
Every build starts from the chosen source, avoiding cumulative erosion. Painted
terrain is saved separately under `Terrain/Editor/`; imported originals stay in
the project. Replaced source files are backed up in `.heightmap-backups/`.
If an edited file changes externally, Save stops and asks you to reopen.

The **Map** panel holds identity, credits, licence, location and dependencies.
The file tree focuses on sources; generated outputs remain on disk. Text,
images, sounds and model sources belong in their appropriate authoring editor.

## Trigger Editor

Start with the illustrated [scripts and scenarios tutorial](https://skieomod.emillon.fr/tutorials/scripts/)
for a beginner route through visual graphs, Super Saint-Bernard's starting
economy and a complete practice scenario. Lua equivalents are optional tabs.
The [offline scripting guide](scripts-and-scenarios.md) ships with the tools.

Click **Triggers** in the top toolbar. A separate window lists triggers on the
left and edits the selected trigger on the right. **New trigger** creates a
visual graph with an Event connected to Print message, and a Text constant
connected to its message input. Choose the event above
the graph, select a constant node to edit its value, and use **Add node…** or
right-click to add actions or values. Drag a coloured output pin to an input
pin of a compatible type. White pins control execution; coloured pins carry
numbers, booleans, text or event values. Branch and Delay provide conditions
and timers. Delete removes selected nodes or links. The graph has its own undo,
redo, wheel zoom and middle-drag navigation.

Data inputs always use connections. For example, add **Number**, select it,
set its value to **50000**, and connect **value → Add funds.amount**. Also
connect the execution chain to **Add funds.in**. The constant displays `50000`
on the graph; Amount has no inline value field. Calculations connect their
own inputs in the same way. An unconnected data input prevents the build and
identifies the missing pin.

Choose **Lua** for a text trigger. Its body receives `api` and `event` when the
chosen event fires. The special **Project initialization • Lua** entry edits
the original map script and its existing API registration function. Switching
modes retains each source; only the selected mode is compiled.

**Configure scenario** connects Text currency and Number start year, starting
balance and ticket price. Its optional **Rules module** loads a local API 1.1
Lua module supplying construction costs, loans and lift tracking; leave it empty
for a basic scenario. Only a new game receives the starting balance and ticket
price. **Register before project script** registers a trigger before the base
script's handlers while retaining its selected event. Use it for configuration
that the base script's first `map.ready` snapshot depends on. Configure a session
only once. The checkbox defaults off for other triggers.

Click **Apply to project**, close the window, then Save and Build. Sources live
in `Triggers/triggers.json`; Build validates typed links and cycles and compiles
enabled graph and Lua triggers into the generated entry script. Disconnected
nodes are validated too. Up to 256 triggers, 512 nodes/2,048 links per graph,
180 data nodes and 64 nested branches/delays are supported. Cyclic graphs use
an event or timer instead. Generated Lua is not an editable source.

![The visual Trigger Editor with an event, message and funds action](https://skieomod.emillon.fr/tutorials/heightmap/images/native-triggers.png)

## Resource Editor

Click **Resources → Import…**, browse to a file and give it a resource ID.
The file is copied into `Resources/Files/`; the library is stored in
`Resources/assets.json`. OBJ models have a rotatable 3D preview. Choose the
source's metres/centimetres and Y/Z up axis when importing.

Portable OBJ is a static, single-material mesh, up to 50,000 triangles and
32 MiB. Build triangulates faces and embeds geometry in Lua for an individual
StaticMesh component. It reuses the replaced component's game material and
keeps the original actor's gameplay and collision. OBJ material files and
custom textures are not imported as game materials. FBX, animated characters
and cooked Unreal packages need their own game-compatible asset workflow.

Images and sound sources can be kept and packaged in the library. To replace
a reflected game sound or an instanced/animated crowd mesh, add a **Game
reference…** to a compatible cooked asset using its full object path, such as
`/Game/Folder/Asset.Asset`. The owning game package or mod must be installed;
add the mod to the map's dependencies where applicable.

## Object Editor

Click **Objects** to browse all buildings, lifts, decorations, terrain park
elements, vehicles, equipment and the skier/crowd renderer. Search by name or filter by category. The table shows properties, the game default, the map value and its
type. Search filters properties. Double-click a scalar value to edit it;
select a mesh or sound row and click **Choose resource…** to use the library.
Changed map values are **bold**. **Reset to game default** removes a difference.
Changes take effect in the project immediately. **Save → Build** writes `Objects/overrides.csv` and compiles
its differences into the map's generated Lua.

The bundled catalogue includes 118 object types and actual defaults captured
from the demo on 8 October 2026, including lift `OperatingSpeed` (cm/s), capacity,
construction cost and opening hours. Defaults may change with a game update.
Refresh them from your installation: start a
map with Custom Map **1.14 or later**, then use **Read game defaults** in the
Object Editor. A snapshot from another installation can be selected with
**Import defaults…**. Before capture, missing values say **Not captured**; no
numeric defaults are invented. The loader writes `Scripts/object-defaults.json`
inside its installed mod folder, and the editor keeps a project copy under
`Objects/game-defaults.json`. Refresh the snapshot after a game update.

Overrides affect existing and newly built instances of those classes in the
current map world. They are restored when the map unloads. The game's class
defaults are not modified. The skier entries refer to the instanced crowd
renderer: they require compatible cooked meshes, not a portable OBJ.

Follow the illustrated [Ticket Office model tutorial](https://skieomod.emillon.fr/tutorials/ticket-office/)
to import an OBJ, select its resource and build the map. A heightmap does not
specify lifts, pistes or buildings; use the placement panel below for objects.

## Place buildings and lifts

![Ticket Office and lift placements in the 3D workshop](https://skieomod.emillon.fr/tutorials/ticket-office/images/placement.png)

Select an object in the Object Editor and click **Place on map**, or open the
main workshop's **Objects** panel and search its palette. Click **Place on
terrain** and left-click a building position. A lift takes two clicks: lower
terminal, then upper terminal. Escape returns to selection.

Instances appear as labelled footprints and lift connections in the 3D view.
The Resource Editor previews imported geometry; cooked game assets are shown
by their footprints in the terrain viewport. Select an instance in the list
or click near its footprint. Change its name, position, rotation or height
offset, use **Move…** to pick a new position, or **Delete** to remove it.
Lift upper terminal coordinates are editable too. Changes support Undo/Redo.

The selected object's properties show **Default name** and **Name**. Enter a
custom name, such as “Not Ticket Office”, to rename only this building. A
custom name is **bold**; **Reset name** makes it inherit the type's name again.
An untouched Ticket Office inherits a renamed `DisplayName` from the separate
Object Editor.

The **Property / Default / This object** table below these fields edits only
the selected instance: construction cost, lift speed, opening hours, resources
and the other captured game properties. Search the table to find a field,
change its value, or use **Resource…** for a mesh or sound. Differences are
**bold** and apply immediately; **Reset value** restores the map's type default.
![Names and properties of the selected object](https://skieomod.emillon.fr/tutorials/ticket-office/images/selected-properties.png)

Saving writes these differences to `Objects/overrides.csv` with the placed
object's ID in the `instance` column. Build resolves that ID to its stable game
identifier. Other objects of the same type keep their own values.

Save stores `Scene/objects.json` and `build.scene.file` in the source manifest.
Build validates bounds, derives centimetre coordinates, stable instance IDs
and shared hubs for terminals/facilities within 80 metres, and compiles the
scene into Lua. The loader grounds each actor on the final rendered terrain
and follows native construction and lift initialization. Object CSV overrides
then apply to these instances and to objects built later in the game.

Use a **new session** to test an updated authored scene. Native saves own
existing instances: loading a save does not recreate authored buildings or
undo a player's removals.
