# Create a map with skieomod editor

Create a playable Ski-E-O! map in the graphical **SkiEO Map Workshop**. Start
with its base terrain or import a heightmap, shape the slopes, add trees and
place a small resort, then build and test your map using the toolbar.

The [illustrated web tutorial](https://skieomod.emillon.fr/tutorials/editor/)
includes real editor captures and a downloadable source project. The
[editor reference](editor.md) describes the more advanced tools.

## 1. Open the workshop

Install the current `skieo-custom-map` tools with Python 3.10+ and pipx, as
described in the [installation guide](getting-started.md). The installation
includes the Qt and OpenGL dependencies. Open a terminal once to launch:

```sh
skieomod editor
```

The remaining map creation steps use the editor. A graphical desktop with an
OpenGL-capable driver is required. You can author without installing the game;
Play requires the Steam Windows game or demo, on Windows or Linux with Proton.

Click **New**, or **Create a map** on the welcome panel. An empty map opens
immediately with the base terrain. You can start sculpting straight away.
The workshop may reopen your last map at startup; **New** starts another.

Identify the three main areas:

- **Left:** terrain brushes, brush settings, overview and project files.
- **Centre:** the 3D terrain, the Source/Last built selector and build output.
- **Right:** Terrain, Nature, Map and Objects panels.

**Save**, **Build**, **Test** and **Play** are in the top toolbar. You will use
them after editing. The separate **Triggers**, **Resources** and **Objects**
buttons open advanced editors.

## 2. Choose a terrain

You can keep the base terrain and continue to step 3. Importing is optional.
To use an existing heightmap, click **Import** and choose an R16/RAW file or a
16-bit grayscale PNG. Set **Sample spacing** to the distance in metres between
adjacent samples, using the value from your terrain exporter.

For a known working example, download the
[Alpine Valley PNG](https://skieomod.emillon.fr/tutorials/heightmap/downloads/alpine-valley.png).
In the import dialog, use:

| Setting | Practice value |
| --- | --- |
| Sample spacing | **8 m** |
| Elevation | **Known lowest / highest** |
| Lowest / highest (m) | **800 / 2200** |
| File encoding | Leave automatic |

Wait for **513 × 513 samples • 4096 × 4096 m • ready to import**, then click
**Import heightmap**. These numbers belong to the practice file, not every map.
The editor preserves your original file and keeps a project copy when needed.

For your own file, **Relative test: 0–1000 m** gives a first relief preview when
you do not know the altitude encoding. Use **Known lowest / highest** or
**Exporter scale / offset** when your export metadata supplies those values.
Pixels alone cannot recover real altitudes.

PNG dimensions come from its header. A square R16 can infer dimensions from
file size. For rectangular raw data, open **File encoding • advanced** and
enter at least one known side under **Samples across / down**. Choose
**R16 big-endian** only if your exporter used it. PNG must be non-interlaced,
16-bit grayscale without alpha; an ordinary colour or 8-bit image is unsuitable.

Check the dimensions before accepting: width in metres is
`(samples across − 1) × sample spacing`. Click **Fit map** to see the whole terrain.

## 3. Navigate and shape the slopes

Keep **Source terrain** selected above the viewport. This is the editable view.

| Control | Action |
| --- | --- |
| Right drag | Rotate the camera |
| Middle drag | Grab and move the terrain view |
| Mouse wheel | Zoom; over a panel, scroll that panel |
| Fit map | Show the full terrain |
| Overview | Click to move to a part of the map |

Choose a brush on the left and left-drag on the terrain:

- **Raise / Lower:** change elevation. Brush radius is in metres; **Height per
  dab** is the change applied by each brush dab. Start with small changes.
- **Level:** flatten a small area for the resort base. Leave **Level height
  (m)** blank to pick the height at the start of the stroke, or enter a height.
- **Smooth:** soften sharp transitions around the levelled area.

For practice, try a **60 m** radius and **1 m** height per dab, then inspect the
result from another angle. Use **Ctrl+Z / Ctrl+Y** to undo/redo entire strokes;
**Escape** cancels a stroke. Choose **Select** when you finish painting.

Surface treatments in the **Terrain** panel are optional build settings.
Start with them off. To try smoothing or erosion later, enable a treatment,
click **Apply settings**, then **Build** and inspect **Last built terrain**.
Each build starts from the source, so erosion does not accumulate across builds.

## 4. Name and save the source project

Open the **Map** panel on the right. Fill in **Name**, **Authors**,
**Package ID**, **Version**, **Licence** and **Description**. For your own map,
use an ID such as `yourname.alpine-valley` and a version such as `0.1.0`.
Keep this ID for future releases. Credit imported terrain and other resources.
Leave location fields blank for an imaginary place; if you supply a location,
enter both latitude and longitude. Leave dependencies empty for this first map.

Click **Apply settings**, then **Save** or **Ctrl+S**. On the first save,
choose an **empty writable folder**, such as `alpine-valley-workshop`.
You can create it in the chooser, then click **Save map here**. Later saves
use this folder automatically.

This folder is your editable source project. Keep it for future changes;
the built `.skieomap` is the file players will use. **Open** selects a source
folder containing `custom-map.json`; **File → Recent maps** reopens saved projects.

## 5. Add trees

Choose one of two ways to create the forest:

- **Manual:** choose **Plant trees**, set the radius and **Tree spacing**, then
  paint on the terrain. **Erase trees** clears a route or the resort base.
  Painting switches the Nature panel to **Manual**.
- **Automatic:** open **Nature** and choose **Automatic**. For Alpine Valley,
  try **Tree line (m): 1900**, **Trees / hectare: 12**, and **Tree limit: 10000**.
  Click **Apply settings**. Generated trees appear after **Build** in
  **Last built terrain**.

The automatic values suit the practice terrain's 800–2200 m elevations. Adapt
them to your map, especially if you imported with relative elevations. To clear
an automatic forest, use its exclusion rectangles; erasing with a brush
switches to Manual. These modes represent different forest sources.

For example, the downloadable project uses the automatic clearing
`[[-450, 880, 180, 1300]]`, entered in the exclusions box as
`[west, north, east, south]` in metres, around its lower lift terminal.
You can leave the box at `[]` for no exclusions. **Bake grass / rock ground
colours** is optional; it creates ground colour, not 3D grass blades.

## 6. Place buildings and a lift

Switch to **Source terrain**, then open the **Objects tab on the right**.
Search for **Ticket Office**, choose it in the palette and click
**Place on terrain**. Left-click a level area at the resort base. Press
**Escape** after placement so another click does not place a second building.

Search for a lift, such as **Chair lift (one seat)**, select it and click **Place on
terrain** again. Click the **lower terminal first**, then a position uphill
for the **upper terminal**. Both terminals must stay inside the map. Escape
returns to selection.

Select an instance in **Objects in this map** or near its footprint in the
viewport. Edit its name, position, rotation or height offset. A lift also has
**Upper terminal** coordinates. **Move…** picks a new position; **Delete**
removes the instance. Undo/Redo also works for placements.

The right-hand tab places and edits individual instances. The separate
**Objects toolbar button** opens the Object Editor for defaults shared by an
object type. You do not need to change those defaults for this exercise.

Buildings appear as labelled footprints and lifts as terminal connections in
the preview. Their game models appear when you play. The game grounds them on
the final terrain. Pistes are not drawn by importing a heightmap or placing a
lift; lay them out in the game when testing this first resort.

## 7. Build, validate and play

1. Click **Save**, then **Build**. Read the output below the terrain. On success,
   the editor selects **Last built terrain** and shows the compiled forest.
   The playable archive is in your source folder's `bin/` directory.
2. Click **Test**. It validates the project without launching the game.
   Wait for **Project validation passed**. Fix any reported problem in the
   relevant panel, then build again if you changed the map.
3. Configure Play once through **Game → Configure Steam installation…**.
   Choose the Steam game folder containing `SkiResortSimulator`. This installs
   Custom Map/UE4SS and remembers the paths. Close the game before setup.
   On Linux, first launch the game through Steam once to prepare Proton.
4. Click **Play** or **F5**. It saves, rebuilds, installs the map and opens a
   separate editor test instance. Inspect the slopes, forest, buildings and
   lift, then try making a piste and using the resort.

Build, Test and Play save current editor changes before running. Play starts
a fresh resort with your authored objects. After changing the source, press
Play again to rebuild and reload the same test instance once loading has
finished. Existing game saves retain their own buildings and removals; use
the editor test to check a changed starting layout.

To resume editing after Build, switch back to **Source terrain**. Brushes and
placement are disabled in **Last built terrain**. The preview uses simple
terrain colours and tree geometry; materials, snow and gameplay need checking
in the game.

## 8. Share and continue

Use **File → Show project folder** and open `bin/`. Send the versioned
`.skieomap` to a tester who has the matching Custom Map loader. Keep your source
folder separately, or zip the source folder for a collaborator who will edit it.
Increase **Version** in the Map panel before building a new release and keep
the same Package ID.

The [practice source ZIP](https://skieomod.emillon.fr/tutorials/editor/files/alpine-valley-workshop.zip)
contains the imported CC0 terrain, automatic forest and two placed objects.
Extract it, click **Open** and choose the extracted `alpine-valley-workshop`
folder. Change its identity before releasing your own derivative. Terrain
licence details are in `CREDITS.txt`.

Next, use the [visual scripts tutorial](https://skieomod.emillon.fr/tutorials/scripts/)
to set starting money or add a scenario, the
[Ticket Office tutorial](https://skieomod.emillon.fr/tutorials/ticket-office/)
to replace a model, or the [mapmod tutorial](https://skieomod.emillon.fr/tutorials/mapmods/)
to attach reusable behaviour. For publication routes, see the
[Workshop guide](steam-workshop.md) and [mapmod distribution guide](mapmod-tutorial.md#8-distribute-versions-separately).

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Import heightmap stays grey | Read the dialog feedback. Check spacing, altitude range, raw dimensions and image format. |
| Save map here stays grey | Select an empty writable folder; create a new one in the chooser if needed. |
| Save, Build or Test is disabled | Finish the current operation or fix the inline settings error. |
| Brushes or placement are disabled | Switch from Last built terrain to Source terrain. |
| No automatic trees in the preview | Build, select Last built terrain, then check tree line, density, slope limit and exclusions. |
| A second building appears by accident | Undo the extra placement and press Escape to leave placement mode. |
| Play is disabled | Configure the Steam installation through the Game menu; wait if the test is still loading. |
| Build or Play fails | Read the output panel. Fix the reported source/settings problem; launch errors also give a log path. |
| Source changes conflict with an external edit | Reopen the source project before saving again. |
| An old save shows the old buildings | Test the updated starting layout with Play and a fresh resort. |
