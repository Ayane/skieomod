# Native terrain and scenario helper

Build the Windows helper from the repository root with MinGW-w64:

```sh
x86_64-w64-mingw32-gcc -shared -O2 -s -Wall -Wextra \
  native/SkiEONativeTerrain/native_terrain.c \
  -o mod/SkiEO-CustomMaps/Scripts/skieo_native_terrain.dll
```

Terrain diagnostics and supported layouts are documented in [terrain-runtime-debugging.md](../../docs/terrain-runtime-debugging.md).

Terrain jobs `SKNT` v5/v6 append the rendering stride, cliff subdivision stride,
refined-cell count, a zero reserved word and unique one-based refined-cell keys.
The helper validates the bounded topology, then samples the same triangles and
stitched fans as `terrain_mesh.lua`. It generates the complete native grid and
textures before committing the cache. This keeps guests, snow and brushes on
the displayed relief without increasing rendering density or changing map data.
The portable sampler is checked against actual Lua-generated mesh triangles.

Build 26056171 moves the hub batching counter to `+0xB10` and changes the
navigation work counter and terrain dirty flag. The navigation resolver now
checks the counter instruction as well as its prologue before choosing the
paired terrain-change handler. Older reviewed profiles remain supported.

`skieo_stage_game_options` accepts a bounded `SKGO` v1 request containing the
game-session address and class, seed, day-length scale, days per month and
sandbox flag. It checks the session class and an exact, unique executable
signature of the native request assignment before writing the reviewed fields.
Lua additionally checks the reflected session anchors. Portable tests verify
the signature, rejection paths, write bounds and preservation of adjacent state.

The Lua loader now checks reflected terrain, Landscape, placement and session
anchors before staging a world or registering private properties. It obtains
field addresses through UE4SS `ContainerPtrToValuePtr` on default objects, without
reading a guessed FProperty layout. These extra checks protect the existing
private bridges; changed hub/staff/snow/engine layouts still need profile review.

Terrain-pad registration uses the native placement method after final source
alignment. `terrain_pads_layout.h` guards all 2,088 bytes of the reviewed
function and all 267 bytes of its preceding component cleanup for builds
25996759 and 26019240, including their call displacements.
The Lua caller checks reflected placement fields and live actor ownership;
the helper validates every actor in a batch before invoking the first method.
It does not clear the brush render target, sculpt layers or snowpack. See the
[snow investigation](../../docs/buildings-snow-26019240.md) for the reproduced
save/restore rendering defect.

## Scripted scenario saves

`skieo_sync_scenario_state` synchronizes script state with the current world's `ScenarioSubsystem` before the native manual or asynchronous save copies its state. Native C++ saves bypass the `GameplayStatics` UFunction hooks, so those hooks cannot provide reliable persistence.

The loader encodes at most 32 KiB of JSON into chunked FNames in `FScenarioSaveData.CompletedObjectives`. The JSON includes the map id. Restoration validates the complete chunk sequence and the map identity before handing state to the map script. Unknown objective names are ignored by the native scenario evaluator.

The helper reads a versioned `SKIS` job on the game thread. It verifies the subsystem class, active definition, readable memory, bounded array and unique executable signatures for the native completed/failed getters before using the private layout (`FScenarioSaveData` at `+0x98`, objective array at `+0xB0`). The array stays owned by Unreal and is resized through UE4SS's Unreal allocator. An incompatible layout returns an error; it must never be replaced by an unverified custom array property.

Verified in the game demo build **25808900**, Unreal **5.8**, UE4SS **3.0.1-1152-ge3ba1016**: a manual native save and the file read back from disk contained the maintenance level, condition gauges and an 800,000 F Menouve refit. Full level travel restored that state, the existing five placeables and the original project deadline. The new scenario definition is cloned from the initialized Corporate Takeover asset; constructing nested objective/condition arrays from Lua tables is unsafe on this build.

Travel to the independent level must retain the native game mode:

```text
/Engine/Maps/Entry?game=/Game/Core/BP_SkiResortGameMode.BP_SkiResortGameMode_C
```

Opening `Entry` without that mode leaves an empty black world and does not test native save restoration.

## Geographic hub names and initial skiability

`skieo_name_hubs` stores up to 64 GUID/name pairs in the native hub name map. It uses Unreal's FText factory and map insertion function, so the native management groups and save writer share the new names. The `SKHN` job validates UTF-8, lengths, owner class, map bounds and three executable signatures before calling the verified private layout. It releases the temporary FText through its native reference interface after the map has copied it.

`skieo_refresh_skiability` invalidates the minute key of `TrailMapSubsystem::HasAnySkiableTrail`, once the native snow cache reports ready. Source-world loading pauses the game clock: a false result computed before snow readback can otherwise remain cached at the same minute after 120 cm of snow is present. The `SKSK` job checks the owner class and the exact query/memo instruction signatures. It changes neither the stored result nor the snow threshold. Verified on demo build **25808900**: both historical lifts become Operating with 100 cm packed + 20 cm fresh snow, and both correctly return No Snow to Ski after clearing the native snow planes and waiting for CPU readback.

These bridges return an explicit unsupported-layout error on a different executable. Reverify the layouts before extending support to another build.

`SKIS` v2 additionally accepts a null scenario for a loaded sandbox map. It
requires the native active scenario pointer to be null, keeps scenario identity
and outcome flags intact, and writes only the bounded objective-name array. This
allows mapmod checkpoints without presenting a scenario UI. The fox example
checkpoints every 30 real seconds to avoid per-frame FName allocations.
Verified in demo build 25808900: a named native save read back from disk
contained four foxes and four rodents, and native level travel restored all four
foxes at their saved coordinates.

## CPU snow samples for wildlife

`skieo_sample_snow` reads the existing asynchronous `SnowStateCache` on the game
thread, without requesting or flushing GPU readback. A 40-byte `SKSN` v1 job
contains the cache address, expected class address and world XY. The 16-byte
result contains ready, packed centimetres, fresh centimetres and X cell spacing.
It verifies three exact executable signatures, owner class, valid-cache flag,
bounds, tile map allocation bits and bounded 64×64 sample arrays before reading.
Missing tiles or unsupported layouts return ready zero. It owns no Unreal
objects and mutates neither snow nor cache. Verified on demo build 25808900:
all four Veymont fox territories report 100 cm packed + 20 cm fresh in 0–1 ms.
Lua caches spatial samples for two seconds; wildlife rendering makes no
synchronous GPU snow reads. Reverify the private layout for another build.
