# Optional asset tools

The mod, CLI and website do not require UAssetAPI. Asset research and
`tools/UAssetPatcher` use the upstream submodule pinned by this repository.
With .NET SDK 8 installed, run from the repository root:

```sh
git submodule update --init third_party/UAssetAPI
git -C third_party/UAssetAPI apply --check ../uassetapi-net8.patch
git -C third_party/UAssetAPI apply ../uassetapi-net8.patch
dotnet build tools/UAssetPatcher -c Release
```

The patch targets .NET 8 and replaces one newer C# syntax construct. It is
kept separately so the upstream source and license remain identifiable.
Apply it once to a fresh submodule checkout. Generated `bin` and `obj`
directories are ignored. UAssetAPI retains its MIT license and notices.
