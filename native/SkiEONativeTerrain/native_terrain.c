#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "render_mapping_layout.h"
#include "navigation_layout.h"
#include "game_options_layout.h"
#include "terrain_pads_layout.h"
#include "surface_sampling.h"
#include "layout_profiles.h"

static uint32_t native_layout_rva(enum SkiEOLayoutId id)
{
    static uint32_t cached[SKIEO_LAYOUT_COUNT];
    static uint8_t searched[SKIEO_LAYOUT_COUNT];
    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module || id >= SKIEO_LAYOUT_COUNT) return 0;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 1048576) return 0;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        !nt->FileHeader.NumberOfSections || nt->FileHeader.NumberOfSections > 96) return 0;
    const SkiEOCodeLayout *layout = &skieo_layouts[id];
    uint32_t jump_target = id == SKIEO_LAYOUT_HUBS_DEFERRED ? native_layout_rva(SKIEO_LAYOUT_HUBS_DEFERRED_TARGET) : 0;
    if (id == SKIEO_LAYOUT_HUBS_DEFERRED && !jump_target) return 0;
    if (searched[id]) {
        uint32_t rva = cached[id];
        if (rva && jump_target) {
            int32_t displacement; memcpy(&displacement, module + rva + SKIEO_LAYOUT_HUBS_DEFERRED_OFFSET, 4);
            if ((int64_t)rva + SKIEO_LAYOUT_HUBS_DEFERRED_END + displacement != jump_target) return 0;
        }
        return rva && skieo_code_layout_matches(layout, module + rva, layout->code_size) ? rva : 0;
    }
    IMAGE_SECTION_HEADER *sections = IMAGE_FIRST_SECTION(nt);
    unsigned matches = 0;
    uint32_t resolved = 0;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; i++) {
        IMAGE_SECTION_HEADER *section = &sections[i];
        uint32_t start = section->VirtualAddress, size = section->Misc.VirtualSize;
        if (!(section->Characteristics & IMAGE_SCN_MEM_EXECUTE) || start >= nt->OptionalHeader.SizeOfImage ||
            size > nt->OptionalHeader.SizeOfImage - start) continue;
        size_t offset = 0;
        unsigned count = 0;
        if (jump_target) {
            for (size_t at = 0; at + layout->code_size <= size; at++) {
                const uint8_t *code = module + start + at;
                if (code[0] != layout->prefix[0] || !skieo_code_layout_matches(layout, code, size - at)) continue;
                int32_t displacement; memcpy(&displacement, code + SKIEO_LAYOUT_HUBS_DEFERRED_OFFSET, 4);
                if ((int64_t)start + (int64_t)at + SKIEO_LAYOUT_HUBS_DEFERRED_END + displacement != jump_target) continue;
                offset = at;
                if (++count == 2) break;
            }
        } else count = skieo_code_layout_scan(layout, module + start, size, &offset);
        matches += count;
        if (matches > 1) break;
        if (count) resolved = start + (uint32_t)offset;
    }
    searched[id] = 1;
    cached[id] = matches == 1 ? resolved : 0;
    return cached[id];
}

#pragma pack(push, 1)
typedef struct SkiEOHeightJob {
    char magic[4];
    uint32_t version;
    uint64_t destination;
    uint64_t cache;
    uint32_t source_width;
    uint32_t source_height;
    uint32_t target_width;
    uint32_t target_height;
    uint32_t flags;
    double spacing_cm;
    double height_scale_cm;
    double origin_x;
    double origin_y;
    double maximum_x;
    double maximum_y;
    float origin_z;
    float maximum_z;
    float spacing_x;
    float spacing_y;
} SkiEOHeightJob;

typedef struct SkiEOHubJob {
    char magic[4];
    uint32_t version;
    uint64_t subsystem;
} SkiEOHubJob;

typedef struct SkiEOStaffJob {
    char magic[4];
    uint32_t version;
    uint64_t subsystem;
    uint64_t settings;
    uint32_t pool_count;
    uint32_t reserved;
} SkiEOStaffJob;

typedef struct SkiEOHubRegistrationHeader {
    char magic[4];
    uint32_t version;
    uint64_t subsystem;
    uint32_t actor_count;
    uint32_t reserved;
} SkiEOHubRegistrationHeader;

typedef struct SkiEOHubRegistrationActor {
    uint64_t actor;
    uint32_t kind;
    uint32_t reserved;
} SkiEOHubRegistrationActor;

typedef struct SkiEOTextureMipJob {
    char magic[4];
    uint32_t version;
    uint64_t destination;
    uint64_t template_texture;
    uint32_t mip_count;
    uint32_t reserved;
    uint64_t sources[10];
} SkiEOTextureMipJob;

typedef struct SkiEOTextureFormatJob {
    char magic[4];
    uint32_t version;
    uint64_t texture;
    uint32_t expected_width;
    uint32_t expected_height;
    uint8_t source_format;
    uint8_t destination_format;
    uint8_t reserved[6];
} SkiEOTextureFormatJob;

typedef struct SkiEOTextureSwapJob {
    char magic[4];
    uint32_t version;
    uint64_t destination;
    uint64_t source;
    uint32_t width;
    uint32_t height;
} SkiEOTextureSwapJob;

typedef struct SkiEORenderMappingJob {
    char magic[4];
    uint32_t version;
    uint64_t height_texture;
    uint64_t previous_height_texture;
    uint64_t previous_snow_height_texture;
    uint64_t wind_texture;
    uint64_t canopy_texture;
    uint64_t morphology_texture;
    uint64_t slope_texture;
    float bounds[6];
    uint64_t world;
} SkiEORenderMappingJob;
#pragma pack(pop)

enum {
    SKIEO_LITTLE_ENDIAN = 1,
    SKIEO_SOUTH_TO_NORTH = 2,
};

static int readable_range(const void *address, size_t size);

static void write_cache_header(const SkiEOHeightJob *job)
{
    uint8_t *cache = (uint8_t *)(uintptr_t)job->cache;
    const float height_min = 0.0f;
    const float height_range = 1.0f;
    memcpy(cache + 0x58, &height_min, sizeof(height_min));
    memcpy(cache + 0x5C, &height_range, sizeof(height_range));
    memcpy(cache + 0x88, &job->origin_x, sizeof(job->origin_x));
    memcpy(cache + 0x90, &job->origin_y, sizeof(job->origin_y));
    memcpy(cache + 0x98, &job->maximum_x, sizeof(job->maximum_x));
    memcpy(cache + 0xA0, &job->maximum_y, sizeof(job->maximum_y));
    memcpy(cache + 0xA8, &job->origin_z, sizeof(job->origin_z));
    memcpy(cache + 0xAC, &job->maximum_z, sizeof(job->maximum_z));
    memcpy(cache + 0xB0, &job->spacing_x, sizeof(job->spacing_x));
    memcpy(cache + 0xB4, &job->spacing_y, sizeof(job->spacing_y));
    /* A freshly constructed Landscape has no cooked heightfield collision.
       Every source sample is nevertheless authoritative. Mark the native
       validity bitset so lazy collision probes cannot overwrite the R16. */
    uint32_t bits = 0, capacity = 0;
    uintptr_t heap = 0;
    memcpy(&heap, cache + 0x70, sizeof(heap));
    memcpy(&bits, cache + 0x78, sizeof(bits));
    memcpy(&capacity, cache + 0x7C, sizeof(capacity));
    size_t samples = (size_t)job->target_width * job->target_height;
    size_t words = (samples + 31) / 32;
    uint32_t *validity = heap ? (uint32_t *)heap : (uint32_t *)(cache + 0x60);
    if (bits == samples && capacity >= bits &&
        readable_range(validity, words * sizeof(uint32_t))) {
        memset(validity, 0xFF, words * sizeof(uint32_t));
        if (bits % 32) validity[words - 1] = (1U << (bits % 32)) - 1;
    }
}

static int sibling_path(wchar_t *path, size_t capacity, const wchar_t *name)
{
    HMODULE module = NULL;
    if (!GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            (LPCWSTR)&sibling_path, &module)) {
        return 0;
    }
    DWORD length = GetModuleFileNameW(module, path, (DWORD)capacity);
    if (!length || length >= capacity) return 0;
    while (length > 0 && path[length - 1] != L'\\' && path[length - 1] != L'/') {
        --length;
    }
    if (length + wcslen(name) + 1 > capacity) return 0;
    wcscpy(path + length, name);
    return 1;
}

static void write_status(const char *message)
{
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_terrain.status")) return;
    FILE *file = _wfopen(path, L"wb");
    if (!file) return;
    fwrite(message, 1, strlen(message), file);
    fclose(file);
}

static void write_hub_status(const char *message)
{
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_hubs.status")) return;
    FILE *file = _wfopen(path, L"wb");
    if (!file) return;
    fwrite(message, 1, strlen(message), file);
    fclose(file);
}

static void write_mip_status(const char *message)
{
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_mips.status")) return;
    FILE *file = _wfopen(path, L"wb");
    if (!file) return;
    fwrite(message, 1, strlen(message), file);
    fclose(file);
}

static void write_format_status(const char *message)
{
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_format.status")) return;
    FILE *file = _wfopen(path, L"wb");
    if (!file) return;
    fwrite(message, 1, strlen(message), file);
    fclose(file);
}

static void put_u16(uint8_t *bytes, uint16_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
}

static void put_be32(uint8_t *bytes, uint32_t value)
{
    bytes[0] = (uint8_t)(value >> 24);
    bytes[1] = (uint8_t)(value >> 16);
    bytes[2] = (uint8_t)(value >> 8);
    bytes[3] = (uint8_t)value;
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *bytes, size_t size)
{
    for (size_t index = 0; index < size; ++index) {
        crc ^= bytes[index];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xEDB88320U & (uint32_t)-(int32_t)(crc & 1));
        }
    }
    return crc;
}

static uint32_t adler32_update(uint32_t adler, const uint8_t *bytes, size_t size)
{
    uint32_t a = adler & 0xFFFFU;
    uint32_t b = adler >> 16;
    for (size_t index = 0; index < size; ++index) {
        a += bytes[index];
        if (a >= 65521U) a -= 65521U;
        b += a;
        if (b >= 65521U) b -= 65521U;
    }
    return (b << 16) | a;
}

static int write_png_chunk(
    FILE *file, const char type[4], const uint8_t *data, uint32_t size)
{
    uint8_t word[4];
    put_be32(word, size);
    if (fwrite(word, 1, 4, file) != 4 || fwrite(type, 1, 4, file) != 4 ||
        (size && fwrite(data, 1, size, file) != size)) {
        return 0;
    }
    uint32_t crc = crc32_update(UINT32_MAX, (const uint8_t *)type, 4);
    crc = crc32_update(crc, data, size) ^ UINT32_MAX;
    put_be32(word, crc);
    return fwrite(word, 1, 4, file) == 4;
}

/* Write an uncompressed 16-bit PNG without passing terrain data through an
   image library.  Runtime imports must preserve every R16 bit: ordinary
   colour conversion, an sRGB transfer function, or an 8-bit intermediate
   changes both elevation and the IEEE-754 half-float payloads used by the
   derived slope textures.  One-channel files use PNG grayscale; four-channel
   files use RGBA in source order. */
static int write_png16(
    const uint16_t *samples, uint32_t width, uint32_t height,
    uint32_t channels, const wchar_t *filename, const char *label)
{
    if (!samples || (channels != 1 && channels != 4) ||
        width > INT32_MAX || height > INT32_MAX ||
        width > (UINT16_MAX - 1) / (channels * 2)) {
        char status[160];
        snprintf(status, sizeof(status),
            "error: %s texture dimensions overflow", label);
        write_status(status);
        return 0;
    }
    const uint32_t scanline_size = 1 + width * channels * 2;
    uint64_t zlib_size_64 = 2 + (uint64_t)height * (5 + scanline_size) + 4;
    if (scanline_size > UINT16_MAX || zlib_size_64 > UINT32_MAX) {
        char status[160];
        snprintf(status, sizeof(status),
            "error: %s texture dimensions overflow", label);
        write_status(status);
        return 0;
    }
    const uint32_t zlib_size = (uint32_t)zlib_size_64;

    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, filename)) {
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not resolve %s texture path", label);
        write_status(status);
        return 0;
    }
    FILE *file = _wfopen(path, L"wb");
    if (!file) {
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not create %s texture", label);
        write_status(status);
        return 0;
    }

    static const uint8_t signature[8] = {
        0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A,
    };
    uint8_t ihdr[13] = {0};
    put_be32(ihdr, width);
    put_be32(ihdr + 4, height);
    ihdr[8] = 16;
    ihdr[9] = channels == 1 ? 0 : 6;
    uint8_t gamma[4];
    put_be32(gamma, 100000U); /* gAMA 1.0: packed data, never sRGB colour */
    if (fwrite(signature, 1, sizeof(signature), file) != sizeof(signature) ||
        !write_png_chunk(file, "IHDR", ihdr, sizeof(ihdr)) ||
        !write_png_chunk(file, "gAMA", gamma, sizeof(gamma))) {
        fclose(file);
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not write %s PNG header", label);
        write_status(status);
        return 0;
    }

    uint8_t word[4];
    put_be32(word, zlib_size);
    if (fwrite(word, 1, 4, file) != 4 || fwrite("IDAT", 1, 4, file) != 4) {
        fclose(file);
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not write %s PNG data header", label);
        write_status(status);
        return 0;
    }
    uint32_t crc = crc32_update(UINT32_MAX, (const uint8_t *)"IDAT", 4);
    uint32_t adler = 1;
    const uint8_t zlib_header[2] = {0x78, 0x01};
    if (fwrite(zlib_header, 1, 2, file) != 2) {
        fclose(file);
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not write %s PNG zlib header", label);
        write_status(status);
        return 0;
    }
    crc = crc32_update(crc, zlib_header, 2);

    uint8_t *scanline = (uint8_t *)malloc(scanline_size);
    if (!scanline) {
        fclose(file);
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not allocate %s PNG scanline", label);
        write_status(status);
        return 0;
    }
    scanline[0] = 0;
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width * channels; ++x) {
            uint16_t value = samples[
                ((size_t)y * width * channels) + x];
            scanline[1 + (size_t)x * 2] = (uint8_t)(value >> 8);
            scanline[2 + (size_t)x * 2] = (uint8_t)value;
        }
        uint8_t block_header[5];
        block_header[0] = y + 1 == height ? 1 : 0;
        block_header[1] = (uint8_t)scanline_size;
        block_header[2] = (uint8_t)(scanline_size >> 8);
        uint16_t inverse = (uint16_t)~scanline_size;
        block_header[3] = (uint8_t)inverse;
        block_header[4] = (uint8_t)(inverse >> 8);
        if (fwrite(block_header, 1, sizeof(block_header), file) !=
                sizeof(block_header) ||
            fwrite(scanline, 1, scanline_size, file) != scanline_size) {
            free(scanline);
            fclose(file);
            char status[160];
            snprintf(status, sizeof(status),
                "error: could not write %s PNG scanline", label);
            write_status(status);
            return 0;
        }
        crc = crc32_update(crc, block_header, sizeof(block_header));
        crc = crc32_update(crc, scanline, scanline_size);
        adler = adler32_update(adler, scanline, scanline_size);
    }
    free(scanline);

    put_be32(word, adler);
    if (fwrite(word, 1, 4, file) != 4) {
        fclose(file);
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not finish %s PNG zlib stream", label);
        write_status(status);
        return 0;
    }
    crc = crc32_update(crc, word, 4) ^ UINT32_MAX;
    put_be32(word, crc);
    if (fwrite(word, 1, 4, file) != 4 ||
        !write_png_chunk(file, "IEND", NULL, 0)) {
        fclose(file);
        char status[160];
        snprintf(status, sizeof(status),
            "error: could not finish %s PNG", label);
        write_status(status);
        return 0;
    }
    fclose(file);
    return 1;
}

static int write_height_texture(
    const uint16_t *samples, uint32_t width, uint32_t height)
{
    return write_png16(samples, width, height, 1,
        L"native_terrain.png", "height");
}

static uint8_t packed_normal(double value)
{
    long encoded = lround(128.0 - 127.0 * value);
    if (encoded < 0) return 0;
    if (encoded > 255) return 255;
    return (uint8_t)encoded;
}

/* Convert a finite float to IEEE-754 binary16 without depending on compiler
   half-float extensions.  The PNG importer preserves grayscale G16 bits; the
   loader subsequently changes only the platform pixel-format tag to R16F.
   Encoding the binary16 payload here therefore creates a genuine float
   texture while still using Unreal's public runtime image importer. */
static uint16_t float_to_half(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    uint32_t sign = (bits >> 16) & 0x8000U;
    int32_t exponent = (int32_t)((bits >> 23) & 0xFFU) - 127 + 15;
    uint32_t mantissa = bits & 0x7FFFFFU;
    if (exponent <= 0) {
        if (exponent < -10) return (uint16_t)sign;
        mantissa = (mantissa | 0x800000U) >> (1 - exponent);
        return (uint16_t)(sign + ((mantissa + 0x1000U) >> 13));
    }
    if (exponent >= 31) {
        return (uint16_t)(sign | 0x7C00U);
    }
    mantissa += 0x1000U;
    if (mantissa & 0x800000U) {
        mantissa = 0;
        if (++exponent >= 31) return (uint16_t)(sign | 0x7C00U);
    }
    return (uint16_t)(sign | ((uint32_t)exponent << 10) |
        (mantissa >> 13));
}

static double slope_degrees(
    const uint16_t *samples, const SkiEOHeightJob *job,
    uint32_t x, uint32_t y)
{
    uint32_t x0 = x > 0 ? x - 1 : x;
    uint32_t x1 = x + 1 < job->target_width ? x + 1 : x;
    uint32_t y0 = y > 0 ? y - 1 : y;
    uint32_t y1 = y + 1 < job->target_height ? y + 1 : y;
    double dzdx = ((double)samples[(size_t)y * job->target_width + x1] -
            samples[(size_t)y * job->target_width + x0]) *
        job->height_scale_cm / ((x1 - x0) * job->spacing_x);
    double dzdy = ((double)samples[(size_t)y1 * job->target_width + x] -
            samples[(size_t)y0 * job->target_width + x]) *
        job->height_scale_cm / ((y1 - y0) * job->spacing_y);
    return atan(hypot(dzdx, dzdy)) * (180.0 / 3.14159265358979323846);
}

static double smoothstep(double first, double last, double value)
{
    double normalized = (value - first) / (last - first);
    if (normalized <= 0.0) return 0.0;
    if (normalized >= 1.0) return 1.0;
    return normalized * normalized * (3.0 - 2.0 * normalized);
}

