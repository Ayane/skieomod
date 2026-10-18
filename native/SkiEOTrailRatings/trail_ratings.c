#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "rating_policy.h"
#include "rating_colors.h"
#include "vendor/minhook/include/MinHook.h"

/* Recognize reviewed code semantics, allowing address-only relocations.
   Never modify shared literals or accept ambiguous entry points. */
#include "rating_resolver.h"

typedef struct RatingJob {
    char magic[4];
    uint32_t version, enabled;
    int32_t style;
    RatingPolicy policy;
    RatingColors colors;
} RatingJob;
_Static_assert(sizeof(RatingJob) == 52, "rating job ABI v2");

typedef struct RatingHook {
    void *target, *original;
    uint8_t prefix[5];
    uint8_t expected[208];
    size_t size;
    int created, enabled;
} RatingHook;

static SRWLOCK policy_lock = SRWLOCK_INIT;
static RatingPolicy policy;
static RatingColors colors;
static RatingColor linear_colors[4];
static RatingHook slope_hook, color_hook;
static uint8_t *style_cache;
static uint8_t original_style;
static uint8_t *palette_target, palette_expected[65];
static RatingResolution resolution;
static int active, resolved, style_owned;
static const uint8_t *threshold_literals[3], *color_table, *color_fallback;
static uint8_t threshold_expected[3][4];
static uint8_t color_table_expected[28];

static uint8_t calculate(float angle)
{
    AcquireSRWLockShared(&policy_lock);
    int custom = policy.count != 0;
    uint8_t result = custom ? rating_from_slope(angle, &policy) : 0;
    ReleaseSRWLockShared(&policy_lock);
    return custom ? result : ((uint8_t (*)(float))slope_hook.original)(angle);
}

/* Win64 return-by-address ABI: RCX is the FLinearColor result, DL the grade.
   Unspecified levels and native special values (e.g. unrated 255) use the
   original implementation, including the selected native style. */
static RatingColor *difficulty_color(RatingColor *result, uint8_t difficulty)
{
    AcquireSRWLockShared(&policy_lock);
    int custom = difficulty < 4 && (colors.mask & (1u << difficulty));
    if (custom) *result = linear_colors[difficulty];
    ReleaseSRWLockShared(&policy_lock);
    return custom ? result : ((RatingColor *(*)(RatingColor *, uint8_t))color_hook.original)(result, difficulty);
}

static int readable(const void *pointer, size_t size)
{
    MEMORY_BASIC_INFORMATION m;
    return VirtualQuery(pointer, &m, sizeof(m)) == sizeof(m) &&
        m.State == MEM_COMMIT && !(m.Protect & (PAGE_GUARD | PAGE_NOACCESS)) &&
        (uintptr_t)pointer >= (uintptr_t)m.BaseAddress &&
        size <= m.RegionSize - ((uintptr_t)pointer - (uintptr_t)m.BaseAddress);
}

static int readable_span(const void *pointer,size_t size)
{
    uintptr_t current=(uintptr_t)pointer;
    if(size>UINTPTR_MAX-current)return 0;
    uintptr_t end=current+size;
    while(current<end) {
        MEMORY_BASIC_INFORMATION m;
        if(!VirtualQuery((void *)current,&m,sizeof(m)) || m.State!=MEM_COMMIT ||
            (m.Protect & (PAGE_GUARD|PAGE_NOACCESS)))return 0;
        uintptr_t next=(uintptr_t)m.BaseAddress+m.RegionSize;
        if(next<=current)return 0;
        current=next;
    }
    return 1;
}

static int hook_matches(RatingHook *hook)
{
    const uint8_t *function=hook->target;
    if (!function || !readable(function, hook->size)) return 0;
    if (!hook->enabled) return !memcmp(function, hook->expected, hook->size);
    return !memcmp(function, hook->prefix, 5) &&
        !memcmp(function + 5, hook->expected + 5, hook->size - 5);
}

