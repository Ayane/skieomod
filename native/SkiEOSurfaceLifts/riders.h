/* One coherent read-only game-thread snapshot avoids thousands of UE4SS
   property wrappers per frame. Layout comes from the reviewed guest renderer
   and evacuation bridge; both must already have passed their full guards. */
typedef struct RiderRow {
    uint32_t index,discipline;int32_t color;uint32_t reserved;
    uint32_t guest[4],lift[4];double position[3];
} RiderRow;
_Static_assert(sizeof(RiderRow)==72,"rider snapshot layout");
__declspec(dllexport) int skieo_surface_riders(void *lua)
{
    (void)lua;wchar_t p[MAX_PATH];if(!path(p,L"surface-riders.job"))return 0;
    FILE *f=_wfopen(p,L"rb");if(!f)return 0;
    struct {char magic[4];uint32_t version;uint64_t owner,cls;uint32_t nonce,reserved;}j={0};
    size_t n=fread(&j,1,sizeof j,f);int extra=fgetc(f);fclose(f);const char *error=NULL;
    if(n!=sizeof j||extra!=EOF||memcmp(j.magic,"SKRD",4)||j.version!=1||j.reserved)error="invalid rider snapshot job";
    if(!error&&(!installed||!evac_ready))error="guest layout has not passed its full native guards";
    if(!error&&!evac_object(j.owner,j.cls,0x78))error="invalid guest snapshot owner";
    Array *cold=(Array *)(uintptr_t)(j.owner+0x58),*hot=(Array *)(uintptr_t)(j.owner+0x68);
    if(!error&&(cold->count<0||cold->count>20000||cold->count!=hot->count||cold->capacity<cold->count||hot->capacity<hot->count
        ||(cold->count&&(!readable(cold->data,(size_t)cold->count*0xba0)||!readable(hot->data,(size_t)hot->count*0x80)))))error="invalid guest snapshot arrays";
    RiderRow *rows=NULL;uint32_t total=0;
    if(!error&&cold->count){rows=calloc((size_t)cold->count,sizeof *rows);if(!rows)error="rider snapshot allocation failed";}
    Tow selected[16];uint32_t selected_count=0;
    AcquireSRWLockShared(&lock);selected_count=count;memcpy(selected,lifts,sizeof selected);ReleaseSRWLockShared(&lock);
    if(selected_count>16)error="invalid snapshot lift registry";
    if(!error)for(int32_t i=0;i<cold->count;i++){
        const uint8_t *c=cold->data+(size_t)i*0xba0,*h=hot->data+(size_t)i*0x80;
        if(h[0x68]!=3)continue;
        int owned=0;for(uint32_t k=0;k<selected_count;k++)if(!memcmp(c+0xa30,selected[k].id,16)){owned=1;break;}
        if(!owned)continue;
        double position[3];memcpy(position,h,24);
        if(!isfinite(position[0])||!isfinite(position[1])||!isfinite(position[2]))continue;
        RiderRow *r=rows+total++;r->index=(uint32_t)i;r->discipline=c[0x1d];memcpy(&r->color,h+0x50,4);
        memcpy(r->guest,c,16);memcpy(r->lift,c+0xa30,16);memcpy(r->position,position,24);
    }
    if(path(p,L"surface-riders.bin")){
        f=_wfopen(p,L"wb");if(f){
            struct {char magic[4];uint32_t version,nonce,count;}header={{'S','K','R','D'},1,j.nonce,total};
            if(error)memcpy(header.magic,"SKER",4);
            fwrite(&header,1,sizeof header,f);if(!error&&total)fwrite(rows,sizeof *rows,total,f);fclose(f);
        }
    }
    free(rows);
    if(error&&path(p,L"surface-riders.status")){f=_wfopen(p,L"wb");if(f){fputs(error,f);fclose(f);}}
    return 0;
}
