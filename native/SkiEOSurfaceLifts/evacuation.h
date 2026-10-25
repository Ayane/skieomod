/* Game-thread-only evacuation bridge for reviewed build 26178224. Guests ski
   on closed native trails: ordinary movement, snow contact and save data apply.
   Waiting gates stop the three native snowcat movement phases before they can
   advance a blade or a job. Other trails and native breakdowns keep running. */
typedef void (*EvacClearRoute)(void *);
typedef uint8_t *(*EvacAddStep)(void *);
typedef void (*EvacResize)(int,int,int,Array *,int,int *);
typedef void (*EvacActivity)(void *,void *,uint8_t);
typedef void (*EvacLane)(void *,void *,int,void *,void *,int);
typedef void (*EvacGroomStep)(void *,uint8_t *,float);
static EvacGroomStep evac_groom_original[3];
static uintptr_t evac_groom_owner;
enum {EVAC_WAIT_MAX=272};
typedef struct {int32_t id;uint32_t blocked;} EvacCorridor;
static EvacCorridor evac_waiting[EVAC_WAIT_MAX];
static uint32_t evac_waiting_count;
static SRWLOCK evac_lock=SRWLOCK_INIT;
static int evac_ready;
static int evac_waits(void *owner,uint8_t *vehicle)
{
    int waiting=0;
    AcquireSRWLockShared(&evac_lock);
    if((uintptr_t)owner==evac_groom_owner&&readable(vehicle,0x318)) {
        int32_t trail;memcpy(&trail,vehicle+0x7c,4);
        for(uint32_t i=0;i<evac_waiting_count;i++)if(trail==evac_waiting[i].id){
            /* Native lane planning otherwise offsets the blade towards pylons.
               The reviewed position helper reads this exact lateral field. */
            float center=0;memcpy(vehicle+0xe4,&center,4);
            waiting=evac_waiting[i].blocked!=0;break;
        }
    }
    ReleaseSRWLockShared(&evac_lock);return waiting;
}
static void evac_groom_deploy(void *o,uint8_t *v,float dt){if(!evac_waits(o,v))evac_groom_original[0](o,v,dt);}
static void evac_groom_grade(void *o,uint8_t *v,float dt){if(!evac_waits(o,v))evac_groom_original[1](o,v,dt);}
static void evac_groom_turn(void *o,uint8_t *v,float dt){if(!evac_waits(o,v))evac_groom_original[2](o,v,dt);}
static const char *evac_prepare(void)
{
    if(evac_ready)return NULL;
    uint8_t *base=(uint8_t *)GetModuleHandleW(NULL);
    const struct {uint32_t rva,size;uint64_t digest;} guards[]={
        {0x5183e80,0x28a,UINT64_C(0x240cc9eeb81b1cb5)}, /* ChangeActivity */
        {0x4fcae70,0x87,UINT64_C(0x1229477397293627)}, /* Normal unboarding counters and status */
        {0x519cd40,0x83,UINT64_C(0x4275adde08ac83ba)}, /* ClearRoute, with destructors */
        {0x55a1540,0x72,UINT64_C(0xfe2a46af66488451)}, /* Add initialized route step */
        {0x1288d10,0x76,UINT64_C(0x01737a32de33f82c)}, /* Native array allocation */
        {0x51e4450,0x11a,UINT64_C(0xbc93b3c8c85683a8)}, /* Project skiing lane */
        {0x55a3ab0,0x2d0,UINT64_C(0xc48af84a17bc74c9)}, /* Native lift release and guest layout */
        {0x52f2c50,0x330,UINT64_C(0xaca7a5be7e0216df)}, /* Grooming lateral position */
        {0x530de50,0x2ce,UINT64_C(0x4dd4f1ce6786fd82)},
        {0x530e120,0x7f0,UINT64_C(0x48f4a350e178fcca)},
        {0x530e910,0x937,UINT64_C(0x03eff6de9eebd6b5)},
    };
    for(unsigned i=0;i<sizeof guards/sizeof guards[0];i++)
        if(!readable(base+guards[i].rva,guards[i].size)||hash(base+guards[i].rva,guards[i].size)!=guards[i].digest)
            return "unreviewed native evacuation or snowcat layout";
    MH_STATUS s=MH_Initialize();if(s!=MH_OK&&s!=MH_ERROR_ALREADY_INITIALIZED)return "evacuation hook initialization failed";
    uint32_t targets[]={0x530de50,0x530e120,0x530e910};
    EvacGroomStep replacements[]={evac_groom_deploy,evac_groom_grade,evac_groom_turn};
    unsigned created=0,enabled=0;
    for(;created<3;created++)if(MH_CreateHook(base+targets[created],replacements[created],(void **)&evac_groom_original[created])!=MH_OK)break;
    if(created==3)for(;enabled<3;enabled++)if(MH_EnableHook(base+targets[enabled])!=MH_OK)break;
    if(created!=3||enabled!=3){
        for(unsigned i=0;i<enabled;i++)MH_DisableHook(base+targets[i]);
        for(unsigned i=0;i<created;i++)MH_RemoveHook(base+targets[i]);
        return "native snowcat waiting hooks unavailable";
    }
    evac_ready=1;return NULL;
}
typedef struct EvacEntry {
    uint32_t index,id[4];int32_t trail;
    double target[3];
} EvacEntry;
typedef struct EvacHeader {
    char magic[4];uint32_t version,count,reserved;
    uint64_t owner,owner_class,trails,trails_class,lift,lift_class;
} EvacHeader;
_Static_assert(sizeof(EvacEntry)==48,"evacuation entry layout");
_Static_assert(sizeof(EvacHeader)==64,"evacuation header layout");
static int evac_object(uint64_t address,uint64_t cls,size_t size)
{
    if(!address||!cls||!readable((void *)(uintptr_t)address,size))return 0;
    uint64_t actual;memcpy(&actual,(uint8_t *)(uintptr_t)address+0x10,8);return actual==cls;
}
__declspec(dllexport) int skieo_surface_evacuate(void *lua)
{
    (void)lua;wchar_t p[MAX_PATH];if(!path(p,L"surface-evacuation.job"))return 0;
    FILE *f=_wfopen(p,L"rb");if(!f)return 0;
    EvacHeader j={0};const char *error=NULL;EvacEntry *entries=NULL;
    if(fread(&j,1,sizeof j,f)!=sizeof j||memcmp(j.magic,"SKEV",4)||j.version!=1||j.reserved||j.count>4096)error="invalid evacuation header";
    if(!error&&j.count){entries=calloc(j.count,sizeof *entries);if(!entries||fread(entries,sizeof *entries,j.count,f)!=j.count)error="incomplete evacuation batch";}
    if(!error&&fgetc(f)!=EOF)error="trailing evacuation data";
    fclose(f);
    if(!error)error=evac_prepare();
    if(!error&&(!evac_object(j.owner,j.owner_class,0x78)||!evac_object(j.trails,j.trails_class,0x330)))error="invalid evacuation world";
    if(!error&&j.count&&!evac_object(j.lift,j.lift_class,0x440))error="invalid evacuation lift";
    Array *cold=(Array *)(uintptr_t)(j.owner+0x58),*hot=(Array *)(uintptr_t)(j.owner+0x68);
    if(!error&&(cold->count<0||cold->count>20000||cold->count!=hot->count||cold->capacity<cold->count||hot->capacity<hot->count
        ||(cold->count&&(!readable(cold->data,(size_t)cold->count*0xba0)||!readable(hot->data,(size_t)hot->count*0x80)))))error="invalid native guest arrays";
    /* Validate the whole batch before changing the first guest. The normal
       OnLiftDeleted release was called synchronously on the game thread. */
    for(uint32_t i=0;!error&&i<j.count;i++){
        EvacEntry *e=entries+i;
        if(e->index>=(uint32_t)cold->count||e->trail<=0||memcmp(cold->data+(size_t)e->index*0xba0,e->id,16)
            ||hot->data[(size_t)e->index*0x80+0x68]!=1)error="evacuation guest changed before release";
        for(unsigned k=0;k<3;k++)if(!isfinite(e->target[k])||fabs(e->target[k])>=1e7)error="invalid evacuation destination";
        for(uint32_t k=0;k<i;k++)if(entries[k].index==e->index)error="duplicate evacuation guest";
    }
    if(!error){
        uint8_t *base=(uint8_t *)GetModuleHandleW(NULL);
        for(uint32_t i=0;i<j.count;i++){
            EvacEntry *e=entries+i;uint8_t *c=cold->data+(size_t)e->index*0xba0,*h=hot->data+(size_t)e->index*0x80;
            /* Guest lift reservations use None (0); seated/standing venue
               reservations belong to other interaction kinds and staff. */
            ((void (*)(void *,uint8_t))(base+0x4fcae70))((void *)(uintptr_t)j.lift,0);
            ((EvacClearRoute)(base+0x519cd40))(c+0x928);
            uint8_t *step=((EvacAddStep)(base+0x55a1540))(c+0x928);
            step[0]=3;step[0x20]=9;memcpy(step+8,e->target,24);memcpy(step+0x54,&e->trail,4);
            /* TrailPath contains native trail IDs, never world coordinates. */
            Array *ids=(Array *)(step+0x58);
            ((EvacResize)(base+0x1288d10))(4,4,1,ids,0,&ids->capacity);
            memcpy(ids->data,&e->trail,4);ids->count=1;
            memset(c+0xa30,0,16);memset(c+0x9b0,0,4);memcpy(h+0x54,&e->trail,4);
            /* Keep a single file through the narrow service corridor. */
            float bias=0;memcpy(c+0x328,&bias,4);
            ((EvacActivity)(base+0x5183e80))(c,h,4);
            int32_t tile[4]={0};((EvacLane)(base+0x51e4450))(c,(void *)(uintptr_t)j.trails,e->trail,h,tile,0);
        }
    }
    free(entries);if(!path(p,L"surface-evacuation.status"))return 0;
    f=_wfopen(p,L"wb");if(f){fprintf(f,"%s: %s; guests=%u",error?"error":"ok",error?error:"native service descent",j.count);fclose(f);}return 0;
}
__declspec(dllexport) int skieo_surface_wait(void *lua)
{
    (void)lua;wchar_t p[MAX_PATH];if(!path(p,L"surface-wait.job"))return 0;
    FILE *f=_wfopen(p,L"rb");if(!f)return 0;
    struct {char magic[4];uint32_t version,count,reserved;uint64_t owner,cls;EvacCorridor corridors[EVAC_WAIT_MAX];}j={0};
    size_t n=fread(&j,1,sizeof j,f);int extra=fgetc(f);fclose(f);
    const char *error=NULL;
    if(n!=sizeof j||extra!=EOF||memcmp(j.magic,"SKWT",4)||j.version!=2||j.reserved||j.count>EVAC_WAIT_MAX)error="invalid snowcat waiting job";
    if(!error)error=evac_prepare();
    if(!error&&j.count&&!evac_object(j.owner,j.cls,0x88))error="invalid native grooming world";
    for(uint32_t i=0;!error&&i<j.count;i++)if(j.corridors[i].id<=0||j.corridors[i].blocked>1)error="invalid waiting trail";
    for(uint32_t i=1;!error&&i<j.count;i++)if(j.corridors[i-1].id>=j.corridors[i].id)error="duplicate or unordered waiting trail";
    if(!error){AcquireSRWLockExclusive(&evac_lock);evac_groom_owner=(uintptr_t)j.owner;evac_waiting_count=j.count;memcpy(evac_waiting,j.corridors,sizeof evac_waiting);ReleaseSRWLockExclusive(&evac_lock);}
    if(!path(p,L"surface-wait.status"))return 0;
    f=_wfopen(p,L"wb");if(f){fprintf(f,"%s: %s; corridors=%u",error?"error":"ok",error?error:"native snowcats waiting",j.count);fclose(f);}return 0;
}
