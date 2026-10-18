#ifndef SKIEO_RATING_POLICY_H
#define SKIEO_RATING_POLICY_H
#include <math.h>
#include <stdint.h>

typedef struct RatingPolicy {
    uint32_t count;
    float degrees[3];
} RatingPolicy;

static int rating_policy_valid(const RatingPolicy *policy)
{
    if (policy->count != 0 && policy->count != 2 && policy->count != 3) return 0;
    for (uint32_t i = 0; i < 3; ++i) {
        float value = policy->degrees[i];
        if (i >= policy->count) { if (value != 0) return 0; continue; }
        if (!isfinite(value) || value <= 0 || value > 90 ||
            (i && value <= policy->degrees[i - 1])) return 0;
    }
    return 1;
}

static uint8_t rating_from_slope(float angle, const RatingPolicy *policy)
{
    if (isnan(angle)) return 0;
    for (uint32_t i = 0; i < policy->count; ++i)
        if (angle < policy->degrees[i]) return (uint8_t)i;
    return (uint8_t)policy->count;
}
#endif