/* Rebuild the native data that is derived from a stock map's heightfield.

   TerrainHeightCacheSubsystem creates these textures before a custom map can
   replace the template R16.  Leaving them untouched makes placement tests,
   snow accumulation and cliff morphology continue to describe Sugar Bowl.
   The portable format intentionally does not ship these cooked products: all
   of them are deterministic consequences of elevation and metric spacing.

   PlacementSlopeTex is a full-resolution PF_R16F angle map. The other two
   products use the new world's native coarse grid dimensions. TerrainMorphologyTex.R is a smooth
   steep-rock mask, G is normalized slope, B is reserved, and A stores the
   complement used by conservative snow redistribution.  The redistribution
   coefficients are normalized to a mean of one so replacing the terrain does
   not change total snowfall; faces over 55 degrees receive only a small
   residual while the removed mass is spread over gentler cells. */
static int write_derived_terrain_textures(
    const uint16_t *samples, const SkiEOHeightJob *job)
{
    uint32_t coarse_width = 0, coarse_height = 0;
    const uint8_t *cache = (const uint8_t *)(uintptr_t)job->cache;
    if (!readable_range(cache, 0xFC)) {
        write_status("error: native coarse terrain cache unavailable");
        return 0;
    }
    memcpy(&coarse_width, cache + 0xF4, 4);
    memcpy(&coarse_height, cache + 0xF8, 4);
    if (coarse_width < 2 || coarse_height < 2 ||
        coarse_width > 4096 || coarse_height > 4096) {
        write_status("error: native coarse terrain dimensions changed");
        return 0;
    }
    const size_t full_count =
        (size_t)job->target_width * job->target_height;
    const size_t coarse_count = (size_t)coarse_width * coarse_height;
    uint16_t *placement = (uint16_t *)malloc(full_count * sizeof(uint16_t));
    uint16_t *redistribution =
        (uint16_t *)malloc(coarse_count * sizeof(uint16_t));
    uint16_t *morphology =
        (uint16_t *)calloc(coarse_count * 4, sizeof(uint16_t));
    double *retention = (double *)malloc(coarse_count * sizeof(double));
    if (!placement || !redistribution || !morphology || !retention) {
        free(placement);
        free(redistribution);
        free(morphology);
        free(retention);
        write_status("error: could not allocate derived terrain textures");
        return 0;
    }

    for (uint32_t y = 0; y < job->target_height; ++y) {
        for (uint32_t x = 0; x < job->target_width; ++x) {
            placement[(size_t)y * job->target_width + x] =
                float_to_half((float)slope_degrees(samples, job, x, y));
        }
    }

    double retention_sum = 0.0;
    for (uint32_t y = 0; y < coarse_height; ++y) {
        uint32_t source_y = (uint32_t)lround(
            (double)y * (job->target_height - 1) / (coarse_height - 1));
        for (uint32_t x = 0; x < coarse_width; ++x) {
            uint32_t source_x = (uint32_t)lround(
                (double)x * (job->target_width - 1) / (coarse_width - 1));
            double slope = slope_degrees(
                samples, job, source_x, source_y);
            double cliff = smoothstep(35.0, 55.0, slope);
            double cell_retention = 1.0 - 0.95 * cliff;
            size_t index = (size_t)y * coarse_width + x;
            retention[index] = cell_retention;
            retention_sum += cell_retention;
            morphology[index * 4] =
                (uint16_t)lround(cliff * 65535.0);
            morphology[index * 4 + 1] = (uint16_t)lround(
                fmin(slope / 90.0, 1.0) * 65535.0);
            morphology[index * 4 + 2] = 0;
            morphology[index * 4 + 3] = (uint16_t)lround(
                cell_retention * 65535.0);
        }
    }
    double retention_mean = retention_sum / coarse_count;
    for (size_t index = 0; index < coarse_count; ++index) {
        double coefficient = retention[index] / retention_mean;
        if (coefficient > 3.0) coefficient = 3.0;
        redistribution[index] = float_to_half((float)coefficient);
    }
    free(retention);

    int ok = write_png16(placement,
            job->target_width, job->target_height, 1,
            L"native_placement_slope.png", "placement slope") &&
        write_png16(redistribution,
            coarse_width, coarse_height, 1,
            L"native_snow_redistribution.png", "snow redistribution") &&
        write_png16(morphology,
            coarse_width, coarse_height, 4,
            L"native_terrain_morphology.png", "terrain morphology");
    free(placement);
    free(redistribution);
    free(morphology);
    return ok;
}

static int write_landscape_png(
    const uint16_t *samples, const SkiEOHeightJob *job,
    uint32_t tile, uint32_t mip_level)
{
    const uint32_t side = 512U >> mip_level;
    const uint32_t footprint = 1U << mip_level;
    /* Landscape heightmaps are BGRA8 resources in the game.  R/G encode the
       high/low height bytes and B/A encode the packed XY normal.  Importing a
       16-bit-per-channel PNG creates PF_FloatRGBA instead; although mip 0 can
       be sampled, the Landscape vertex factory then reads component borders
       and derived mips incorrectly, producing the repeated edge stripes seen
       on distant chunks.  Emit the exact native four-byte texel instead. */
    const uint32_t scanline_size = 1 + side * 4;
    const uint32_t zlib_size = 2 + side * (5 + scanline_size) + 4;
    wchar_t name[64], path[MAX_PATH];
    if (mip_level == 0) {
        swprintf(name, 64, L"native_landscape_%02u.png", tile);
    } else {
        swprintf(name, 64, L"native_landscape_%02u_mip%02u.png",
            tile, mip_level);
    }
    if (!sibling_path(path, MAX_PATH, name)) {
        write_status("error: could not resolve Landscape texture path");
        return 0;
    }
    FILE *file = _wfopen(path, L"wb");
    if (!file) {
        write_status("error: could not create Landscape texture");
        return 0;
    }

    static const uint8_t signature[8] = {
        0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A,
    };
    uint8_t ihdr[13] = {0};
    put_be32(ihdr, side);
    put_be32(ihdr + 4, side);
    ihdr[8] = 8;
    ihdr[9] = 6;
    uint8_t gamma[4];
    put_be32(gamma, 100000U); /* gAMA 1.0: packed data, never sRGB colour */
    if (fwrite(signature, 1, sizeof(signature), file) != sizeof(signature) ||
        !write_png_chunk(file, "IHDR", ihdr, sizeof(ihdr)) ||
        !write_png_chunk(file, "gAMA", gamma, sizeof(gamma))) {
        fclose(file);
        write_status("error: could not write Landscape PNG header");
        return 0;
    }

    uint8_t word[4];
    put_be32(word, zlib_size);
    if (fwrite(word, 1, 4, file) != 4 || fwrite("IDAT", 1, 4, file) != 4) {
        fclose(file);
        write_status("error: could not write Landscape PNG data header");
        return 0;
    }
    uint32_t crc = crc32_update(UINT32_MAX, (const uint8_t *)"IDAT", 4);
    uint32_t adler = 1;
    const uint8_t zlib_header[2] = {0x78, 0x01};
    if (fwrite(zlib_header, 1, 2, file) != 2) {
        fclose(file);
        write_status("error: could not write Landscape PNG zlib header");
        return 0;
    }
    crc = crc32_update(crc, zlib_header, 2);

    uint8_t *scanline = (uint8_t *)malloc(scanline_size);
    if (!scanline) {
        fclose(file);
        write_status("error: could not allocate Landscape PNG scanline");
        return 0;
    }
    uint32_t tile_x = tile % 4;
    uint32_t tile_y = tile / 4;
    scanline[0] = 0;
    for (uint32_t py = 0; py < side; ++py) {
        for (uint32_t px = 0; px < side; ++px) {
            uint64_t height_sum = 0;
            double normal_x_sum = 0.0;
            double normal_y_sum = 0.0;
            double normal_z_sum = 0.0;
            for (uint32_t local_y = 0; local_y < footprint; ++local_y) {
                uint32_t atlas_y = py * footprint + local_y;
                uint32_t source_y = tile_y * 504 +
                    atlas_y - atlas_y / 64;
                uint32_t y0 = source_y > 0 ? source_y - 1 : source_y;
                uint32_t y1 = source_y + 1 < job->target_height
                    ? source_y + 1 : source_y;
                for (uint32_t local_x = 0; local_x < footprint; ++local_x) {
                    uint32_t atlas_x = px * footprint + local_x;
                    uint32_t source_x = tile_x * 504 +
                        atlas_x - atlas_x / 64;
                    uint32_t x0 = source_x > 0 ? source_x - 1 : source_x;
                    uint32_t x1 = source_x + 1 < job->target_width
                        ? source_x + 1 : source_x;
                    uint16_t sample = samples[
                        (size_t)source_y * job->target_width + source_x];
                    height_sum += sample;
                    double dzdx = ((double)samples[
                            (size_t)source_y * job->target_width + x1] -
                            samples[(size_t)source_y * job->target_width + x0]) *
                        job->height_scale_cm /
                        ((x1 - x0) * job->spacing_x);
                    double dzdy = ((double)samples[
                            (size_t)y1 * job->target_width + source_x] -
                            samples[(size_t)y0 * job->target_width + source_x]) *
                        job->height_scale_cm /
                        ((y1 - y0) * job->spacing_y);
                    double length = sqrt(dzdx * dzdx + dzdy * dzdy + 1.0);
                    normal_x_sum += dzdx / length;
                    normal_y_sum += dzdy / length;
                    normal_z_sum += 1.0 / length;
                }
            }
            uint64_t footprint_count = (uint64_t)footprint * footprint;
            uint16_t height = (uint16_t)(
                (height_sum + footprint_count / 2) / footprint_count);
            double normal_length = sqrt(
                normal_x_sum * normal_x_sum +
                normal_y_sum * normal_y_sum +
                normal_z_sum * normal_z_sum);
            uint8_t channels[4] = {
                (uint8_t)(height >> 8),
                (uint8_t)height,
                packed_normal(normal_x_sum / normal_length),
                packed_normal(normal_y_sum / normal_length),
            };
            memcpy(scanline + 1 + (size_t)px * 4, channels, 4);
        }

        uint8_t block_header[5];
        block_header[0] = py + 1 == side ? 1 : 0;
        block_header[1] = (uint8_t)scanline_size;
        block_header[2] = (uint8_t)(scanline_size >> 8);
        uint16_t inverse = (uint16_t)~scanline_size;
        block_header[3] = (uint8_t)inverse;
        block_header[4] = (uint8_t)(inverse >> 8);
        if (fwrite(block_header, 1, sizeof(block_header), file) !=
                sizeof(block_header) ||
            fwrite(scanline, 1, scanline_size, file) != scanline_size) {
            free(scanline);
            fclose(file);
            write_status("error: could not write Landscape PNG scanline");
            return 0;
        }
        crc = crc32_update(crc, block_header, sizeof(block_header));
        crc = crc32_update(crc, scanline, scanline_size);
        adler = adler32_update(adler, scanline, scanline_size);
    }
    free(scanline);

    put_be32(word, adler);
    if (fwrite(word, 1, 4, file) != 4) {
        fclose(file);
        write_status("error: could not finish Landscape PNG zlib stream");
        return 0;
    }
    crc = crc32_update(crc, word, 4) ^ UINT32_MAX;
    put_be32(word, crc);
    if (fwrite(word, 1, 4, file) != 4 ||
        !write_png_chunk(file, "IEND", NULL, 0)) {
        fclose(file);
        write_status("error: could not finish Landscape PNG");
        return 0;
    }
    fclose(file);
    return 1;
}

static int write_landscape_textures(
    const uint16_t *samples, const SkiEOHeightJob *job)
{
    /* The supported stock Landscape is 32x32 components of 63 quads. Each
       512 texture contains an 8x8 component atlas with duplicated borders. */
    if (job->target_width != 2017 || job->target_height != 2017 ||
        job->spacing_cm <= 0.0 || job->height_scale_cm <= 0.0) {
        write_status("error: template Landscape topology is not 2017x2017");
        return 0;
    }

    for (uint32_t tile = 0; tile < 16; ++tile) {
        for (uint32_t mip_level = 0; mip_level < 10; ++mip_level) {
            if (!write_landscape_png(samples, job, tile, mip_level)) return 0;
        }
    }
    return 1;
}

static int write_landscape_bounds(
    const uint16_t *samples, const SkiEOHeightJob *job)
{
    if (job->target_width != 2017 || job->target_height != 2017) {
        write_status("error: template Landscape topology is not 2017x2017");
        return 0;
    }
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_landscape.bounds")) {
        write_status("error: could not resolve Landscape bounds path");
        return 0;
    }
    FILE *file = _wfopen(path, L"wb");
    if (!file) {
        write_status("error: could not create Landscape bounds");
        return 0;
    }
    uint8_t record[4];
    for (uint32_t component_y = 0; component_y < 32; ++component_y) {
        for (uint32_t component_x = 0; component_x < 32; ++component_x) {
            uint16_t minimum = UINT16_MAX;
            uint16_t maximum = 0;
            const uint32_t first_x = component_x * 63;
            const uint32_t first_y = component_y * 63;
            for (uint32_t local_y = 0; local_y < 64; ++local_y) {
                for (uint32_t local_x = 0; local_x < 64; ++local_x) {
                    uint16_t value = samples[
                        (size_t)(first_y + local_y) * job->target_width +
                        first_x + local_x];
                    if (value < minimum) minimum = value;
                    if (value > maximum) maximum = value;
                }
            }
            put_u16(record, minimum);
            put_u16(record + 2, maximum);
            if (fwrite(record, 1, sizeof(record), file) != sizeof(record)) {
                fclose(file);
                write_status("error: could not write Landscape bounds");
                return 0;
            }
        }
    }
    fclose(file);
    return 1;
}

__declspec(dllexport) int skieo_copy_heightmap(void *lua_state)
{
    (void)lua_state;
    wchar_t config_path[MAX_PATH], source_path[MAX_PATH];
    if (!sibling_path(config_path, MAX_PATH, L"native_terrain.job") ||
        !sibling_path(source_path, MAX_PATH, L"native_terrain.r16")) {
        write_status("error: could not resolve helper directory");
        return 0;
    }

    FILE *config = _wfopen(config_path, L"rb");
    if (!config) {
        write_status("error: could not open native_terrain.job");
        return 0;
    }
    SkiEOHeightJob job;
    size_t config_read = fread(&job, 1, sizeof(job), config);
    if (config_read != sizeof(job) || memcmp(job.magic, "SKNT", 4) != 0 ||
        (job.version < 3 || job.version > 6) ||
        ((job.version == 3 || job.version == 5) && (job.destination == 0 || job.cache == 0)) ||
        ((job.version == 4 || job.version == 6) && (job.destination != 0 || job.cache != 0)) ||
        job.source_width < 2 || job.source_height < 2 ||
        job.target_width < 2 || job.target_height < 2 ||
        job.source_width > 16384 || job.source_height > 16384 ||
        job.target_width > 16384 || job.target_height > 16384) {
        fclose(config);
        write_status("error: invalid native terrain job");
        return 0;
    }

    SkiEOSurface surface={0};
    uint8_t *refined=NULL;
    surface.width=job.source_width;surface.height=job.source_height;surface.flags=job.flags;
    int topology_valid=1;
    if (job.version>=5) {
        uint32_t topology[4]={0};
        topology_valid=fread(topology,sizeof(uint32_t),4,config)==4;
        surface.step=topology[0];surface.fine=topology[1];
        if (!surface.step || surface.step>64 || surface.fine!=(surface.step+3)/4 ||
            topology[2]>16384 || topology[3] || (job.flags&~3U)) topology_valid=0;
        if (topology_valid) {
            surface.columns=(surface.width-2)/surface.step+1;
            surface.rows=(surface.height-2)/surface.step+1;
            size_t cells=(size_t)surface.columns*surface.rows;
            refined=calloc((cells+7)/8,1);
            if (!refined) topology_valid=0;
            for (uint32_t i=0;topology_valid && i<topology[2];i++) {
                uint32_t key=0;
                if (fread(&key,4,1,config)!=1 || !key || key>cells) {topology_valid=0;break;}
                --key;
                if (refined[key/8]&(1U<<(key%8))) {topology_valid=0;break;}
                refined[key/8]|=(uint8_t)(1U<<(key%8));
            }
            surface.refined=refined;
        }
    }
    if (fgetc(config)!=EOF) topology_valid=0;
    fclose(config);
    if (!topology_valid) {
        free(refined);write_status("error: invalid terrain surface topology");return 0;
    }

    uint8_t *cache = (uint8_t *)(uintptr_t)job.cache;
    uint64_t cache_samples = 0;
    uint32_t cache_width = 0, cache_height = 0;
    if (cache) {
        memcpy(&cache_samples, cache + 0x48, sizeof(cache_samples));
        memcpy(&cache_width, cache + 0x80, sizeof(cache_width));
        memcpy(&cache_height, cache + 0x84, sizeof(cache_height));
    }
    if (cache && (cache_samples != job.destination || cache_width != job.target_width ||
        cache_height != job.target_height)) {
        free(refined);
        write_status("error: native terrain cache layout changed");
        return 0;
    }

    size_t source_count = (size_t)job.source_width * job.source_height;
    size_t target_count = (size_t)job.target_width * job.target_height;
    if (source_count > SIZE_MAX / 2 || target_count > SIZE_MAX / 2) {
        free(refined);
        write_status("error: native terrain dimensions overflow");
        return 0;
    }
    FILE *source_file = _wfopen(source_path, L"rb");
    if (!source_file) {
        free(refined);
        write_status("error: could not open native_terrain.r16");
        return 0;
    }
    uint8_t *source = (uint8_t *)malloc(source_count * 2);
    if (!source) {
        free(refined);
        fclose(source_file);
        write_status("error: could not allocate source heightmap");
        return 0;
    }
    size_t source_read = fread(source, 2, source_count, source_file);
    int trailing = fgetc(source_file);
    fclose(source_file);
    if (source_read != source_count || trailing != EOF) {
        free(refined);
        free(source);
        write_status("error: source heightmap size mismatch");
        return 0;
    }

    /* Before travel there is no world/cache yet. Stage the same source data
       into temporary storage; Unreal will initialize its caches from the
       resulting textures and freshly constructed Landscape. */
    uint16_t *target = (uint16_t *)malloc(target_count * 2);
    if (!target) {
        free(refined);
        free(source);
        write_status("error: could not allocate staging heightmap");
        return 0;
    }
    surface.bytes=source;
    if (!surface.step && job.source_width == job.target_width &&
        job.source_height == job.target_height &&
        (job.flags & (SKIEO_LITTLE_ENDIAN | SKIEO_SOUTH_TO_NORTH)) ==
            SKIEO_LITTLE_ENDIAN) {
        memcpy(target, source, target_count * 2);
    } else {
        for (uint32_t y = 0; y < job.target_height; ++y) {
            double sy = (double)y * (job.source_height - 1) /
                (job.target_height - 1);
            for (uint32_t x = 0; x < job.target_width; ++x) {
                double sx = (double)x * (job.source_width - 1) /
                    (job.target_width - 1);
                double value=skieo_surface_sample(&surface,sx,sy);
                if (!isfinite(value) || value<-.000001 || value>65535.000001) {
                    free(target);free(source);free(refined);
                    write_status("error: invalid terrain surface sample");return 0;
                }
                target[(size_t)y * job.target_width + x] =
                    (uint16_t)floor(fmax(0,fmin(65535,value)) + 0.5);
            }
        }
    }
    free(source);
    free(refined);
    int generated = write_height_texture(target, job.target_width, job.target_height) &&
        (!cache || write_derived_terrain_textures(target, &job)) &&
        write_landscape_bounds(target, &job) && write_landscape_textures(target, &job);
    if (generated && cache) {
        memcpy((void *)(uintptr_t)job.destination,target,target_count*2);
        write_cache_header(&job);
    }
    free(target);
    if (!generated) return 0;

    char status[256];
    snprintf(status, sizeof(status),
        "ok: copied %llu samples (%ux%u -> %ux%u), bounds %.1f,%.1f to %.1f,%.1f",
        (unsigned long long)target_count, job.source_width, job.source_height,
        job.target_width, job.target_height, job.origin_x, job.origin_y,
        job.maximum_x, job.maximum_y);
    write_status(status);
    return 0;
}

