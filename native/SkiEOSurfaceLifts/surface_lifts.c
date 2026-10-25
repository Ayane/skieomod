#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
#include "../SkiEOTrailRatings/vendor/minhook/include/MinHook.h"
#include "reviewed_build.h"
#include "track_policy.h"
/* Render-only override. Guest activity, queues and travel bookkeeping remain
   native RidingLift. The game's VAT renderer chooses its equipped skier or
   snowboarder from this animation result, including foot/boot attachment. */
typedef uint8_t (*Animation)(const uint8_t *,const uint8_t *,const void *);
typedef struct Tow { uint32_t id[4]; float speed; } Tow;
typedef struct Job {char magic[4];uint32_t version,count,posed_count;Tow lifts[16];uint32_t posed[64][4];} Job;
typedef struct Array {uint8_t *data;int32_t count,capacity;} Array;
typedef uint8_t (*GuestRender)(void *,int32_t,const Array *,const Array *,void *,void *,uint8_t,void *);
static GuestRender original_guest_render;
typedef void (*Stamp)(void *,float,uint8_t,const Array *,const Array *);
static uint32_t posed[64][4],posed_count;
static uint64_t pose_count;
static Tow lifts[16];static uint32_t count;static Animation original_animation;
static Stamp original_stamp;
/* The native collector receives several changing batches, not the complete
   guest array. History must be keyed by GUID, never by a batch index/count. */
static Previous *previous;
static int installed;static SRWLOCK lock=SRWLOCK_INIT;
static uint64_t render_count;
static uint64_t track_count;
static int tow(const uint8_t *guest)
{
    int result=0;AcquireSRWLockShared(&lock);
    for(uint32_t i=0;i<count;i++)if(!memcmp(guest+0xa30,lifts[i].id,16)){result=1;break;}
    ReleaseSRWLockShared(&lock);return result;
}
/* The crowd's single-guest builder is synchronous within its joined parallel
   batch. Omit only GUIDs whose native skeletal replacement is ready this frame. */
static uint8_t guest_render(void *owner,int32_t index,const Array *cold,const Array *hot,
                            void *interactions,void *settings,uint8_t flag,void *output)
{
    int hidden=0;
    if(cold&&hot&&index>=0&&index<cold->count&&index<hot->count&&hot->data[index*0x80+0x68]==3){
        const uint8_t *guest=cold->data+(size_t)index*0xba0;
        AcquireSRWLockShared(&lock);
        for(uint32_t i=0;i<posed_count;i++)if(!memcmp(guest,posed[i],16)){hidden=1;break;}
        ReleaseSRWLockShared(&lock);
    }
    if(hidden){InterlockedIncrement64((volatile LONG64 *)&pose_count);return 0;}
    return original_guest_render(owner,index,cold,hot,interactions,settings,flag,output);
}
static uint8_t animation(const uint8_t *guest,const uint8_t *hot,const void *interaction)
{
    if(hot[0x68]==3) {
        if(tow(guest)){InterlockedIncrement64((volatile LONG64 *)&render_count);return guest[0x1d]==1?19:2;}
    }
    return original_animation(guest,hot,interaction);
}
/* Native footprint collection excludes RidingLift. Supply a private render/
   imprint copy to that collector only. It appends ordinary ski/snowboard stamps
   to the native snow simulation; no simulation guest is ever changed to Skiing.
   Measured displacement prevents stopped lifts, pauses and teleports stamping. */
