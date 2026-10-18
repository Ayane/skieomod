# Veymont terrain repairs

Veymont 0.6.1 corrects four adjacent 500 m source tiles near Les Deux and
the Col des Deux. The CRAIG Isère MNT contains large interpolation facets
there, including at its full 0.5 m resolution. These are elevation-data
defects rather than mesh-index or shadow defects.

The replacement is the official IGN LiDAR HD MNT, mission **21LHD7PN**,
acquired on **14 October 2021**, classified by **Avineon**, and published
on **20 February 2025**, under **Open Licence v2.0**. The tile is
`LHD_FXX_0902_6430_MNT_O_0M50_LAMB93_IGN69.tif`, available from the
[official IGN download interface](https://cartes.gouv.fr/telechargement/IGNF_MNT-LIDAR-HD).
The exact GeoTIFF download URL, source checksum and repair footprint are
recorded in `maps/veymont/map.json` and attributed in the packaged manifest.

The corrected square covers Lambert-93 coordinates **902000–903000 m east**
and **6429000–6430000 m north**. Its heights come entirely from IGN's
replacement. A smooth 32 m margin joins it to the surrounding CRAIG data.
The map keeps its 2017 × 3025 grid, 4 m spacing and existing R16 encoding.
The previous central 8.064 km square, all SKXY tree coordinates, lifts,
trails and buildings remain unchanged. Start a new session to inspect the
correction; older installed map versions and saves are preserved.

## Reproduce the correction

Use the original `Terrain/heightmap.r16` from Veymont **0.6.0**, included
in the versioned Custom Maps **1.8.0** archive. With NumPy and GDAL installed:

```sh
python3 tools/repair_heightmap.py \
  --input /path/to/veymont-0.6.0/Terrain/heightmap.r16 \
  --output build/terrain/veymont-0.6.1.r16 \
  --fetch
```

The tool verifies the original input and downloaded source checksums,
rejects missing elevation data, retains the original encoding, and writes
the result atomically. It refuses an already corrected input, so repeated
builds cannot apply the blend twice. Samples outside the repair margin
remain byte-identical to the original.
