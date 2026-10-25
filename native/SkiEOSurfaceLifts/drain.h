/* Keep a detachable installation in native WindingDown while its retained
   hangers return to stock. Native event stops, boarding and accounting remain
   authoritative; no fabricated riders or virtual passenger counts are used. */
typedef uint8_t (*DrainState)(void *);
typedef float (*DrainSpeed)(void *);
static DrainState drain_state_original;
static DrainSpeed drain_speed_original;
typedef struct {uint64_t lift,cls;float speed;uint32_t reserved;} DrainEntry;
static DrainEntry drain_entries[16];
static uint32_t drain_count;
static SRWLOCK drain_lock=SRWLOCK_INIT;
static int drain_ready;
static float drain_for(void *lift)
{
    float speed=0;AcquireSRWLockShared(&drain_lock);
    for(uint32_t i=0;i<drain_count;i++)if(drain_entries[i].lift==(uintptr_t)lift
        &&evac_object(drain_entries[i].lift,drain_entries[i].cls,0x600)){
        float operating;memcpy(&operating,(uint8_t *)lift+0x464,4);
        if(isfinite(operating)&&operating>0)speed=drain_entries[i].speed;
        break;
    }
    ReleaseSRWLockShared(&drain_lock);return speed;
}
static uint8_t drain_state(void *lift)
{
    uint8_t state=drain_state_original(lift);
    return(state==1||state==4)&&drain_for(lift)>0?1:state;
}
static float drain_speed(void *lift)
{
    float speed=drain_speed_original(lift),requested=drain_for(lift);
    uint8_t state=drain_state_original(lift);
    if(requested>0&&(state==1||state==4))return speed>0?fminf(speed,requested):requested;
    return speed;
}
static const char *drain_prepare(void)
{
    if(drain_ready)return NULL;
    uint8_t *base=(uint8_t *)GetModuleHandleW(NULL);
    /* Full reviewed code, including all rider/staff/event branches. */
    if(!readable(base+0x4fbf680,0x24a)||hash(base+0x4fbf680,0x24a)!=UINT64_C(0x46b447bbfde66ab2)
        ||!readable(base+0x4fc3f40,0xd6)||hash(base+0x4fc3f40,0xd6)!=UINT64_C(0xaa37c076cac83575))
        return "unreviewed native wind-down layout";
    MH_STATUS s=MH_Initialize();if(s!=MH_OK&&s!=MH_ERROR_ALREADY_INITIALIZED)return "wind-down hook initialization failed";
    if(MH_CreateHook(base+0x4fbf680,drain_state,(void **)&drain_state_original)!=MH_OK)return "wind-down state hook unavailable";
    if(MH_CreateHook(base+0x4fc3f40,drain_speed,(void **)&drain_speed_original)!=MH_OK){MH_RemoveHook(base+0x4fbf680);return "wind-down speed hook unavailable";}
    if(MH_EnableHook(base+0x4fbf680)!=MH_OK||MH_EnableHook(base+0x4fc3f40)!=MH_OK){
        MH_DisableHook(base+0x4fbf680);MH_DisableHook(base+0x4fc3f40);MH_RemoveHook(base+0x4fbf680);MH_RemoveHook(base+0x4fc3f40);
        return "wind-down hooks could not be enabled";
    }
    drain_ready=1;return NULL;
}
__declspec(dllexport) int skieo_surface_drain(void *lua)
{
    (void)lua;wchar_t p[MAX_PATH];if(!path(p,L"surface-drain.job"))return 0;
    FILE *f=_wfopen(p,L"rb");if(!f)return 0;
    struct {char magic[4];uint32_t version,count,reserved;DrainEntry entries[16];}j={0};
    size_t n=fread(&j,1,sizeof j,f);int extra=fgetc(f);fclose(f);const char *error=NULL;
    if(n!=sizeof j||extra!=EOF||memcmp(j.magic,"SKDR",4)||j.version!=1||j.count>16||j.reserved)error="invalid wind-down job";
    for(uint32_t i=0;!error&&i<j.count;i++){
        DrainEntry *e=j.entries+i;
        if(!evac_object(e->lift,e->cls,0x600)||e->reserved||!isfinite(e->speed)||e->speed<30||e->speed>500)error="invalid wind-down lift";
        for(uint32_t k=0;k<i;k++)if(j.entries[k].lift==e->lift)error="duplicate wind-down lift";
    }
    if(!error)error=drain_prepare();
    if(!error){AcquireSRWLockExclusive(&drain_lock);memcpy(drain_entries,j.entries,sizeof drain_entries);drain_count=j.count;ReleaseSRWLockExclusive(&drain_lock);}
    if(!path(p,L"surface-drain.status"))return 0;
    f=_wfopen(p,L"wb");if(f){fprintf(f,"%s: %s; lifts=%u",error?"error":"ok",error?error:"native detachable wind-down",j.count);fclose(f);}return 0;
}