static void stamp(void *owner,float dt,uint8_t clear,const Array *cold,const Array *hot)
{
    if(clear||!count||!cold||!hot||cold->count!=hot->count||hot->count<0||hot->count>20000||!(dt>0&&dt<5)) {
        original_stamp(owner,dt,clear,cold,hot);return;
    }
    size_t n=(size_t)hot->count;
    if(!previous)previous=calloc(HISTORY_SIZE,sizeof *previous);
    uint8_t *copy=n&&previous?malloc(n*0x80):NULL;
    if(!copy){original_stamp(owner,dt,clear,cold,hot);return;}
    memcpy(copy,hot->data,n*0x80);
    ULONGLONG now=GetTickCount64();
    for(size_t i=0;i<n;i++) {
        const uint8_t *guest=cold->data+i*0xba0;uint8_t *h=copy+i*0x80;
        if(h[0x68]!=3||!tow(guest))continue;
        if(towing_velocity(previous,guest,(const double *)h,dt,now,(double *)(h+0x18))) {
            h[0x68]=4;h[0x79]=0;h[0x7a]=0;track_count++;
        }
    }
    Array visual={copy,hot->count,hot->count};original_stamp(owner,dt,clear,cold,&visual);free(copy);
}
static int readable(const void *p,size_t n)
{
    MEMORY_BASIC_INFORMATION m;
    return VirtualQuery(p,&m,sizeof m)==sizeof m&&m.State==MEM_COMMIT&&
        !(m.Protect&(PAGE_NOACCESS|PAGE_GUARD))&&(uintptr_t)p>=(uintptr_t)m.BaseAddress&&
        n<=m.RegionSize-((uintptr_t)p-(uintptr_t)m.BaseAddress);
}
static int path(wchar_t *out,const wchar_t *name)
{
    HMODULE module=NULL;
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(LPCWSTR)&path,&module))return 0;
    if(!GetModuleFileNameW(module,out,MAX_PATH))return 0;
    wchar_t *slash=wcsrchr(out,L'\\');if(!slash||slash-out+wcslen(name)+2>=MAX_PATH)return 0;
    wcscpy(slash+1,name);return 1;
}
static uint64_t hash(const uint8_t *p,size_t n)
{uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<n;i++){h^=p[i];h*=UINT64_C(1099511628211);}return h;}
__declspec(dllexport) int skieo_surface_lifts(void *lua)
{
    (void)lua;wchar_t p[MAX_PATH];if(!path(p,L"surface-lifts.job"))return 0;
    FILE *f=_wfopen(p,L"rb");if(!f)return 0;Job j={0};size_t n=fread(&j,1,sizeof j,f);fclose(f);
    if(!path(p,L"surface-lifts.status"))return 0;
    f=_wfopen(p,L"wb");if(!f)return 0;
    const char *error=NULL;MH_STATUS hook_status=MH_OK;
    if(n!=sizeof j||memcmp(j.magic,"SKTL",4)||j.version!=2||j.count>16||j.posed_count>64)error="invalid surface lift job";
    for(uint32_t i=0;!error&&i<j.count;i++)if(!(j.lifts[i].speed>=50&&j.lifts[i].speed<=500))error="invalid towing speed";
    if(!error&&j.count&&!installed){
        uint8_t *base=(uint8_t *)GetModuleHandleW(NULL);
        int newer=readable(base+ANIMATION_NEW_RVA,ANIMATION_SIZE)&&hash(base+ANIMATION_NEW_RVA,ANIMATION_SIZE)==ANIMATION_NEW_HASH;
        uint8_t *target=base+(newer?ANIMATION_NEW_RVA:ANIMATION_RVA);
        uint8_t *tracks=base+(newer?STAMP_NEW_RVA:STAMP_RVA);
        uint8_t *render=base+(newer?GUEST_RENDER_NEW_RVA:GUEST_RENDER_RVA);
        if(!readable(target,ANIMATION_SIZE)||hash(target,ANIMATION_SIZE)!=(newer?ANIMATION_NEW_HASH:ANIMATION_HASH))error="unreviewed guest animation function";
        else if(!readable(tracks,STAMP_SIZE)||hash(tracks,STAMP_SIZE)!=(newer?STAMP_NEW_HASH:STAMP_HASH))error="unreviewed snow stamp collector";
        else if(!readable(render,GUEST_RENDER_SIZE)||hash(render,GUEST_RENDER_SIZE)!=(newer?GUEST_RENDER_NEW_HASH:GUEST_RENDER_HASH))error="unreviewed single-guest renderer";
        else {
            MH_STATUS s=MH_Initialize();
            if(s!=MH_OK&&s!=MH_ERROR_ALREADY_INITIALIZED)error="hook initialization failed";
            else if((hook_status=MH_CreateHook(target,animation,(void **)&original_animation))!=MH_OK)error=MH_StatusToString(hook_status);
            else if(MH_CreateHook(tracks,stamp,(void **)&original_stamp)!=MH_OK){MH_RemoveHook(target);error="snow hook creation failed";}
            else if(MH_CreateHook(render,guest_render,(void **)&original_guest_render)!=MH_OK){MH_RemoveHook(target);MH_RemoveHook(tracks);error="pose hook creation failed";}
            else if(MH_EnableHook(render)!=MH_OK||MH_EnableHook(target)!=MH_OK||MH_EnableHook(tracks)!=MH_OK){MH_DisableHook(render);MH_DisableHook(target);MH_DisableHook(tracks);MH_RemoveHook(render);MH_RemoveHook(target);MH_RemoveHook(tracks);error="surface hooks activation failed";}
            else installed=1;
        }
    }
    if(!error){AcquireSRWLockExclusive(&lock);count=j.count;memcpy(lifts,j.lifts,sizeof lifts);posed_count=j.posed_count;memcpy(posed,j.posed,sizeof posed);ReleaseSRWLockExclusive(&lock);if(!count){free(previous);previous=NULL;}}
    fprintf(f,"%s: %s; equipped renders=%llu; native track stamps=%llu; posed renders=%llu",error?"error":"ok",error?error:"native surface lift visuals",(unsigned long long)render_count,(unsigned long long)track_count,(unsigned long long)pose_count);fclose(f);return 0;
}
#include "contact_read.h"
#include "snow_grade.h"
#include "evacuation.h"
