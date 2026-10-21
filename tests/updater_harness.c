/* Windows integration harness: production bootstrap/worker, disposable mod root.
   No game/Steam URI or external process is ever terminated. */
#include <io.h>
#include "common.h"
static int marker(const wchar_t *root,const wchar_t *name,const char *text) {
    wchar_t path[PATH_CAP];return join(path,root,name)&&atomic_bytes(root,path,text,strlen(text));
}
int wmain(int argc,wchar_t **argv) {
    if(argc!=3)return 2;wchar_t root[PATH_CAP];
    if(_snwprintf(root,PATH_CAP,L"\\\\?\\%ls",argv[1])<0)return 2;
    wchar_t dll[PATH_CAP];join(dll,root,L"Scripts\\skieo_update_bootstrap.dll");HMODULE module=LoadLibraryW(dll);if(!module)die("bootstrap load");
    typedef int (*Bridge)(void *);Bridge recover=(Bridge)GetProcAddress(module,"skieo_update_recover");
    Bridge begin=(Bridge)GetProcAddress(module,"skieo_update_begin"),restart=(Bridge)GetProcAddress(module,"skieo_update_restart");
    if(!recover||!begin||!restart)die("bootstrap exports");recover(NULL);
    wchar_t payload_dll[PATH_CAP];join(payload_dll,root,L"Scripts\\payload.dll");
    HMODULE payload=LoadLibraryW(payload_dll);if(!payload)die("payload DLL load");
    int (*value)(void)=(int (*)(void))GetProcAddress(payload,"value");if(!value)die("payload DLL export");
    char native_value[8];snprintf(native_value,sizeof(native_value),"%d",value());
    marker(root,L"native-payload-value.txt",native_value);
    if(!wcscmp(argv[2],L"recover"))return marker(root,L"recovered.txt","recovered")?0:3;
    wchar_t record[PATH_CAP];join(record,root,RECORD);FILE *f=_wfopen(record,L"rb");char bytes[2048]={0};
    if(f){fread(bytes,1,sizeof(bytes)-1,f);fclose(f);}
    char pid[32];snprintf(pid,sizeof(pid),"%lu",GetCurrentProcessId());
    if(strstr(bytes,"1.24.8"))return value()==2&&marker(root,L"restarted.txt",pid)?0:4;
    if(value()!=1)return 8;
    marker(root,L"original-pid.txt",pid);begin(NULL);
    Context *ctx=calloc(1,sizeof(Context));wchar_t context[PATH_CAP];join(context,root,CONTEXT);
    for(int i=0;i<1200;i++) {
        char phase[32]={0};if(load_context(context,ctx)&&status_read(ctx,phase,sizeof(phase))) {
            if(!strcmp(phase,"failed"))return 5;
            if(!strcmp(phase,"ready")) {
                wchar_t payload[PATH_CAP];join(payload,root,L"Scripts\\payload.lua");FILE *old=_wfopen(payload,L"rb");char content[16]={0};
                if(old){fread(content,1,15,old);fclose(old);}if(strcmp(content,"old payload"))return 6;
                marker(root,L"ready-before-exit.txt","original files unchanged while game alive");
                if(!wcscmp(argv[2],L"tamper")) {
                    wchar_t relative[160],staged[PATH_CAP];swprintf(relative,160,L".skieomod-updates\\%hs\\next\\Scripts\\payload.lua",ctx->nonce);
                    join(staged,root,relative);atomic_bytes(root,staged,"corrupt",7);
                }
                if(!wcscmp(argv[2],L"restart"))restart(NULL);
                Sleep(1000);return 0;
            }
        }
        Sleep(100);
    }
    return 7;
}
