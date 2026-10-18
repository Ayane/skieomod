// Thin C ABI for the optional meshoptimizer offline simplifier. The caller
// locks borders, audits topology and regenerates native projection UVs. Source:
// https://github.com/zeux/meshoptimizer (MIT); built separately in build/.
#include "meshoptimizer.h"
#include <cstddef>

extern "C" size_t simplify_rock(unsigned int* destination, const unsigned int* indices,
    size_t index_count, const float* positions, size_t vertex_count, const float* uvs,
    const unsigned char* locks, size_t target_count, float error, float* actual_error)
{
    const float weights[2] = {0.01f, 0.01f};
    return meshopt_simplifyWithAttributes(destination, indices, index_count,
        positions, vertex_count, 3*sizeof(float), uvs, 2*sizeof(float), weights, 2,
        locks, target_count, error, meshopt_SimplifyLockBorder | meshopt_SimplifyErrorAbsolute,
        actual_error);
}
