/* Read our own small terrain-only depth capture through the reflected engine
   API. Avoid creating a Lua userdata for every pixel. No game layout offsets
   beyond UObject::ClassPrivate; Lua verifies the complete parameter layout. */
typedef struct ContactJob {
    char magic[4]; uint32_t version, side, reserved;
    uint64_t world, library, library_class, target, target_class, function, function_class;
} ContactJob;
typedef struct ContactParams {
    void *world,*target; int32_t x,y,width,height; uint8_t normalize,pad[7]; Array pixels;
} ContactParams;
_Static_assert(sizeof(ContactParams)==56,"Reflected readback parameters changed");
static int contact_object(uint64_t address,uint64_t cls)
{
    uint64_t actual=0;
    if(!address||!cls||!readable((void *)(uintptr_t)address,0x28))return 0;
    memcpy(&actual,(uint8_t *)(uintptr_t)address+0x10,8);return actual==cls;
}
__declspec(dllexport) int skieo_surface_contact(void *lua)
{
    (void)lua;wchar_t filename[MAX_PATH];
    if(!path(filename,L"surface-contact.job"))return 0;
    FILE *f=_wfopen(filename,L"rb");if(!f)return 0;
    ContactJob j={0};size_t n=fread(&j,1,sizeof j,f);int extra=fgetc(f);fclose(f);
    if(!path(filename,L"surface-contact.bin"))return 0;
    f=_wfopen(filename,L"wb");if(!f)return 0;
    if(n!=sizeof j||extra!=EOF||memcmp(j.magic,"SKSC",4)||j.version!=1||j.reserved
        ||j.side<64||j.side>1024||(j.side&(j.side-1))
        ||!contact_object(j.library,j.library_class)||!contact_object(j.target,j.target_class)
        ||!contact_object(j.function,j.function_class)||!readable((void *)(uintptr_t)j.world,0x28))goto done;
    HMODULE module=GetModuleHandleW(L"UE4SS.dll");
    typedef void (*Event)(void *,void *,void *);
    typedef void (*Free)(void *);
    typedef const uint16_t *(*ParamSize)(void *);
    Event event=NULL;Free release=NULL;ParamSize size=NULL;FARPROC symbol;
    symbol=GetProcAddress(module,"?ProcessEvent@UObject@Unreal@RC@@QEAAXPEAVUFunction@23@PEAX@Z");memcpy(&event,&symbol,sizeof event);
    symbol=GetProcAddress(module,"?Free@FMemory@Unreal@RC@@SAXPEAX@Z");memcpy(&release,&symbol,sizeof release);
    symbol=GetProcAddress(module,"?GetParmsSize@UFunction@Unreal@RC@@QEBAAEBGXZ");memcpy(&size,&symbol,sizeof size);
    if(!event||!release||!size)goto done;
    const uint16_t *bytes=size((void *)(uintptr_t)j.function);
    if(!readable(bytes,2)||*bytes!=sizeof(ContactParams))goto done;
    ContactParams p={.world=(void *)(uintptr_t)j.world,.target=(void *)(uintptr_t)j.target,
        .width=(int32_t)j.side,.height=(int32_t)j.side};
    event((void *)(uintptr_t)j.library,(void *)(uintptr_t)j.function,&p);
    size_t count=(size_t)j.side*j.side;
    if(p.pixels.count==(int32_t)count&&p.pixels.capacity>=p.pixels.count&&p.pixels.capacity<=(int32_t)count*2
        &&readable(p.pixels.data,count*16)) {
        float *depth=malloc(count*sizeof(float));
        if(depth){
            for(size_t i=0;i<count;i++)memcpy(depth+i,p.pixels.data+i*16,4);
            fwrite(depth,sizeof(float),count,f);free(depth);
        }
    }
    if(p.pixels.data)release(p.pixels.data);
done:
    fclose(f);return 0;
}