static int readable_range(const void *address, size_t size)
{
    MEMORY_BASIC_INFORMATION memory;
    if (!address || !size ||
        !VirtualQuery(address, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) {
        return 0;
    }
    uintptr_t first = (uintptr_t)address;
    uintptr_t last = first + size;
    uintptr_t region_last = (uintptr_t)memory.BaseAddress + memory.RegionSize;
    return last >= first && last <= region_last;
}

static int texture_mips(
    uint64_t texture_address, uintptr_t **mips,
    int32_t *count, int32_t *capacity, uint8_t *pixel_format,
    uint32_t *size_x_out, uint32_t *size_y_out,
    uint8_t **platform_out)
{
    uint8_t *texture = (uint8_t *)(uintptr_t)texture_address;
    if (!readable_range(texture, 0x168)) return 0;
    uintptr_t platform_address = 0;
    memcpy(&platform_address, texture + 0x158, sizeof(platform_address));
    uint8_t *platform = (uint8_t *)platform_address;
    if (!readable_range(platform, 0x38)) return 0;
    uint32_t size_x = 0, size_y = 0;
    memcpy(&size_x, platform, sizeof(size_x));
    memcpy(&size_y, platform + 4, sizeof(size_y));
    /* EPixelFormat is stored as TEnumAsByte here. The following three bytes
       are unrelated cooked/transient platform flags and must not take part
       in the format comparison. */
    memcpy(pixel_format, platform + 0x0C, sizeof(*pixel_format));
    uintptr_t array_address = 0;
    memcpy(&array_address, platform + 0x18, sizeof(array_address));
    memcpy(count, platform + 0x20, sizeof(*count));
    memcpy(capacity, platform + 0x24, sizeof(*capacity));
    if (size_x == 0 || size_y == 0 || *count < 0 || *capacity < 1 ||
        *capacity < *count || *capacity > 64 ||
        !readable_range((void *)array_address,
            (size_t)*capacity * sizeof(uintptr_t))) {
        return 0;
    }
    if (size_x_out) *size_x_out = size_x;
    if (size_y_out) *size_y_out = size_y;
    if (platform_out) *platform_out = platform;
    *mips = (uintptr_t *)array_address;
    return 1;
}

static int mip_dimensions(uintptr_t mip, uint16_t expected)
{
    if (!readable_range((void *)mip, 0x50)) return 0;
    uint16_t size_x = 0, size_y = 0;
    memcpy(&size_x, (uint8_t *)mip + 0x48, sizeof(size_x));
    memcpy(&size_y, (uint8_t *)mip + 0x4A, sizeof(size_y));
    return size_x == expected && size_y == expected;
}

static int game_vtable(uintptr_t table, uintptr_t module)
{
    MEMORY_BASIC_INFORMATION region;
    if (!readable_range((void *)table, 3 * sizeof(uintptr_t)) ||
        !VirtualQuery((void *)table, &region, sizeof(region)) ||
        region.Type != MEM_IMAGE || (uintptr_t)region.AllocationBase != module) return 0;
    for (unsigned index = 0; index < 3; ++index) {
        uintptr_t function;
        memcpy(&function, (void *)(table + index * 8), sizeof(function));
        if (!VirtualQuery((void *)function, &region, sizeof(region)) ||
            region.Type != MEM_IMAGE || (uintptr_t)region.AllocationBase != module ||
            !(region.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ |
                PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))) return 0;
    }
    return 1;
}

static int render_mapping_matches(
    uintptr_t candidate, uintptr_t scene, uintptr_t module,
    const SkiEORenderMappingJob *job)
{
    uint8_t data[0xE0];
    SIZE_T copied = 0;
    /* Older allocations may end at 0xB8 or 0xC0. Read only their prefix if
       the larger snapshot crosses the committed region; never relax ownership. */
    size_t size = readable_range((void *)candidate, sizeof(data))
        ? sizeof(data) : readable_range((void *)candidate, 0xC0) ? 0xC0 : 0xB8;
    if (!ReadProcessMemory(GetCurrentProcess(), (void *)candidate,
            data, size, &copied) || copied != size) return 0;
    uintptr_t table;
    memcpy(&table, data, 8);
    const uint64_t textures[7] = {job->height_texture, job->previous_height_texture,
        job->previous_snow_height_texture, job->wind_texture, job->canopy_texture,
        job->morphology_texture, job->slope_texture};
    return skieo_render_mapping_matches_snapshot(data, size, scene, textures)
        && game_vtable(table, module);
}

/* The terrain view extension snapshots the source height texture and XY/Z
   normalization during level initialization. Changing subsystem UPROPERTYs
   does not refresh this native snapshot. Walk the current world's FScene and
   its immediate native containers, requiring the scene owner, all four cache
   texture identities, height texture and a game vtable to match. No code RVA
   is assumed: Steam updates can move the vtable without changing the layout.
   ReadProcessMemory snapshots tolerate concurrently released graph nodes.
   No Unreal container allocation or ownership is changed. */
__declspec(dllexport) int skieo_update_render_mapping(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_render.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) return 0;
    SkiEORenderMappingJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    const char *error = NULL;
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKTR", 4) || job.version != 2 ||
        !readable_range((void *)(uintptr_t)job.height_texture, 0x168) ||
        !job.previous_height_texture || !job.previous_snow_height_texture || !job.wind_texture ||
        !job.canopy_texture || !job.morphology_texture ||
        !job.slope_texture || job.bounds[0] >= job.bounds[2] ||
        job.bounds[1] >= job.bounds[3] || job.bounds[4] >= job.bounds[5]) {
        error = "error: invalid terrain render mapping job";
    }
    for (unsigned i = 0; !error && i < 6; ++i) {
        if (!isfinite(job.bounds[i])) error = "error: nonfinite terrain bounds";
    }
    uintptr_t module = (uintptr_t)GetModuleHandleW(L"skieogame.exe");
    if (!module) error = "error: game module is unavailable";
    struct Node { uintptr_t address; uint32_t size, depth; };
    enum { MAX_NODES = 4096, MAX_SETTINGS = 16, SCENE_SIZE = 0x5000 };
    struct Node *nodes = calloc(MAX_NODES, sizeof(*nodes));
    uintptr_t settings[MAX_SETTINGS] = {0};
    unsigned node_count = 0, settings_count = 0;
    if (!nodes) error = "error: could not allocate bounded render mapping scan";
    uintptr_t scene = 0;
    SIZE_T copied = 0;
    if (!error && (!readable_range((void *)(uintptr_t)job.world, 0x258) ||
        !ReadProcessMemory(GetCurrentProcess(),
            (uint8_t *)(uintptr_t)job.world + 0x250,
            &scene, sizeof(scene), &copied) || copied != sizeof(scene) ||
        !readable_range((void *)scene, SCENE_SIZE))) {
        error = "error: native world scene layout changed";
    }
    if (!error) {
        nodes[node_count++] = (struct Node){scene, SCENE_SIZE, 0};
    }
    uint8_t snapshot[SCENE_SIZE];
    /* The first pass covers direct scene containers. A reload can put the
       view-extension array behind another native owner; inspect that second
       level only if the first pass found no validated settings. */
    unsigned direct_count = 0;
    for (unsigned index = 0; !error && index < node_count; ++index) {
        struct Node node = nodes[index];
        if (node.depth == 2 && settings_count) break;
        if (node.depth == 1) ++direct_count;
        if (!ReadProcessMemory(GetCurrentProcess(), (void *)node.address,
                snapshot, node.size, &copied) || copied != node.size) continue;
        for (unsigned offset = 0; offset + 8 <= node.size; offset += 8) {
            uintptr_t value;
            memcpy(&value, snapshot + offset, sizeof(value));
            if (value >= 0x100000 && render_mapping_matches(
                    value, scene, module, &job)) {
                uintptr_t candidate = value;
                unsigned previous = 0;
                for (; previous < settings_count; ++previous) {
                    if (settings[previous] == candidate) break;
                }
                if (previous == settings_count) {
                    if (settings_count == MAX_SETTINGS) {
                        error = "error: terrain render mapping count changed";
                        break;
                    }
                    settings[settings_count++] = candidate;
                }
            }
            if (node.depth >= 2 || node_count == MAX_NODES || value < 0x100000) continue;
            MEMORY_BASIC_INFORMATION region;
            if (!VirtualQuery((void *)value, &region, sizeof(region)) ||
                region.Type != MEM_PRIVATE || region.State != MEM_COMMIT ||
                (region.Protect & (PAGE_NOACCESS | PAGE_GUARD))) continue;
            /* Small native allocations near a committed region's end are
               still valid containers. Do not reject them for lacking a full
               4 KiB after their address. Never cross the readable region. */
            size_t available = (uintptr_t)region.BaseAddress + region.RegionSize - value;
            uint32_t scan_size = available < 0x1000 ? (uint32_t)available : 0x1000;
            if (scan_size < 8) continue;
            unsigned previous = 0;
            for (; previous < node_count; ++previous) {
                if (nodes[previous].address == value) break;
            }
            if (previous == node_count) {
                nodes[node_count++] = (struct Node){value, scan_size, node.depth + 1};
            }
        }
    }
    if (!error && !settings_count) {
        error = "error: supported terrain renderer settings were not found";
    }
    for (unsigned i = 0; !error && i < settings_count; ++i) {
        MEMORY_BASIC_INFORMATION region;
        if (!render_mapping_matches(settings[i], scene, module, &job) ||
            !VirtualQuery((void *)settings[i], &region, sizeof(region)) ||
            region.Type != MEM_PRIVATE || region.Protect != PAGE_READWRITE) {
            error = "error: terrain renderer settings changed during validation";
        }
    }
    if (!error) {
        for (unsigned i = 0; i < settings_count; ++i) {
            uint8_t *data = (uint8_t *)settings[i];
            memcpy(data + 0x18, job.bounds, sizeof(job.bounds));
            memcpy(data + 0x10, &job.height_texture, sizeof(job.height_texture));
        }
    }
    free(nodes);
    if (!sibling_path(path, MAX_PATH, L"native_render.status")) return 0;
    file = _wfopen(path, L"wb");
    if (file) {
        if (error) fputs(error, file);
        else fprintf(file, "ok: updated %u terrain renderer mapping(s), inspected %u direct containers (%u bounded nodes)",
            settings_count, direct_count, node_count);
        fclose(file);
    }
    return 0;
}

/* The native snow renderer retains UTexture pointers outside UPROPERTYs.
   Keep those UObject identities when replacing derived maps. Both platform
   allocations remain engine-owned, with the imported donor taking the old
   data. Lua refreshes the destination resource and retains both textures. */
__declspec(dllexport) int skieo_swap_texture_data(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_swap.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) return 0;
    SkiEOTextureSwapJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    const char *status = "error: invalid texture data exchange";
    if (read == sizeof(job) && trailing == EOF &&
        memcmp(job.magic, "SKTS", 4) == 0 && job.version == 1 &&
        job.destination != job.source) {
        uintptr_t *mips[2];
        int32_t count[2], capacity[2];
        uint8_t format[2], *platform[2];
        uint32_t width[2], height[2];
        int first = texture_mips(job.destination, &mips[0], &count[0],
            &capacity[0], &format[0], &width[0], &height[0], &platform[0]);
        int second = texture_mips(job.source, &mips[1], &count[1],
            &capacity[1], &format[1], &width[1], &height[1], &platform[1]);
        int compatible_format = first && second &&
            (format[0] == format[1] ||
             (format[0] == 19 && format[1] == 62));
        if (first && second && platform[0] != platform[1] &&
            count[0] == 1 && count[1] == 1 && compatible_format &&
            width[0] == job.width && width[1] == job.width &&
            height[0] == job.height && height[1] == job.height) {
            /* PF_A16B16G16R16 (19) and PF_R16G16B16A16_UNORM (62)
               are the same four UNORM16 channels. The runtime PNG importer
               uses the latter; the game's generated morphology uses 19. */
            platform[1][0x0C] = format[0];
            memcpy((uint8_t *)(uintptr_t)job.destination + 0x158,
                &platform[1], sizeof(uintptr_t));
            memcpy((uint8_t *)(uintptr_t)job.source + 0x158,
                &platform[0], sizeof(uintptr_t));
            status = "ok: texture data exchanged, UObject identities preserved";
        } else {
            status = "error: texture data exchange layout or format changed";
        }
    }
    if (!sibling_path(path, MAX_PATH, L"native_swap.status")) return 0;
    file = _wfopen(path, L"wb");
    if (file) { fputs(status, file); fclose(file); }
    return 0;
}

/* ImportFileAsTexture2D exposes 16-bit grayscale PNGs as PF_G16.  For maps
   whose pixels are already IEEE-754 binary16 payloads, change only the
   validated platform-data tag to PF_R16F before Lua calls UpdateResource.
   The byte width is identical, so Unreal retains ownership of the mip and no
   private allocation is created or freed by the mod. */
__declspec(dllexport) int skieo_reinterpret_texture_format(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_format.job")) {
        write_format_status("error: could not resolve texture format job path");
        return 0;
    }
    FILE *file = _wfopen(path, L"rb");
    if (!file) {
        write_format_status("error: could not open native_format.job");
        return 0;
    }
    SkiEOTextureFormatJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKTF", 4) != 0 || job.version != 1 ||
        job.texture == 0 || job.expected_width == 0 ||
        job.expected_height == 0 || job.source_format != 4 ||
        job.destination_format != 21) {
        write_format_status("error: invalid texture format job");
        return 0;
    }
    for (size_t index = 0; index < sizeof(job.reserved); ++index) {
        if (job.reserved[index] != 0) {
            write_format_status("error: invalid texture format job padding");
            return 0;
        }
    }

    uintptr_t *mips = NULL;
    int32_t count = 0, capacity = 0;
    uint8_t format = 0;
    uint32_t width = 0, height = 0;
    uint8_t *platform = NULL;
    if (!texture_mips(job.texture, &mips, &count, &capacity,
            &format, &width, &height, &platform) || count != 1 ||
        width != job.expected_width || height != job.expected_height ||
        (format != job.source_format && format != job.destination_format)) {
        write_format_status("error: imported float texture layout changed");
        return 0;
    }
    (void)mips;
    (void)capacity;
    if (format == job.source_format) {
        memcpy(platform + 0x0C, &job.destination_format,
            sizeof(job.destination_format));
    }
    char status[192];
    snprintf(status, sizeof(status),
        "ok: texture %016llX reinterpreted as PF_R16F (%ux%u)",
        (unsigned long long)job.texture, width, height);
    write_format_status(status);
    return 0;
}

/* Grow only the imported texture's array with the allocator resolved by
   UE4SS. Cooked textures remain untouched: their streaming providers cache
   mip counts and can still run after Landscape stops referencing them. */
typedef void *(*UnrealRealloc)(void *, size_t, uint32_t);

static UnrealRealloc unreal_realloc(void)
{
    HMODULE ue4ss = GetModuleHandleW(L"UE4SS.dll");
    if (!ue4ss) return NULL;
    FARPROC function = GetProcAddress(ue4ss,
        "?Realloc@FMemory@Unreal@RC@@SAPEAXPEAX_KI@Z");
    void *global = (void *)GetProcAddress(ue4ss,
        "?GMalloc@Unreal@RC@@3PEAPEAVFMalloc@12@EA");
    uintptr_t allocator_global = 0, allocator = 0;
    if (!function || !readable_range(global, sizeof(uintptr_t))) return NULL;
    memcpy(&allocator_global, global, sizeof(uintptr_t));
    if (!readable_range((void *)allocator_global, sizeof(uintptr_t))) return NULL;
    memcpy(&allocator, (void *)allocator_global, sizeof(uintptr_t));
    if (!readable_range((void *)allocator, sizeof(uintptr_t))) return NULL;
    UnrealRealloc reallocate = NULL;
    memcpy(&reallocate, &function, sizeof(reallocate));
    return reallocate;
}

/* ScenarioSubsystem holds an unreflected FScenarioSaveData at +0x98. Native
   autosaves copy that state directly, bypassing GameplayStatics UFunction
   hooks. Verify both native result getters before touching this layout. */
static int scenario_layout_supported(void)
{
    static int result = -1;
    if (result >= 0) return result;
    result = 0;
    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!readable_range(module, sizeof(IMAGE_DOS_HEADER))) return 0;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 0x100000 ||
        !readable_range(module + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64))) return 0;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    IMAGE_SECTION_HEADER *sections = IMAGE_FIRST_SECTION(nt);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        !nt->FileHeader.NumberOfSections || nt->FileHeader.NumberOfSections > 96 ||
        !readable_range(sections, nt->FileHeader.NumberOfSections * sizeof(*sections))) return 0;
    static const uint8_t signature[] = {0x0F,0xB6,0x81,0xA2,0,0,0,0x41,0x88,0,0xC3};
    unsigned completed = 0, failed = 0;
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        if (!(sections[i].Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        size_t start = sections[i].VirtualAddress, size = sections[i].Misc.VirtualSize;
        if (start > image_size || size > image_size - start || size < sizeof(signature) ||
            !readable_range(module + start, size)) continue;
        for (size_t offset = 0; offset <= size - sizeof(signature); ++offset) {
            uint8_t *p = module + start + offset;
            if (*p != signature[0] || p[3] < 0xA2 || p[3] > 0xA3) continue;
            if (!memcmp(p, signature, 3) && !memcmp(p + 4, signature + 4, sizeof(signature) - 4)) {
                if (p[3] == 0xA2) ++completed; else ++failed;
            }
        }
    }
    result = completed == 1 && failed == 1;
    return result;
}

