import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image, TiffImagePlugin

from tools.catalog_rock_photos import catalog, load_review


class PhotoCatalogTests(unittest.TestCase):
    def test_catalog_preserves_originals_handles_unreadable_files_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); photos = root/'photos'; photos.mkdir()
            first = photos/'<sample>.jpg'
            Image.new('RGB', (40, 20), (80, 120, 150)).save(first)
            shutil.copyfile(first, photos/'duplicate.jpg')
            (photos/'broken.jpg').write_bytes(b'not an image')
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in photos.iterdir()}
            (root/'map.json').write_text(json.dumps({'projection': 'EPSG:2154',
                'center': {'easting': 901000, 'northing': 6424000}}))
            report = catalog(photos, root/'output', root/'map.json')
            self.assertEqual(report['summary'], {'photos': 3, 'gps_photos': 0,
                'utc_photos': 0, 'duplicates': 1, 'errors': 1})
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in photos.iterdir()}
            self.assertEqual(before, after)
            page = (root/'output/index.html').read_text()
            self.assertIn('&lt;sample&gt;.jpg', page)
            self.assertNotIn('<sample>.jpg', page)
            self.assertFalse(report['camera_or_surface_calibration_verified'])
            for item in report['photos']:
                self.assertNotIn('gps_datetime_utc', item.get('metadata', {}))
            with self.assertRaisesRegex(ValueError, 'outside'):
                catalog(photos, photos/'output', root/'map.json')

    @unittest.skipUnless(shutil.which('cs2cs'), 'GPS catalog requires PROJ cs2cs')
    def test_gps_without_utc_does_not_invent_sunlight_or_an_altitude_datum(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); photos=root/'photos'; photos.mkdir()
            rational = TiffImagePlugin.IFDRational
            exif = Image.Exif()
            exif[34853] = {1:'N',2:tuple(map(rational,[44,53,49])),
                3:'E',4:tuple(map(rational,[5,33,25])),5:b'\x00',6:rational(3000)}
            exif[34665] = {36867:'2025:01:18 10:30:53',41989:26}
            Image.new('RGB',(40,20)).save(photos/'photo.jpg',exif=exif)
            (root/'georef.json').write_text(json.dumps({'projection':'EPSG:2154',
                'center':{'easting':901820.9909,'northing':6425240.9074}}))
            np.full((16,16),10,dtype='<u2').tofile(root/'heights.r16')
            definition={'terrain':{'size_meters':[15,15],'source':{'file':'heights.r16',
                'format':'r16le','vertices':[16,16],'spacing_meters':1,
                'height_scale_meters':1,'height_offset_meters':0}}}
            (root/'terrain.json').write_text(json.dumps(definition))
            report=catalog(photos,root/'output',root/'georef.json',root/'terrain.json')
            item=report['photos'][0]
            self.assertEqual(report['summary']['gps_photos'],1)
            self.assertEqual(report['summary']['utc_photos'],0)
            self.assertNotIn('light_direction_world',item['anchors'])
            self.assertEqual(item['anchors']['heightmap_ground_meters'],10)
            self.assertFalse(item['metadata']['gps_altitude_used'])
            self.assertTrue(any('No UTC' in issue for issue in item['issues']))

    def test_review_rejects_unknown_roles_and_missing_photos(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); review=root/'review.json'
            review.write_text(json.dumps({'version':1,'photos':{'sample.jpg':{'roles':['measured_normals']}}}))
            with self.assertRaises(ValueError): load_review(review)
            review.write_text(json.dumps({'version':1,'photos':{'missing.jpg':{'roles':['shape']}}}))
            photos=root/'photos';photos.mkdir();Image.new('RGB',(10,10)).save(photos/'sample.jpg')
            (root/'georef.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'missing photos'):
                catalog(photos,root/'out',root/'georef.json',review_path=review)

    @unittest.skipUnless(shutil.which('cs2cs'), 'GPS hint projection requires PROJ cs2cs')
    def test_user_location_remains_a_hint_without_inventing_gps_or_utc(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); photos=root/'photos'; photos.mkdir()
            Image.new('RGB',(20,20)).save(photos/'trail.jpg')
            (root/'georef.json').write_text(json.dumps({'projection':'EPSG:2154',
                'center':{'easting':901000,'northing':6424000}}))
            review={'version':1,'photos':{'trail.jpg':{'roles':['shape'],'location_hint':{
                'latitude':44.881055555555555,'longitude':5.527138888888889,
                'radius_meters':150,'source':'user estimate'}}}}
            (root/'review.json').write_text(json.dumps(review))
            result=catalog(photos,root/'out',root/'georef.json',review_path=root/'review.json')
            item=result['photos'][0]
            self.assertEqual(result['summary']['gps_photos'],0)
            self.assertNotIn('anchors',item)
            self.assertNotIn('latitude',item['metadata'])
            self.assertNotIn('gps_datetime_utc',item['metadata'])
            self.assertNotIn('light_direction_world',item['location_hint_anchors'])
            self.assertIn('Proposed position', (root/'out/index.html').read_text())


if __name__ == '__main__':
    unittest.main()
