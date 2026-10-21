#ifndef SKIEO_LAYOUT_RESOLUTION_H
#define SKIEO_LAYOUT_RESOLUTION_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* Only reviewed PC-relative address operands are masked. Instructions,
   private field offsets, constants and internal branches remain exact. */
typedef struct { uint16_t offset, size; } SkiEOAddressMask;
typedef struct {
    const uint8_t *prefix;
    uint16_t prefix_size, code_size;
    const SkiEOAddressMask *masks;
    uint16_t mask_count;
    uint64_t fingerprint;
} SkiEOCodeLayout;

static inline int skieo_code_layout_matches(const SkiEOCodeLayout *layout,
                                   const uint8_t *code, size_t size)
{
    if (!layout || !code || size < layout->code_size || !layout->prefix_size ||
        layout->prefix_size > layout->code_size ||
        memcmp(code, layout->prefix, layout->prefix_size)) return 0;
    uint64_t hash = UINT64_C(14695981039346656037);
    unsigned mask = 0;
    for (unsigned i = 0; i < layout->code_size; i++) {
        while (mask < layout->mask_count &&
               i >= layout->masks[mask].offset + layout->masks[mask].size) mask++;
        uint8_t value = mask < layout->mask_count && i >= layout->masks[mask].offset ? 0 : code[i];
        hash = (hash ^ value) * UINT64_C(1099511628211);
    }
    return hash == layout->fingerprint;
}

/* Return a count, rather than selecting the first match. The caller combines
   executable sections and refuses ambiguous results, including cached ones. */
static inline unsigned skieo_code_layout_scan(const SkiEOCodeLayout *layout,
                                      const uint8_t *code, size_t size, size_t *offset)
{
    if (size < layout->code_size) return 0;
    size_t cursor = 0, limit = size - layout->code_size + 1;
    unsigned count = 0;
    while (cursor < limit) {
        const uint8_t *candidate = memchr(code + cursor, layout->prefix[0], limit - cursor);
        if (!candidate) break;
        cursor = (size_t)(candidate - code);
        if (skieo_code_layout_matches(layout, candidate, size - cursor)) {
            *offset = cursor;
            if (++count == 2) return count;
        }
        cursor++;
    }
    return count;
}
#endif
