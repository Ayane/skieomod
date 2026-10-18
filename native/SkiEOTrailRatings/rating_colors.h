#ifndef SKIEO_RATING_COLORS_H
#define SKIEO_RATING_COLORS_H
#include <math.h>
#include <stdint.h>

typedef struct RatingColors {
    uint32_t mask;
    uint32_t srgb[4];
} RatingColors;

typedef struct RatingColor { float r, g, b, a; } RatingColor;

static int rating_colors_valid(const RatingColors *colors)
{
    if (colors->mask & ~15u) return 0;
    for (unsigned i = 0; i < 4; ++i) {
        if (colors->srgb[i] > 0xffffffu ||
            (!(colors->mask & (1u << i)) && colors->srgb[i])) return 0;
    }
    return 1;
}

static float rating_srgb_channel(unsigned byte)
{
    float value = byte / 255.0f;
    return value <= 0.04045f ? value / 12.92f : powf((value + 0.055f) / 1.055f, 2.4f);
}

static RatingColor rating_linear_color(uint32_t srgb)
{
    RatingColor result = {
        rating_srgb_channel((srgb >> 16) & 255),
        rating_srgb_channel((srgb >> 8) & 255),
        rating_srgb_channel(srgb & 255), 1.0f
    };
    return result;
}
#endif
