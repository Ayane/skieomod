# Native equipped riders and ski imprints

`surface_lifts.c` is a narrowly scoped adapter for Steam build 26143813,
executable SHA-256
`831667e59b6e64df1baecd543d98c719d5f8219ce1f3ac9648a641887dbe135f`.
The Lua loader checks the game fingerprint and reflected guest field offsets.
Before installing any detour, the DLL hashes all three complete reviewed machine
code functions against `reviewed_build.h`. Unknown code fails without patching.

A second, statically reviewed profile covers build 26178224, SHA-256
`89e207dfc37b94be6f439e4590f4140b711a369bb1e85bb7d14212b06d98e567`.
All three functions have identical normalized instructions and data offsets.
The loader still requires full game qualification before enabling this build;
the additional native profile does not bypass executable recognition.

The animation classifier (`RVA 0x51e4730`, 0x30f bytes) normally selects Idle for
standing lift passengers. Registered surface-lift GUIDs select the game's
native Skiing/Snowboarding VAT, including equipment bound to the feet. Their
simulation activity remains RidingLift. Chairlifts and unregistered guests use
the retained original function.

The imprint collector (`RVA 0x559bad0`, 0x323 bytes) normally excludes RidingLift.
Its arguments are a cold FGuestState array (stride 0xba0) and a hot array (0x80).
The adapter supplies a private hot-array copy to this collector only. It measures
actual displacement for registered passengers with stable guest GUIDs, rejects
teleports and stationary positions, and sets the native ski/snowboard stamping
activity in the copy. The game's snow simulation still creates, fades and saves
the marks. Live simulation state is never written by this hook.
The collector receives changing batches, so its bounded history is keyed by
GUID, not by array index or batch length. `track_policy.h` is also tested without
Unreal for reordering, stationary riders, expiration and rejected teleports.

The single-guest renderer (`RVA 0x5276180`, 0x1127 bytes) skips only the nearby
RidingLift guests for whom Lua has prepared a native equipped skeletal pose.
The full function spans multiple PE unwind entries; its complete code is guarded.
The replacement keeps the native skis, applies two-bone arm and leg IK and carries both
sticks in the other hand. Far riders keep the ordinary equipped VAT rendering.

The fixed-size 1360-byte SKTL v2 job contains at most 16 GUID/speed rows and
64 posed guest GUIDs. An empty job
disables all overrides. Installed trampolines remain valid and forward to native
code after cleanup, avoiding removal while renderer worker threads may be using
them. The GUID registry is protected by an SRW lock. Status includes equipped
render, native imprint submission and skeletal replacement counters for UE4SS acceptance checks.

`contact_read.h` exposes a second entry point for the loader's own terrain-only
depth targets. Lua checks every reflected parameter type and offset before
calling it. The helper checks object classes, the 56-byte parameter struct and
the UE4SS-resolved ProcessEvent/allocator exports. It reads at most 1024² pixels
through KismetRenderingLibrary and returns just their float depth channel.
The engine array is freed on every call; no per-pixel Lua wrappers, renderer
detours, private GPU offsets or persistent native buffers are used. Malformed
jobs and mismatched readback counts produce an empty result and fail closed.

`snow_grade.h` exposes the native circular snow-clear operation used by
the player's Clear Snow brush. It verifies both full reviewed functions on
26178224 before calling them, including all chained unwind regions of the
oriented implementation. A bounded SKSG v2 packet contains at most 256 world
positions, radius (100..300 cm) and removal budget (up to 500 cm). Native
clearing stops at 80 cm and updates tiled snow and its coarse cache together.
Readback textures remain outputs. Lua admits passages only from native working
groomers, with movement, job continuity, pause and snow-readback guards. It
never spawns or teleports a groomer or fabricates a completed maintenance job.

Build with `sh native/SkiEOSurfaceLifts/build.sh` (MinGW-w64). It uses the same
unmodified MinHook 1.3.4 sources as SkiEOTrailRatings; the distributed loader
includes `LICENSE-MINHOOK.md`. No game machine code or game assets are shipped.

`evacuation.h` adds a game-thread-only bridge for stopped surface lifts on
26178224. Lua validates reflected arrays and route fields. The bridge hashes
all complete reviewed functions before using the native release accounting,
route destructors/constructors, activity transition and skiing projection.
The public OnLiftDeleted path releases seats and reservations; the actor and
save GUID remain. SKEV v1 has a 64-byte header and at most 4,096 48-byte guest
entries, checked by index and GUID before any mutation. Ski routes use native
trail-ID arrays, so movement and serialization stay native.

SKWT v2 is a fixed 2,208-byte job with a 32-byte header and up to 272 ordered
trail-ID/blocked pairs. Three guarded native snowcat phase hooks stop active
jobs before movement or grading while evacuated skiers occupy the corridor.
For registered service/escape trails they also zero the native lateral lane
offset, whose use is anchored by the complete reviewed position helper. Native
snowcats follow the narrow corridor centre rather than driving through pylons.
An empty job clears this registry on disposal; other jobs forward unchanged.
