/* Stable bootstrap ABI v1. Keep this DLL and main.lua byte-identical across
   automatic releases. Changes to them require the normal installer. */
#include <io.h>
#include "common.h"
static wchar_t root[PATH_CAP];
static int own_root(void) {
    HMODULE module=NULL;wchar_t path[PATH_CAP];
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(LPCWSTR)(uintptr_t)own_root,&module)
        ||!GetModuleFileNameW(module,path,PATH_CAP)||wcslen(path)>=PATH_CAP-1)return 0;
    wchar_t *end=wcsrchr(path,L'\\');if(!end)return 0;*end=0;end=wcsrchr(path,L'\\');if(!end||_wcsicmp(end+1,L"Scripts"))return 0;*end=0;
    if(!wcsncmp(path,L"\\\\?\\",4))wcscpy(root,path);
    else if(_snwprintf(root,PATH_CAP,L"\\\\?\\%ls",path)<0)return 0;
    return 1;
}
static void bridge_status(const char *text) {
    wchar_t path[PATH_CAP];if(root[0]&&join(path,root,L"Scripts\\update_bootstrap.status"))atomic_bytes(root,path,text,strlen(text));
}
static int run_worker(Context *ctx,const wchar_t *mode,int wait) {
    wchar_t source[PATH_CAP],worker[PATH_CAP],context[PATH_CAP],command[PATH_CAP*2+128];
    if(!join(source,root,L"Scripts\\skieo_updater.exe")||!join(worker,root,L".skieomod-updates\\worker.exe")||!join(context,root,CONTEXT)
        ||!safe_tree(root,worker,1)||!safe_tree(root,source,0))return 0;
    if(!wait&&!CopyFileW(source,worker,FALSE))return 0;
    /* Recovery uses the exact worker that staged this transaction. */
    if(_snwprintf(command,sizeof(command)/sizeof(command[0]),L"\"%ls\" %ls \"%ls\"",worker,mode,context)<0)return 0;
    PROCESS_INFORMATION process;if(!launch(worker,command,ctx->cwd,&process))return 0;
    CloseHandle(process.hThread);int ok=1;
    if(wait) {DWORD code=1;ok=WaitForSingleObject(process.hProcess,65000)==WAIT_OBJECT_0&&GetExitCodeProcess(process.hProcess,&code)&&code==0;}
    CloseHandle(process.hProcess);return ok;
}
__declspec(dllexport) int skieo_update_recover(void *lua_state) {
    (void)lua_state;if(!own_root())return 0;
    wchar_t path[PATH_CAP];Context *ctx=calloc(1,sizeof(Context));char phase[32]={0};
    if(!ctx||!join(path,root,CONTEXT)){bridge_status("error: recovery path unavailable");free(ctx);return 0;}
    if(GetFileAttributesW(path)==INVALID_FILE_ATTRIBUTES){bridge_status("ok");free(ctx);return 0;}
    if(!load_context(path,ctx)){bridge_status("error: update context unreadable; reinstall the mod");free(ctx);return 0;}
    status_read(ctx,phase,sizeof(phase));
    if(!strcmp(phase,"ready")||!strcmp(phase,"applying")) {
        HANDLE game=game_process(ctx);int alive=game&&WaitForSingleObject(game,0)==WAIT_TIMEOUT;if(game)CloseHandle(game);
        /* A second game must not load DLLs while an earlier process owns them. */
        if(alive&&ctx->pid!=GetCurrentProcessId())bridge_status("error: close the other game before recovering its prepared update");
        else if(alive)bridge_status("ok");
        else bridge_status(run_worker(ctx,L"--recover",1)?"ok":"error: update recovery failed; reinstall the mod before loading a map");
    } else {
        if(!strcmp(phase,"starting")||!strcmp(phase,"staging")) {
            HANDLE game=game_process(ctx);int alive=game&&WaitForSingleObject(game,0)==WAIT_TIMEOUT;if(game)CloseHandle(game);
            if(!alive)status_write(ctx,"failed","preparation interrupted; existing mod unchanged");
        }
        bridge_status("ok");
    }
    free(ctx);return 0;
}
__declspec(dllexport) int skieo_update_begin(void *lua_state) {
    (void)lua_state;if(!own_root())return 0;
    Context *ctx=calloc(1,sizeof(Context));wchar_t path[PATH_CAP];char phase[32]={0};
    if(!ctx||!join(path,root,CONTEXT)){bridge_status("error: update path unavailable");free(ctx);return 0;}
    if(load_context(path,ctx)&&status_read(ctx,phase,sizeof(phase))&&(!strcmp(phase,"ready")||!strcmp(phase,"applying")||!strcmp(phase,"staging"))) {
        bridge_status("error: an update is already pending");free(ctx);return 0;
    }
    memset(ctx,0,sizeof(*ctx));memcpy(ctx->magic,"SKUC",4);ctx->version=1;ctx->pid=GetCurrentProcessId();wcscpy(ctx->root,root);
    unsigned char random[16];FILETIME exit,kernel,user;
    int ok=BCryptGenRandom(NULL,random,16,BCRYPT_USE_SYSTEM_PREFERRED_RNG)==0
        &&GetProcessTimes(GetCurrentProcess(),&ctx->created,&exit,&kernel,&user)
        &&GetModuleFileNameW(NULL,ctx->image,PATH_CAP)>0&&GetCurrentDirectoryW(PATH_CAP,ctx->cwd)>0&&wcslen(GetCommandLineW())<32768;
    for(int i=0;i<16;i++)sprintf(ctx->nonce+2*i,"%02x",random[i]);
    wcscpy(ctx->command,GetCommandLineW());
    if(ok)ok=atomic_bytes(root,path,ctx,sizeof(*ctx))&&status_write(ctx,"starting","launching update worker")&&run_worker(ctx,L"--stage",0);
    bridge_status(ok?"ok":"error: could not launch update worker");free(ctx);return 0;
}
__declspec(dllexport) int skieo_update_restart(void *lua_state) {
    (void)lua_state;if(!own_root())return 0;wchar_t path[PATH_CAP];Context *ctx=calloc(1,sizeof(Context));char phase[32]={0};
    int ok=ctx&&join(path,root,CONTEXT)&&load_context(path,ctx)&&ctx->pid==GetCurrentProcessId()&&status_read(ctx,phase,sizeof(phase))&&!strcmp(phase,"ready");
    HANDLE game=ok?game_process(ctx):NULL;ok=ok&&game!=NULL;if(game)CloseHandle(game);
    if(ok)ok=join(path,root,L"Scripts\\loader-update.restart")&&atomic_bytes(root,path,ctx->nonce,32);
    bridge_status(ok?"ok":"error: prepared update is no longer available");free(ctx);return 0;
}
