#ifndef SKIEO_RENDER_MAPPING_LAYOUT_H
#define SKIEO_RENDER_MAPPING_LAYOUT_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

/* Trailing renderer controls moved in builds 25808900 and 25970577. Texture
   references and sampling bounds retain their verified offsets. Keep each
   layout explicit, including its minimum readable snapshot size. */
static int skieo_render_mapping_matches_snapshot(
    const uint8_t *data, size_t size, uint64_t scene,
    const uint64_t textures[7])
{
    if (size < 0xB8) return 0;
    uint64_t owner, height, wind, canopy, morphology, slope;
    memcpy(&owner, data + 8, 8);
    memcpy(&height, data + 0x10, 8);
    memcpy(&wind, data + 0x40, 8);
    memcpy(&canopy, data + 0x48, 8);
    memcpy(&morphology, data + 0x50, 8);
    memcpy(&slope, data + 0x58, 8);
    float bounds[6];
    memcpy(bounds, data + 0x18, sizeof(bounds));
    for (unsigned i=0; i<6; ++i) if (!isfinite(bounds[i])) return 0;
    int controls_match = (data[0xB0] == 1 && data[0xB4] == 1)
        || (size >= 0xC0 && data[0xB8] == 1 && data[0xBC] == 1)
        || (size >= 0xE0 && data[0xD8] == 1 && data[0xDC] == 1);
    return owner == scene
        && (height == textures[0] || height == textures[1] || height == textures[2])
        && wind == textures[3] && canopy == textures[4]
        && morphology == textures[5] && slope == textures[6]
        && bounds[0] < bounds[2] && bounds[1] < bounds[3]
        && bounds[4] < bounds[5] && controls_match;
}

#endif
