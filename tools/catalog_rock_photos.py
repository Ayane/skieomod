#!/usr/bin/env python3
"""Inventory a local photo selection without assuming its views are calibrated.

EXIF anchors and human assessments stay separate: GPS and a solar direction
do not establish direct illumination, matching surface pixels or camera pose.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    from extract_rock_surface import Heightfield
    from rock_photo_metadata import geographic_anchors, read_metadata
except ModuleNotFoundError:
    from tools.extract_rock_surface import Heightfield
    from tools.rock_photo_metadata import geographic_anchors, read_metadata


ROLES = {'shape': 'Silhouette and volumes', 'snow': 'Snow cornices',
         'rock': 'Snow-free rock', 'radiometry_candidate': 'Lighting to review',
         'context': 'Overview'}
SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}


def load_review(path: Path | None) -> dict:
    if path is None:
        return {}
    review = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(review, dict) or review.get('version') != 1 or not isinstance(review.get('photos'), dict):
        raise ValueError('photo review requires version 1 and a photos object')
    for name, item in review['photos'].items():
        if Path(name).name != name or not isinstance(item, dict):
            raise ValueError('photo review keys must be filenames in the input directory')
        if (type(item.get('priority', 3)) is not int or not 1 <= item.get('priority', 3) <= 4
                or not isinstance(item.get('roles', []), list)
                or any(not isinstance(role, str) or role not in ROLES for role in item.get('roles', []))
                or not isinstance(item.get('notes', ''), str)):
            raise ValueError('photo review priority, roles or notes are invalid')
        if 'location_hint' in item:
            hint = item['location_hint']
            if not isinstance(hint, dict):
                raise ValueError('location hint must be an object')
            try:
                latitude, longitude = float(hint['latitude']), float(hint['longitude'])
                radius = float(hint['radius_meters'])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError('location hint requires numeric coordinates and radius') from error
            if (not isinstance(hint.get('source'), str) or not -90 <= latitude <= 90
                    or not -180 <= longitude <= 180 or not 0 < radius <= 500):
                raise ValueError('location hint requires geographic coordinates, a source and a 0..500 metre radius')
            hint.update(latitude=latitude, longitude=longitude, radius_meters=radius)
    return review['photos']


def write_gallery(report: dict, path: Path) -> None:
    cards = []
    esc = html.escape
    for photo in report['photos']:
        metadata = photo.get('metadata', {})
        anchors = photo.get('anchors', {})
        review = photo['review']
        roles = ' '.join(review.get('roles', []))
        badges = ' · '.join(ROLES[role] for role in review.get('roles', [])) or 'To review'
        details = [' × '.join(map(str, metadata['image_size']))+' pixels'] if metadata else []
        if 'gps_datetime_utc' in metadata:
            details.append('UTC '+metadata['gps_datetime_utc'])
        elif 'camera_datetime_local' in metadata:
            details.append('Camera time '+metadata['camera_datetime_local']+' (UTC unknown)')
        if anchors:
            xy = anchors['position_xy_meters']
            details.append(f'Map: X {xy[0]:.0f} m, Y {xy[1]:.0f} m')
            if anchors.get('heightmap_ground_meters') is not None:
                details.append(f"Ground: {anchors['heightmap_ground_meters']:.0f} m")
            if 'sun_altitude_degrees' in anchors:
                details.append(f"Calculated sun: {anchors['sun_altitude_degrees']:.1f}°")
        hint = photo.get('location_hint_anchors')
        if hint:
            xy = hint['position_xy_meters']
            details.append(f"Proposed position: X {xy[0]:.0f} m, Y {xy[1]:.0f} m (±{review['location_hint']['radius_meters']:.0f} m)")
        preview = ('<img loading="lazy" alt="'+esc(photo['file'], quote=True)+'" src="'
                   +esc(photo['thumbnail'], quote=True)+'">') if photo.get('thumbnail') else '<div class="failed">Unreadable image</div>'
        issues = ''.join('<li>'+esc(issue)+'</li>' for issue in photo['issues'])
        duplicate = '<p>Identical to '+esc(photo['duplicate_of'])+'</p>' if photo.get('duplicate_of') else ''
        cards.append('<article data-roles="'+esc(roles, quote=True)+'" data-name="'
            +esc(photo['file'].lower(), quote=True)+'" data-gps="'+str('latitude' in metadata).lower()+'">'
            +preview+'<div class="body"><h2>'+esc(photo['file'])+'</h2><p class="badge">'
            +esc(badges)+'</p><p>'+esc(review.get('notes', ''))+'</p><p class="meta">'
            +'<br>'.join(esc(value) for value in details)+'</p>'+duplicate+'<ul>'+issues+'</ul></div></article>')
    options = ''.join('<option value="'+role+'">'+label+'</option>' for role,label in ROLES.items())
    summary = report['summary']
    document = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reference photos — Veymont</title><style>
*{box-sizing:border-box}body{margin:0;background:#eef1f4;color:#192c38;font:16px/1.5 system-ui}
header,main{max-width:1450px;margin:auto;padding:24px}h1{margin:0}header p{max-width:1000px}
nav{display:flex;gap:18px;flex-wrap:wrap;align-items:end}label{display:grid;gap:4px}input,select{font:inherit;padding:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}
article{background:white;border-radius:8px;overflow:hidden}article[hidden]{display:none}
img{width:100%;height:230px;object-fit:contain;background:#17212b}.body{padding:16px}
h2{font-size:17px;margin:0;overflow-wrap:anywhere}.meta,li{font-size:13px;color:#405564}.badge{color:#215f73;font-weight:600}
.failed{height:230px;padding:40px}footer{padding:24px;color:#405564}.notice{border-left:4px solid #7293a0;padding-left:16px}
</style><header><h1>Grand Veymont reference photos</h1><p>__SUMMARY__</p>
<p class="notice">Roles come from visual inspection. Metadata provides starting points;
it does not validate the camera or surface normals. Check shadows, clouds and snow changes on each cliff.</p>
<nav><label>Usage<select id="role"><option value="">All views</option>__OPTIONS__</select></label>
<label>Name<input id="search" type="search" placeholder="Date or filename"></label>
<label><span>GPS</span><select id="gps"><option value="">With or without GPS</option><option value="true">GPS present</option><option value="false">GPS absent</option></select></label>
<span id="count" role="status"></span></nav></header><main class="grid">__CARDS__</main>
<footer>Full report: <a href="inventory.json">inventory.json</a>. Original files are preserved.</footer>
<script>const cards=[...document.querySelectorAll('article')];
function filter(){let n=0;for(const c of cards){const ok=(!role.value||c.dataset.roles.split(' ').includes(role.value))&&
(!gps.value||c.dataset.gps===gps.value)&&c.dataset.name.includes(search.value.toLowerCase());c.hidden=!ok;if(ok)n++;}
document.getElementById('count').textContent=n+' view(s)';}
const role=document.getElementById('role'),gps=document.getElementById('gps'),search=document.getElementById('search');
for(const e of [role,gps,search])e.addEventListener('input',filter);filter();</script></html>'''
    text = f"{summary['photos']} photos · {summary['gps_photos']} with GPS · {summary['utc_photos']} with UTC time · {summary['duplicates']} duplicate(s)."
    document = document.replace('__SUMMARY__', esc(text)).replace('__OPTIONS__', options).replace('__CARDS__', '\n'.join(cards))
    path.write_text(document, encoding='utf-8')


def catalog(source: Path, output: Path, georeference: Path,
            manifest: Path | None = None, review_path: Path | None = None) -> dict:
    source, output = source.resolve(), output.resolve()
    if not source.is_dir():
        raise ValueError('photo input must be an existing directory')
    if output == source or output.is_relative_to(source):
        raise ValueError('catalog output must be outside the original photo directory')
    files = sorted(path for path in source.iterdir() if path.is_file() and path.suffix.lower() in SUFFIXES)
    if not files or len(files) > 512:
        raise ValueError('photo directory must contain 1..512 supported images')
    review = load_review(review_path)
    unknown = set(review)-{path.name for path in files}
    if unknown:
        raise ValueError('review references missing photos: '+', '.join(sorted(unknown)))
    georef = json.loads(georeference.read_text(encoding='utf-8'))
    field = Heightfield(manifest) if manifest else None
    (output/'thumbnails').mkdir(parents=True, exist_ok=True)
    photos, known = [], {}
    for path in files:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        item = {'file': path.name, 'source': str(path), 'sha256': digest,
                'review': review.get(path.name, {}), 'issues': []}
        if digest in known:
            item['duplicate_of'] = known[digest]
        else:
            known[digest] = path.name
        try:
            item['metadata'] = read_metadata(path)
            metadata = item['metadata']
            with Image.open(path) as photo:
                photo = ImageOps.exif_transpose(photo).convert('RGB')
                photo.thumbnail((960, 600))
                name = 'thumbnails/'+digest[:24]+'.jpg'
                photo.save(output/name, quality=88)
                item['thumbnail'] = name
            if 'latitude' not in metadata:
                item['issues'].append('No GPS: register the position separately.')
                if item['review'].get('location_hint'):
                    hint = item['review']['location_hint']
                    # Do not turn user evidence into invented EXIF or UTC.
                    item['location_hint_anchors'] = geographic_anchors(
                        {'latitude': hint['latitude'], 'longitude': hint['longitude']}, georef)
            else:
                anchors = geographic_anchors(metadata, georef)
                if field:
                    xy = anchors['position_xy_meters']
                    z = float(field.sample(np.array([*xy, 0])))
                    anchors['heightmap_ground_meters'] = z if np.isfinite(z) else None
                    anchors['inside_heightmap'] = bool(np.isfinite(z))
                    if not np.isfinite(z):
                        item['issues'].append('Photo taken outside the heightmap: provide camera altitude separately.')
                item['anchors'] = anchors
                if anchors.get('sun_altitude_degrees', 90) <= 0:
                    item['issues'].append('Calculated sun below the horizon: do not use the direct sunlight model.')
                elif anchors.get('sun_altitude_degrees', 90) < 5:
                    item['issues'].append('Low sun: review cast shadows and diffuse light.')
            if 'gps_datetime_utc' not in metadata:
                item['issues'].append('No UTC: local time or a filename does not replace a calibrated timestamp.')
            if 'focal_equivalent_35mm' not in metadata:
                item['issues'].append('No equivalent focal length: estimate the field of view.')
        except (ValueError, KeyError, OSError) as error:
            item['error'] = str(error)
            item['issues'].append('Lecture ou projection impossible : '+str(error))
        photos.append(item)
    photos.sort(key=lambda item: (item['review'].get('priority', 3), item['file']))
    report = {'version': 1, 'source_directory': str(source), 'photos': photos,
        'summary': {'photos': len(photos), 'gps_photos': sum('latitude' in item.get('metadata', {}) for item in photos),
            'utc_photos': sum('gps_datetime_utc' in item.get('metadata', {}) for item in photos),
            'duplicates': sum('duplicate_of' in item for item in photos),
            'errors': sum('error' in item for item in photos)},
        'heightmap_sha256': field.source_sha256 if field else None,
        'originals_modified': False, 'camera_or_surface_calibration_verified': False}
    (output/'inventory.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
    write_gallery(report, output/'index.html')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--georeference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = catalog(args.directory, args.output_dir, args.georeference, args.manifest, args.review)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