__declspec(dllexport) int skieo_sync_scenario_state(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_scenario.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) { write_status("error: missing scenario state job"); return 0; }
    struct { char magic[4]; uint32_t version; uint64_t owner, owner_class, scenario;
        uint32_t count, outcome; } job;
    uint64_t values[128];
    size_t read = fread(&job, 1, sizeof(job), file);
    if (read != sizeof(job) || memcmp(job.magic, "SKIS", 4) || (job.version != 1 && job.version != 2) ||
        !job.owner || !job.owner_class || (job.version == 1 && !job.scenario) ||
        (!job.scenario && job.outcome) || !job.count || job.count > 128 || job.outcome > 2) {
        fclose(file); write_status("error: invalid scenario state job"); return 0;
    }
    read = fread(values, 8, job.count, file);
    int trailing = fgetc(file); fclose(file);
    uint8_t *owner = (uint8_t *)(uintptr_t)job.owner;
    uint8_t *scenario = (uint8_t *)(uintptr_t)job.scenario;
    uint64_t cls = 0, active = 0, old_data = 0;
    int32_t old_count = 0, capacity = 0;
    if (read != job.count || trailing != EOF || !scenario_layout_supported() ||
        !readable_range(owner, 0xC0) || (job.scenario && !readable_range(scenario, 0x30))) {
        write_status("error: unsupported scenario state layout"); return 0;
    }
    memcpy(&cls, owner + 0x10, 8); memcpy(&active, owner + 0x90, 8);
    memcpy(&old_data, owner + 0xB0, 8); memcpy(&old_count, owner + 0xB8, 4);
    memcpy(&capacity, owner + 0xBC, 4);
    if (cls != job.owner_class || active != job.scenario || old_count < 0 || old_count > capacity ||
        capacity < 0 || capacity > 4096 || (!capacity && old_data) ||
        (capacity && !readable_range((void *)(uintptr_t)old_data, capacity * 8))) {
        write_status("error: invalid scenario state owner or array"); return 0;
    }
    for (uint32_t i = 0; i < job.count; ++i) if (!values[i] || values[i] > UINT32_MAX) {
        write_status("error: invalid scenario state name index"); return 0;
    }
    if (capacity < (int32_t)job.count) {
        UnrealRealloc allocate = unreal_realloc();
        if (!allocate) { write_status("error: Unreal allocator unavailable"); return 0; }
        void *data = allocate((void *)(uintptr_t)old_data, job.count * 8, 0);
        if (!data) { write_status("error: scenario state allocation failed"); return 0; }
        old_data = (uint64_t)(uintptr_t)data; capacity = (int32_t)job.count;
    }
    memcpy((void *)(uintptr_t)old_data, values, job.count * 8);
    int32_t count = (int32_t)job.count;
    memcpy(owner + 0xB0, &old_data, 8); memcpy(owner + 0xB8, &count, 4); memcpy(owner + 0xBC, &capacity, 4);
    /* v2 also stores mapmod checkpoints in a sandbox's existing save data.
       An absent definition is accepted only when ActiveScenario is also null;
       preserve its identity/flags rather than inventing a playable scenario. */
    if (job.scenario) {
        memcpy(owner + 0x98, scenario + 0x28, 8); /* serialized scenario identity */
        owner[0xA0] = 1; owner[0xA1] = 1; /* setup applied, briefing shown */
        owner[0xA2] = job.outcome == 1; owner[0xA3] = job.outcome == 2;
    }
    write_status("ok: script state synchronized with native scenario saves");
    return 0;
}

__declspec(dllexport) int skieo_install_texture_mips(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_mips.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) {
        write_mip_status("error: could not open native_mips.job");
        return 0;
    }
    SkiEOTextureMipJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKTM", 4) != 0 ||
        (job.version != 3 && job.version != 4 && job.version != 5) ||
        job.destination == 0 || (job.version == 3 && job.template_texture == 0) ||
        (job.version == 5 && job.template_texture != 0) ||
        job.sources[0] != job.destination || job.mip_count < 1 || job.mip_count > 10 ||
        (job.version != 5 && job.mip_count != 10) ||
        job.reserved != 0 || job.template_texture == job.destination) {
        write_mip_status("error: invalid texture mip job");
        return 0;
    }

    uintptr_t *destination_mips = NULL;
    int32_t destination_count = 0, destination_capacity = 0;
    uint8_t destination_format = 0;
    uint32_t destination_x = 0, destination_y = 0;
    uint8_t *destination_platform = NULL;
    if (!texture_mips(job.destination, &destination_mips,
            &destination_count, &destination_capacity,
            &destination_format, &destination_x, &destination_y,
            &destination_platform) || destination_format != 2 ||
        destination_x != destination_y || destination_x > 512 ||
        destination_x != (1U << (job.mip_count - 1)) ||
        !mip_dimensions(destination_mips[0], (uint16_t)destination_x)) {
        write_mip_status("error: transient Landscape texture layout changed");
        return 0;
    }

    uintptr_t *template_mips = NULL;
    int32_t template_count = 0, template_capacity = 0;
    uint8_t template_format = 0;
    uint32_t template_x = 0, template_y = 0;
    if (job.template_texture && (!texture_mips(job.template_texture, &template_mips,
            &template_count, &template_capacity, &template_format,
            &template_x, &template_y, NULL) ||
        template_x != 512 || template_y != 512 ||
        template_format != destination_format || template_count != 10)) {
        write_mip_status("error: template Landscape texture layout changed");
        return 0;
    }

    int forward = destination_count == 1;
    int reverse = destination_count == (int32_t)job.mip_count;
    if (!forward && !reverse) {
        write_mip_status("error: unexpected transient Landscape mip count");
        return 0;
    }
    uintptr_t *source_mips[10] = {0};
    uint8_t *source_platforms[10] = {0};
    for (uint32_t mip = 1; mip < job.mip_count; ++mip) {
        int32_t source_count = 0, source_capacity = 0;
        uint8_t source_format = 0;
        uint32_t source_x = 0, source_y = 0;
        if (job.sources[mip] == job.destination ||
            !texture_mips(job.sources[mip], &source_mips[mip],
                &source_count, &source_capacity, &source_format,
                &source_x, &source_y, &source_platforms[mip]) ||
            source_platforms[mip] == destination_platform ||
            job.sources[mip] == job.template_texture ||
            source_count != (forward ? 1 : 0) ||
            source_format != destination_format ||
            source_x != (destination_x >> mip) || source_y != (destination_y >> mip) ||
            !mip_dimensions(source_mips[mip][0], (uint16_t)(destination_x >> mip)) ||
            (reverse && destination_mips[mip] != source_mips[mip][0])) {
            write_mip_status("error: imported texture mip ownership or layout changed");
            return 0;
        }
        for (uint32_t previous = 1; previous < mip; ++previous) {
            if (source_platforms[previous] == source_platforms[mip]) {
                write_mip_status("error: duplicate imported mip owner");
                return 0;
            }
        }
    }

    if (forward) {
        UnrealRealloc reallocate = unreal_realloc();
        if (!reallocate) {
            write_mip_status("error: UE4SS Unreal allocator is unavailable");
            return 0;
        }
        uintptr_t *full_mips = reallocate(destination_mips,
            job.mip_count * sizeof(uintptr_t), 0);
        if (!full_mips) {
            write_mip_status("error: could not allocate Unreal mip array");
            return 0;
        }
        for (uint32_t mip = 1; mip < job.mip_count; ++mip) {
            full_mips[mip] = source_mips[mip][0];
            /* The donor retains its empty array allocation, but no longer
               owns the moved mip. Unreal's destructor cannot double free it. */
            int32_t empty = 0;
            memcpy(source_platforms[mip] + 0x20, &empty, sizeof(empty));
        }
        uintptr_t array = (uintptr_t)full_mips;
        int32_t count = (int32_t)job.mip_count;
        memcpy(destination_platform + 0x18, &array, sizeof(array));
        memcpy(destination_platform + 0x20, &count, sizeof(count));
        memcpy(destination_platform + 0x24, &count, sizeof(count));
    } else {
        /* Roll back before resource recreation. Keep the grown allocation;
           its capacity is independent of the number of owned mip objects. */
        int32_t one = 1;
        for (uint32_t mip = 1; mip < job.mip_count; ++mip) {
            memcpy(source_platforms[mip] + 0x20, &one, sizeof(one));
            destination_mips[mip] = 0;
        }
        memcpy(destination_platform + 0x20, &one, sizeof(one));
    }
    char status[192];
    snprintf(status, sizeof(status),
        "ok: %s %u BGRA8 Landscape mips %016llX; cooked template unchanged",
        forward ? "installed" : "restored", job.mip_count,
        (unsigned long long)job.destination);
    write_mip_status(status);
    return 0;
}

/* Read the native TSet counters without invoking any gameplay code. This is
   also useful as a build-independent lifecycle check: TSet::Num is the number
   of allocated sparse slots minus the free-list size. */
__declspec(dllexport) int skieo_probe_hubs(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_hubs.job")) {
        write_hub_status("error: could not resolve hub helper directory");
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) {
        write_hub_status("error: could not open native_hubs.job");
        return 0;
    }
    SkiEOHubJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKNH", 4) != 0 || job.version != 1 ||
        job.subsystem == 0) {
        write_hub_status("error: invalid native hub job");
        return 0;
    }

    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module) {
        write_hub_status("error: game module is unavailable");
        return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        write_hub_status("error: invalid game module header");
        return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        write_hub_status("error: unsupported game module header");
        return 0;
    }

    uint8_t *subsystem = (uint8_t *)(uintptr_t)job.subsystem;
    MEMORY_BASIC_INFORMATION memory;
    if (!VirtualQuery(subsystem, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
        (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize - subsystem)
            < 0xF0) {
        write_hub_status("error: invalid hub subsystem address");
        return 0;
    }
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    uintptr_t vtable = *(uintptr_t *)subsystem;
    uintptr_t image_first = (uintptr_t)module;
    uintptr_t image_last = image_first + image_size;
    if (vtable < image_first || vtable >= image_last) {
        write_hub_status("error: hub subsystem vtable is outside the game module");
        return 0;
    }

    uint32_t member_slots = 0, member_capacity = 0, member_free = 0;
    uint32_t clusters = 0, cluster_capacity = 0;
    uint32_t sources = 0, source_capacity = 0;
    memcpy(&member_slots, subsystem + 0x80, sizeof(member_slots));
    memcpy(&member_capacity, subsystem + 0x84, sizeof(member_capacity));
    memcpy(&member_free, subsystem + 0xAC, sizeof(member_free));
    memcpy(&clusters, subsystem + 0xD0, sizeof(clusters));
    memcpy(&cluster_capacity, subsystem + 0xD4, sizeof(cluster_capacity));
    memcpy(&sources, subsystem + 0xE8, sizeof(sources));
    memcpy(&source_capacity, subsystem + 0xEC, sizeof(source_capacity));
    if (member_slots > member_capacity || member_free > member_slots) {
        write_hub_status("error: invalid hub container counters");
        return 0;
    }
    char status[320];
    snprintf(status, sizeof(status),
        "ok: hub state; member slots %u/%u, free %u, live %u, clusters %u/%u, sources %u/%u",
        member_slots, member_capacity, member_free, member_slots - member_free,
        clusters, cluster_capacity, sources, source_capacity);
    write_hub_status(status);
    return 0;
}

/* Exercise only the terrain-coverage calculation used by the first hub
   rebuild phase. Keeping the sparse set untouched makes this a safe way to
   identify a malformed compound member before attempting graph restoration.
   The scratch TArray is deliberately reused across members; this diagnostic
   runs once during development and leaves at most one small UE allocation. */
__declspec(dllexport) int skieo_probe_hub_coverage(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_hubs.job")) {
        write_hub_status("error: could not resolve hub helper directory");
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) {
        write_hub_status("error: could not open native_hubs.job");
        return 0;
    }
    SkiEOHubJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKNH", 4) != 0 || job.version != 1 ||
        job.subsystem == 0) {
        write_hub_status("error: invalid native hub job");
        return 0;
    }

    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module) {
        write_hub_status("error: game module is unavailable");
        return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        write_hub_status("error: invalid game module header");
        return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    enum {
        HUB_COVERAGE_RVA = 0x05001BD0,
        HUB_ELEMENT_SIZE = 0xA0,
        HUB_INFO_OFFSET = 0x10,
    };
    static const uint8_t coverage_signature[] = {
        0x40, 0x55, 0x53, 0x56, 0x57, 0x41, 0x55, 0x41,
        0x57, 0x48, 0x8D, 0x6C, 0x24, 0xD1,
    };
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt->OptionalHeader.SizeOfImage <
            HUB_COVERAGE_RVA + sizeof(coverage_signature) ||
        memcmp(module + HUB_COVERAGE_RVA, coverage_signature,
            sizeof(coverage_signature)) != 0) {
        write_hub_status("error: unsupported Ski-E-O executable build");
        return 0;
    }

    uint8_t *subsystem = (uint8_t *)(uintptr_t)job.subsystem;
    uint8_t *elements = NULL;
    uint32_t member_slots = 0, member_capacity = 0;
    memcpy(&elements, subsystem + 0x78, sizeof(elements));
    memcpy(&member_slots, subsystem + 0x80, sizeof(member_slots));
    memcpy(&member_capacity, subsystem + 0x84, sizeof(member_capacity));
    if (!elements || !member_slots || member_slots > member_capacity ||
        member_slots > 4096) {
        write_hub_status("error: invalid hub member storage");
        return 0;
    }

    typedef void (*SkiEOCoverage)(void *, const void *, void *);
    SkiEOCoverage coverage =
        (SkiEOCoverage)(module + HUB_COVERAGE_RVA);
    struct {
        uint16_t *data;
        int32_t count;
        int32_t capacity;
    } scratch = {0};
    uint32_t maximum_count = 0;
    char status[320];
    for (uint32_t index = 0; index < member_slots; ++index) {
        uint8_t *info = elements + (size_t)index * HUB_ELEMENT_SIZE
            + HUB_INFO_OFFSET;
        snprintf(status, sizeof(status),
            "running: hub coverage member %u/%u type %u; previous cells %d/%d",
            index + 1, member_slots, (unsigned)info[0x10],
            scratch.count, scratch.capacity);
        write_hub_status(status);
        coverage(subsystem, info, &scratch);
        if (scratch.count < 0 || scratch.capacity < scratch.count ||
            scratch.capacity > 65536) {
            write_hub_status("error: invalid hub coverage result");
            return 0;
        }
        if ((uint32_t)scratch.count > maximum_count) {
            maximum_count = (uint32_t)scratch.count;
        }
    }
    snprintf(status, sizeof(status),
        "ok: coverage calculated for %u hub members; maximum %u terrain cells",
        member_slots, maximum_count);
    write_hub_status(status);
    return 0;
}

/* Source maps create placeables after the stock level has completed its load
   transaction. Their FHubMemberInfo values reach the subsystem, but the stock
   preview/finalization transaction unregisters them again before the loader can
   connect trails. UE's sparse-set removal deliberately leaves the POD member
   value intact while overwriting only the duplicated TSet key and sparse/hash
   bookkeeping. Reconstitute that bookkeeping from the validated member IDs,
   then let the subsystem rebuild all derived clusters and compound HubActors. */
