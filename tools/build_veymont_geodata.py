#!/usr/bin/env python3
"""Build the real-world Veymont resort layout and forest distribution.

The input is an OpenStreetMap XML extract plus the source terrain R16. Output is
a compact Lua module and an SKXY forest stream consumed by the custom-map
loader. Keeping both outputs on the same projection is important: the
lift/trail clearings then match the actors created in game exactly.
"""

from __future__ import annotations

import argparse
from array import array
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SNOWCAT_SHED_WAY = "662311859"
TICKET_OFFICE_BUILDING_WAY = "131619525"
PANINI_TRAILER_WAY = "131619246"
FRONT_RETAIL_BUILDING_WAY = "131619464"
SUN_VALLEY_NODE = "6658126749"
GRILLET_SPORTS_NODE = "5756060569"


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    spacing_cm: float
    west: float
    north: float
    origin_x: float
    origin_y: float
    height_offset_cm: float
    height_scale_cm: float

    @classmethod
    def read(cls, config, manifest):
        terrain = manifest['terrain']
        source = terrain['source']
        width, height = source['vertices']
        if [width, height] != [config['terrain']['vertices_x'], config['terrain']['vertices_y']]:
            raise ValueError('Geographic crop dimensions differ from the map manifest')
        if source['format'] != 'r16le' or source.get('row_order', 'north_to_south') != 'north_to_south':
            raise ValueError('Geodata generation requires a north-to-south R16LE grid')
        spacing = source['spacing_meters']
        west, south, east, north = config['terrain']['bounds_east_north']
        if abs(east - west - (width - 1) * spacing) > 1e-6 or abs(north - south - (height - 1) * spacing) > 1e-6:
            raise ValueError('Geographic crop bounds differ from the map manifest')
        origin = terrain['origin_centimeters']
        return cls(width, height, spacing * 100, west, north, origin[0], origin[1],
                   origin[2] + source['height_offset_meters'] * 100,
                   source['height_scale_meters'] * 100)


def parse_osm(paths: list[Path]):
    nodes: dict[str, tuple[float, float, dict[str, str]]] = {}
    ways: dict[str, tuple[list[str], dict[str, str]]] = {}
    relations: dict[str, tuple[list[tuple[str, str, str]], dict[str, str]]] = {}
    for path in paths:
        root = ET.parse(path).getroot()
        for node in root.findall("node"):
            tags = {t.attrib["k"]: t.attrib["v"] for t in node.findall("tag")}
            nodes[node.attrib["id"]] = (
                float(node.attrib["lon"]), float(node.attrib["lat"]), tags)
        for way in root.findall("way"):
            refs = [n.attrib["ref"] for n in way.findall("nd")]
            tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
            ways[way.attrib["id"]] = (refs, tags)
        for relation in root.findall("relation"):
            members = [
                (m.attrib["type"], m.attrib["ref"], m.attrib.get("role", ""))
                for m in relation.findall("member")
            ]
            tags = {t.attrib["k"]: t.attrib["v"] for t in relation.findall("tag")}
            relations[relation.attrib["id"]] = (members, tags)
    return nodes, ways, relations


def project_nodes(nodes, wanted_refs: set[str]):
    refs = sorted(ref for ref in wanted_refs if ref in nodes)
    source = "".join(f"{nodes[ref][1]:.9f} {nodes[ref][0]:.9f}\n" for ref in refs)
    result = subprocess.run(
        ["cs2cs", "EPSG:4326", "EPSG:2154", "-f", "%.4f"],
        input=source, text=True, capture_output=True, check=True)
    projected = {}
    for ref, line in zip(refs, result.stdout.splitlines(), strict=True):
        east, north, *_ = line.split()
        projected[ref] = (float(east), float(north))
    return projected


def world_xy(projected_point: tuple[float, float], grid):
    east, north = projected_point
    return grid.origin_x + (east - grid.west) * 100, grid.origin_y + (grid.north - north) * 100


def load_r16(path: Path, grid):
    data = path.read_bytes()
    expected = grid.width * grid.height * 2
    if len(data) != expected:
        raise ValueError(f"{path}: {len(data)} bytes instead of {expected}")
    heights = array("H")
    heights.frombytes(data)
    if struct.pack("=H", 1) != struct.pack("<H", 1):
        heights.byteswap()
    return heights