static const char *resolve_image(void)
{
    if(resolved)return NULL;
    uint8_t *base = (uint8_t *)GetModuleHandleW(NULL);
    if (!readable(base, sizeof(IMAGE_DOS_HEADER))) return "game module unavailable";
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 4096)
        return "invalid game module";
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (!readable(nt, sizeof(*nt)) || nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt->FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64 ||
        !nt->FileHeader.NumberOfSections || nt->FileHeader.NumberOfSections>96)
        return "unsupported game image";
    IMAGE_SECTION_HEADER *headers=IMAGE_FIRST_SECTION(nt);
    if(!readable(headers,nt->FileHeader.NumberOfSections*sizeof(*headers)))return "unreadable game sections";
    RatingSection sections[96];size_t count=0;
    for(unsigned i=0;i<nt->FileHeader.NumberOfSections;++i) {
        uint32_t rva=headers[i].VirtualAddress,size=headers[i].Misc.VirtualSize;
        if(!size)continue;
        if(rva>nt->OptionalHeader.SizeOfImage || size>nt->OptionalHeader.SizeOfImage-rva)
            return "invalid game section range";
        if(!readable_span(base+rva,size))continue; /* discarded sections are not candidates */
        uint32_t flags=headers[i].Characteristics;
        unsigned kind=(flags & IMAGE_SCN_MEM_EXECUTE) ? RATING_CODE :
            (flags & IMAGE_SCN_MEM_WRITE) ? RATING_DATA : RATING_CONST;
        sections[count++]=(RatingSection){base+rva,rva,size,kind};
    }
    RatingImage image={sections,count};resolution=rating_resolve(&image);
    if(resolution.calculate) {
        slope_hook.target=base+resolution.calculate;slope_hook.size=sizeof(rating_calculate_guard);
        memcpy(slope_hook.expected,slope_hook.target,slope_hook.size);
        static const unsigned refs[]={3,15,27};
        for(unsigned i=0;i<3;++i) {
            threshold_literals[i]=base+rating_relative(resolution.calculate,refs[i]+4,slope_hook.expected+refs[i]);
            memcpy(threshold_expected[i],threshold_literals[i],4);
        }
    }
    if(resolution.color) {
        color_hook.target=base+resolution.color;color_hook.size=RATING_COLOR_BYTES;
        memcpy(color_hook.expected,color_hook.target,color_hook.size);
        color_table=base+rating_u32(color_hook.expected+39);
        memcpy(color_table_expected,color_table,sizeof(color_table_expected));
        color_fallback=base+rating_relative(resolution.color,193,color_hook.expected+189);
    }
    if(resolution.palette) {
        palette_target=base+resolution.palette;
        memcpy(palette_expected,palette_target,sizeof(palette_expected));
        style_cache=base+resolution.style;
    }
    resolved=1;return NULL;
}

static const char *resolve_profile(int slope,int palette,int color)
{
    const char *failure=resolve_image();if(failure)return failure;
    if ((slope || slope_hook.enabled) && !hook_matches(&slope_hook))
        return "unsupported native slope classification";
    if(slope || slope_hook.enabled) {
        for(unsigned i=0;i<3;++i)
            if(!readable(threshold_literals[i],4) || memcmp(threshold_literals[i],threshold_expected[i],4))
                return "native slope constants changed";
    }
    if ((color || color_hook.enabled) && !hook_matches(&color_hook))
        return "unsupported native difficulty colors";
    if(color || color_hook.enabled) {
        static const float white[]={1,1,1,1};
        if(!readable(color_table,28) || memcmp(color_table,color_table_expected,28) ||
            !readable(color_fallback,16) || memcmp(color_fallback,white,16))
            return "native color references changed";
    }
    if (!(palette || color || style_owned)) return NULL;
    if(!palette_target || !readable(palette_target,sizeof(palette_expected)) ||
        memcmp(palette_target,palette_expected,sizeof(palette_expected)))return "unsupported native rating palette";
    MEMORY_BASIC_INFORMATION m;
    if (!readable(style_cache, 1) || *style_cache > 3 ||
        !VirtualQuery(style_cache, &m, sizeof(m)) ||
        !(m.Protect & (PAGE_READWRITE | PAGE_WRITECOPY)))
        return "unsupported native rating style cache";
    return NULL;
}

static int create_hook(RatingHook *hook, void *callback)
{
    if (hook->created) return 1;
    MH_STATUS status = MH_Initialize();
    if (status != MH_OK && status != MH_ERROR_ALREADY_INITIALIZED) return 0;
    if (MH_CreateHook(hook->target, callback, &hook->original) != MH_OK) return 0;
    hook->created = 1;
    return 1;
}

static int switch_hook(RatingHook *hook, int wanted)
{
    if (wanted == hook->enabled) return 1;
    MH_STATUS status = wanted ? MH_EnableHook(hook->target) : MH_DisableHook(hook->target);
    if (status != MH_OK) return 0;
    hook->enabled = wanted;
    if (wanted) memcpy(hook->prefix, hook->target, sizeof(hook->prefix));
    return 1;
}

