from __future__ import annotations

import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import struct
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("custom_maps", ROOT / "tools/custom_maps.py")
custom_maps = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(custom_maps)


class CustomMapFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest_path = ROOT / "mod/SkiEO-Veymont/custom-map.json"
        cls.manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    def test_veymont_is_valid_and_complete(self) -> None:
        manifest, paths = custom_maps.load_manifest(self.manifest_path, check_files=True)
        self.assertEqual(manifest["id"], "community.veymont")
        self.assertEqual(len(paths), 18)
        self.assertIn(Path('Scripts/furnishings.lua'), paths)
        self.assertIn(Path("Preview/veymont.png"), paths)
        self.assertIn(Path("Preview/veymont-loading.png"), paths)
        self.assertEqual(manifest["format"]["version"], "1.4.0")
        self.assertEqual(manifest["metadata"]["language"], "en")
        self.assertIn("fr", manifest["metadata"]["localizations"])
        self.assertNotIn("game", manifest)
        self.assertNotIn("containers", manifest["content"])
        terrain = manifest["terrain"]["source"]
        self.assertEqual(terrain["file"], "Terrain/heightmap.r16")
        self.assertEqual(terrain['vertices'], [2017, 3025])
        self.assertEqual((self.manifest_path.parent / terrain["file"]).stat().st_size, 2017 * 3025 * 2)
        forest = self.manifest_path.parent / "Vegetation/forest.skxy"
        self.assertEqual(forest.stat().st_size, 12 + 383500 * 8)
        self.assertFalse(any(
            path.suffix.lower() in {".pak", ".ucas", ".utoc"}
            for path in self.manifest_path.parent.iterdir()
        ))
        self.assertFalse((self.manifest_path.parent / "enabled.txt").exists())
        script = (self.manifest_path.parent / manifest["script"]["entry"]).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("RegisterKeyBind", script)
        self.assertNotIn("RegisterConsoleCommandHandler", script)

    def test_expanded_veymont_preserves_original_terrain_and_forest(self):
        # Geographic compatibility with 0.5.1: the old square is the middle
        # 2017 rows. Stored reference hashes cover every old height and tree XY.
        root = self.manifest_path.parent
        source = (root / 'Terrain/heightmap.r16').read_bytes()
        old_square = source[504 * 2017 * 2:2521 * 2017 * 2]
        self.assertEqual(hashlib.sha256(old_square).hexdigest(),
                         '9a2cf903e6b201aac9304c9c75a4726927c6a3c6a580fba5456c940318618ca5')
        forest = (root / 'Vegetation/forest.skxy').read_bytes()
        self.assertEqual(struct.unpack('<4sII', forest[:12]), (b'SKXY', 1, 383500))
        boundary = 12 + 255667 * 8
        self.assertEqual(hashlib.sha256(forest[12:boundary]).hexdigest(),
                         '28b91610c8b3655b4ce140bfc3b74af1bb541c654907133cf9263dcf538aabd5')
        for x, y in struct.iter_unpack('<ff', forest[boundary:]):
            self.assertLessEqual(abs(x), 403200)
            self.assertGreater(abs(y), 403200)
            self.assertLessEqual(abs(y), 604800)
        config = json.loads((ROOT / 'maps/veymont/map.json').read_text())
        landmark = config['points_of_interest']['mont_aiguille']
        self.assertEqual(landmark['osm_node'], '410304217')
        # Projected summit (Lambert-93), in the newly added southern band.
        easting, northing = 901646.3774, 6419106.2880
        west, south, east, north = config['terrain']['bounds_east_north']
        self.assertTrue(west < easting < east and south < northing < north)
        row, column = round((north - northing) / 4), round((easting - west) / 4)
        altitude = struct.unpack_from('<H', source, (row * 2017 + column) * 2)[0] * .025 + 723.9875
        self.assertGreater(altitude, 1950)

    def test_legacy_template_metadata_is_optional(self) -> None:
        legacy = copy.deepcopy(self.manifest)
        legacy["format"]["version"] = "1.2.0"
        legacy["game"] = {"template_level": "/Game/Maps/Generated/Map_sugar_bowl_real"}
        custom_maps.validate_manifest(legacy)
        legacy["game"]["template_level"] = "../unsafe"
        with self.assertRaisesRegex(custom_maps.ManifestError, "legacy game.template_level"):
            custom_maps.validate_manifest(legacy)

    def test_rejects_path_traversal(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["script"]["entry"] = "../escape.lua"
        with self.assertRaisesRegex(custom_maps.ManifestError, "inside the map directory"):
            custom_maps.validate_manifest(manifest)

    def test_rejects_ragged_preview(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["terrain"]["preview"]["samples"][1].pop()
        with self.assertRaisesRegex(custom_maps.ManifestError, "rectangular"):
            custom_maps.validate_manifest(manifest)

    def test_rejects_invalid_world_map_position(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["location"]["world_map_uv"] = [1.2, 0.5]
        with self.assertRaisesRegex(custom_maps.ManifestError, "within 0..1"):
            custom_maps.validate_manifest(manifest)

    def test_rejects_invalid_localization_language(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["metadata"]["localizations"]["french"] = {
            "description": "Description"
        }
        with self.assertRaisesRegex(custom_maps.ManifestError, "BCP 47"):
            custom_maps.validate_manifest(manifest)

    def test_rejects_cooked_content(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["content"]["assets"].append("Content/map.pak")
        with self.assertRaisesRegex(custom_maps.ManifestError, "source-only"):
            custom_maps.validate_manifest(manifest)

    def test_rejects_inconsistent_terrain_size(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["terrain"]["size_meters"][0] *= 2
        with self.assertRaisesRegex(custom_maps.ManifestError, "vertices - 1"):
            custom_maps.validate_manifest(manifest)

    def test_rejects_invalid_runtime_grounding_options(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        runtime = manifest["terrain"]["runtime"]
        runtime["skirt_enabled"] = "yes"
        with self.assertRaisesRegex(custom_maps.ManifestError, "must be a boolean"):
            custom_maps.validate_manifest(manifest)
        runtime["skirt_enabled"] = True
        runtime["placeable_below_ground_tolerance_centimeters"] = -1
        with self.assertRaisesRegex(custom_maps.ManifestError, "must not be negative"):
            custom_maps.validate_manifest(manifest)

    def test_archive_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "Veymont.skieomap"
            custom_maps.pack(self.manifest_path, archive)
            result = custom_maps.inspect_archive(archive)
            self.assertEqual(result["id"], "community.veymont")
            with zipfile.ZipFile(archive) as package:
                self.assertTrue(all(
                    item.compress_type == zipfile.ZIP_DEFLATED
                    for item in package.infolist()
                ))
                self.assertIn("Terrain/heightmap.r16", package.namelist())
                self.assertIn("Vegetation/forest.skxy", package.namelist())
                self.assertIn("Terrain/limestone-albedo.png", package.namelist())
                self.assertIn("Terrain/limestone-albedo-mip09.png", package.namelist())

    def test_texture_channels_and_material_parameters(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        texture = manifest["terrain"]["textures"]["albedo"]
        self.assertEqual(len(texture["mips"]), 9)
        manifest["terrain"]["textures"]["reflection"] = {
            "file": "Terrain/reflection.png", "mips": [], "color_space": "linear"
        }
        with self.assertRaisesRegex(custom_maps.ManifestError, "texture_parameters"):
            custom_maps.validate_manifest(manifest)
        manifest["terrain"]["runtime"]["texture_parameters"] = {"reflection": "Reflection"}
        custom_maps.validate_manifest(manifest)
        manifest["terrain"]["runtime"]["texture_parameters"]["reflection"] = "../invalid"
        with self.assertRaisesRegex(custom_maps.ManifestError, "parameter names"):
            custom_maps.validate_manifest(manifest)

    def test_texture_mip_paths_and_dimensions(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        texture = manifest["terrain"]["textures"]["albedo"]
        texture["mips"][0] = "../outside.png"
        with self.assertRaisesRegex(custom_maps.ManifestError, "inside the map directory"):
            custom_maps.validate_manifest(manifest)
        texture["mips"][0] = texture["file"]
        with self.assertRaisesRegex(custom_maps.ManifestError, "more than once"):
            custom_maps.validate_manifest(manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest["terrain"]["textures"]["albedo"]["mips"].pop()
        with self.assertRaisesRegex(custom_maps.ManifestError, "all mips down to 1x1"):
            custom_maps.validate_texture_images(
                manifest, lambda path: (self.manifest_path.parent / path).read_bytes()[:33]
            )


if __name__ == "__main__":
    unittest.main()