__declspec(dllexport) int skieo_restore_hubs(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_hubs.job")) {
        write_hub_status("error: could not resolve hub helper directory");
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) {
        write_hub_status("error: could not open native_hubs.job");
        return 0;
    }
    SkiEOHubJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKNH", 4) != 0 || job.version != 1 ||
        job.subsystem == 0) {
        write_hub_status("error: invalid native hub job");
        return 0;
    }

    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module) {
        write_hub_status("error: game module is unavailable");
        return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        write_hub_status("error: invalid game module header");
        return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        write_hub_status("error: unsupported game module header");
        return 0;
    }

    enum {
        HUB_HASH_RVA = 0x01306E10,
        HUB_REBUILD_RVA = 0x04FFBB10,
        HUB_COVERAGE_PHASE_RVA = 0x04FFED00,
        HUB_CLUSTER_PHASE_RVA = 0x04FFD1E0,
        HUB_SOURCES_PHASE_RVA = 0x04FE4700,
        HUB_ROUTING_PHASE_RVA = 0x04FE5D10,
        HUB_ELEMENT_SIZE = 0xA0,
        HUB_INFO_OFFSET = 0x10,
    };
    static const uint8_t hash_signature[] = {
        0x40, 0x53, 0x55, 0x41, 0x57, 0x48, 0x83, 0xEC,
        0x20, 0x44, 0x8B, 0xD2, 0x4C, 0x8B, 0xF9, 0x83,
    };
    static const uint8_t rebuild_signature[] = {
        0x40, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x83, 0xB9,
        0x38, 0x08, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xF9,
    };
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    if (image_size < HUB_HASH_RVA + sizeof(hash_signature) ||
        image_size < HUB_REBUILD_RVA + sizeof(rebuild_signature) ||
        memcmp(module + HUB_HASH_RVA, hash_signature,
            sizeof(hash_signature)) != 0 ||
        memcmp(module + HUB_REBUILD_RVA, rebuild_signature,
            sizeof(rebuild_signature)) != 0) {
        write_hub_status("error: unsupported Ski-E-O executable build");
        return 0;
    }

    uint8_t *subsystem = (uint8_t *)(uintptr_t)job.subsystem;
    MEMORY_BASIC_INFORMATION memory;
    if (!VirtualQuery(subsystem, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
        (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize - subsystem)
            < 0x83C) {
        write_hub_status("error: invalid hub subsystem address");
        return 0;
    }
    uintptr_t vtable = *(uintptr_t *)subsystem;
    uintptr_t image_first = (uintptr_t)module;
    uintptr_t image_last = image_first + image_size;
    if (vtable < image_first || vtable >= image_last) {
        write_hub_status("error: hub subsystem vtable is outside the game module");
        return 0;
    }

    uint8_t *elements = NULL;
    uint32_t member_slots = 0, member_capacity = 0, member_free = 0;
    memcpy(&elements, subsystem + 0x78, sizeof(elements));
    memcpy(&member_slots, subsystem + 0x80, sizeof(member_slots));
    memcpy(&member_capacity, subsystem + 0x84, sizeof(member_capacity));
    memcpy(&member_free, subsystem + 0xAC, sizeof(member_free));
    if (!elements || member_slots == 0 || member_slots > member_capacity ||
        member_slots > 4096 || member_free != member_slots) {
        write_hub_status(member_free == 0 && member_slots > 0
            ? "ok: native hub members are already active"
            : "error: hub members are not a complete recoverable free set");
        return 0;
    }
    if (!VirtualQuery(elements, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
        (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize - elements)
            < (size_t)member_slots * HUB_ELEMENT_SIZE) {
        write_hub_status("error: invalid hub member storage");
        return 0;
    }

    for (uint32_t index = 0; index < member_slots; ++index) {
        uint8_t *source = elements + (size_t)index * HUB_ELEMENT_SIZE
            + HUB_INFO_OFFSET;
        uint64_t member_id[2], owner_id[2], hub_id[2];
        double location[3];
        float extent;
        memcpy(member_id, source, sizeof(member_id));
        memcpy(location, source + 0x18, sizeof(location));
        memcpy(&extent, source + 0x30, sizeof(extent));
        memcpy(owner_id, source + 0x34, sizeof(owner_id));
        memcpy(hub_id, source + 0x58, sizeof(hub_id));
        if ((!member_id[0] && !member_id[1]) ||
            (!owner_id[0] && !owner_id[1]) ||
            (!hub_id[0] && !hub_id[1]) || source[0x10] > 2 ||
            !isfinite(location[0]) || !isfinite(location[1]) ||
            !isfinite(location[2]) || !isfinite(extent) || extent <= 0.0f) {
            write_hub_status("error: stale hub member validation failed");
            return 0;
        }
    }

    uint8_t *set = subsystem + 0x78;
    uint8_t *allocation_bits = NULL;
    uint8_t *hash_buckets = NULL;
    uint32_t allocation_count = 0, allocation_capacity = 0;
    uint32_t hash_capacity = 0;
    memcpy(&allocation_bits, set + 0x20, sizeof(allocation_bits));
    memcpy(&allocation_count, set + 0x28, sizeof(allocation_count));
    memcpy(&allocation_capacity, set + 0x2C, sizeof(allocation_capacity));
    memcpy(&hash_buckets, set + 0x40, sizeof(hash_buckets));
    memcpy(&hash_capacity, set + 0x48, sizeof(hash_capacity));
    if (allocation_count != member_slots ||
        allocation_capacity < member_slots || allocation_capacity > 65536 ||
        hash_capacity == 0 || hash_capacity > 65536 ||
        (hash_capacity & (hash_capacity - 1)) != 0) {
        write_hub_status("error: invalid hub sparse-set metadata");
        return 0;
    }
    if (!allocation_bits) allocation_bits = set + 0x10;
    if (!hash_buckets) hash_buckets = set + 0x38;
    size_t allocation_bytes =
        ((size_t)allocation_capacity + 31) / 32 * sizeof(uint32_t);
    size_t hash_bytes = (size_t)hash_capacity * sizeof(int32_t);
    if (!VirtualQuery(allocation_bits, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
        (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize
            - allocation_bits) < allocation_bytes ||
        !VirtualQuery(hash_buckets, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
        (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize
            - hash_buckets) < hash_bytes) {
        write_hub_status("error: invalid hub allocation or hash storage");
        return 0;
    }

    typedef uint32_t (*SkiEOHashBytes)(const void *, uint32_t);
    typedef void (*SkiEOHubPhase)(void *);
    SkiEOHashBytes hash_bytes_function =
        (SkiEOHashBytes)(module + HUB_HASH_RVA);
    SkiEOHubPhase coverage_phase =
        (SkiEOHubPhase)(module + HUB_COVERAGE_PHASE_RVA);
    SkiEOHubPhase cluster_phase =
        (SkiEOHubPhase)(module + HUB_CLUSTER_PHASE_RVA);
    SkiEOHubPhase sources_phase =
        (SkiEOHubPhase)(module + HUB_SOURCES_PHASE_RVA);
    SkiEOHubPhase routing_phase =
        (SkiEOHubPhase)(module + HUB_ROUTING_PHASE_RVA);
    memset(allocation_bits, 0, allocation_bytes);
    memset(hash_buckets, 0xFF, hash_bytes);
    for (uint32_t index = 0; index < member_slots; ++index) {
        uint8_t *element = elements + (size_t)index * HUB_ELEMENT_SIZE;
        uint8_t *info = element + HUB_INFO_OFFSET;
        /* FHubMemberInfo owns a TArray<uint16> at +0x70. Removal destroys its
           allocation but leaves the old pointer/capacity bytes in the sparse
           slot. Present it as an empty array so the native rebuild allocates
           fresh terrain-coverage storage instead of touching freed memory. */
        memset(info + 0x70, 0, 0x10);
        memcpy(element, info, 0x10);
        uint32_t hash = hash_bytes_function(info, 0x10);
        uint32_t bucket = hash & (hash_capacity - 1);
        int32_t previous = -1;
        memcpy(&previous, hash_buckets + (size_t)bucket * sizeof(previous),
            sizeof(previous));
        memcpy(element + 0x98, &previous, sizeof(previous));
        memcpy(element + 0x9C, &bucket, sizeof(bucket));
        int32_t element_index = (int32_t)index;
        memcpy(hash_buckets + (size_t)bucket * sizeof(element_index),
            &element_index, sizeof(element_index));
        uint32_t word = index / 32;
        uint32_t bit = UINT32_C(1) << (index & 31);
        uint32_t value = 0;
        memcpy(&value, allocation_bits + (size_t)word * sizeof(value),
            sizeof(value));
        value |= bit;
        memcpy(allocation_bits + (size_t)word * sizeof(value), &value,
            sizeof(value));
    }
    int32_t free_head = -1;
    uint32_t free_count = 0;
    memcpy(set + 0x30, &free_head, sizeof(free_head));
    memcpy(set + 0x34, &free_count, sizeof(free_count));
    write_hub_status("running: restored members; hub coverage phase 1/4");
    coverage_phase(subsystem);
    write_hub_status("running: hub clustering phase 2/4");
    cluster_phase(subsystem);
    write_hub_status("running: hub sources phase 3/4");
    sources_phase(subsystem);
    write_hub_status("running: hub routing phase 4/4");
    routing_phase(subsystem);

    uint32_t slots_after = 0, free_after = 0;
    uint32_t clusters_after = 0, sources_after = 0;
    memcpy(&slots_after, subsystem + 0x80, sizeof(slots_after));
    memcpy(&free_after, subsystem + 0xAC, sizeof(free_after));
    memcpy(&clusters_after, subsystem + 0xD0, sizeof(clusters_after));
    memcpy(&sources_after, subsystem + 0xE8, sizeof(sources_after));
    char status[320];
    snprintf(status, sizeof(status),
        "ok: restored %u hub members; slots %u, free %u, live %u, clusters %u, sources %u",
        member_slots, slots_after, free_after,
        slots_after >= free_after ? slots_after - free_after : 0,
        clusters_after, sources_after);
    write_hub_status(status);
    return 0;
}

/* Register late-created placeables through the same native functions used by
   the Build tool.  FinalizePlacement runs while a source map is still in its
   preview lifecycle and unregisters the generated hub members afterwards;
   replaying these two actor-level registrations once all transforms are final
   preserves every FHubMemberInfo field (IDs, rectangular footprint, owner,
   label and routability) exactly as the game constructs it.

   Rebuilding after every member is needlessly expensive and exposes trails to
   a partially populated graph.  The subsystem's native rebuild hold counter
   batches the registrations, then a single stock rebuild creates compound
   HubActors and routing sources for the complete station. */
__declspec(dllexport) int skieo_register_placeable_hubs(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_hubs.job")) {
        write_hub_status("error: could not resolve hub helper directory");
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) {
        write_hub_status("error: could not open native_hubs.job");
        return 0;
    }
    SkiEOHubRegistrationHeader job;
    size_t read = fread(&job, 1, sizeof(job), file);
    if (read != sizeof(job) || memcmp(job.magic, "SKHR", 4) != 0 ||
        job.version != 1 || job.subsystem == 0 || job.actor_count == 0 ||
        job.actor_count > 4096 || job.reserved != 0) {
        fclose(file);
        write_hub_status("error: invalid native hub registration job");
        return 0;
    }
    SkiEOHubRegistrationActor *actors = (SkiEOHubRegistrationActor *)calloc(
        job.actor_count, sizeof(*actors));
    if (!actors) {
        fclose(file);
        write_hub_status("error: could not allocate hub registration job");
        return 0;
    }
    read = fread(actors, sizeof(*actors), job.actor_count, file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != job.actor_count || trailing != EOF) {
        free(actors);
        write_hub_status("error: incomplete native hub registration job");
        return 0;
    }

    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module) {
        free(actors);
        write_hub_status("error: game module is unavailable");
        return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        free(actors);
        write_hub_status("error: invalid game module header");
        return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        free(actors);
        write_hub_status("error: unsupported game module header");
        return 0;
    }

    /* Entry points inspected on Steam builds 25612747, 25668054, 25744336,
       25766443, 25808900 and 25970577. The batching counter moved from 0x838
       through 0x8A8, 0x948 and 0xA60 to 0xB08 in build 25996759.
       Every profile must match all three independent signatures before any call. */
    uint32_t profiles[][5] = {
        {0x04F75EB0, 0x04F9D390, 0x04FFBB10, 0x838},
        {0x04F76210, 0x04F9D750, 0x04FFBF60, 0x838},
        {0x04F81140, 0x04FAAF20, 0x0502C9A0, 0x838},
        {0x04F81190, 0x04FAB720, 0x0502F060, 0x8A8},
        {0x04F81940, 0x04FAB800, 0x0502FF60, 0x948},
        {0x04FADA50, 0x04FADC10, 0x05045D70, 0xA60},
        {0x04FAEC80, 0x04FAEE40, 0x05048280, 0xB08},
        {0x04FB04B0, 0x04FB0670, 0x05049FA0, 0xB08}, /* build 26019240 */
        {0x04FB00F0, 0x04FB02B0, 0x0504A9A0, 0xB08}, /* build 26040817 */
        {0x04FAFD20, 0x04FAFEE0, 0x0504A990, 0xB10}, /* build 26056171 */
        {0x04FB02F0, 0x04FB04B0, 0x0504B300, 0xB10}, /* build 26071000 */
        {0x04FA35B0, 0x04FCD150, 0x0504E0D0, 0xB60}, /* build 26097896 */
        {0x04FA1870, 0x04FCCFE0, 0x0504E8D0, 0xB60}, /* build 26111862 */
        {0x04FA4A80, 0x04FD02B0, 0x05051830, 0xB50, 1}, /* build 26119568 */
        {0x04FA6490, 0x04FCEF50, 0x05053EF0, 0xB50, 2}, /* build 26141846 */
    };
    uint32_t building_rva = 0, lift_rva = 0, rebuild_rva = 0, hold_offset = 0;
    static const uint8_t building_signature[] = {
        0x48, 0x89, 0x5C, 0x24, 0x20, 0x55, 0x48, 0x8D,
        0x6C, 0x24, 0xA9, 0x48, 0x81, 0xEC, 0xC0, 0x00,
        0x00, 0x00,
    };
    static const uint8_t lift_signature[] = {
        0x40, 0x55, 0x56, 0x57, 0x48, 0x8D, 0xAC, 0x24,
        0x70, 0xFF, 0xFF, 0xFF, 0x48, 0x81, 0xEC, 0x90,
        0x01, 0x00, 0x00, 0x48, 0x8B, 0xF9,
    };
    static const uint8_t expanded_lift_signature[] = {
        0x40, 0x55, 0x56, 0x57, 0x48, 0x8D, 0xAC, 0x24,
        0x50, 0xFF, 0xFF, 0xFF, 0x48, 0x81, 0xEC, 0xB0,
        0x01, 0x00, 0x00, 0x48, 0x8B, 0xF9,
    };
    static const uint8_t revised_lift_signature[] = {
        0x48,0x89,0x5C,0x24,0x18,0x48,0x89,0x7C,0x24,0x20,0x55,
        0x48,0x8D,0xAC,0x24,0x70,0xFF,0xFF,0xFF,0x48,0x81,0xEC,0x90,0x01,0,0,
    };
    static const uint8_t compact_lift_signature[] = {
        0x48,0x89,0x5C,0x24,0x18,0x48,0x89,0x7C,0x24,0x20,0x55,0x48,0x8D,0x6C,0x24,0x90,0x48,0x81,0xEC,0x70,0x01,0x00,0x00,0x48,0x8B,0xD9,
    };
    static const uint8_t routing_lift_signature[] = {
        0x40,0x55,0x53,0x57,0x48,0x8D,0xAC,0x24,0x70,0xFF,0xFF,0xFF,0x48,0x81,0xEC,0x90,0x01,0x00,0x00,
    };
    static const uint8_t rebuild_signature[] = {
        0x40, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x83, 0xB9,
        0x38, 0x08, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xF9,
    };
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    size_t latest = sizeof(profiles)/sizeof(profiles[0])-1;
    profiles[latest][0] = native_layout_rva(SKIEO_LAYOUT_HUBS_BUILDING);
    profiles[latest][1] = native_layout_rva(SKIEO_LAYOUT_HUBS_LIFT);
    profiles[latest][2] = native_layout_rva(SKIEO_LAYOUT_HUBS_REBUILD);
    for (size_t index = 0; index < sizeof(profiles) / sizeof(profiles[0]); ++index) {
        const uint32_t *profile = profiles[index];
        uint8_t expected_building[sizeof(building_signature)];
        memcpy(expected_building, building_signature, sizeof(expected_building));
        if (profile[4] == 1) expected_building[14] = 0xB0;
        uint8_t expected_rebuild[sizeof(rebuild_signature)];
        memcpy(expected_rebuild, rebuild_signature, sizeof(expected_rebuild));
        expected_rebuild[8] = (uint8_t)profile[3];
        expected_rebuild[9] = (uint8_t)(profile[3] >> 8);
        const uint8_t *lift_guard = profile[4] == 2 ? routing_lift_signature
            : profile[4] == 1 ? compact_lift_signature
            : profile[3] == 0xB60 ? revised_lift_signature
            : profile[3] >= 0xA60 ? expanded_lift_signature : lift_signature;
        size_t lift_guard_size = profile[4] == 2 ? sizeof(routing_lift_signature)
            : profile[4] == 1 ? sizeof(compact_lift_signature)
            : profile[3] == 0xB60 ? sizeof(revised_lift_signature) : sizeof(lift_signature);
        if (image_size >= profile[0] + sizeof(building_signature) &&
            image_size >= profile[1] + lift_guard_size &&
            image_size >= profile[2] + sizeof(rebuild_signature) &&
            memcmp(module + profile[0], expected_building, sizeof(expected_building)) == 0 &&
            memcmp(module + profile[1], lift_guard, lift_guard_size) == 0 &&
            memcmp(module + profile[2], expected_rebuild, sizeof(expected_rebuild)) == 0) {
            building_rva = profile[0]; lift_rva = profile[1]; rebuild_rva = profile[2];
            hold_offset = profile[3];
            break;
        }
    }
    if (!rebuild_rva) {
        free(actors);
        write_hub_status("error: unsupported Ski-E-O executable build");
        return 0;
    }

    uint8_t *subsystem = (uint8_t *)(uintptr_t)job.subsystem;
    MEMORY_BASIC_INFORMATION memory;
    if (!VirtualQuery(subsystem, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
        (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize - subsystem)
            < hold_offset + sizeof(int32_t)) {
        free(actors);
        write_hub_status("error: invalid hub subsystem address");
        return 0;
    }
    uintptr_t image_first = (uintptr_t)module;
    uintptr_t image_last = image_first + image_size;
    uintptr_t subsystem_vtable = *(uintptr_t *)subsystem;
    if (subsystem_vtable < image_first || subsystem_vtable >= image_last) {
        free(actors);
        write_hub_status("error: hub subsystem vtable is outside the game module");
        return 0;
    }

    uint32_t lift_count = 0, building_count = 0;
    for (uint32_t index = 0; index < job.actor_count; ++index) {
        uint8_t *actor = (uint8_t *)(uintptr_t)actors[index].actor;
        size_t required = actors[index].kind == 1 ? 0x570 : 0x3D0;
        if (!actor || (actors[index].kind != 1 && actors[index].kind != 2) ||
            actors[index].reserved != 0 ||
            !VirtualQuery(actor, &memory, sizeof(memory)) ||
            memory.State != MEM_COMMIT ||
            (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0 ||
            (size_t)((uint8_t *)memory.BaseAddress + memory.RegionSize - actor)
                < required) {
            free(actors);
            write_hub_status("error: invalid placeable actor address");
            return 0;
        }
        uintptr_t actor_vtable = *(uintptr_t *)actor;
        if (actor_vtable < image_first || actor_vtable >= image_last) {
            free(actors);
            write_hub_status("error: placeable actor vtable is outside the game module");
            return 0;
        }
        if (actors[index].kind == 1) ++lift_count;
        else ++building_count;
    }

    typedef void (*SkiEORegisterPlaceable)(void *);
    typedef void (*SkiEORebuildHubs)(void *);
    SkiEORegisterPlaceable register_building =
        (SkiEORegisterPlaceable)(module + building_rva);
    SkiEORegisterPlaceable register_lift =
        (SkiEORegisterPlaceable)(module + lift_rva);
    SkiEORebuildHubs rebuild =
        (SkiEORebuildHubs)(module + rebuild_rva);

    int32_t hold = 0;
    memcpy(&hold, subsystem + hold_offset, sizeof(hold));
    if (hold < 0 || hold == INT32_MAX) {
        free(actors);
        write_hub_status("error: invalid hub rebuild hold counter");
        return 0;
    }
    int32_t batch_hold = hold + 1;
    memcpy(subsystem + hold_offset, &batch_hold, sizeof(batch_hold));
    write_hub_status("running: registering native placeable hub members");
    for (uint32_t index = 0; index < job.actor_count; ++index) {
        void *actor = (void *)(uintptr_t)actors[index].actor;
        if (actors[index].kind == 1) register_lift(actor);
        else register_building(actor);
    }
    memcpy(subsystem + hold_offset, &hold, sizeof(hold));
    write_hub_status("running: rebuilding complete native hub graph");
    rebuild(subsystem);

    uint32_t member_slots = 0, member_free = 0;
    uint32_t clusters = 0, sources = 0;
    memcpy(&member_slots, subsystem + 0x80, sizeof(member_slots));
    memcpy(&member_free, subsystem + 0xAC, sizeof(member_free));
    memcpy(&clusters, subsystem + 0xD0, sizeof(clusters));
    memcpy(&sources, subsystem + 0xE8, sizeof(sources));
    char status[384];
    snprintf(status, sizeof(status),
        "ok: registered %u lift and %u building hub sources; slots %u, free %u, live %u, clusters %u, sources %u",
        lift_count, building_count, member_slots, member_free,
        member_slots >= member_free ? member_slots - member_free : 0,
        clusters, sources);
    free(actors);
    write_hub_status(status);
    return 0;
}

/* UE 5.8 build 25551097 does not expose UHubConnectivitySubsystem's complete
   rebuild operation as a UFunction. Late source-map placeables populate its
   member set, but the derived clusters are discarded after the registration
   burst. Call the same guarded native wrapper used by the stock lifecycle.

   Both entry-point byte signatures and the UObject vtable range are checked
   before the private function is called. A different executable build fails
   closed instead of jumping through a stale RVA. */
__declspec(dllexport) int skieo_rebuild_hubs(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_hubs.job")) {
        write_hub_status("error: could not resolve hub helper directory");
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) {
        write_hub_status("error: could not open native_hubs.job");
        return 0;
    }
    SkiEOHubJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (read != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKNH", 4) != 0 || job.version != 1 ||
        job.subsystem == 0) {
        write_hub_status("error: invalid native hub job");
        return 0;
    }

    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module) {
        write_hub_status("error: game module is unavailable");
        return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        write_hub_status("error: invalid game module header");
        return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        write_hub_status("error: unsupported game module header");
        return 0;
    }

    /* Rebuild RVA, deferred wrapper RVA, batching-counter offset and the
       wrapper's inspected relative jump displacement. */
    uint32_t profiles[][5] = {
        {0x04FFBB10, 0x04FF46F0, 0x838, 0x7413},
        {0x04FFBF60, 0x04FF4B40, 0x838, 0x7413},
        {0x0502FF60, 0x050284E0, 0x948, 0x7A73},
        {0x05045D70, 0x0503D2C0, 0xA60, 0x8AA3},
        {0x05048280, 0x0503F780, 0xB08, 0x8AF3},
        {0x05049FA0, 0x050414A0, 0xB08, 0x8AF3}, /* build 26019240 */
        {0x0504A9A0, 0x05041AC0, 0xB08, 0x8ED3}, /* build 26040817 */
        {0x0504A990, 0x05041AD0, 0xB10, 0x8EB3}, /* build 26056171 */
        {0x0504B300, 0x05042440, 0xB10, 0x8EB3}, /* build 26071000 */
        {0x0504E0D0, 0x05045510, 0xB60, 0x8BB3}, /* build 26097896 */
        {0x0504E8D0, 0x05045D10, 0xB60, 0x8BB3}, /* build 26111862 */
        {0x05051830, 0x05048D30, 0xB50, 0x8AF3, 1}, /* build 26119568 */
        {0x05053EF0, 0x05049E30, 0xB50, 0xA0B3, 2}, /* build 26141846 */
    };
    uint32_t rebuild_wrapper_rva = 0, hold_offset = 0, member_layout = 0;
    static const uint8_t rebuild_signature[] = {
        0x40, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x83, 0xB9,
        0x38, 0x08, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xF9,
    };
    static const uint8_t wrapper_signature[] = {
        0x83, 0xB9, 0x38, 0x08, 0x00, 0x00, 0x00, 0x0F,
        0x8E, 0x13, 0x74, 0x00, 0x00, 0xC3, 0xCC, 0xCC,
    };
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    size_t latest = sizeof(profiles)/sizeof(profiles[0])-1;
    profiles[latest][0] = native_layout_rva(SKIEO_LAYOUT_HUBS_REBUILD);
    profiles[latest][1] = native_layout_rva(SKIEO_LAYOUT_HUBS_DEFERRED);
    for (size_t index = 0; index < sizeof(profiles) / sizeof(profiles[0]); ++index) {
        const uint32_t *profile = profiles[index];
        uint8_t expected_rebuild[sizeof(rebuild_signature)];
        uint8_t expected_wrapper[sizeof(wrapper_signature)];
        memcpy(expected_rebuild, rebuild_signature, sizeof(expected_rebuild));
        memcpy(expected_wrapper, wrapper_signature, sizeof(expected_wrapper));
        memcpy(expected_rebuild + 8, &profile[2], 4);
        memcpy(expected_wrapper + 2, &profile[2], 4);
        memcpy(expected_wrapper + 9, &profile[3], 4);
        if (image_size >= profile[0] + sizeof(rebuild_signature) &&
            image_size >= profile[1] + sizeof(wrapper_signature) &&
            memcmp(module + profile[0], expected_rebuild, sizeof(expected_rebuild)) == 0 &&
            memcmp(module + profile[1], expected_wrapper, index == latest ? 9 : sizeof(expected_wrapper)) == 0) {
            rebuild_wrapper_rva = profile[1];
            hold_offset = profile[2]; member_layout = profile[4];
            break;
        }
    }
    if (!rebuild_wrapper_rva) {
        write_hub_status("error: unsupported Ski-E-O executable build");
        return 0;
    }

    uint8_t *subsystem = (uint8_t *)(uintptr_t)job.subsystem;
    MEMORY_BASIC_INFORMATION memory;
    if (!VirtualQuery(subsystem, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) {
        write_hub_status("error: invalid hub subsystem address");
        return 0;
    }
    uintptr_t vtable = *(uintptr_t *)subsystem;
    uintptr_t image_first = (uintptr_t)module;
    uintptr_t image_last = image_first + image_size;
    if (vtable < image_first || vtable >= image_last) {
        write_hub_status("error: hub subsystem vtable is outside the game module");
        return 0;
    }

    typedef void (*SkiEORebuildHubs)(void *);
    SkiEORebuildHubs rebuild =
        (SkiEORebuildHubs)(module + rebuild_wrapper_rva);
    /* 26119568 packs coverage beside routability (+0x69), shrinking
       FHubMemberInfo to 0x80 and its sparse-set element to 0x98 bytes.
       Reflected IDs/position/type/routability retain their offsets. */
    /* 26141846 adds a uint16 at +0x80, growing elements back to 0xA0
       without changing the batching counter. Select by the reviewed profile. */
    size_t member_stride = member_layout == 1 ? 0x98 : 0xA0;
    size_t coverage_offset = member_layout ? 0x69 : 0x80;
    uint32_t members_before = 0, members_max_before = 0;
    uint32_t members_free_before = 0;
    uint32_t clusters_before = 0, clusters_max_before = 0;
    uint32_t source_before = 0, source_max_before = 0;
    int32_t rebuild_hold_before = 0;
    memcpy(&members_before, subsystem + 0x80, sizeof(members_before));
    memcpy(&members_max_before, subsystem + 0x84, sizeof(members_max_before));
    memcpy(&members_free_before, subsystem + 0xAC,
        sizeof(members_free_before));
    memcpy(&clusters_before, subsystem + 0xD0, sizeof(clusters_before));
    memcpy(&clusters_max_before, subsystem + 0xD4, sizeof(clusters_max_before));
    memcpy(&source_before, subsystem + 0xE8, sizeof(source_before));
    memcpy(&source_max_before, subsystem + 0xEC, sizeof(source_max_before));
    memcpy(&rebuild_hold_before, subsystem + hold_offset,
        sizeof(rebuild_hold_before));
    uint32_t type_counts[8] = {0};
    uint32_t routable_count = 0, coverage_count = 0;
    uint32_t valid_hub_ids = 0, valid_owner_ids = 0;
    uint32_t valid_locations = 0, xy_overlaps = 0, xyz_overlaps = 0;
    uint32_t same_hub_pairs = 0;
    float minimum_extent = INFINITY, maximum_extent = 0.0f;
    uint8_t *elements = NULL;
    memcpy(&elements, subsystem + 0x78, sizeof(elements));
    if (elements && members_before <= members_max_before &&
        members_before <= 4096) {
        wchar_t dump_path[MAX_PATH];
        FILE *dump = sibling_path(
            dump_path, MAX_PATH, L"native_hubs.dump")
            ? _wfopen(dump_path, L"wb") : NULL;
        for (uint32_t index = 0; index < members_before; ++index) {
            uint8_t *info = elements + (size_t)index * member_stride + 0x10;
            uint8_t type = info[0x10];
            if (type < 8) ++type_counts[type];
            if (info[0x68]) ++routable_count;
            if (info[coverage_offset]) ++coverage_count;
            uint64_t hub_words[2], owner_words[2];
            memcpy(owner_words, info + 0x34, sizeof(owner_words));
            memcpy(hub_words, info + 0x58, sizeof(hub_words));
            if (owner_words[0] || owner_words[1]) ++valid_owner_ids;
            if (hub_words[0] || hub_words[1]) ++valid_hub_ids;
            double location[3];
            float extent;
            memcpy(location, info + 0x18, sizeof(location));
            memcpy(&extent, info + 0x30, sizeof(extent));
            if (isfinite(location[0]) && isfinite(location[1]) &&
                isfinite(location[2]) && isfinite(extent) && extent >= 0.0f) {
                ++valid_locations;
                if (extent < minimum_extent) minimum_extent = extent;
                if (extent > maximum_extent) maximum_extent = extent;
            }
            if (dump) {
                fprintf(dump,
                    "%u,%u,%.3f,%.3f,%.3f,%.3f,%u,%u,%016llx%016llx\n",
                    index, (unsigned)type,
                    location[0], location[1], location[2], extent,
                    (unsigned)info[0x68], (unsigned)info[coverage_offset],
                    (unsigned long long)hub_words[1],
                    (unsigned long long)hub_words[0]);
            }
            for (uint32_t other = 0; other < index; ++other) {
                uint8_t *other_info =
                    elements + (size_t)other * member_stride + 0x10;
                double other_location[3];
                float other_extent;
                memcpy(other_location, other_info + 0x18,
                    sizeof(other_location));
                memcpy(&other_extent, other_info + 0x30,
                    sizeof(other_extent));
                double dx = location[0] - other_location[0];
                double dy = location[1] - other_location[1];
                double dz = location[2] - other_location[2];
                double reach = extent + other_extent;
                if (dx * dx + dy * dy <= reach * reach) ++xy_overlaps;
                if (dx * dx + dy * dy + dz * dz <= reach * reach) {
                    ++xyz_overlaps;
                }
                if (memcmp(info + 0x58, other_info + 0x58, 0x10) == 0) {
                    ++same_hub_pairs;
                }
            }
        }
        if (dump) fclose(dump);
    }
    rebuild(subsystem);
    uint32_t members_after = 0, clusters_after = 0, source_after = 0;
    memcpy(&members_after, subsystem + 0x80, sizeof(members_after));
    memcpy(&clusters_after, subsystem + 0xD0, sizeof(clusters_after));
    memcpy(&source_after, subsystem + 0xE8, sizeof(source_after));
    char status[896];
    snprintf(status, sizeof(status),
        "ok: native hub graph rebuilt; hold=%d, member slots %u/%u, free %u, live %u -> slots %u, clusters %u/%u -> %u, source %u/%u -> %u; types [%u,%u,%u,%u,%u,%u,%u,%u], routable %u, coverage %u, owner IDs %u, hub IDs %u, locations %u, extent %.1f..%.1f, overlaps xy=%u xyz=%u, same-hub pairs=%u",
        rebuild_hold_before,
        members_before, members_max_before, members_free_before,
        members_before >= members_free_before
            ? members_before - members_free_before : 0,
        members_after,
        clusters_before, clusters_max_before, clusters_after,
        source_before, source_max_before, source_after,
        type_counts[0], type_counts[1], type_counts[2], type_counts[3],
        type_counts[4], type_counts[5], type_counts[6], type_counts[7],
        routable_count, coverage_count, valid_owner_ids, valid_hub_ids,
        valid_locations, minimum_extent, maximum_extent,
        xy_overlaps, xyz_overlaps, same_hub_pairs);
    write_hub_status(status);
    return 0;
}

/* The game's Staff.RegenerateHiringPool console delegate resolves its world
   through a gameplay-world lookup, which skips our neutral Entry world. Invoke the
   same native regeneration on the current world's reflected StaffSubsystem.
   Hiring, assignment, wages and serialization still use public UFunctions.
   The entry points and pool layouts below retain the verified older builds.
   Build 25970577 grows FStaffMember again, from 0x4F8 to 0x518 bytes. */
__declspec(dllexport) int skieo_refresh_staff_pool(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH], status_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_staff.job") ||
        !sibling_path(status_path, MAX_PATH, L"native_staff.status")) return 0;
    FILE *status = _wfopen(status_path, L"wb");
    if (!status) return 0;
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) {
        fprintf(status, "error: could not open staff job"); fclose(status); return 0;
    }
    SkiEOStaffJob job;
    size_t count = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    if (count != sizeof(job) || trailing != EOF ||
        memcmp(job.magic, "SKNS", 4) || job.version != 1 || job.reserved ||
        !job.subsystem || !job.settings || job.pool_count > 1024) {
        fprintf(status, "error: invalid staff job"); fclose(status); return 0;
    }
    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module || !readable_range(module, sizeof(IMAGE_DOS_HEADER))) {
        fprintf(status, "error: game module is unavailable"); fclose(status); return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 ||
        !readable_range(module + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64))) {
        fprintf(status, "error: invalid game module"); fclose(status); return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    struct {
        uint32_t rva, settings_offset, pool_offset, element_size, owner_size;
        uint8_t signature[12], settings_guard[17];
    } profiles[] = {
        {0x052330E0, 0x300, 0x2D0, 0x310, 0x400,
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x03,0x00,0x00},
            {0x48,0x83,0xB9,0x00,0x03,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x4D,0x02,0x00,0x00}},
        {0x0529CD20, 0x508, 0x4D8, 0x4F8, 0x570,
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0x80,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x052A8750, 0x508, 0x4D8, 0x4F8, 0x570,
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0x80,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x052AECE0, 0x508, 0x4D8, 0x4F8, 0x570,
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0x80,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x0530F7C0, 0x508, 0x4D8, 0x518, 0x680,
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x05314480, 0x508, 0x4D8, 0x518, 0x688,
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x053319E0, 0x508, 0x4D8, 0x518, 0x688, /* build 26019240 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x05335670, 0x508, 0x4D8, 0x518, 0x688, /* build 26040817: native RNG now at +0x680 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x05335970, 0x508, 0x4D8, 0x518, 0x688, /* build 26056171 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x05338A10, 0x508, 0x4D8, 0x518, 0x688, /* build 26071000 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xA0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x0533DD60, 0x508, 0x4D8, 0x528, 0x688, /* build 26097896 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xB0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x0533E890, 0x508, 0x4D8, 0x528, 0x688, /* build 26111862 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0xB0,0x05,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x053424A0, 0x508, 0x4D8, 0x578, 0x688, /* build 26119568 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0x00,0x06,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
        {0x053490A0, 0x508, 0x4D8, 0x578, 0x6E4, /* build 26141846 */
            {0x4C,0x8B,0xDC,0x41,0x56,0x48,0x81,0xEC,0x00,0x06,0x00,0x00},
            {0x48,0x83,0xB9,0x08,0x05,0x00,0x00,0x00,0x4C,0x8B,0xF1,0x0F,0x84,0x72,0x02,0x00,0x00}},
    };
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
        fprintf(status, "error: invalid staff executable header"); fclose(status); return 0;
    }
    profiles[sizeof(profiles)/sizeof(profiles[0])-1].rva = native_layout_rva(SKIEO_LAYOUT_STAFF_REGENERATE);
    size_t profile_index = sizeof(profiles) / sizeof(profiles[0]);
    for (size_t i = 0; i < sizeof(profiles) / sizeof(profiles[0]); ++i) {
        if (nt->OptionalHeader.SizeOfImage >= profiles[i].rva + 0x375 &&
            !memcmp(module + profiles[i].rva, profiles[i].signature, sizeof(profiles[i].signature)) &&
            !memcmp(module + profiles[i].rva + 0x1E, profiles[i].settings_guard, i == sizeof(profiles)/sizeof(profiles[0])-1 ? 13 : sizeof(profiles[i].settings_guard))) {
            profile_index = i;
            break;
        }
    }
    if (profile_index == sizeof(profiles) / sizeof(profiles[0])) {
        fprintf(status, "error: unsupported staff executable layout"); fclose(status); return 0;
    }
    uint32_t regenerate_rva = profiles[profile_index].rva;
    uint32_t settings_offset = profiles[profile_index].settings_offset;
    uint32_t pool_offset = profiles[profile_index].pool_offset;
    uint8_t *subsystem = (uint8_t *)(uintptr_t)job.subsystem;
    if (!readable_range(subsystem, profiles[profile_index].owner_size)) {
        fprintf(status, "error: invalid staff subsystem"); fclose(status); return 0;
    }
    uintptr_t vtable = 0, settings = 0, pool = 0;
    uint32_t pool_count = 0, pool_max = 0;
    memcpy(&vtable, subsystem, sizeof(vtable));
    memcpy(&settings, subsystem + settings_offset, sizeof(settings));
    memcpy(&pool, subsystem + pool_offset, sizeof(pool));
    memcpy(&pool_count, subsystem + pool_offset + 8, sizeof(pool_count));
    memcpy(&pool_max, subsystem + pool_offset + 12, sizeof(pool_max));
    if (vtable < (uintptr_t)module ||
        vtable >= (uintptr_t)module + nt->OptionalHeader.SizeOfImage ||
        settings != job.settings || pool_count != job.pool_count ||
        pool_max < pool_count || pool_max > 1024 ||
        (pool_count && !readable_range((void *)pool,
            (size_t)pool_count * profiles[profile_index].element_size))) {
        fprintf(status, "error: staff pool layout does not match reflected state"); fclose(status); return 0;
    }
    typedef void (*RegenerateStaffPool)(void *);
    ((RegenerateStaffPool)(module + regenerate_rva))(subsystem);
    memcpy(&pool_count, subsystem + pool_offset + 8, sizeof(pool_count));
    fprintf(status, "ok: regenerated %u native staff candidates", pool_count);
    fclose(status);
    return 0;
}