static const char *apply(const RatingJob *job)
{
    if (memcmp(job->magic, "SKRT", 4) || job->version != 2 || job->enabled > 1 ||
        job->style < -1 || job->style == 0 || job->style > 3 ||
        !rating_policy_valid(&job->policy) || !rating_colors_valid(&job->colors) ||
        (!job->enabled && (job->style != -1 || job->policy.count || job->colors.mask)))
        return "invalid trail rating configuration";
    if (!job->enabled && !active) return NULL;
    int want_slope = job->enabled && job->policy.count;
    int want_color = job->enabled && job->colors.mask;
    const char *failure = resolve_profile(want_slope,job->enabled && job->style!=-1,want_color);
    if (failure) return failure;
    if ((want_slope && !create_hook(&slope_hook, (void *)calculate)) ||
        (want_color && !create_hook(&color_hook, (void *)difficulty_color)))
        return "could not create native rating hooks";
    int previous_slope = slope_hook.enabled;
    if (!switch_hook(&slope_hook, want_slope)) return "could not switch native slope hook";
    if (!switch_hook(&color_hook, want_color)) {
        if(!switch_hook(&slope_hook, previous_slope))
            return "could not roll back native slope hook";
        return "could not switch native color hook";
    }
    AcquireSRWLockExclusive(&policy_lock);
    policy = job->policy;
    colors = job->colors;
    for (unsigned i = 0; i < 4; ++i) linear_colors[i] = rating_linear_color(colors.srgb[i]);
    ReleaseSRWLockExclusive(&policy_lock);
    if (job->enabled && job->style!=-1) {
        if (!style_owned) original_style = *style_cache;
        *style_cache=(uint8_t)job->style;style_owned=1;
    } else if(style_owned) {
        *style_cache = original_style;
        style_owned=0;
    }
    active=job->enabled;
    return NULL;
}

static int sibling(wchar_t *path, const wchar_t *name)
{
    HMODULE module = NULL;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)&sibling, &module)) return 0;
    DWORD length = GetModuleFileNameW(module, path, MAX_PATH);
    if (!length || length >= MAX_PATH) return 0;
    while (length && path[length - 1] != L'\\' && path[length - 1] != L'/') --length;
    if (length + wcslen(name) >= MAX_PATH) return 0;
    wcscpy(path + length, name);
    return 1;
}

/* Read-only capability probe. It resolves code but creates no hooks and never
   changes preferences or gameplay state. Features are independent. */
__declspec(dllexport) int skieo_trail_ratings_capabilities(void *lua_state)
{
    (void)lua_state;
    const char *failure=resolve_image();
    int slope=!failure && !resolve_profile(1,0,0);
    int palette=!failure && !resolve_profile(0,1,0);
    int color=!failure && !resolve_profile(0,0,1);
    wchar_t path[MAX_PATH];
    if(!sibling(path,L"native_trail_ratings.capabilities.json"))return 0;
    FILE *f=_wfopen(path,L"wb");
    if(f) {
        fprintf(f,"{\"thresholds\":%s,\"style\":%s,\"colors\":%s,"
            "\"addresses\":{\"calculate\":%u,\"palette\":%u,\"color\":%u,\"style\":%u},"
            "\"mode\":\"guarded_relocation\",\"detail\":\"%s\"}",
            slope?"true":"false",palette?"true":"false",color?"true":"false",
            resolution.calculate,resolution.palette,resolution.color,resolution.style,
            failure?failure:(slope && palette && color)?"unique code shapes and cross-references checked":
                "unavailable contracts are missing, changed or ambiguous");
        fclose(f);
    }
    return 0;
}

/* Lua C callback uses the loader's bounded file ABI, without a second Lua VM.
   MinHook suspends peer threads and relocates instruction pointers when
   enabling/disabling the detour. Configuration stays allocated for readers
   already inside the callback when a map stops. */
__declspec(dllexport) int skieo_trail_ratings(void *lua_state)
{
    (void)lua_state;
    wchar_t path[MAX_PATH];
    if (!sibling(path, L"native_trail_ratings.job")) return 0;
    RatingJob job;
    const char *failure = "missing trail rating job";
    FILE *file = _wfopen(path, L"rb");
    if (file) {
        size_t size = fread(&job, 1, sizeof(job), file);
        int trailing = fgetc(file);
        fclose(file);
        failure = size == sizeof(job) && trailing == EOF ? apply(&job) : "invalid trail rating job size";
    }
    if (!sibling(path, L"native_trail_ratings.status")) return 0;
    file = _wfopen(path, L"wb");
    if (file) { if (failure) fprintf(file, "error: %s", failure); else fputs("ok", file); fclose(file); }
    return 0;
}
