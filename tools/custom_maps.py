#!/usr/bin/env python3
"""Validate and package versioned Ski-E-O! custom maps.

The runtime deliberately has a small JSON validator of its own.  This tool is
the stricter authoring-side implementation and is dependency-free so map
authors can run it with a stock Python installation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import struct
import stat
import functools
import zipfile


FORMAT_NAME = "skieo-map"
SUPPORTED_FORMAT_MAJOR = 1
MANIFEST_NAME = "custom-map.json"
ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
PACKAGE_RE = re.compile(r"^/Game/[A-Za-z0-9_./]+$")
MATERIAL_RE = re.compile(r"^/(?:Game|Engine)/[A-Za-z0-9_./]+$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?$")
ALLOWED_PERMISSIONS = {"gameplay", "skieo.unrestricted"}
COOKED_EXTENSIONS = {".pak", ".ucas", ".utoc"}
MAX_UNPACKED_BYTES = 1024 ** 3
MAX_ARCHIVE_FILES = 4096
MAX_MANIFEST_BYTES = 1024 ** 2


class ManifestError(ValueError):
    """A manifest is invalid or unsafe."""


def semver_compare(left: str, right: str) -> int:
    def parts(value):
        if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
            raise ManifestError(f"invalid semantic version: {value!r}")
        core, _, pre = value.split("+", 1)[0].partition("-")
        return tuple(map(int, core.split("."))), pre.split(".") if pre else []
    a, ap = parts(left)
    b, bp = parts(right)
    if a != b:
        return (a > b) - (a < b)
    if not ap or not bp:
        return (not ap) - (not bp)
    for av, bv in zip(ap, bp):
        if av == bv:
            continue
        if av.isdigit() and bv.isdigit():
            return (int(av) > int(bv)) - (int(av) < int(bv))
        if av.isdigit() != bv.isdigit():
            return -1 if av.isdigit() else 1
        return (av > bv) - (av < bv)
    return (len(ap) > len(bp)) - (len(ap) < len(bp))


def version_matches(version: str, requirement: str) -> bool:
    if not isinstance(requirement, str) or not requirement.strip() or len(requirement) > 120:
        raise ManifestError("dependency version must be a non-empty version range")
    semver_compare(version, version)
    if requirement == "*":
        return "-" not in version.split("+", 1)[0]
    result = True
    explicit_prerelease = False
    for clause in requirement.split():
        match = re.fullmatch(r"(>=|<=|>|<|=|\^|~)?(.+)", clause)
        operator, expected = match.groups()
        comparison = semver_compare(version, expected)
        explicit_prerelease |= "-" in expected.split("+", 1)[0]
        if operator in {"^", "~"}:
            major, minor, patch = map(int, expected.split("-", 1)[0].split("+", 1)[0].split("."))
            if operator == "~":
                upper = f"{major}.{minor + 1}.0"
            elif major:
                upper = f"{major + 1}.0.0"
            elif minor:
                upper = f"0.{minor + 1}.0"
            else:
                upper = f"0.0.{patch + 1}"
            result &= comparison >= 0 and semver_compare(version, upper) < 0
        else:
            result &= {None: comparison == 0, "=": comparison == 0,
                       ">=": comparison >= 0, "<=": comparison <= 0,
                       ">": comparison > 0, "<": comparison < 0}[operator]
    return result and ("-" not in version.split("+", 1)[0] or explicit_prerelease)


def validate_dependencies(manifest: dict) -> None:
    dependencies = _array(manifest.get("dependencies", []), "dependencies")
    if len(dependencies) > 32:
        raise ManifestError("at most 32 dependencies are allowed")
    seen = set()
    for dep in dependencies:
        dep = _object(dep, "dependency")
        identifier = dep.get("id")
        if not isinstance(identifier, str) or not ID_RE.fullmatch(identifier):
            raise ManifestError("dependency id must be namespaced")
        if identifier == manifest.get("id") or identifier in seen:
            raise ManifestError("duplicate or self dependency")
        seen.add(identifier)
        if "workshop_id" in dep:
            value = dep["workshop_id"]
            if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) >= 2**64 - 1:
                raise ManifestError("dependency.workshop_id must be a nonzero uint64 decimal string")
        version_matches("1.0.0", dep.get("version", "*"))
        if "optional" in dep and not isinstance(dep["optional"], bool):
            raise ManifestError("dependency.optional must be boolean")


def write_zip_member(archive, name, data, compression=zipfile.ZIP_DEFLATED):
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, data, compresslevel=6)


def validate_zip(archive, *, max_unpacked=MAX_UNPACKED_BYTES, allow_cooked=False) -> list[str]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_FILES:
        raise ManifestError("archive contains too many files")
    if sum(entry.file_size for entry in entries) > max_unpacked:
        raise ManifestError("archive exceeds the unpacked size limit")
    seen = set()
    files = []
    for entry in entries:
        name = entry.filename
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
            raise ManifestError("archive links and special files are forbidden")
        if entry.flag_bits & 1 or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ManifestError("only unencrypted ZIP Store/Deflate entries are supported")
        # Canonical paths must also be portable to the Windows game client.
        safe_relative_path(name.rstrip("/") if entry.is_dir() else name, "archive path", allow_cooked=allow_cooked)
        folded = name.rstrip("/").casefold()
        if folded in seen:
            raise ManifestError("archive contains duplicate paths")
        seen.add(folded)
        if not entry.is_dir():
            files.append(name)
    if archive.testzip() is not None:
        raise ManifestError("archive CRC check failed")
    return files


def read_zip_manifest(archive, name):
    if archive.getinfo(name).file_size > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest exceeds 1 MiB")
    return json.loads(archive.read(name).decode("utf-8"))


def validate_texture_images(manifest: dict, read) -> None:
    for channel, texture in manifest["terrain"].get("textures", {}).items():
        paths = [texture["file"], *texture["mips"]]
        side = 1 << (len(paths) - 1)
        for level, path in enumerate(paths):
            header = read(path)
            expected = side >> level
            if (len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n"
                    or header[12:16] != b"IHDR"
                    or struct.unpack(">II", header[16:24]) != (expected, expected)
                    or header[24] != 8 or header[25] not in {2, 6}):
                raise ManifestError(
                    f"terrain.textures.{channel}: {path} must be an 8-bit RGB/RGBA "
                    f"PNG of {expected}x{expected}; provide all mips down to 1x1"
                )


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be an array")
    return value


def _string(value: object, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ManifestError(f"{label} must be a non-empty string")
    return value


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ManifestError(f"{label} must be finite")
    return result


def safe_relative_path(value: object, label: str, *, allow_cooked=False) -> PurePosixPath:
    text = _string(value, label)
    if "\\" in text:
        raise ManifestError(f"{label} must use '/' separators")
    path = PurePosixPath(text)
    if (path.is_absolute() or not path.parts or len(text) > 240
            or any(part in {"", ".", ".."} for part in text.split("/"))
            or any(ord(char) < 32 for char in text)
            or re.search(r'[<>:"|?*]', text)
            or any(part.endswith((".", " ")) or re.fullmatch(
                r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                   for part in path.parts)):
        raise ManifestError(f"{label} must stay inside the map directory")
    if ":" in path.parts[0]:
        raise ManifestError(f"{label} must not contain a drive name")
    if not allow_cooked and path.suffix.lower() in COOKED_EXTENSIONS:
        raise ManifestError(f"{label} contains cooked Unreal data; .skieomap is source-only")
    return path


def _validate_metadata(manifest: dict) -> None:
    metadata = _object(manifest.get("metadata"), "metadata")
    _string(metadata.get("name"), "metadata.name")
    _string(metadata.get("version"), "metadata.version")
    _string(metadata.get("description"), "metadata.description")
    language = _string(metadata.get("language", "en"), "metadata.language")
    if not LANGUAGE_RE.fullmatch(language):
        raise ManifestError("metadata.language must be a BCP 47 language tag")
    localizations = _object(metadata.get("localizations", {}), "metadata.localizations")
    for tag, localized in localizations.items():
        if not LANGUAGE_RE.fullmatch(tag):
            raise ManifestError(
                f"metadata.localizations key {tag!r} must be a BCP 47 language tag"
            )
        localized = _object(localized, f"metadata.localizations.{tag}")
        for field in ("name", "description", "license"):
            if field in localized:
                _string(localized[field], f"metadata.localizations.{tag}.{field}")
    authors = _array(metadata.get("authors"), "metadata.authors")
    if not authors or len(authors) > 32:
        raise ManifestError("metadata.authors must not be empty")
    for index, author in enumerate(authors):
        _string(author, f"metadata.authors[{index}]")
    tags = metadata.get("tags", [])
    _array(tags, "metadata.tags")
    for tag in tags:
        _string(tag, "metadata.tags[]")
    if len(tags) > 32:
        raise ManifestError("metadata.tags supports at most 32 tags")
    if len(tags) != len(set(tags)):
        raise ManifestError("metadata.tags must be unique")
    players = metadata.get("players")
    if players is not None:
        players = _object(players, "metadata.players")
        minimum = players.get("min")
        maximum = players.get("max")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ManifestError("metadata.players.min must be a positive integer")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < minimum:
            raise ManifestError("metadata.players.max must be >= min")


def _validate_terrain(manifest: dict) -> None:
    terrain = _object(manifest.get("terrain"), "terrain")
    size = _array(terrain.get("size_meters"), "terrain.size_meters")
    if len(size) != 2 or any(_number(value, "terrain.size_meters[]") <= 0 for value in size):
        raise ManifestError("terrain.size_meters must contain two positive numbers")
    elevation = _array(terrain.get("elevation_meters"), "terrain.elevation_meters")
    if len(elevation) != 2:
        raise ManifestError("terrain.elevation_meters must contain min and max")
    low, high = (_number(value, "terrain.elevation_meters[]") for value in elevation)
    if low >= high:
        raise ManifestError("terrain.elevation_meters min must be lower than max")

    origin = _array(terrain.get("origin_centimeters"), "terrain.origin_centimeters")
    if len(origin) != 3:
        raise ManifestError("terrain.origin_centimeters must contain X, Y and Z")
    for value in origin:
        _number(value, "terrain.origin_centimeters[]")

    source = _object(terrain.get("source"), "terrain.source")
    safe_relative_path(source.get("file"), "terrain.source.file")
    if source.get("format") not in {"r16le", "r16be"}:
        raise ManifestError("terrain.source.format must be r16le or r16be")
    vertices = _array(source.get("vertices"), "terrain.source.vertices")
    if len(vertices) != 2 or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 2
        for value in vertices
    ):
        raise ManifestError("terrain.source.vertices must contain two integers >= 2")
    spacing = _number(source.get("spacing_meters"), "terrain.source.spacing_meters")
    if spacing <= 0:
        raise ManifestError("terrain.source.spacing_meters must be positive")
    expected_size = [(vertices[index] - 1) * spacing for index in range(2)]
    if any(not math.isclose(size[index], expected_size[index], abs_tol=1e-6)
           for index in range(2)):
        raise ManifestError(
            "terrain.size_meters must equal (vertices - 1) * spacing_meters"
        )
    if _number(source.get("height_scale_meters"), "terrain.source.height_scale_meters") <= 0:
        raise ManifestError("terrain.source.height_scale_meters must be positive")
    _number(source.get("height_offset_meters"), "terrain.source.height_offset_meters")
    if source.get("row_order", "north_to_south") not in {
        "north_to_south", "south_to_north"
    }:
        raise ManifestError("terrain.source.row_order is invalid")

    runtime = _object(terrain.get("runtime", {}), "terrain.runtime")
    textures = _object(terrain.get("textures", {}), "terrain.textures")
    for channel, texture in textures.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", channel):
            raise ManifestError("terrain texture channel must use a lowercase identifier")
        label = f"terrain.textures.{channel}"
        texture = _object(texture, label)
        paths = [texture.get("file"), *_array(texture.get("mips"), f"{label}.mips")]
        if len(paths) > 10:
            raise ManifestError("terrain textures support at most nine additional mips")
        for path in paths:
            if safe_relative_path(path, label).suffix.lower() != ".png":
                raise ManifestError("terrain textures must reference PNG images")
        if texture.get("color_space", "srgb") not in {"srgb", "linear"}:
            raise ManifestError("terrain texture color_space must be srgb or linear")
    parameters = _object(runtime.get("texture_parameters", {}), "terrain.runtime.texture_parameters")
    for channel, parameter in parameters.items():
        if channel not in textures or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", _string(parameter, "texture parameter")):
            raise ManifestError("texture_parameters must map declared channels to material parameter names")
    if any(channel != "albedo" and channel not in parameters for channel in textures):
        raise ManifestError("non-albedo texture channels need a runtime texture_parameters mapping")
    for name, minimum, maximum in (
        ("sample_step", 1, 64), ("tile_quads", 8, 127)
    ):
        value = runtime.get(name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise ManifestError(
                f"terrain.runtime.{name} must be an integer within {minimum}..{maximum}"
            )
    for name in ("material", "snow_material", "skirt_material"):
        material = runtime.get(name)
        if material is not None and not MATERIAL_RE.fullmatch(
            _string(material, f"terrain.runtime.{name}")
        ):
            raise ManifestError(
                f"terrain.runtime.{name} must be a /Game/... or /Engine/... asset path"
            )
    for name in ("material_color", "snow_color", "skirt_color"):
        color = runtime.get(name)
        if color is not None:
            color = _array(color, f"terrain.runtime.{name}")
            if len(color) not in {3, 4} or any(
                not 0 <= _number(value, f"terrain.runtime.{name}[]") <= 1
                for value in color
            ):
                raise ManifestError(
                    f"terrain.runtime.{name} must contain 3 or 4 values within 0..1"
                )
    uv_tile_meters = runtime.get("uv_tile_meters")
    if uv_tile_meters is not None and _number(
        uv_tile_meters, "terrain.runtime.uv_tile_meters"
    ) <= 0:
        raise ManifestError("terrain.runtime.uv_tile_meters must be positive")
    snow_offset = runtime.get("snow_offset_centimeters")
    if snow_offset is not None and _number(
        snow_offset, "terrain.runtime.snow_offset_centimeters"
    ) < 0:
        raise ManifestError(
            "terrain.runtime.snow_offset_centimeters must not be negative"
        )
    skirt_depth = runtime.get("skirt_depth_meters")
    if skirt_depth is not None and _number(
        skirt_depth, "terrain.runtime.skirt_depth_meters"
    ) <= 0:
        raise ManifestError("terrain.runtime.skirt_depth_meters must be positive")
    skirt_enabled = runtime.get("skirt_enabled")
    if skirt_enabled is not None and not isinstance(skirt_enabled, bool):
        raise ManifestError("terrain.runtime.skirt_enabled must be a boolean")
    below_tolerance = runtime.get(
        "placeable_below_ground_tolerance_centimeters"
    )
    if below_tolerance is not None and _number(
        below_tolerance,
        "terrain.runtime.placeable_below_ground_tolerance_centimeters",
    ) < 0:
        raise ManifestError(
            "terrain.runtime.placeable_below_ground_tolerance_centimeters "
            "must not be negative"
        )
    snow_bias = runtime.get("snow_surface_bias_centimeters")
    if snow_bias is not None and abs(_number(snow_bias, "terrain.runtime.snow_surface_bias_centimeters")) > 100:
        raise ManifestError("terrain.runtime.snow_surface_bias_centimeters must be -100..100")
    clearance = runtime.get("placeable_clearance_centimeters")
    if clearance is not None:
        _number(clearance, "terrain.runtime.placeable_clearance_centimeters")

    preview = _object(terrain.get("preview"), "terrain.preview")
    samples = _array(preview.get("samples"), "terrain.preview.samples")
    if not 3 <= len(samples) <= 33:
        raise ManifestError("terrain preview must contain 3 to 33 rows")
    width = None
    for row_index, row_value in enumerate(samples):
        row = _array(row_value, f"terrain.preview.samples[{row_index}]")
        width = len(row) if width is None else width
        if len(row) != width or not 3 <= len(row) <= 33:
            raise ManifestError("terrain preview must be a rectangular 3..33 grid")
        for column_index, sample in enumerate(row):
            height = _number(sample, f"terrain.preview.samples[{row_index}][{column_index}]")
            if not 0.0 <= height <= 1.0:
                raise ManifestError("terrain preview samples must be normalized to 0..1")


def referenced_paths(manifest: dict) -> list[PurePosixPath]:
    result: list[PurePosixPath] = []
    terrain = _object(manifest.get("terrain"), "terrain")
    source = _object(terrain.get("source"), "terrain.source")
    result.append(safe_relative_path(source.get("file"), "terrain.source.file"))
    for channel, texture in terrain.get("textures", {}).items():
        for path in [texture["file"], *texture["mips"]]:
            result.append(safe_relative_path(path, f"terrain.textures.{channel}"))

    content = _object(manifest.get("content"), "content")
    if "containers" in content:
        raise ManifestError(
            "content.containers is obsolete; custom maps may not embed cooked data"
        )

    packaged_assets: set[PurePosixPath] = set()
    for asset_index, path in enumerate(_array(content.get("assets", []), "content.assets")):
        safe_path = safe_relative_path(path, f"content.assets[{asset_index}]")
        packaged_assets.add(safe_path)
        result.append(safe_path)

    editor = _object(manifest.get("editor", {}), "editor")
    editor_files: list[tuple[object, str]] = []
    for section_name in ("layers", "asset_catalog"):
        for index, value in enumerate(_array(editor.get(section_name, []), f"editor.{section_name}")):
            value = _object(value, f"editor.{section_name}[{index}]")
            if "file" in value:
                editor_files.append((value["file"], f"editor.{section_name}[{index}].file"))
    for value, label in editor_files:
        editor_path = safe_relative_path(value, label)
        if editor_path not in packaged_assets:
            raise ManifestError(f"{label} must also be listed in content.assets")

    script = manifest.get("script")
    if script is not None:
        script = _object(script, "script")
        if script.get("language") != "lua":
            raise ManifestError("script.language must be 'lua'")
        api_version = _string(script.get("api"), "script.api")
        if not re.fullmatch(r"1\.[0-9]+", api_version):
            raise ManifestError("only script API 1.x is supported")
        result.append(safe_relative_path(script.get("entry"), "script.entry"))
        permissions = _array(script.get("permissions", []), "script.permissions")
        for permission in permissions:
            _string(permission, "script.permissions[]")
        unknown = set(permissions) - ALLOWED_PERMISSIONS
        if unknown:
            raise ManifestError(f"unknown script permissions: {', '.join(sorted(unknown))}")
        if len(permissions) != len(set(permissions)):
            raise ManifestError("script.permissions must be unique")

    duplicates = sorted(str(path) for path in result if result.count(path) > 1)
    if duplicates:
        raise ManifestError(f"files are referenced more than once: {', '.join(sorted(set(duplicates)))}")
    return result


def validate_manifest(manifest: object) -> dict:
    manifest = _object(manifest, "manifest")
    format_info = _object(manifest.get("format"), "format")
    if format_info.get("name") != FORMAT_NAME:
        raise ManifestError(f"format.name must be {FORMAT_NAME!r}")
    match = SEMVER_RE.fullmatch(_string(format_info.get("version"), "format.version"))
    if not match or int(match.group("major")) != SUPPORTED_FORMAT_MAJOR:
        raise ManifestError("the loader supports skieo-map format 1.x")

    map_id = _string(manifest.get("id"), "id")
    if not ID_RE.fullmatch(map_id):
        raise ManifestError("id must be a lowercase, namespaced identifier")
    _validate_metadata(manifest)
    if not SEMVER_RE.fullmatch(manifest["metadata"]["version"]):
        raise ManifestError("metadata.version must be a semantic version")
    validate_dependencies(manifest)

    game = _object(manifest.get("game", {}), "game")
    if "level" in game or "initial_save" in game:
        raise ManifestError(
            "game.level/initial_save are obsolete; maps initialize their own world"
        )
    # Legacy 1.x metadata is accepted but no longer selects an Unreal level.
    if "template_level" in game:
        level = _string(game["template_level"], "game.template_level")
        if not PACKAGE_RE.fullmatch(level):
            raise ManifestError("legacy game.template_level must be a /Game/... package path")

    location = manifest.get("location")
    if location is not None:
        location = _object(location, "location")
        latitude = _number(location.get("latitude"), "location.latitude")
        longitude = _number(location.get("longitude"), "location.longitude")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ManifestError("location coordinates are outside WGS84 bounds")
        world_map_uv = location.get("world_map_uv")
        if world_map_uv is not None:
            world_map_uv = _array(world_map_uv, "location.world_map_uv")
            if len(world_map_uv) != 2 or any(
                not 0.0 <= _number(value, "location.world_map_uv[]") <= 1.0
                for value in world_map_uv
            ):
                raise ManifestError(
                    "location.world_map_uv must contain two values within 0..1"
                )

    _validate_terrain(manifest)
    referenced_paths(manifest)
    extensions = _object(manifest.get("extensions", {}), "extensions")
    for key in extensions:
        if not ID_RE.fullmatch(key):
            raise ManifestError(f"extension key is not namespaced: {key}")
    return manifest


def load_manifest(path: Path, *, check_files: bool) -> tuple[dict, list[PurePosixPath]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(str(error)) from error
    validate_manifest(manifest)
    files = referenced_paths(manifest)
    if check_files:
        root = path.parent.resolve()
        missing = []
        for item in files:
            target = (root / item).resolve()
            try:
                target.relative_to(root)
            except ValueError as error:
                raise ManifestError(f"referenced path escapes through a symlink: {item}") from error
            if not target.is_file():
                missing.append(str(item))
        if missing:
            raise ManifestError(f"referenced files do not exist: {', '.join(missing)}")
        terrain_source = manifest["terrain"]["source"]
        terrain_path = root / terrain_source["file"]
        expected_size = math.prod(terrain_source["vertices"]) * 2
        if terrain_path.stat().st_size != expected_size:
            raise ManifestError(
                f"terrain source has {terrain_path.stat().st_size} bytes; "
                f"expected {expected_size}"
            )
        def read_header(relative):
            with (root / relative).open("rb") as image:
                return image.read(33)
        validate_texture_images(manifest, read_header)
    return manifest, files


def pack(manifest_path: Path, output_path: Path, *, compression=zipfile.ZIP_DEFLATED) -> None:
    manifest, files = load_manifest(manifest_path, check_files=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=compression, compresslevel=6) as archive:
        canonical = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        write_zip_member(archive, MANIFEST_NAME, canonical.encode("utf-8"), compression)
        for relative in sorted(files):
            write_zip_member(archive, str(relative), (manifest_path.parent / relative).read_bytes(), compression)


def inspect_archive(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            names = validate_zip(archive)
            if MANIFEST_NAME not in names:
                raise ManifestError(f"archive has no root {MANIFEST_NAME}")
            manifest = read_zip_manifest(archive, MANIFEST_NAME)
            validate_manifest(manifest)
            missing = [str(item) for item in referenced_paths(manifest) if str(item) not in names]
            if missing:
                raise ManifestError(f"archive is missing: {', '.join(missing)}")
            def read_header(relative):
                with archive.open(relative) as image:
                    return image.read(33)
            validate_texture_images(manifest, read_header)
            terrain_source = manifest["terrain"]["source"]
            expected_size = math.prod(terrain_source["vertices"]) * 2
            actual_size = archive.getinfo(terrain_source["file"]).file_size
            if actual_size != expected_size:
                raise ManifestError(
                    f"terrain source has {actual_size} bytes; expected {expected_size}"
                )
            return manifest
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, EOFError) as error:
        raise ManifestError(str(error)) from error


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate an installed map directory")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--no-files", action="store_true", help="only validate JSON references")
    package = commands.add_parser("pack", help="build a .skieomap ZIP")
    package.add_argument("manifest", type=Path)
    package.add_argument("output", type=Path)
    inspect = commands.add_parser("inspect", help="validate and summarize a .skieomap ZIP")
    inspect.add_argument("archive", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        if args.command == "validate":
            manifest, files = load_manifest(args.manifest, check_files=not args.no_files)
            print(f"Valid {manifest['format']['name']} {manifest['format']['version']}: "
                  f"{manifest['id']} ({len(files)} referenced files)")
        elif args.command == "pack":
            pack(args.manifest, args.output)
            print(f"Packed {args.output}")
        else:
            manifest = inspect_archive(args.archive)
            print(json.dumps({
                "id": manifest["id"],
                "name": manifest["metadata"]["name"],
                "version": manifest["metadata"]["version"],
                "format": manifest["format"]["version"],
            }, ensure_ascii=False, indent=2))
    except ManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