#ifdef SKIEO_NATIVE_DIAGNOSTICS
__declspec(dllexport) int skieo_probe_memory(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH], status_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_memory.job") ||
        !sibling_path(status_path, MAX_PATH, L"native_memory.status")) {
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) return 0;
    SkiEOHubJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    fclose(file);
    if (read != sizeof(job) || memcmp(job.magic, "SKNM", 4) != 0 ||
        job.version != 1 || job.subsystem == 0) {
        return 0;
    }
    uint8_t *address = (uint8_t *)(uintptr_t)job.subsystem;
    MEMORY_BASIC_INFORMATION memory;
    if (!VirtualQuery(address, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) {
        return 0;
    }
    size_t readable = (size_t)((uint8_t *)memory.BaseAddress
        + memory.RegionSize - address);
    if (readable >= 0x900) {
        wchar_t object_path[MAX_PATH];
        if (sibling_path(object_path, MAX_PATH, L"native_object.bin")) {
            FILE *object_file = _wfopen(object_path, L"wb");
            if (object_file) {
                fwrite(address, 1, 0x900, object_file);
                fclose(object_file);
            }
        }
    }
    file = _wfopen(status_path, L"wb");
    if (!file) return 0;
    for (uint32_t offset = 0; offset < 0x100; offset += 8) {
        uint64_t value;
        memcpy(&value, address + offset, sizeof(value));
        fprintf(file, "%02X=%016llX\n", offset,
            (unsigned long long)value);
    }
    uintptr_t target;
    memcpy(&target, address + 0xD8, sizeof(target));
    fprintf(file, "TARGET=%016llX\n", (unsigned long long)target);
    if (VirtualQuery((void *)target, &memory, sizeof(memory)) &&
        memory.State == MEM_COMMIT &&
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) == 0) {
        uint8_t *target_bytes = (uint8_t *)target;
        for (uint32_t offset = 0; offset < 0x100; offset += 16) {
            fprintf(file, "T%02X=", offset);
            for (uint32_t index = 0; index < 16; ++index) {
                fprintf(file, "%02X", target_bytes[offset + index]);
            }
            fputc('\n', file);
        }
        wchar_t target_path[MAX_PATH];
        if (sibling_path(target_path, MAX_PATH, L"native_target.bin")) {
            FILE *target_file = _wfopen(target_path, L"wb");
            if (target_file) {
                fwrite(target_bytes, 1, 0x1000, target_file);
                fclose(target_file);
            }
        }
    }
    fclose(file);
    return 0;
}

