"""Read photographic anchors and estimate daylight without using image colour.

The solar direction uses NOAA's approximate fractional-year equations. GPS
altitude is reported, but terrain altitude remains the heightfield's datum.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image, ImageOps


def coordinate(parts, reference, positive: str, negative: str) -> float:
    values = np.asarray([float(value) for value in parts], dtype=float)
    if values.shape != (3,) or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError('GPS coordinate must contain three finite nonnegative components')
    if isinstance(reference, bytes):
        reference = reference.decode('ascii')
    if reference not in [positive, negative]:
        raise ValueError('GPS coordinate hemisphere is invalid')
    if values[1] >= 60 or values[2] >= 60:
        raise ValueError('GPS minutes and seconds must be less than 60')
    result = float(values @ [1, 1/60, 1/3600])
    return result if reference == positive else -result


def read_metadata(path: Path) -> dict:
    with Image.open(path) as image:
        exif = image.getexif()
        gps, detail = exif.get_ifd(34853), exif.get_ifd(34665)
        oriented = ImageOps.exif_transpose(image)
        report = {'image_size': list(oriented.size)}
        if all(key in gps for key in [1, 2, 3, 4]):
            latitude = coordinate(gps[2], gps[1], 'N', 'S')
            longitude = coordinate(gps[4], gps[3], 'E', 'W')
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError('GPS coordinates lie outside geographic bounds')
            report.update(latitude=latitude, longitude=longitude)
        if 6 in gps:
            altitude = float(gps[6])
            if gps.get(5) in [1, b'\x01']:
                altitude = -altitude
            report['gps_altitude_meters'] = altitude
            report['gps_altitude_used'] = False
        if 16 in gps and 17 in gps:
            report['gps_image_direction_degrees'] = float(gps[17])
            report['gps_image_direction_reference'] = str(gps[16])
        if 31 in gps:
            report['gps_horizontal_error_meters'] = float(gps[31])
        if 29 in gps and 7 in gps:
            date = gps[29].decode('ascii') if isinstance(gps[29], bytes) else str(gps[29])
            date = date.rstrip('\x00')
            hour, minute, second = [float(value) for value in gps[7]]
            utc = datetime.strptime(date, '%Y:%m:%d').replace(hour=int(hour), minute=int(minute),
                second=int(second), microsecond=int((second % 1)*1e6), tzinfo=timezone.utc)
            report['gps_datetime_utc'] = utc.isoformat()
        if detail.get(36867):
            report['camera_datetime_local'] = str(detail[36867])
        if detail.get(41989):
            report['focal_equivalent_35mm'] = float(detail[41989])
        if detail.get(37386):
            report['focal_millimeters'] = float(detail[37386])
        return report


def project_geographic(points: list[tuple[float, float]], crs: str) -> np.ndarray:
    if not re.fullmatch(r'EPSG:[0-9]+', crs):
        raise ValueError('photo georeference must identify an EPSG projection')
    if any(not (-90 <= lat <= 90 and -180 <= lon <= 180) for lat, lon in points):
        raise ValueError('geographic coordinates are invalid')
    try:
        result = subprocess.run(['cs2cs', 'EPSG:4326', crs, '-f', '%.4f'],
            input=''.join(f'{latitude:.10f} {longitude:.10f}\n' for latitude, longitude in points),
            text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as error:
        raise ValueError('GPS projection failed; check the EPSG code and PROJ installation') from error
    projected = np.asarray([[float(value) for value in line.split()[:2]]
                            for line in result.stdout.splitlines()])
    if projected.shape != (len(points), 2) or not np.isfinite(projected).all():
        raise ValueError('GPS projection failed')
    return projected


def solar_enu(latitude: float, longitude: float, instant: datetime) -> np.ndarray:
    """Approximate unit vector towards the sun in true east, north, up."""
    if instant.tzinfo is None:
        raise ValueError('solar calculation requires a timezone-aware timestamp')
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('solar coordinates are invalid')
    instant = instant.astimezone(timezone.utc)
    hour = instant.hour+instant.minute/60+(instant.second+instant.microsecond/1e6)/3600
    year_days = 366 if calendar.isleap(instant.year) else 365
    gamma = 2*math.pi/year_days*(instant.timetuple().tm_yday-1+(hour-12)/24)
    eqtime = 229.18*(0.000075+0.001868*math.cos(gamma)-0.032077*math.sin(gamma)
                    -0.014615*math.cos(2*gamma)-0.040849*math.sin(2*gamma))
    declination = (0.006918-0.399912*math.cos(gamma)+0.070257*math.sin(gamma)
        -0.006758*math.cos(2*gamma)+0.000907*math.sin(2*gamma)
        -0.002697*math.cos(3*gamma)+0.00148*math.sin(3*gamma))
    hour_angle = math.radians((hour*60+eqtime+4*longitude)/4-180)
    latitude = math.radians(latitude)
    east = -math.cos(declination)*math.sin(hour_angle)
    north = math.cos(latitude)*math.sin(declination)-math.sin(latitude)*math.cos(declination)*math.cos(hour_angle)
    up = math.sin(latitude)*math.sin(declination)+math.cos(latitude)*math.cos(declination)*math.cos(hour_angle)
    return np.array([east, north, up])


def geographic_anchors(metadata: dict, georeference: dict) -> dict:
    if not all(key in metadata for key in ['latitude', 'longitude']):
        raise ValueError('photo has no usable EXIF GPS latitude and longitude')
    latitude, longitude = metadata['latitude'], metadata['longitude']
    projection = georeference['projection']
    center = np.array([georeference['center']['easting'], georeference['center']['northing']], dtype=float)
    projected = project_geographic([(latitude, longitude), (latitude, longitude+1e-4),
                                   (latitude+1e-4, longitude)], projection)
    position = projected[0]-center
    position[1] *= -1
    report = {'position_xy_meters': position.tolist(), 'projection': projection,
              'altitude_source': 'heightmap (GPS altitude is not used as its datum)'}
    if 'gps_datetime_utc' in metadata:
        sun = solar_enu(latitude, longitude, datetime.fromisoformat(metadata['gps_datetime_utc']))
        east, north = projected[1]-projected[0], projected[2]-projected[0]
        east /= np.linalg.norm(east); north /= np.linalg.norm(north)
        horizontal = east*sun[0]+north*sun[1]
        direction = np.array([horizontal[0], -horizontal[1], sun[2]])
        direction /= np.linalg.norm(direction)
        report.update(light_direction_world=direction.tolist(),
            sun_altitude_degrees=math.degrees(math.asin(float(sun[2]))),
            sun_azimuth_degrees=math.degrees(math.atan2(float(sun[0]), float(sun[1]))) % 360,
            sun_method='NOAA approximate fractional-year equations; no refraction or weather model')
    if 'focal_equivalent_35mm' in metadata:
        # Treat the equivalent as a horizontal full-frame field of view.
        # Sensor crop and equivalent-focal conventions remain fit uncertainty.
        report['initial_focal_pixels'] = metadata['focal_equivalent_35mm']*metadata['image_size'][0]/36
    return report
