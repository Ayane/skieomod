"""Shared map/mod validation and bounded dependency resolution for Custom Map."""
from __future__ import annotations
import functools
import json
from pathlib import Path
import re
import zipfile
if __package__ == "tools":
    from . import custom_maps as maps
else:
    import custom_maps as maps

ManifestError = maps.ManifestError
MAP_LIMIT = 512 * 1024 ** 2
MOD_LIMIT = 256 * 1024 ** 2
MANIFESTS = {"map": "custom-map.json", "mod": "custom-mod.json"}


def validate_mod(manifest):
    maps._object(manifest, "manifest")
    fmt = maps._object(manifest.get("format"), "format")
    if fmt.get("name") != "skieo-mod" or not re.fullmatch(r"1\.\d+\.\d+", str(fmt.get("version", ""))):
        raise ManifestError("expected skieo-mod format 1.x")
    if not isinstance(manifest.get("id"), str) or not maps.ID_RE.fullmatch(manifest["id"]):
        raise ManifestError("mod id must be namespaced")
    maps._validate_metadata(manifest)
    maps.semver_compare(manifest["metadata"]["version"], manifest["metadata"]["version"])
    maps.validate_dependencies(manifest)
    runtime = manifest.get("runtime", "map-api")
    if runtime not in {"map-api", "ue4ss"}:
        raise ManifestError("mod runtime must be map-api or ue4ss")
    files = maps._array(manifest.get("files"), "files")
    if not files or len(files) > maps.MAX_ARCHIVE_FILES - 1:
        raise ManifestError("mod files must contain 1..4095 paths")
    for path in files:
        maps.safe_relative_path(path, "mod file", allow_cooked=True)
        if path.casefold() in {name.casefold() for name in MANIFESTS.values()}:
            raise ManifestError("mod files cannot contain a package manifest")
    if len({path.casefold() for path in files}) != len(files):
        raise ManifestError("duplicate mod files")
    if runtime == "map-api":
        script = maps._object(manifest.get("script"), "script")
        if script.get("language") != "lua" or not re.fullmatch(r"1\.\d+", str(script.get("api", ""))):
            raise ManifestError("map-api mods require Lua script API 1.x")
        if script.get("entry") not in files:
            raise ManifestError("script.entry must be listed in files")
        permissions = maps._array(script.get("permissions", []), "script.permissions")
        for permission in permissions:
            maps._string(permission, "script.permissions[]")
        if any(item not in maps.ALLOWED_PERMISSIONS for item in permissions):
            raise ManifestError("unknown script permission")
        content = maps._object(manifest.get("content", {}), "content")
        maps._array(content.get("assets", []), "content.assets")
        if any(item not in files for item in content.get("assets", [])):
            raise ManifestError("mod assets must be listed in files")
    else:
        directory = manifest.get("install_directory")
        if not isinstance(directory, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", directory):
            raise ManifestError("ue4ss mods need an install_directory without path separators")
        if directory.lower() in {"skieo-custommaps", "custom-map", "shared"}:
            raise ManifestError("reserved mod installation directory")
        if "Scripts/main.lua" not in files and "dlls/main.dll" not in files:
            raise ManifestError("ue4ss mod must include Scripts/main.lua or dlls/main.dll")
    return manifest


def inspect_package(path: Path, kind: str | None = None, *, max_unpacked=maps.MAX_UNPACKED_BYTES):
    try:
        with zipfile.ZipFile(path) as archive:
            present = [value for value, name in MANIFESTS.items() if name in archive.namelist()]
            if len(present) != 1 or (kind is not None and kind != present[0]):
                raise ManifestError("package must contain exactly one root map/mod manifest matching its kind")
            kind = present[0]
            limit = MAP_LIMIT if kind == "map" else MOD_LIMIT
            if path.stat().st_size > limit:
                raise ManifestError(f"{kind} exceeds the {limit // 1024 ** 2} MiB compressed size limit")
            names = maps.validate_zip(archive, max_unpacked=max_unpacked, allow_cooked=kind == "mod")
            manifest = maps.read_zip_manifest(archive, MANIFESTS[kind])
            if kind == "map":
                maps.inspect_archive(path)
                references = [str(item) for item in maps.referenced_paths(manifest)]
            else:
                validate_mod(manifest)
                references = manifest["files"]
            if any(item not in names for item in references):
                raise ManifestError("package is missing referenced files")
            if set(names) != {MANIFESTS[kind], *references}:
                raise ManifestError("package contains files absent from its manifest")
            return kind, manifest, sum(info.file_size for info in archive.infolist())
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, EOFError) as error:
        raise ManifestError(str(error)) from error


def pack_package(manifest_path: Path, output: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format", {}).get("name") == "skieo-map":
        maps.pack(manifest_path, output)
    else:
        validate_mod(manifest)
        root = manifest_path.parent.resolve()
        paths = []
        for name in manifest["files"]:
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ManifestError(f"missing file or symlink escape: {name}")
            paths.append((name, path))
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w") as archive:
            maps.write_zip_member(archive, MANIFESTS["mod"], (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
            for name, path in sorted(paths):
                maps.write_zip_member(archive, name, path.read_bytes())
    return inspect_package(output)


def resolve(packages, root_id, version="*", *, max_steps=10000):
    """Backtrack across versions, reject cycles and return dependencies first.

    packages are release dictionaries with id, kind, version and manifest.
    Optional dependencies are omitted; authors must mark required mods explicitly.
    """
    by_id = {}
    for package in packages:
        by_id.setdefault(package["id"], []).append(package)
    for candidates in by_id.values():
        candidates.sort(key=functools.cmp_to_key(lambda a, b: maps.semver_compare(a["version"], b["version"])), reverse=True)
    steps = 0

    def search(selected, pending, edges):
        nonlocal steps
        steps += 1
        if steps > max_steps:
            raise ManifestError("dependency graph is too complex")
        if not pending:
            return selected, edges
        identifier, constraint, ancestry, mod_only, workshop_id = pending[0]
        if identifier in ancestry:
            return None
        rest = pending[1:]
        if identifier in selected:
            release = selected[identifier]
            if maps.version_matches(release["version"], constraint) and (not mod_only or release["kind"] == "mod") and (not workshop_id or release.get("workshop_id") == workshop_id):
                return search(selected, rest, edges)
            return None
        if len(selected) >= 64:
            raise ManifestError("dependency closure exceeds 64 packages")
        for release in by_id.get(identifier, []):
            if not maps.version_matches(release["version"], constraint) or (mod_only and release["kind"] != "mod") or (workshop_id and release.get("workshop_id") != workshop_id):
                continue
            dependencies = [dep for dep in release["manifest"].get("dependencies", []) if not dep.get("optional", False)]
            next_edges = {**edges, identifier: [dep["id"] for dep in dependencies]}
            added = [(dep["id"], dep.get("version", "*"), (*ancestry, identifier), True, dep.get("workshop_id")) for dep in dependencies]
            solved = search({**selected, identifier: release}, added + rest, next_edges)
            if solved:
                return solved
        return None

    solution = search({}, [(root_id, version, (), False, None)], {})
    if not solution:
        raise ManifestError(f"missing, conflicting or cyclic dependencies for {root_id} {version}")
    selected, edges = solution
    ordered, visiting, visited = [], set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise ManifestError("cyclic dependency graph")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in edges.get(identifier, []):
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)
        ordered.append(selected[identifier])
    visit(root_id)
    return ordered
