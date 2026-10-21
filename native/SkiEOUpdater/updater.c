/* A staged update never writes game files while the owning game is alive.
   The journal and backups are durable before the first replacement. */
#include <io.h>
#include "common.h"
typedef struct { char name[241]; wchar_t relative[241]; unsigned char sha[32]; unsigned char *data; uint32_t size; int obsolete,changed,existed; } Entry;
typedef struct { Entry *entries;uint32_t count,obsolete,record_size;unsigned char *record;unsigned char original_record[32];int had_record; } Plan;
static wchar_t stage[PATH_CAP],backup[PATH_CAP];
static int managed(const char *path) {
    size_t n=strlen(path);if(!n||n>240)return 0;
    const char *at=path;
    while(*at) {
        const char *end=strchr(at,'/');size_t len=end?(size_t)(end-at):strlen(at);
        if(!len||at[0]=='.'||at[len-1]=='.'||at[len-1]==' ')return 0;
        char component[241];memcpy(component,at,len);component[len]=0;
        for(size_t i=0;i<len;i++)if((unsigned char)at[i]<32||strchr("\\:*?\"<>|",at[i]))return 0;
        char stem[241];strcpy(stem,component);char *dot=strchr(stem,'.');if(dot)*dot=0;
        if(!_stricmp(stem,"CON")||!_stricmp(stem,"PRN")||!_stricmp(stem,"AUX")||!_stricmp(stem,"NUL")
            ||((!_strnicmp(stem,"COM",3)||!_strnicmp(stem,"LPT",3))&&strlen(stem)==4&&stem[3]>='0'&&stem[3]<='9'))return 0;
        if(!end)break;at=end+1;if(!*at)return 0;
    }
    const char *ext=strrchr(path,'.');
    return !strcmp(path,"LICENSE")||!strcmp(path,"LICENSE-miniz.txt")||!strcmp(path,"Scripts/skieo_updater.exe")
        ||(ext&&(!_stricmp(ext,".lua")||!_stricmp(ext,".dll")||!_stricmp(ext,".md")))
        ||(!strncmp(path,"Examples/",9)&&!strchr(path+9,'/')&&ext&&!strcmp(ext,".skieomap"));
}
static int get_entry(FILE *f,Entry *e,int obsolete) {
    uint16_t n=0;if(!read_exact(f,&n,2)||!n||n>240||!read_exact(f,e->name,n))return 0;
    e->name[n]=0;if(memchr(e->name,0,n)||!managed(e->name)||!read_exact(f,e->sha,32))return 0;
    int wide=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,e->name,-1,e->relative,241);if(!wide)return 0;
    for(wchar_t *p=e->relative;*p;p++)if(*p=='/')*p='\\';
    e->obsolete=obsolete;
    if(obsolete)return 1;
    if(!read_exact(f,&e->size,4)||e->size>FILE_LIMIT)return 0;
    e->data=malloc(e->size?e->size:1);if(!e->data||!read_exact(f,e->data,e->size))return 0;
    unsigned char hash[32];return hash_bytes(e->data,e->size,hash)&&!memcmp(hash,e->sha,32);
}
static int plan_read(const Context *ctx,Plan *p) {
    wchar_t path[PATH_CAP];if(!join(path,ctx->root,BUNDLE)||!safe_tree(ctx->root,path,0))return 0;
    FILE *f=_wfopen(path,L"rb");if(!f)return 0;char magic[4];uint32_t version=0;
    int ok=read_exact(f,magic,4)&&!memcmp(magic,"SKUP",4)&&read_exact(f,&version,4)&&version==1
        &&read_exact(f,&p->count,4)&&p->count>0&&p->count<=COUNT_LIMIT
        &&read_exact(f,&p->obsolete,4)&&p->obsolete<=COUNT_LIMIT-p->count
        &&read_exact(f,&p->record_size,4)&&p->record_size>0&&p->record_size<=1024*1024;
    if(ok) {
        p->record=malloc(p->record_size);p->entries=calloc(p->count+p->obsolete,sizeof(Entry));
        ok=p->record&&p->entries&&read_exact(f,p->record,p->record_size);
    }
    uint64_t total=p->record_size;unsigned required=0;
    for(uint32_t i=0;ok&&i<p->count+p->obsolete;i++) {
        Entry *e=&p->entries[i];ok=get_entry(f,e,i>=p->count);total+=e->size;
        if(total>TOTAL_LIMIT)ok=0;
        for(uint32_t j=0;ok&&j<i;j++)if(!_wcsicmp(e->relative,p->entries[j].relative))ok=0;
        if(i<p->count) {
            if(!strcmp(e->name,"Scripts/main.lua"))required|=1;
            if(!strcmp(e->name,"Scripts/entry.lua"))required|=2;
            if(!strcmp(e->name,"Scripts/skieo_update_bootstrap.dll"))required|=4;
            if(!strcmp(e->name,"Scripts/skieo_updater.exe"))required|=8;
            /* main and the tiny recovery DLL are the stable update ABI. */
            if((!strcmp(e->name,"Scripts/main.lua")||!strcmp(e->name,"Scripts/skieo_update_bootstrap.dll"))
                &&(!join(path,ctx->root,e->relative)||!same_hash(path,e->sha)))ok=0;
        } else if(!strcmp(e->name,"Scripts/main.lua")||!strcmp(e->name,"Scripts/skieo_update_bootstrap.dll"))ok=0;
    }
    ok=ok&&required==15&&fgetc(f)==EOF;fclose(f);return ok;
}
static int stage_plan(const Context *ctx,Plan *p) {
    wchar_t path[PATH_CAP];
    for(uint32_t i=0;i<p->count;i++) {
        Entry *e=&p->entries[i];if(!join(path,stage,e->relative)||!atomic_bytes(ctx->root,path,e->data,e->size))return 0;
        free(e->data);e->data=NULL;
    }
    if(!join(path,stage,RECORD)||!atomic_bytes(ctx->root,path,p->record,p->record_size))return 0;
    if(!join(path,ctx->root,RECORD)||!safe_tree(ctx->root,path,0))return 0;
    p->had_record=GetFileAttributesW(path)!=INVALID_FILE_ATTRIBUTES;
    if(p->had_record&&!file_hash(path,p->original_record))return 0;
    unsigned char original[33]={0};original[0]=(unsigned char)p->had_record;memcpy(original+1,p->original_record,32);
    return join(path,stage,L"original-record")&&atomic_bytes(ctx->root,path,original,sizeof(original));
}
static int copy_atomic(const Context *ctx,const wchar_t *from,const wchar_t *to) {
    wchar_t part[PATH_CAP];
    if(_snwprintf(part,PATH_CAP,L"%ls.part",to)<0||!safe_tree(ctx->root,from,0)||!safe_tree(ctx->root,part,1)||!safe_tree(ctx->root,to,1))return 0;
    if(!CopyFileW(from,part,FALSE))return 0;
    HANDLE h=CreateFileW(part,GENERIC_WRITE,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(h==INVALID_HANDLE_VALUE)return 0;int ok=FlushFileBuffers(h);CloseHandle(h);
    return ok&&MoveFileExW(part,to,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
}
/* The journal includes RECORD as its last entry; missing files are recorded too. */
static int prepare_journal(const Context *ctx,Plan *p) {
    wchar_t path[PATH_CAP],saved[PATH_CAP],journal[PATH_CAP];
    if(!join(journal,backup,L"journal")||!safe_tree(ctx->root,journal,1))return 0;
    FILE *f=_wfopen(journal,L"wb");if(!f)return 0;
    uint32_t count=p->count+p->obsolete+1;int ok=fwrite("SKUJ",1,4,f)==4&&fwrite(&count,4,1,f)==1;
    for(uint32_t i=0;ok&&i<count;i++) {
        Entry record={0};strcpy(record.name,"loader-release.json");wcscpy(record.relative,RECORD);
        Entry *e=i+1==count?&record:&p->entries[i];
        if(!join(path,ctx->root,e->relative)||!safe_tree(ctx->root,path,0)){ok=0;break;}
        e->existed=GetFileAttributesW(path)!=INVALID_FILE_ATTRIBUTES;
        /* A removed upstream file is removed only if still unmodified. */
        e->changed=e->obsolete?(e->existed&&same_hash(path,e->sha)):!same_hash(path,e->sha);
        if(i+1==count)e->changed=1;
        uint16_t n=(uint16_t)strlen(e->name);unsigned char flags=(unsigned char)(e->changed|(e->existed<<1));
        ok=fwrite(&n,2,1,f)==1&&fwrite(e->name,1,n,f)==n&&fwrite(&flags,1,1,f)==1;
        if(ok&&e->changed&&e->existed)ok=join(saved,backup,e->relative)&&copy_atomic(ctx,path,saved);
    }
    ok=ok&&flush_file(f);if(fclose(f))ok=0;return ok;
}
static int rollback(const Context *ctx) {
    wchar_t journal[PATH_CAP],path[PATH_CAP],saved[PATH_CAP];char magic[4];uint32_t count=0;
    if(!join(journal,backup,L"journal")||!safe_tree(ctx->root,journal,0))return 0;
    FILE *f=_wfopen(journal,L"rb");if(!f)return 0;
    int ok=read_exact(f,magic,4)&&!memcmp(magic,"SKUJ",4)&&read_exact(f,&count,4)&&count<=COUNT_LIMIT+1;
    for(uint32_t i=0;ok&&i<count;i++) {
        uint16_t n=0;char name[241]={0};wchar_t relative[241];unsigned char flags=0;
        ok=read_exact(f,&n,2)&&n>0&&n<=240&&read_exact(f,name,n)&&!memchr(name,0,n)
            &&(managed(name)||!strcmp(name,"loader-release.json"))&&read_exact(f,&flags,1)&&flags<=3
            &&MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,name,-1,relative,241)>0;
        if(!ok)break;for(wchar_t *at=relative;*at;at++)if(*at=='/')*at='\\';
        ok=join(path,ctx->root,relative)&&safe_tree(ctx->root,path,0);
        if(ok&&(flags&1)) {
            if(flags&2)ok=join(saved,backup,relative)&&copy_atomic(ctx,saved,path);
            else ok=DeleteFileW(path)||GetLastError()==ERROR_FILE_NOT_FOUND;
        }
    }
    ok=ok&&fgetc(f)==EOF;fclose(f);return ok;
}
static int apply(const Context *ctx,Plan *p) {
    wchar_t original[PATH_CAP],path[PATH_CAP],source[PATH_CAP];unsigned char snapshot[33];
    if(!join(original,stage,L"original-record"))return 0;
    FILE *f=_wfopen(original,L"rb");if(!f)return 0;int ok=read_exact(f,snapshot,sizeof(snapshot))&&fgetc(f)==EOF;fclose(f);
    if(!ok||!join(path,ctx->root,RECORD)||!safe_tree(ctx->root,path,0))return 0;
    unsigned char new_hash[32];if(!hash_bytes(p->record,p->record_size,new_hash))return 0;
    if(same_hash(path,new_hash))return status_write(ctx,"applied","already installed");
    if(snapshot[0]?!same_hash(path,snapshot+1):GetFileAttributesW(path)!=INVALID_FILE_ATTRIBUTES)return 0;
    /* Verify the staged bytes again after the potentially long wait. */
    for(uint32_t i=0;i<p->count;i++)if(!join(source,stage,p->entries[i].relative)||!safe_tree(ctx->root,source,0)||!same_hash(source,p->entries[i].sha))return 0;
    if(!prepare_journal(ctx,p)||!status_write(ctx,"applying","installing prepared update"))return 0;
    for(uint32_t i=0;ok&&i<p->count+p->obsolete;i++) {
        Entry *e=&p->entries[i];if(!e->changed)continue;
        ok=join(path,ctx->root,e->relative)&&safe_tree(ctx->root,path,0);
        if(ok)ok=e->obsolete?DeleteFileW(path):join(source,stage,e->relative)&&copy_atomic(ctx,source,path);
#ifdef SKIEO_UPDATER_TEST
        wchar_t fault[PATH_CAP];join(fault,ctx->root,L"inject-update-failure");
        if(i>=1&&GetFileAttributesW(fault)!=INVALID_FILE_ATTRIBUTES)ok=0;
        join(fault,ctx->root,L"inject-update-crash");
        if(i>=1&&GetFileAttributesW(fault)!=INVALID_FILE_ATTRIBUTES)ExitProcess(88);
#endif
    }
    if(ok)ok=join(source,stage,RECORD)&&join(path,ctx->root,RECORD)&&copy_atomic(ctx,source,path);
    if(!ok) {
        if(!rollback(ctx)){status_write(ctx,"applying","rollback pending; recovery required");return -1;}
        status_write(ctx,"failed","update rolled back; existing mod restored");return -1;
    }
    return status_write(ctx,"applied","update installed");
}
int wmain(int argc,wchar_t **argv) {
    if(argc!=3||(wcscmp(argv[1],L"--stage")&&wcscmp(argv[1],L"--recover")))return 2;
    Context *ctx=calloc(1,sizeof(Context));Plan p={0};if(!ctx||!load_context(argv[2],ctx))return 2;
    HANDLE mutex=update_mutex(ctx,60000);if(!mutex)return 3;
    wchar_t rel[160];swprintf(rel,160,L".skieomod-updates\\%hs\\next",ctx->nonce);if(!join(stage,ctx->root,rel))die("stage path");
    swprintf(rel,160,L".skieomod-backups\\auto-%hs",ctx->nonce);if(!join(backup,ctx->root,rel))die("backup path");
    char phase[32]={0};status_read(ctx,phase,sizeof(phase));
    int recover=!wcscmp(argv[1],L"--recover"), result=0;HANDLE game=game_process(ctx);
    if(recover&&game&&WaitForSingleObject(game,0)==WAIT_TIMEOUT) {CloseHandle(game);result=4;goto done;}
    if(recover&&(!strcmp(phase,"applied")||!strcmp(phase,"failed")))goto done;
    if(recover&&!strcmp(phase,"applying")) {
        if(!rollback(ctx))result=5;
        else status_write(ctx,"failed","interrupted update rolled back; existing mod restored");
        goto done;
    }
    if(!plan_read(ctx,&p)){status_write(ctx,"failed","invalid update bundle or bootstrap requires installer");result=6;goto done;}
    if(!recover) {
        if(!game||WaitForSingleObject(game,0)!=WAIT_TIMEOUT){result=7;goto done;}
        if(!status_write(ctx,"staging","verifying update")||!stage_plan(ctx,&p)||!status_write(ctx,"ready","update prepared; restart to apply")) {
            status_write(ctx,"failed","could not prepare update");result=8;goto done;
        }
        WaitForSingleObject(game,INFINITE);
    } else if(strcmp(phase,"ready")){result=9;goto done;}
    int applied=apply(ctx,&p);
    if(applied==0)status_write(ctx,"failed","prepared update changed or installation unavailable; retry later");
    if(applied<=0){result=10;goto done;}
    /* Explicit restart request is bound to this transaction, never a stale PID. */
    wchar_t restart[PATH_CAP];join(restart,ctx->root,L"Scripts\\loader-update.restart");
    FILE *rf=_wfopen(restart,L"rb");char nonce[33]={0};
    int requested=rf&&read_exact(rf,nonce,32)&&fgetc(rf)==EOF&&!memcmp(nonce,ctx->nonce,32);if(rf)fclose(rf);
    if(requested&&!recover) {
        PROCESS_INFORMATION process;
        if(!launch(ctx->image,ctx->command,ctx->cwd,&process))status_write(ctx,"applied","installed; start the game from Steam");
        else {CloseHandle(process.hThread);CloseHandle(process.hProcess);}
    }
done:
    if(game)CloseHandle(game);ReleaseMutex(mutex);CloseHandle(mutex);return result;
}
