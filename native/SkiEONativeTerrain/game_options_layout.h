#ifndef SKIEO_GAME_OPTIONS_LAYOUT_H
#define SKIEO_GAME_OPTIONS_LAYOUT_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
/* Reviewed native new-game request: seed +0x78, settings +0x80, sandbox
   +0x88. Check the complete assignment before using these private fields. */
static const uint8_t skieo_game_options_signature[] = {
    0x41,0x89,0x45,0x78,0x48,0x8B,0x85,0xB0,0,0,0,
    0xF2,0x0F,0x10,0,0xF2,0x41,0x0F,0x11,0x85,0x80,0,0,0,
    0x8B,0x40,0x08,0x41,0x89,0x85,0x88,0,0,0,
};
static int skieo_game_options_valid(float day_length, uint32_t days, uint32_t sandbox)
{
    return isfinite(day_length) && day_length >= 0.05f && day_length <= 64.f
        && days >= 1 && days <= 31 && sandbox <= 1;
}
static int skieo_game_options_apply(uint8_t *owner, size_t size, int32_t seed,
                                  float day_length, uint32_t days, uint32_t sandbox)
{
    if (!owner || size < 0x8A || !skieo_game_options_valid(day_length, days, sandbox)) return 0;
    memcpy(owner + 0x78, &seed, sizeof(seed));
    memcpy(owner + 0x80, &day_length, sizeof(day_length));
    memcpy(owner + 0x84, &days, sizeof(days));
    owner[0x88] = (uint8_t)sandbox;
    owner[0x89] = 0;
    return 1;
}
#endif