/* Diagnostic-only inspection of UE 5.8's UTexture2D private platform data.
   The reflected class dump fixes UTexture2D's size at 0x168; the final two
   pointers are PrivatePlatformData (0x158) and CPUCopyTexture (0x160).
   Keep this reader separate from the shipping export until the exact mip
   layout has been validated against both a cooked and a transient texture. */
__declspec(dllexport) int skieo_probe_texture(void *lua_state)
{
    (void)lua_state;
    wchar_t job_path[MAX_PATH], status_path[MAX_PATH];
    if (!sibling_path(job_path, MAX_PATH, L"native_memory.job") ||
        !sibling_path(status_path, MAX_PATH, L"native_texture.status")) {
        return 0;
    }
    FILE *file = _wfopen(job_path, L"rb");
    if (!file) return 0;
    SkiEOHubJob job;
    size_t read = fread(&job, 1, sizeof(job), file);
    fclose(file);
    if (read != sizeof(job) || memcmp(job.magic, "SKNM", 4) != 0 ||
        job.version != 1 || job.subsystem == 0) {
        return 0;
    }

    uint8_t *texture = (uint8_t *)(uintptr_t)job.subsystem;
    MEMORY_BASIC_INFORMATION memory;
    if (!VirtualQuery(texture, &memory, sizeof(memory)) ||
        memory.State != MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) {
        return 0;
    }
    wchar_t object_path[MAX_PATH];
    if (sibling_path(object_path, MAX_PATH, L"native_texture_object.bin")) {
        FILE *output = _wfopen(object_path, L"wb");
        if (output) {
            fwrite(texture, 1, 0x168, output);
            fclose(output);
        }
    }

    uintptr_t platform = 0, cpu_copy = 0;
    memcpy(&platform, texture + 0x158, sizeof(platform));
    memcpy(&cpu_copy, texture + 0x160, sizeof(cpu_copy));
    file = _wfopen(status_path, L"wb");
    if (!file) return 0;
    fprintf(file, "texture=%016llX platform=%016llX cpu_copy=%016llX\n",
        (unsigned long long)(uintptr_t)texture,
        (unsigned long long)platform,
        (unsigned long long)cpu_copy);
    for (uint32_t offset = 0; offset < 0x168; offset += 8) {
        uint64_t value;
        memcpy(&value, texture + offset, sizeof(value));
        fprintf(file, "O%03X=%016llX\n", offset,
            (unsigned long long)value);
    }

    if (VirtualQuery((void *)platform, &memory, sizeof(memory)) &&
        memory.State == MEM_COMMIT &&
        (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) == 0) {
        uint8_t *bytes = (uint8_t *)platform;
        wchar_t platform_path[MAX_PATH];
        if (sibling_path(platform_path, MAX_PATH,
                L"native_texture_platform.bin")) {
            FILE *output = _wfopen(platform_path, L"wb");
            if (output) {
                fwrite(bytes, 1, 0x400, output);
                fclose(output);
            }
        }
        for (uint32_t offset = 0; offset < 0x100; offset += 8) {
            uint64_t value;
            memcpy(&value, bytes + offset, sizeof(value));
            fprintf(file, "P%03X=%016llX\n", offset,
                (unsigned long long)value);
        }
        uintptr_t mip_array = 0;
        int32_t mip_count = 0, mip_capacity = 0;
        memcpy(&mip_array, bytes + 0x18, sizeof(mip_array));
        memcpy(&mip_count, bytes + 0x20, sizeof(mip_count));
        memcpy(&mip_capacity, bytes + 0x24, sizeof(mip_capacity));
        fprintf(file, "mips=%016llX count=%d capacity=%d\n",
            (unsigned long long)mip_array, mip_count, mip_capacity);
        if (mip_count > 0 && mip_count <= 16 &&
            VirtualQuery((void *)mip_array, &memory, sizeof(memory)) &&
            memory.State == MEM_COMMIT &&
            (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) == 0) {
            for (int32_t index = 0; index < mip_count; ++index) {
                uintptr_t mip = 0;
                memcpy(&mip, (uint8_t *)mip_array +
                    (size_t)index * sizeof(mip), sizeof(mip));
                fprintf(file, "mip[%d]=%016llX\n", index,
                    (unsigned long long)mip);
                if (!VirtualQuery((void *)mip, &memory, sizeof(memory)) ||
                    memory.State != MEM_COMMIT ||
                    (memory.Protect & (PAGE_NOACCESS | PAGE_GUARD)) != 0) {
                    continue;
                }
                uint8_t *mip_bytes = (uint8_t *)mip;
                for (uint32_t offset = 0; offset < 0x100; offset += 8) {
                    uint64_t value;
                    memcpy(&value, mip_bytes + offset, sizeof(value));
                    fprintf(file, "M%02d_%03X=%016llX\n", index, offset,
                        (unsigned long long)value);
                }
                if (index == 0) {
                    wchar_t mip_path[MAX_PATH];
                    if (sibling_path(mip_path, MAX_PATH,
                            L"native_texture_mip0.bin")) {
                        FILE *output = _wfopen(mip_path, L"wb");
                        if (output) {
                            fwrite(mip_bytes, 1, 0x400, output);
                            fclose(output);
                        }
                    }
                }
            }
        }
    } else {
        fprintf(file, "platform pointer is not readable\n");
    }
    fclose(file);
    return 0;
}
#endif

/* Initialize only empty arrays on newly constructed runtime Landscape
   objects, before registration. Values are owned by Unreal's allocator and
   reflected references keep component/material UObjects alive. */
__declspec(dllexport) int skieo_initialize_landscape_array(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_array.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) { write_status("error: missing runtime array job"); return 0; }
    struct { char magic[4]; uint32_t version; uint64_t owner, owner_class;
        uint32_t kind, count; } job;
    size_t read = fread(&job, 1, sizeof(job), file);
    if (read != sizeof(job) || memcmp(job.magic, "SKIA", 4) || job.version != 1 ||
        !job.owner || !job.owner_class || job.kind < 1 || job.kind > 4 ||
        !job.count || job.count > 1024) {
        fclose(file); write_status("error: invalid runtime array job"); return 0;
    }
    uint64_t values[1024];
    read = fread(values, sizeof(uint64_t), job.count, file);
    int trailing = fgetc(file);
    fclose(file);
    size_t offsets[] = {0, 0x498, 0x5A0, 0x5C0, 0x668};
    size_t sizes[] = {0, 8, 8, 1, 8};
    size_t offset = offsets[job.kind], element_size = sizes[job.kind];
    uint8_t *owner = (uint8_t *)(uintptr_t)job.owner;
    uint64_t owner_class = 0, old_data = 0;
    int32_t old_count = 0, old_capacity = 0;
    if (read != job.count || trailing != EOF ||
        !readable_range(owner, offset + 16)) {
        write_status("error: runtime array owner is unreadable"); return 0;
    }
    memcpy(&owner_class, owner + 0x10, 8);
    memcpy(&old_data, owner + offset, 8);
    memcpy(&old_count, owner + offset + 8, 4);
    memcpy(&old_capacity, owner + offset + 12, 4);
    if (owner_class != job.owner_class || old_data || old_count || old_capacity ||
        (job.kind == 2 && job.count != 1) ||
        (job.kind >= 3 && job.count > 16)) {
        char message[256];
        snprintf(message,sizeof(message), "error: runtime array kind %u: data %llx, num %d, max %d; class %llx expected %llx",
            job.kind,(unsigned long long)old_data,old_count,old_capacity,
            (unsigned long long)owner_class,(unsigned long long)job.owner_class);
        write_status(message); return 0;
    }
    for (uint32_t i = 0; i < job.count; ++i) {
        if ((job.kind <= 2 && !readable_range((void *)(uintptr_t)values[i], 0x28)) ||
            (job.kind >= 3 && values[i] != 0)) {
            write_status("error: invalid runtime array element"); return 0;
        }
    }
    UnrealRealloc allocate = unreal_realloc();
    if (!allocate) { write_status("error: Unreal allocator unavailable"); return 0; }
    uint8_t *data = allocate(NULL, job.count * element_size, 0);
    if (!data) { write_status("error: runtime array allocation failed"); return 0; }
    for (uint32_t i = 0; i < job.count; ++i)
        memcpy(data + i * element_size, &values[i], element_size);
    uint64_t address = (uint64_t)(uintptr_t)data;
    int32_t count = (int32_t)job.count;
    memcpy(owner + offset, &address, 8);
    memcpy(owner + offset + 8, &count, 4);
    memcpy(owner + offset + 12, &count, 4);
    write_status("ok: initialized empty runtime Landscape array");
    return 0;
}

/* Portable heights arrive after subsystem BeginPlay. A placeable notification
   refreshes footprints only; the terrain-change handler also invalidates the
   cached ground mask. Call on the game thread after installing source heights.
   Resolve a unique executable signature rather than assuming a build's RVA. */
__declspec(dllexport) int skieo_refresh_navigation(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_navigation.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) { write_status("error: missing navigation job"); return 0; }
    struct { char magic[4]; uint32_t version; uint64_t owner, owner_class; } job = {0};
    size_t read = fread(&job, 1, sizeof(job), file);
    int trailing = fgetc(file);
    fclose(file);
    uint8_t *owner = (uint8_t *)(uintptr_t)job.owner;
    uint64_t owner_class = 0;
    uintptr_t table = 0, tick = 0;
    if (read != sizeof(job) || trailing != EOF || memcmp(job.magic, "SKNV", 4)
        || job.version != 1 || !job.owner || !job.owner_class
        || !readable_range(owner, 0x899)) {
        write_status("error: invalid navigation job"); return 0;
    }
    memcpy(&owner_class, owner + 0x10, 8);
    memcpy(&table, owner + 0x38, 8);
    if (owner_class != job.owner_class || !readable_range((void *)table, 8)) {
        write_status("error: navigation owner class changed"); return 0;
    }
    memcpy(&tick, (void *)table, 8);
    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module || !readable_range(module, sizeof(IMAGE_DOS_HEADER))) {
        write_status("error: game module unavailable"); return 0;
    }
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0
        || dos->e_lfanew > 0x100000
        || !readable_range(module + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64))) {
        write_status("error: invalid game module header"); return 0;
    }
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    if (nt->Signature != IMAGE_NT_SIGNATURE
        || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC
        || tick < (uintptr_t)module || tick - (uintptr_t)module > image_size
        || SKIEO_NAVIGATION_TICK_BYTES > image_size - (tick - (uintptr_t)module)
        || !readable_range((void *)tick, SKIEO_NAVIGATION_TICK_BYTES)
        || !skieo_navigation_changed_signature((void *)tick, SKIEO_NAVIGATION_TICK_BYTES)) {
        write_status("error: unsupported WalkNav tick layout"); return 0;
    }
    const uint8_t *expected_changed = skieo_navigation_changed_signature(
        (void *)tick, SKIEO_NAVIGATION_TICK_BYTES);
    IMAGE_SECTION_HEADER *sections = IMAGE_FIRST_SECTION(nt);
    if (!nt->FileHeader.NumberOfSections || nt->FileHeader.NumberOfSections > 96
        || !readable_range(sections,
            nt->FileHeader.NumberOfSections * sizeof(*sections))) {
        write_status("error: invalid game code sections"); return 0;
    }
    uint8_t *handler = NULL;
    unsigned matches = 0;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        if (!(sections[i].Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        size_t start = sections[i].VirtualAddress, size = sections[i].Misc.VirtualSize;
        if (start > image_size || size > image_size - start
            || size < SKIEO_NAVIGATION_CHANGED_BYTES
            || !readable_range(module + start, size)) continue;
        for (size_t offset = 0; offset <= size - SKIEO_NAVIGATION_CHANGED_BYTES; ++offset) {
            uint8_t *candidate = module + start + offset;
            if (*candidate == expected_changed[0]
                && !memcmp(candidate, expected_changed, SKIEO_NAVIGATION_CHANGED_BYTES)) {
                handler = candidate;
                ++matches;
            }
        }
    }
    if (matches != 1) {
        write_status("error: navigation terrain-change handler is not unique"); return 0;
    }
    typedef void (*TerrainChanged)(void *);
    ((TerrainChanged)handler)(owner);
    write_status("ok: source terrain navigation invalidated through native handler");
    return 0;
}

/* Native restore registers pads before the portable terrain and actor roots
   are finalized. Re-register at the final transforms, through the same native
   method used during placement. It replaces the existing per-id pad and keeps
   the brush's player sculpt layers, CPU terrain and snow simulation intact. */
__declspec(dllexport) int skieo_refresh_placeable_pads(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_pads.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) { write_status("error: missing terrain pads job"); return 0; }
    struct { char magic[4]; uint32_t version, count, reserved; } job = {0};
    size_t read = fread(&job, 1, sizeof(job), file);
    if (read != sizeof(job) || memcmp(job.magic, "SKPD", 4) || job.version != 1
        || !job.count || job.count > 4096 || job.reserved) {
        fclose(file); write_status("error: invalid terrain pads job"); return 0;
    }
    struct { uint64_t actor, actor_class; } *actors = calloc(job.count, sizeof(*actors));
    if (!actors) { fclose(file); write_status("error: terrain pads allocation failed"); return 0; }
    read = fread(actors, sizeof(*actors), job.count, file);
    int trailing = fgetc(file); fclose(file);
    const char *error = NULL;
    if (read != job.count || trailing != EOF) error = "error: truncated terrain pads actors";
    /* Validate every actor before invoking the first native mutation. */
    for (uint32_t i = 0; !error && i < job.count; ++i) {
        uint8_t *actor = (uint8_t *)(uintptr_t)actors[i].actor;
        uint64_t cls = 0;
        if (!actor || !actors[i].actor_class || !readable_range(actor, 0x3D8)) {
            error = "error: terrain pads actor is unreadable"; break;
        }
        memcpy(&cls, actor + 0x10, 8);
        if (cls != actors[i].actor_class) error = "error: terrain pads actor class changed";
    }
    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    uint8_t *handler = NULL, *cleanup = NULL;
    if (!error && module && readable_range(module, sizeof(IMAGE_DOS_HEADER))) {
        IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
        if (dos->e_magic == IMAGE_DOS_SIGNATURE && dos->e_lfanew > 0
            && dos->e_lfanew < 0x100000 && readable_range(module + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64))) {
            IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
            uint32_t profiles[][2] = {{0x4FF3310, 0x4FE0C30}, {0x4FF2D80, 0x4FE0680}, {0x4FE1470, 0x4FCC520}, {0x4FE0F70, 0x4FCC020}, {0x4FE0FF0, 0x4FCC230}, {0x4FE0C00, 0x4FCBE40}, {0x4FDF110, 0x4FCA360}};
            profiles[0][0] = native_layout_rva(SKIEO_LAYOUT_TERRAIN_PADS);
            profiles[0][1] = native_layout_rva(SKIEO_LAYOUT_TERRAIN_PADS_CLEANUP);
            if (nt->Signature == IMAGE_NT_SIGNATURE && nt->OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
                for (size_t i = 0; i < sizeof(profiles)/sizeof(*profiles); ++i) {
                    uint32_t rva = profiles[i][0], clear_rva = profiles[i][1];
                    if (rva <= nt->OptionalHeader.SizeOfImage
                        && SKIEO_TERRAIN_PADS_BYTES <= nt->OptionalHeader.SizeOfImage - rva
                        && readable_range(module + rva, SKIEO_TERRAIN_PADS_BYTES)
                        && skieo_terrain_pads_matches(module + rva, SKIEO_TERRAIN_PADS_BYTES, rva)
                        && clear_rva <= nt->OptionalHeader.SizeOfImage
                        && SKIEO_TERRAIN_PADS_CLEANUP_BYTES <= nt->OptionalHeader.SizeOfImage - clear_rva
                        && readable_range(module + clear_rva, SKIEO_TERRAIN_PADS_CLEANUP_BYTES)
                        && skieo_terrain_pads_cleanup_matches(module + clear_rva,
                            SKIEO_TERRAIN_PADS_CLEANUP_BYTES, clear_rva)) {
                        handler = module + rva; cleanup = module + clear_rva; break;
                    }
                }
            }
        }
    }
    if ((!handler || !cleanup) && !error) error = "error: unsupported native terrain pads code";
    if (!error) {
        typedef void (*RegisterTerrainPads)(void *);
        for (uint32_t i = 0; i < job.count; ++i) {
            /* Match native LoadFromSaveData: destroy the old transient pad
               and placement-blocker components before registering new ones. */
            ((RegisterTerrainPads)cleanup)((void *)(uintptr_t)actors[i].actor);
            ((RegisterTerrainPads)handler)((void *)(uintptr_t)actors[i].actor);
        }
    }
    free(actors);
    if (error) write_status(error);
    else {
        char message[128];
        snprintf(message, sizeof(message), "ok: refreshed %u native terrain pad owner(s)", job.count);
        write_status(message);
    }
    return 0;
}

/* The skiability memo is keyed by game minute and snow threshold. Source
   loading pauses that minute, so the first empty readback can stay cached
   after the snow plane is ready. Invalidate the memo, never its result. */
