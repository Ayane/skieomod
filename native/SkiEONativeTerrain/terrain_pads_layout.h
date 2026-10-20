#ifndef SKIEO_TERRAIN_PADS_LAYOUT_H
#define SKIEO_TERRAIN_PADS_LAYOUT_H

#include <stddef.h>
#include <stdint.h>

/* Reviewed APlaceableActor pad registration, including both branches for
   conforming props and flattened buildings. Exact code fingerprints reject
   changes to the private ABI or any call target. These are code guards, not
   hashes used for authentication. The bridge calls native methods rather
   than overwriting save buffers or terrain samples. */
#define SKIEO_TERRAIN_PADS_BYTES 0x828
#define SKIEO_TERRAIN_PADS_CLEANUP_BYTES 0x10B
static uint64_t skieo_terrain_pads_hash(const uint8_t *code, size_t size)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < size; ++i)
        hash = (hash ^ code[i]) * UINT64_C(1099511628211);
    return hash;
}

static int skieo_terrain_pads_matches(const uint8_t *code, size_t size,
                                    uint32_t rva)
{
    if (size < SKIEO_TERRAIN_PADS_BYTES) return 0;
    uint64_t expected = rva == 0x4FE1470 ? UINT64_C(0x8AB1FF5C88F7D5F9)
        : rva == 0x4FE0F70 ? UINT64_C(0x7BAAABDF7939B880)
        : rva == 0x4FE0FF0 ? UINT64_C(0x836BFA5102F90B48)
        : rva == 0x4FE0C00 ? UINT64_C(0x0879A1D98812E619)
        : rva == 0x4FDF110 ? UINT64_C(0xE916A3448ECA3D54) : 0;
    return expected && skieo_terrain_pads_hash(code, SKIEO_TERRAIN_PADS_BYTES) == expected;
}

static int skieo_terrain_pads_cleanup_matches(const uint8_t *code, size_t size,
                                            uint32_t rva)
{
    if (size < SKIEO_TERRAIN_PADS_CLEANUP_BYTES) return 0;
    uint64_t expected = rva == 0x4FCC520 ? UINT64_C(0xBD5FDE5E6059003A)
        : rva == 0x4FCC020 ? UINT64_C(0x36BC6A519E3F4B78)
        : rva == 0x4FCC230 ? UINT64_C(0x2CC68335B006FA28)
        : rva == 0x4FCBE40 ? UINT64_C(0xD5CE2DE6D6D72363)
        : rva == 0x4FCA360 ? UINT64_C(0x334861B36D7EC8FA) : 0;
    return expected && skieo_terrain_pads_hash(code, SKIEO_TERRAIN_PADS_CLEANUP_BYTES) == expected;
}

#endif
