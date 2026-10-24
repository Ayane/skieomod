/* Native Clear Snow operation: centre FVector2D, radius cm, target depth cm
   and per-call removal budget cm. Updates tiled snow and the coarse cache.
   Readback textures are outputs and must never be used to edit snow. */
typedef struct GradeJob {
    char magic[4];uint32_t version,count,reserved;uint64_t owner,owner_class;
} GradeJob;
typedef struct GradePoint {double x,y;float radius,budget;} GradePoint;
__declspec(dllexport) int skieo_surface_grade(void *lua)
{
    (void)lua;wchar_t filename[MAX_PATH];GradeJob j={0};GradePoint points[256];
    const char *error="invalid native snow grading job";unsigned applied=0;
    if(!path(filename,L"surface-grade.job"))return 0;
    FILE *f=_wfopen(filename,L"rb");if(!f)return 0;
    size_t bytes=fread(&j,1,sizeof j,f);
    size_t n=j.count<=256?fread(points,sizeof *points,j.count,f):0;
    int extra=fgetc(f);fclose(f);
    if(bytes!=sizeof j||n!=j.count||!n||extra!=EOF||memcmp(j.magic,"SKSG",4)||j.version!=2||j.reserved
        ||!contact_object(j.owner,j.owner_class))goto done;
    for(size_t i=0;i<n;i++){
        GradePoint *p=&points[i];
        if(!isfinite(p->x)||!isfinite(p->y)||fabs(p->x)>1e8||fabs(p->y)>1e8
            ||!isfinite(p->radius)||p->radius<100||p->radius>300
            ||!isfinite(p->budget)||p->budget<=0||p->budget>500)goto done;
    }
    uint8_t *base=(uint8_t *)GetModuleHandleW(NULL);
    error="unreviewed native snow-clear operation";
    if(!readable(base+SNOW_CLEAR_RVA,SNOW_CLEAR_SIZE)||hash(base+SNOW_CLEAR_RVA,SNOW_CLEAR_SIZE)!=SNOW_CLEAR_HASH
        ||!readable(base+SNOW_CLEAR_CORE_RVA,SNOW_CLEAR_CORE_SIZE)||hash(base+SNOW_CLEAR_CORE_RVA,SNOW_CLEAR_CORE_SIZE)!=SNOW_CLEAR_CORE_HASH)goto done;
    typedef void (*Clear)(void *,const double *,float,float,float);
    Clear clear=(Clear)(base+SNOW_CLEAR_RVA);
    for(size_t i=0;i<n;i++){
        GradePoint *p=&points[i];double centre[2]={p->x,p->y};
        clear((void *)(uintptr_t)j.owner,centre,p->radius,80.0f,p->budget);applied++;
    }
    error=NULL;
done:
    if(path(filename,L"surface-grade.status")){
        f=_wfopen(filename,L"wb");if(f){fprintf(f,"%s: %s; stamps=%u",error?"error":"ok",error?error:"native snowcat blade",applied);fclose(f);}
    }
    return 0;
}