__declspec(dllexport) int skieo_refresh_skiability(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"native_skiability.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) { write_status("error: missing skiability job"); return 0; }
    struct { char magic[4]; uint32_t version; uint64_t owner, owner_class; } job={0};
    size_t read=fread(&job,1,sizeof(job),file);int trailing=fgetc(file);fclose(file);
    uint8_t *owner=(uint8_t *)(uintptr_t)job.owner;
    uint64_t cls=0;
    if(read!=sizeof(job)||trailing!=EOF||memcmp(job.magic,"SKSK",4)||job.version!=1
        ||!job.owner||!job.owner_class||!readable_range(owner,0x1a5)) {
        write_status("error: invalid skiability job");return 0;
    }
    memcpy(&cls,owner+0x10,8);
    if(cls!=job.owner_class) {write_status("error: skiability owner class changed");return 0;}
    uint8_t *module=(uint8_t *)GetModuleHandleW(L"skieogame.exe");
    uint32_t profiles[][3] = {
        {0x05321560, 0x05321842, 0x19C},
        {0x0538DF30, 0x0538E212, 0x19C},
        {0x05390430, 0x05390712, 0x1B4}, /* build 25996759 */
        {0x053A6210, 0x053A64F2, 0x1B4}, /* build 26019240 */
        {0x053AA870, 0x053AAB52, 0x1B4}, /* build 26040817 */
        {0x053AAC70, 0x053AAF52, 0x1B4}, /* build 26056171 */
        {0x053ADA10, 0x053ADCF2, 0x1B4}, /* build 26071000 */
        {0x053B2CF0, 0x053B2FD2, 0x1B4}, /* build 26097896 */
        {0x053B39E0, 0x053B3CC2, 0x1B4}, /* build 26111862 */
    };
    static const uint8_t query[]={0x40,0x55,0x53,0x56,0x48,0x8d,0x6c,0x24,0xb9,0x48,0x81,0xec,0xb0,0,0,0};
    static const uint8_t memo[]={0x44,0x3b,0xbe,0x9c,0x01,0,0,0x75,0x27,0x0f,0x28,0xc6,0xf3,0x0f,0x5c,0x86,0xa0,0x01,0,0};
    uint32_t memo_offset=0;
    size_t latest=sizeof(profiles)/sizeof(profiles[0])-1;
    profiles[latest][0]=native_layout_rva(SKIEO_LAYOUT_SKIABILITY_QUERY);
    profiles[latest][1]=native_layout_rva(SKIEO_LAYOUT_SKIABILITY_MEMO);
    for(size_t i=0;module&&i<sizeof(profiles)/sizeof(profiles[0]);i++) {
        uint8_t expected_memo[sizeof(memo)];
        uint32_t threshold_offset=profiles[i][2]+4;
        memcpy(expected_memo,memo,sizeof(memo));
        memcpy(expected_memo+3,&profiles[i][2],4);
        memcpy(expected_memo+16,&threshold_offset,4);
        if(readable_range(module+profiles[i][0],sizeof(query))
            &&readable_range(module+profiles[i][1],sizeof(memo))
            &&!memcmp(module+profiles[i][0],query,sizeof(query))
            &&!memcmp(module+profiles[i][1],expected_memo,sizeof(expected_memo))) {memo_offset=profiles[i][2];break;}
    }
    if(!memo_offset || !readable_range(owner,memo_offset+sizeof(int32_t))) {
        write_status("error: unsupported skiability memo layout");return 0;
    }
    int32_t invalid=-1;
    memcpy(owner+memo_offset,&invalid,sizeof(invalid));
    write_status("ok: skiability memo invalidated; native snow checks retained");return 0;
}

/* Store authored geographic hub names in the native name map. The stock
   name getter, management groups and save writer all read this same map. */
__declspec(dllexport) int skieo_name_hubs(void *lua_state)
{
    (void)lua_state;wchar_t path[MAX_PATH];
    if(!sibling_path(path,MAX_PATH,L"native_hub_names.job")) return 0;
    FILE *file=_wfopen(path,L"rb");if(!file){write_status("error: missing hub names job");return 0;}
    struct {char magic[4];uint32_t version;uint64_t owner,owner_class;uint32_t count,reserved;} job={0};
    size_t read=fread(&job,1,sizeof(job),file);
    struct Name {uint32_t id[4];wchar_t text[33];} names[64]={0};
    int good=read==sizeof(job)&&!memcmp(job.magic,"SKHN",4)&&job.version==1&&job.count>0&&job.count<=64;
    for(uint32_t i=0;good&&i<job.count;i++) {
        uint32_t length=0;char utf8[129]={0};
        good=fread(names[i].id,16,1,file)==1&&fread(&length,4,1,file)==1&&length>0&&length<=128;
        if(good) good=fread(utf8,1,length,file)==length&&memchr(utf8,0,length)==NULL;
        if(good) good=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,utf8,(int)length,names[i].text,32)>0;
    }
    good=good&&fgetc(file)==EOF;fclose(file);
    uint8_t *owner=(uint8_t *)(uintptr_t)job.owner;uint64_t cls=0;
    if(!good||!job.owner||!job.owner_class||!readable_range(owner,0x220)) {write_status("error: invalid hub names job");return 0;}
    memcpy(&cls,owner+0x10,8);if(cls!=job.owner_class){write_status("error: hub names owner class changed");return 0;}
    uint8_t *module=(uint8_t *)GetModuleHandleW(L"skieogame.exe");
    uint32_t profiles[][3] = {
        {0x050269A0, 0x050054B0, 0x01349070},
        {0x0503C070, 0x0501E3A0, 0x01349260}, /* build 25970577 */
        {0x0503E520, 0x0501F560, 0x01349600}, /* build 25996759 */
        {0x050401E0, 0x050210F0, 0x013499C0}, /* build 26019240 */
        {0x05040800, 0x050214E0, 0x01349860}, /* build 26040817 */
        {0x050407F0, 0x050214B0, 0x01349820}, /* build 26056171 */
        {0x05041160, 0x05021DF0, 0x01349820}, /* build 26071000 */
        {0x05044340, 0x05027810, 0x01349B60}, /* build 26097896 */
        {0x05044B40, 0x05028010, 0x01349BA0}, /* build 26111862 */
    };
    static const uint8_t get[]={0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x6c,0x24,0x10,0x48,0x89,0x74,0x24,0x18,0x57,0x48,0x83,0xec,0x20,0x48,0x8b,0xfa,0x48,0x8d,0xb1,0xd0,0x01,0,0};
    static const uint8_t insert[]={0x48,0x89,0x5c,0x24,0x10,0x48,0x89,0x6c,0x24,0x18,0x48,0x89,0x74,0x24,0x20,0x57,0x48,0x83,0xec,0x40};
    static const uint8_t factory[]={0x48,0x8b,0xc4,0x57,0x41,0x56,0x48,0x83,0xec,0x58,0x48,0x89,0x58,0x10};
    size_t latest=sizeof(profiles)/sizeof(profiles[0])-1;
    profiles[latest][0]=native_layout_rva(SKIEO_LAYOUT_HUB_NAMES_GET);
    profiles[latest][1]=native_layout_rva(SKIEO_LAYOUT_HUB_NAMES_INSERT);
    profiles[latest][2]=native_layout_rva(SKIEO_LAYOUT_HUB_NAMES_TEXT);
    const uint32_t *profile=NULL;
    for(size_t i=0;module&&i<sizeof(profiles)/sizeof(profiles[0]);i++) {
        const uint32_t *p=profiles[i];
        if(readable_range(module+p[0],sizeof(get))&&readable_range(module+p[1],sizeof(insert))
            &&readable_range(module+p[2],sizeof(factory))&&!memcmp(module+p[0],get,sizeof(get))
            &&!memcmp(module+p[1],insert,sizeof(insert))&&!memcmp(module+p[2],factory,sizeof(factory))) {profile=p;break;}
    }
    if(!profile) {
        write_status("error: unsupported native hub names layout");return 0;
    }
    uint32_t slots=0,capacity=0;memcpy(&slots,owner+0x1d8,4);memcpy(&capacity,owner+0x1dc,4);
    if(slots>capacity||capacity>4096){write_status("error: invalid native hub name map");return 0;}
    struct Text {void *reference;uint32_t flags,padding;};
    struct String {wchar_t *data;int32_t count,capacity;};
    typedef void *(*FromString)(struct Text *,const struct String *);
    typedef void *(*Insert)(void *,const uint32_t *,const struct Text *);
    typedef void (*Release)(void *,void *);
    for(uint32_t i=0;i<job.count;i++) {
        struct String string={names[i].text,(int32_t)wcslen(names[i].text)+1,33};
        struct Text text={0};((FromString)(module+profile[2]))(&text,&string);
        ((Insert)(module+profile[1]))(owner+0x1d0,names[i].id,&text);
        if(text.reference) {
            void **table=*(void ***)text.reference;uint64_t scratch[2]={0};
            ((Release)table[2])(text.reference,scratch);
        }
    }
    write_status("ok: geographic hub names stored in native map");return 0;
}

/* Read the game's asynchronously refreshed CPU snow tiles. Never flush the
   render thread to sample a pixel. Layout is guarded by the native cache
   validity, tile lookup and world-to-cell signatures. Build 25996759 uses
   56-byte map entries, with readiness at +0x28 instead of +0x24. */
__declspec(dllexport) int skieo_stage_game_options(void *lua_state)
{
    (void)lua_state;
    struct {
        char magic[4]; uint32_t version;
        uint64_t owner, owner_class;
        int32_t seed; float day_length;
        uint32_t days, sandbox;
    } job;
    wchar_t path[MAX_PATH];
    if (!sibling_path(path, MAX_PATH, L"game_options.job")) return 0;
    FILE *file = _wfopen(path, L"rb");
    if (!file) return 0;
    size_t count = fread(&job, 1, sizeof(job), file);
    int extra = fgetc(file); fclose(file);
    const char *status = "error: invalid new-game options";
    if (count != sizeof(job) || extra != EOF || memcmp(job.magic, "SKGO", 4)
        || job.version != 1 || !job.owner || !job.owner_class
        || !skieo_game_options_valid(job.day_length, job.days, job.sandbox)) goto done;
    uint8_t *owner = (uint8_t *)(uintptr_t)job.owner;
    uint64_t owner_class;
    status = "error: game session layout unavailable";
    if (!readable_range(owner, 0xB0)) goto done;
    memcpy(&owner_class, owner + 0x10, sizeof(owner_class));
    if (owner_class != job.owner_class) goto done;
    uint8_t *module = (uint8_t *)GetModuleHandleW(L"skieogame.exe");
    if (!module || !readable_range(module, sizeof(IMAGE_DOS_HEADER))) goto done;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)module;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0
        || dos->e_lfanew > 0x100000
        || !readable_range(module + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64))) goto done;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(module + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC
        || !nt->FileHeader.NumberOfSections || nt->FileHeader.NumberOfSections > 96) goto done;
    IMAGE_SECTION_HEADER *sections = IMAGE_FIRST_SECTION(nt);
    if (!readable_range(sections, nt->FileHeader.NumberOfSections * sizeof(*sections))) goto done;
    size_t image_size = nt->OptionalHeader.SizeOfImage;
    unsigned matches = 0;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        size_t start = sections[i].VirtualAddress, size = sections[i].Misc.VirtualSize;
        if (!(sections[i].Characteristics & IMAGE_SCN_MEM_EXECUTE) || start > image_size
            || size > image_size - start || size < sizeof(skieo_game_options_signature)
            || !readable_range(module + start, size)) continue;
        for (size_t j = 0; j <= size - sizeof(skieo_game_options_signature); ++j)
            if (module[start+j] == skieo_game_options_signature[0]
                && !memcmp(module + start+j, skieo_game_options_signature, sizeof(skieo_game_options_signature))) ++matches;
    }
    status = "error: unsupported native new-game settings layout";
    if (matches != 1) goto done;
    skieo_game_options_apply(owner, 0xB0, job.seed, job.day_length, job.days, job.sandbox);
    status = "ok: staged native new-game options";
done:
    if (sibling_path(path, MAX_PATH, L"game_options.status")) {
        file = _wfopen(path, L"wb");
        if (file) { fputs(status, file); fclose(file); }
    }
    return 0;
}

__declspec(dllexport) int skieo_sample_snow(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH], output[MAX_PATH];
    if (!sibling_path(path,MAX_PATH,L"native_entity_snow.job") ||
        !sibling_path(output,MAX_PATH,L"native_entity_snow.bin")) return 0;
    FILE *f=_wfopen(path,L"rb"); if(!f)return 0;
    struct {char magic[4];uint32_t version;uint64_t owner,cls;double x,y;} job={0};
    size_t n=fread(&job,1,sizeof(job),f);int extra=fgetc(f);fclose(f);
    uint8_t *cache=(uint8_t *)(uintptr_t)job.owner;
    uint8_t *exe=(uint8_t *)GetModuleHandleW(L"skieogame.exe");
    static const uint8_t validity[]={0x0f,0xb6,0x81,0xa5,0x01,0,0,0x41,0x88,0};
    static const uint8_t lookup[]={0x49,0x63,0xc1,0x4c,0x8d,0x04,0x40,0x49,0xc1,0xe0,0x04};
    static const uint8_t expanded_lookup[]={0x49,0x63,0xc0,0x48,0x6b,0xd0,0x38,0x49,0x03,0xd2,0x48,0x8b,0x0a,0x41,0x3b,0xc9};
    static const uint8_t expanded_ready[]={0x41,0x38,0x54,0x24,0x20,0x0f,0x84,0xe3,0xfd,0xff,0xff};
    static const uint8_t mapping[]={0xf2,0x0f,0x10,0x89,0xf8,0,0,0,0x0f,0x57,0xd2,0xf2,0x0f,0x5c,0x89,0xe8,0,0,0};
    struct {
        uint32_t validity_rva,lookup_rva,mapping_rva,ready_rva,stride,ready;
        const uint8_t *lookup_signature;
        size_t lookup_size;
    } profiles[]={
        {0x04F576F5,0x05284FB0,0x052863D0,0,48,0x24,lookup,sizeof(lookup)},
        {0x04F5A315,0x052EA970,0x052E8900,0x052EABB6,56,0x28,expanded_lookup,sizeof(expanded_lookup)},
        {0x04F5AC15,0x052ECCC0,0x052EAE50,0x052ECF06,56,0x28,expanded_lookup,sizeof(expanded_lookup)}, /* build 26019240 */
        {0x04F83915,0x052EE090,0x052EC220,0x052EE2D6,56,0x28,expanded_lookup,sizeof(expanded_lookup)}, /* build 26040817 */
        {0x04F83625,0x052EE390,0x052EC520,0x052EE5D6,56,0x28,expanded_lookup,sizeof(expanded_lookup)}, /* build 26056171 */
        {0x04F83C35,0x052F0C00,0x052EED90,0x052F0E46,56,0x28,expanded_lookup,sizeof(expanded_lookup)}, /* build 26071000 */
        {0x04F7FFF5,0x052F5A00,0x052F3B90,0x052F5C46,56,0x28,expanded_lookup,sizeof(expanded_lookup)}, /* build 26097896 */
        {0x04F7FE25,0x052F6530,0x052F46C0,0x052F6776,56,0x28,expanded_lookup,sizeof(expanded_lookup)}, /* build 26111862 */
    };
    size_t latest=sizeof(profiles)/sizeof(profiles[0])-1;
    profiles[latest].validity_rva=native_layout_rva(SKIEO_LAYOUT_SNOW_CPU_VALIDITY);
    profiles[latest].lookup_rva=native_layout_rva(SKIEO_LAYOUT_SNOW_CPU_LOOKUP);
    profiles[latest].mapping_rva=native_layout_rva(SKIEO_LAYOUT_SNOW_CPU_MAPPING);
    profiles[latest].ready_rva=native_layout_rva(SKIEO_LAYOUT_SNOW_CPU_READY);
    uint32_t stride=0,ready=0;
    for(size_t i=0;exe&&i<sizeof(profiles)/sizeof(profiles[0]);i++) {
        if((i!=latest || profiles[i].ready_rva) && profiles[i].validity_rva && profiles[i].lookup_rva && profiles[i].mapping_rva
            && readable_range(exe+profiles[i].validity_rva,sizeof(validity))
            &&readable_range(exe+profiles[i].lookup_rva,profiles[i].lookup_size)
            &&readable_range(exe+profiles[i].mapping_rva,sizeof(mapping))
            &&!memcmp(exe+profiles[i].validity_rva,validity,sizeof(validity))
            &&!memcmp(exe+profiles[i].lookup_rva,profiles[i].lookup_signature,profiles[i].lookup_size)
            &&!memcmp(exe+profiles[i].mapping_rva,mapping,sizeof(mapping))
            &&(!profiles[i].ready_rva || (readable_range(exe+profiles[i].ready_rva,sizeof(expanded_ready))
                &&!memcmp(exe+profiles[i].ready_rva,expanded_ready,i==latest ? 7 : sizeof(expanded_ready))))) {
            stride=profiles[i].stride;ready=profiles[i].ready;break;
        }
    }
    uint64_t cls=0;
    float result[4]={0,0,0,0};
    if(n!=sizeof(job)||extra!=EOF||memcmp(job.magic,"SKSN",4)||job.version!=1
        ||!exe||!job.owner||!job.cls||!isfinite(job.x)||!isfinite(job.y)
        ||!readable_range(cache,0x2a0)||!stride) goto done;
    memcpy(&cls,cache+0x10,8);if(cls!=job.cls||!cache[0x1a5])goto done;
    double bounds[4];memcpy(bounds,cache+0xe8,32);
    int32_t tiles;memcpy(&tiles,cache+0x10c,4);
    if(tiles<1||tiles>128||!isfinite(bounds[0])||!isfinite(bounds[1])
        ||!isfinite(bounds[2])||!isfinite(bounds[3])||bounds[2]<=bounds[0]||bounds[3]<=bounds[1])goto done;
    double gx=(job.x-bounds[0])/(bounds[2]-bounds[0])*tiles*64;
    double gy=(job.y-bounds[1])/(bounds[3]-bounds[1])*tiles*64;
    if(gx<0||gy<0||gx>=tiles*64||gy>=tiles*64)goto done;
    int32_t ix=(int32_t)floor(gx),iy=(int32_t)floor(gy),tx=ix/64,ty=iy/64;
    uint8_t *entries=NULL;int32_t count,capacity,bits;
    memcpy(&entries,cache+0x48,8);memcpy(&count,cache+0x50,4);memcpy(&capacity,cache+0x54,4);memcpy(&bits,cache+0x70,4);
    uint32_t *allocated=NULL;memcpy(&allocated,cache+0x68,8);
    if(!allocated)allocated=(uint32_t *)(cache+0x58);
    if(count<0||count>2048||capacity<count||capacity>4096||bits<count||bits>4096
        ||!readable_range(entries,(size_t)count*stride)||!readable_range(allocated,((size_t)bits+31)/32*4))goto done;
    for(int32_t i=0;i<count;++i){
        if(!(allocated[i/32]&(1U<<(i%32))))continue;
        uint8_t *entry=entries+(size_t)i*stride;int32_t key[2],length;float *samples=NULL;
        memcpy(key,entry,8);if(key[0]!=tx||key[1]!=ty)continue;
        memcpy(&samples,entry+8,8);memcpy(&length,entry+16,4);
        if(length!=4096||!entry[ready]||!readable_range(samples,4096*32))break;
        float *pixel=(float *)((uint8_t *)samples+((iy%64)*64+ix%64)*32);
        if(isfinite(pixel[0])&&isfinite(pixel[1])&&pixel[0]>=0&&pixel[1]>=0&&pixel[0]+pixel[1]<10000){
            result[0]=1;result[1]=pixel[0];result[2]=pixel[1];
            result[3]=(float)((bounds[2]-bounds[0])/(tiles*64));
        }
        break;
    }
 done:
    f=_wfopen(output,L"wb");if(f){fwrite(result,1,sizeof(result),f);fclose(f);}return 0;
}