def sample_height(heights, x_cm: float, y_cm: float, grid):
    px = min(grid.width - 1.0, max(0.0, (x_cm - grid.origin_x) / grid.spacing_cm))
    py = min(grid.height - 1.0, max(0.0, (y_cm - grid.origin_y) / grid.spacing_cm))
    x0 = min(grid.width - 2, int(px))
    y0 = min(grid.height - 2, int(py))
    fx, fy = px - x0, py - y0
    h00 = heights[y0 * grid.width + x0]
    h10 = heights[y0 * grid.width + x0 + 1]
    h01 = heights[(y0 + 1) * grid.width + x0]
    h11 = heights[(y0 + 1) * grid.width + x0 + 1]
    encoded = (
        h00 * (1.0 - fx) * (1.0 - fy)
        + h10 * fx * (1.0 - fy)
        + h01 * (1.0 - fx) * fy
        + h11 * fx * fy
    )
    return grid.height_offset_cm + encoded * grid.height_scale_cm


def pixels_for_way(refs, projected, grid):
    result = []
    for ref in refs:
        if ref not in projected:
            continue
        x, y = world_xy(projected[ref], grid)
        result.append(((x - grid.origin_x) / grid.spacing_cm,
                       (y - grid.origin_y) / grid.spacing_cm))
    return result


def fill_polygon(mask: bytearray, points, value: int, grid):
    if len(points) < 3:
        return
    min_y = max(0, int(math.floor(min(p[1] for p in points))))
    max_y = min(grid.height - 1, int(math.ceil(max(p[1] for p in points))))
    edges = list(zip(points, points[1:] + points[:1]))
    for row in range(min_y, max_y + 1):
        scan_y = row + 0.5
        intersections = []
        for (x1, y1), (x2, y2) in edges:
            if (y1 <= scan_y < y2) or (y2 <= scan_y < y1):
                intersections.append(x1 + (scan_y - y1) * (x2 - x1) / (y2 - y1))
        intersections.sort()
        for first, last in zip(intersections[0::2], intersections[1::2]):
            x0 = max(0, int(math.ceil(first - 0.5)))
            x1 = min(grid.width - 1, int(math.floor(last - 0.5)))
            if x1 >= x0:
                start = row * grid.width + x0
                mask[start:start + x1 - x0 + 1] = bytes([value]) * (x1 - x0 + 1)


def clear_disc(mask: bytearray, x: float, y: float, radius: int, grid):
    x0, x1 = max(0, int(x) - radius), min(grid.width - 1, int(x) + radius)
    y0, y1 = max(0, int(y) - radius), min(grid.height - 1, int(y) + radius)
    radius2 = radius * radius
    for py in range(y0, y1 + 1):
        dy2 = (py - y) ** 2
        for px in range(x0, x1 + 1):
            if (px - x) ** 2 + dy2 <= radius2:
                mask[py * grid.width + px] = 0


def clear_polyline(mask: bytearray, points, radius: int, grid):
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(math.ceil(length / max(1.0, radius * 0.45))))
        for step in range(steps + 1):
            t = step / steps
            clear_disc(mask, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, radius, grid)


