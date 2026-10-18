# Web publication and the in-game catalogue

The default domain is **https://skieomod.emillon.fr**. The old
`skieomap.emillon.fr` hostname redirects to it. The website presents the mod,
installation instructions and tutorials; map browsing happens in
**New Game → Custom Map**.

## Publish with skieomod

Sign in with Steam at [the creator account](https://skieomod.emillon.fr/account)
and create a publishing token. It is shown once, expires in 30 days and can
be revoked from the same page. The token identifies the Steam account that
owns your package ID. Keep it outside your project and shell history.

In Bash:

```sh
read -rsp 'Publishing token: ' CUSTOM_MAP_TOKEN; echo
export CUSTOM_MAP_TOKEN
skieomod publish my-map
unset CUSTOM_MAP_TOKEN
```

In PowerShell:

```powershell
$token = Read-Host 'Publishing token' -AsSecureString
$env:CUSTOM_MAP_TOKEN = [System.Net.NetworkCredential]::new('', $token).Password
skieomod publish my-map
Remove-Item Env:CUSTOM_MAP_TOKEN
```

`publish` accepts a project directory, a manifest, or a built `.skieomap`,
`.skieomod` or ZIP archive. Projects are built and every package is validated
before upload. `--check-scripts` also checks Lua syntax using Lua 5.4.
The server validates again, including dependency resolution and archive limits.
A version is immutable; increase `metadata.version` before publishing an update.
Only the original Steam owner may publish further versions of a package ID.

The default destination can be overridden with `CUSTOM_MAP_REPOSITORY` or
`skieomod publish my-map --repository https://your-repository.example`.
Authentication is only sent to an HTTPS origin. Publication does not follow
redirects or retry POSTs automatically. If a connection fails after upload,
refresh the in-game catalogue before retrying the same version.

## Browse and play

The in-game menu combines local projects/packages, the web API registry and
the separate Featured catalogue. Use **All**, **Local**, **Web** or **Steam**,
then search by name, package ID, author, location, description or tags.
**Local** includes downloaded maps: a map can match both Local and Web.

**Refresh maps** updates metadata without downloading every map. **Play**
fetches missing map content and map API dependencies, checks their size,
SHA-256 and manifests, then loads the map. Downloaded maps work offline.
Updates are optional and use separate versioned packages; local authoring
files are never replaced. Unavailable servers retain their cached catalogue.
UE4SS startup dependencies still require installation and a game restart.

## Steam Workshop

Web publication remains the default while Steam integration is prepared:

```sh
skieomod publish my-map --prepare
skieomod --steam-client PATH publish my-map --steam
```

`--prepare` works offline. `--steam` explicitly selects the separately supplied
native client; it never silently falls back to web publication. See the
[Steam contract](steam-workshop.md) for item metadata and dependency IDs.
