#ifndef SKIEO_NAVIGATION_LAYOUT_H
#define SKIEO_NAVIGATION_LAYOUT_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum { SKIEO_NAVIGATION_TICK_BYTES = 71, SKIEO_NAVIGATION_CHANGED_BYTES = 12 };

/* Pair each verified tick with its terrain-change handler. A matching tick
   alone must never authorize a handler from another subsystem layout. */
static const uint8_t *skieo_navigation_changed_signature(
    const uint8_t *tick, size_t size)
{
    static const uint8_t legacy_tick[] = {
        0x48,0x89,0x5C,0x24,0x18,0x56,0x48,0x83,0xEC,0x30,
        0x48,0x8D,0x71,0xC8,
    };
    static const uint8_t paused_tick[] = {
        0x40,0x53,0x48,0x83,0xEC,0x30,0x0F,0x29,0x74,0x24,0x20,
        0x48,0x8B,0xD9,0x48,0x89,0x74,0x24,0x40,0x0F,0x28,0xF1,
        0x48,0x8D,0x71,0xC8,
    };
    /* Build 25970577: additional navigation work, same +0x38 tick subobject. */
    static const uint8_t expanded_tick[] = {
        0x48,0x89,0x5C,0x24,0x18,0x48,0x89,0x74,0x24,0x20,
        0x57,0x48,0x83,0xEC,0x60,0x48,0x8D,0x71,0xC8,
        0x0F,0x29,0x74,0x24,0x50,0x48,0x8B,0xD9,
    };
    static const uint8_t legacy_changed[SKIEO_NAVIGATION_CHANGED_BYTES] = {
        0xC6,0x81,0x68,0x06,0x00,0x00,0x01,0xC6,0x41,0x49,0x01,0xC3,
    };
    static const uint8_t expanded_changed[SKIEO_NAVIGATION_CHANGED_BYTES] = {
        0xC6,0x81,0x48,0x08,0x00,0x00,0x01,0xC6,0x41,0x69,0x01,0xC3,
    };
    /* Build 26056171 retains the tick prologue but moves its work counter
       from +0x568 to +0x570 and the terrain dirty flag from +0x848 to +0x860.
       Inspect the counter instruction as well before selecting either ABI. */
    static const uint8_t expanded_counter[] = {0xC7,0x83,0x68,0x05,0,0,0,0,0,0};
    static const uint8_t current_counter[] = {0xC7,0x83,0x70,0x05,0,0,0,0,0,0};
    static const uint8_t current_changed[SKIEO_NAVIGATION_CHANGED_BYTES] = {
        0xC6,0x81,0x60,0x08,0x00,0x00,0x01,0xC6,0x41,0x69,0x01,0xC3,
    };
    if ((size >= sizeof(legacy_tick) && !memcmp(tick, legacy_tick, sizeof(legacy_tick)))
        || (size >= sizeof(paused_tick) && !memcmp(tick, paused_tick, sizeof(paused_tick))))
        return legacy_changed;
    if (size >= SKIEO_NAVIGATION_TICK_BYTES && !memcmp(tick, expanded_tick, sizeof(expanded_tick))) {
        if (!memcmp(tick + 0x3D, expanded_counter, sizeof(expanded_counter))) return expanded_changed;
        if (!memcmp(tick + 0x3D, current_counter, sizeof(current_counter))) return current_changed;
    }
    return NULL;
}

#endif