def write_forest(path, eligible, grid, count, preserve=None, previous=None):
    """Keep existing trees at the same coordinates and populate only new land."""
    preserved_count, preserved = 0, b''
    maximum_x = grid.origin_x + (grid.width - 1) * grid.spacing_cm
    maximum_y = grid.origin_y + (grid.height - 1) * grid.spacing_cm
    if preserve:
        data = Path(preserve).read_bytes()
        if len(data) < 12:
            raise ValueError('Invalid existing SKXY header')
        magic, version, preserved_count = struct.unpack('<4sII', data[:12])
        if magic != b'SKXY' or version != 1 or len(data) != 12 + preserved_count * 8 or count < preserved_count:
            raise ValueError('Invalid existing SKXY stream or target count smaller than the existing forest')
        preserved = data[12:]
        for x, y in struct.iter_unpack('<ff', preserved):
            if not math.isfinite(x) or not math.isfinite(y) or not grid.origin_x <= x <= maximum_x or not grid.origin_y <= y <= maximum_y:
                raise ValueError('An existing tree falls outside the expanded map')
        terrain = json.loads(Path(previous).read_text())['terrain']
        old_x, old_y = terrain['origin_centimeters'][:2]
        old_max_x = old_x + terrain['size_meters'][0] * 100
        old_max_y = old_y + terrain['size_meters'][1] * 100
        if old_x < grid.origin_x or old_y < grid.origin_y or old_max_x > maximum_x or old_max_y > maximum_y:
            raise ValueError('Expanded map must contain the whole previous extent')
        eligible = array('I', (index for index in eligible
            if not (old_x <= grid.origin_x + (index % grid.width) * grid.spacing_cm <= old_max_x
                and old_y <= grid.origin_y + (index // grid.width) * grid.spacing_cm <= old_max_y)))
    if count > preserved_count and not eligible:
        raise ValueError('No forest cells are available in the added area')
    randomizer = random.Random(0x5645594D4F4E54)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as output:
        output.write(struct.pack('<4sII', b'SKXY', 1, count))
        output.write(preserved)
        for _ in range(count - preserved_count):
            index = eligible[randomizer.randrange(len(eligible))]
            row, column = divmod(index, grid.width)
            jitter = grid.spacing_cm * .475
            x = grid.origin_x + column * grid.spacing_cm + randomizer.uniform(-jitter, jitter)
            y = grid.origin_y + row * grid.spacing_cm + randomizer.uniform(-jitter, jitter)
            x = min(maximum_x, max(grid.origin_x, x))
            y = min(maximum_y, max(grid.origin_y, y))
            output.write(struct.pack('<ff', x, y))
    return preserved_count


def point_record(projected, heights, ref, grid):
    x, y = world_xy(projected[ref], grid)
    return {"x": round(x, 3), "y": round(y, 3),
            "z": round(sample_height(heights, x, y, grid), 3)}


def polygon_placement(projected, heights, refs, grid):
    """Return the terrain position and long-axis yaw of an OSM footprint."""
    points = [world_xy(projected[ref], grid) for ref in refs if ref in projected]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        raise ValueError("building footprint needs at least three projected nodes")

    twice_area = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    longest_edge = (-1.0, 0.0)
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        cross = first[0] * second[1] - second[0] * first[1]
        twice_area += cross
        centroid_x += (first[0] + second[0]) * cross
        centroid_y += (first[1] + second[1]) * cross
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length > longest_edge[0]:
            longest_edge = (length, math.degrees(math.atan2(dy, dx)))
    if abs(twice_area) < 1e-6:
        raise ValueError("building footprint has no area")
    centroid_x /= 3.0 * twice_area
    centroid_y /= 3.0 * twice_area
    return {
        "position": {
            "x": round(centroid_x, 3),
            "y": round(centroid_y, 3),
            "z": round(sample_height(heights, centroid_x, centroid_y, grid) + 20.0, 3),
        },
        "yaw": round(longest_edge[1], 3),
    }


def lua_string(value: str):
    return json.dumps(value, ensure_ascii=False)


def lua_point(point):
    return "{ X = %.3f, Y = %.3f, Z = %.3f }" % (
        point["x"], point["y"], point["z"])


def write_lua(path: Path, lifts, trails, ticket, ticket_yaw, snowcat_shed,
              amenities):
    lines = ["-- Generated by tools/build_veymont_geodata.py; do not edit by hand.",
             "local data = {}", "", "data.lifts = {"]
    for lift in lifts:
        lines += ["    {", f"        name = {lua_string(lift['name'])},",
                  f"        real_type = {lua_string(lift['real_type'])},",
                  f"        bottom = {lua_point(lift['bottom'])},",
                  f"        top = {lua_point(lift['top'])},", "    },"]
    lines += ["}", "", "data.trails = {"]
    for trail in trails:
        lines += ["    {", f"        name = {lua_string(trail['name'])},",
                  f"        difficulty = {trail['difficulty']},",
                  f"        width = {trail['width']:.1f},", "        curves = {"]
        for curve in trail["curves"]:
            lines += ["            {", f"                start = {lua_point(curve['start'])},",
                      f"                control = {lua_point(curve['control'])},",
                      f"                finish = {lua_point(curve['finish'])},", "            },"]
        lines += ["        },", "    },"]
    lines += ["}", "", f"data.ticket_office = {lua_point(ticket)}",
              f"data.ticket_office_yaw = {ticket_yaw:.3f}",
              "data.snowcat_shed = {",
              f"    position = {lua_point(snowcat_shed['position'])},",
              f"    yaw = {snowcat_shed['yaw']:.3f},",
              "}",
              "data.amenities = {"]
    for amenity in amenities:
        lines += ["    {",
                  f"        kind = {lua_string(amenity['kind'])},",
                  f"        name = {lua_string(amenity['name'])},",
                  f"        position = {lua_point(amenity['position'])},",
                  f"        yaw = {amenity['yaw']:.3f},",
                  "    },"]
    lines += ["}", "", "return data", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--osm", action="append", required=True, type=Path)
    parser.add_argument("--r16", required=True, type=Path)
    parser.add_argument('--config', type=Path, default=ROOT / 'maps/veymont/map.json')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'mod/SkiEO-Veymont/custom-map.json')
    parser.add_argument('--forest-count', type=int, default=255667)
    parser.add_argument('--preserve-forest', type=Path, help='retain these SKXY points when expanding a map')
    parser.add_argument('--previous-manifest', type=Path, help='original extent; extra trees are placed outside it')
    parser.add_argument("--xy-output", required=True, type=Path)
    parser.add_argument("--lua-output", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.forest_count <= 5_000_000:
        parser.error('--forest-count must be within 1..5000000')
    if bool(args.preserve_forest) != bool(args.previous_manifest):
        parser.error('--preserve-forest and --previous-manifest must be supplied together')
    config = json.loads(args.config.read_text())
    manifest = json.loads(args.manifest.read_text())
    grid = Grid.read(config, manifest)

    nodes, ways, relations = parse_osm(args.osm)
    forest_ways = {
        way_id for way_id, (_, tags) in ways.items()
        if tags.get("landuse") == "forest" or tags.get("natural") == "wood"
    }
    forest_relations = [
        value for value in relations.values()
        if value[1].get("landuse") == "forest" or value[1].get("natural") == "wood"
    ]
    aerialways = [
        (way_id, refs, tags) for way_id, (refs, tags) in ways.items()
        if tags.get("aerialway") in {"chair_lift", "drag_lift"}
    ]
    pistes = [
        (way_id, refs, tags) for way_id, (refs, tags) in ways.items()
        if tags.get("piste:type") == "downhill"
    ]

    wanted = set()
    for way_id in forest_ways:
        wanted.update(ways[way_id][0])
    for members, _ in forest_relations:
        for member_type, ref, _ in members:
            if member_type == "way" and ref in ways:
                wanted.update(ways[ref][0])
    for _, refs, _ in aerialways + pistes:
        wanted.update(refs)

    ticket_refs = [
        ref for ref, (_, _, tags) in nodes.items()
        if tags.get("shop") == "ticket" and "ski" in (
            tags.get("description", "") + tags.get("name", "")).lower()
    ]
    if not ticket_refs:
        raise RuntimeError("OSM ski ticket office was not found")
    ticket_ref = ticket_refs[0]
    wanted.add(ticket_ref)

    required_ways = {
        SNOWCAT_SHED_WAY: "snowcat shed",
        TICKET_OFFICE_BUILDING_WAY: "ticket office building",
        PANINI_TRAILER_WAY: "panini trailer",
        FRONT_RETAIL_BUILDING_WAY: "restaurant and ski rental building",
    }
    for way_id, label in required_ways.items():
        if way_id not in ways:
            raise RuntimeError(f"OSM {label} footprint was not found")
        wanted.update(ways[way_id][0])
    for ref, label in (
            (SUN_VALLEY_NODE, "Le Sun Valley"),
            (GRILLET_SPORTS_NODE, "Grillet Sports")):
        if ref not in nodes:
            raise RuntimeError(f"OSM {label} point was not found")
        wanted.add(ref)

    snowcat_refs = ways[SNOWCAT_SHED_WAY][0]

    projected = project_nodes(nodes, wanted)
    heights = load_r16(args.r16, grid)

    mask = bytearray(grid.width * grid.height)
    for way_id in forest_ways:
        fill_polygon(mask, pixels_for_way(ways[way_id][0], projected, grid), 1, grid)
    for members, _ in forest_relations:
        for role in ("outer", "inner"):
            for member_type, ref, member_role in members:
                if member_type == "way" and member_role == role and ref in ways:
                    fill_polygon(mask, pixels_for_way(ways[ref][0], projected, grid),
                                 1 if role == "outer" else 0, grid)

    # Real pistes get a 40 m treeless corridor; lift axes get 24 m.  The
    # broader piste buffer also keeps trees away from the quadratic in-game
    # approximation of each OSM polyline.
    for _, refs, _ in pistes:
        clear_polyline(mask, pixels_for_way(refs, projected, grid), math.ceil(2000 / grid.spacing_cm), grid)
    for _, refs, _ in aerialways:
        clear_polyline(mask, pixels_for_way(refs, projected, grid), math.ceil(1200 / grid.spacing_cm), grid)
    tx, ty = pixels_for_way([ticket_ref], projected, grid)[0]
    clear_disc(mask, tx, ty, math.ceil(4800 / grid.spacing_cm), grid)
    snowcat_pixels = pixels_for_way(snowcat_refs, projected, grid)
    if snowcat_pixels:
        sx = sum(point[0] for point in snowcat_pixels) / len(snowcat_pixels)
        sy = sum(point[1] for point in snowcat_pixels) / len(snowcat_pixels)
        clear_disc(mask, sx, sy, math.ceil(2400 / grid.spacing_cm), grid)

    eligible = array("I", (index for index, value in enumerate(mask) if value))
    if not eligible:
        raise RuntimeError("forest mask is empty")
    preserved_count = write_forest(args.xy_output, eligible, grid, args.forest_count,
                                   args.preserve_forest, args.previous_manifest)

    lifts = []
    for _, refs, tags in sorted(aerialways, key=lambda value: value[2].get("name", "")):
        if len(refs) < 2:
            continue
        first = point_record(projected, heights, refs[0], grid)
        last = point_record(projected, heights, refs[-1], grid)
        bottom, top = (first, last) if first["z"] < last["z"] else (last, first)
        lifts.append({"name": tags.get("name", "Lift"),
                      "real_type": tags["aerialway"], "bottom": bottom, "top": top})

    difficulty = {"novice": 0, "easy": 1, "intermediate": 1,
                  "advanced": 3, "expert": 3, "freeride": 3}
    width = {0: 3400.0, 1: 3000.0, 2: 2600.0, 3: 2300.0}
    trails = []
    for _, refs, tags in sorted(pistes, key=lambda value: value[2].get("name", "")):
        route = [point_record(projected, heights, ref, grid) for ref in refs if ref in projected]
        if len(route) < 2:
            continue
        if route[0]["z"] < route[-1]["z"]:
            route.reverse()
        curves = []
        for start, finish in zip(route, route[1:]):
            middle_x = 0.5 * (start["x"] + finish["x"])
            middle_y = 0.5 * (start["y"] + finish["y"])
            control = {"x": middle_x, "y": middle_y,
                       "z": sample_height(heights, middle_x, middle_y, grid)}
            curves.append({"start": start, "control": control, "finish": finish})
        level = difficulty.get(tags.get("piste:difficulty", "intermediate"), 1)
        trails.append({"name": tags.get("name") or "Unnamed trail",
                       "difficulty": level, "width": width[level],
                       "curves": curves})

    ticket = point_record(projected, heights, ticket_ref, grid)
    ticket["z"] += 20.0
    ticket_yaw = polygon_placement(
        projected, heights, ways[TICKET_OFFICE_BUILDING_WAY][0], grid)["yaw"]
    snowcat_shed = polygon_placement(projected, heights, snowcat_refs, grid)
    panini = polygon_placement(
        projected, heights, ways[PANINI_TRAILER_WAY][0], grid)
    front_building = polygon_placement(
        projected, heights, ways[FRONT_RETAIL_BUILDING_WAY][0], grid)
    sun_valley = point_record(projected, heights, SUN_VALLEY_NODE, grid)
    grillet_sports = point_record(projected, heights, GRILLET_SPORTS_NODE, grid)
    sun_valley["z"] += 20.0
    grillet_sports["z"] += 20.0
    # The patrol shares the real ticket-office building. Represent its native
    # gameplay service immediately south of the office, in world +Y.
    patrol = {"x": ticket["x"], "y": ticket["y"] + 1400.0}
    patrol["z"] = sample_height(heights, patrol["x"], patrol["y"], grid) + 20.0
    amenities = [
        {"kind": "ski_patrol_hut", "name": "Gresse Ski Patrol Hut",
         "position": patrol, "yaw": ticket_yaw},
        {"kind": "hot_cocoa_cart", "name": "Panini Trailer by the Bridge",
         "position": panini["position"], "yaw": panini["yaw"]},
        {"kind": "waffle_stand", "name": "Le Sun Valley",
         "position": sun_valley, "yaw": front_building["yaw"]},
        {"kind": "warming_hut", "name": "Grillet Sports - Ski Rental",
         "position": grillet_sports, "yaw": front_building["yaw"]},
    ]

    document = {"source": "OpenStreetMap", "lifts": lifts, "trails": trails,
                "ticket_office": ticket, "ticket_office_yaw": ticket_yaw,
                "snowcat_shed": snowcat_shed, "amenities": amenities,
                "forest_cells": len(eligible), "forest_obstacles": args.forest_count, "forest_preserved": preserved_count}
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    write_lua(args.lua_output, lifts, trails, ticket, ticket_yaw,
              snowcat_shed, amenities)
    print(f"{len(lifts)} lifts, {len(trails)} pistes, {len(amenities)} amenities; "
          f"{len(eligible)} forest cells -> {args.forest_count} obstacles")


if __name__ == "__main__":
    main()
