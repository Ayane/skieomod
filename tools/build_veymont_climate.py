#!/usr/bin/env python3
"""Derive a modest local game climate from open Meteo-France daily observations.

Inputs: the official Isere 1950–2024 RR-T-Vent and autres-parametres CSV.gz.
Temperatures use complete 1991–2020 TN/TX normals at nearby St-Baudille,
with an explicit -0.65 C/100 m adjustment from 1040 to 1220 m.
Missing fresh-snow days are excluded, never filled with zero.
"""
import argparse
import calendar
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path


def build(temperature_file, snow_file):
    data = collections.defaultdict(list)
    for path, station, fields in [(temperature_file, '38366001', ('TN', 'TX')),
                                  (snow_file, '38186001', ('HNEIGEF',))]:
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for row in csv.DictReader(stream, delimiter=';'):
                date = row['AAAAMMJJ']
                if row['NUM_POSTE'] != station or not '19910101' <= date <= '20201231':
                    continue
                for field in fields:
                    if row.get(field):
                        data[field, int(date[4:6])].append(float(row[field]))
    months = []
    for month in range(1, 13):
        tn, tx, snow = (data[field, month] for field in ('TN', 'TX', 'HNEIGEF'))
        days = sum(calendar.monthrange(year, month)[1] for year in range(1991, 2021))
        assert len(tn) == len(tx) == days, 'Incomplete temperature normals'
        # Off-season snow reporting is sparse; zero measurements remain valid.
        assert len(snow) >= days * .45, 'Insufficient fresh-snow coverage'
        months.append({'month': month,
                       'temperature_c': round((sum(tn) / len(tn) + sum(tx) / len(tx)) / 2 - 1.17, 2),
                       'fresh_snow_cm': round(sum(snow) / len(snow) * days / 30, 2),
                       'snow_observed_days': len(snow), 'period_days': days})
    annual = round(sum(row['fresh_snow_cm'] for row in months), 2)
    return {'period': [1991, 2020], 'reference_elevation_m': 1220,
            'latitude': 44.899833, 'annual_fresh_snow_cm': annual,
            'temperature_method': '(mean TN + mean TX) / 2 at ST-BAUDILLE (1040 m), minus 1.17 C',
            'snow_method': 'GRESSE (1220 m), monthly mean of observed HNEIGEF days, scaled to calendar month',
            'source': 'https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes',
            'license': 'Meteo-France, Licence Ouverte 2.0',
            'inputs': {Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                       for path in (temperature_file, snow_file)}, 'months': months}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('temperature_file', type=Path)
    parser.add_argument('snow_file', type=Path)
    parser.add_argument('--output', type=Path, default=Path('mod/SkiEO-Veymont/Data/climate.json'))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build(args.temperature_file, args.snow_file), indent=2) + '\n')
