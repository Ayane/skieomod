# Custom Map Windows helper

`repository.c` exports Lua C callbacks using the existing loader's file-based
ABI, without linking against UE4SS internals or a separate Lua runtime.

- `skieo_fetch`: starts one WinHTTP worker. The Lua caller polls its status
  through a retained delayed callback. Requests require HTTPS, reject redirects,
  enforce a byte limit and verify an optional SHA-256 with Windows BCrypt.
  The worker publishes received bytes in `network.progress`, allowing the
  loading screen to display download progress without blocking the game thread.
- `skieo_inflate`: validates a bounded raw Deflate member and CRC using miniz,
  then writes the result. The Lua fallback supports the same ZIP methods.
- `skieo_game_identity`: hashes the running executable with BCrypt on a separate
  worker, once per process. Lua compares its SHA-256 with qualified builds to
  display the Custom Map version warning, including when offline.

Build on Linux with MinGW:

```sh
sh native/SkiEORepository/build.sh
```

The resulting `skieo_repository.dll` is bundled beside the Lua scripts. Registry
requests and downloads use the configured repository origin; no game API key or
Steam credential is sent by the helper. Temporary files always stay beside it.

The miniz headers and inflate source are vendored from
https://github.com/richgel999/miniz/tree/3.0.2 under the included `LICENSE`.
`miniz_export.h` is the local static-build export definition. The portable editor
vendors fflate 0.8.2 with its license in `editor/vendor/`.
