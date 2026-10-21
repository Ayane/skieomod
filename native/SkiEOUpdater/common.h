#ifndef SKIEO_UPDATE_COMMON_H
#define SKIEO_UPDATE_COMMON_H
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>
#define PATH_CAP 4096
#define FILE_LIMIT (16u*1024*1024)
#define TOTAL_LIMIT (128u*1024*1024)
#define COUNT_LIMIT 4095
#define CONTEXT L"Scripts\\loader-update.context"
#define STATUS L"Scripts\\loader-update.status"
#define BUNDLE L"Scripts\\loader-update.bundle"
#define RECORD L"loader-release.json"
#pragma pack(push,1)
typedef struct {
    char magic[4]; uint32_t version, pid; FILETIME created;
    char nonce[33]; wchar_t root[PATH_CAP], image[PATH_CAP], cwd[PATH_CAP], command[32768];
} Context;
#pragma pack(pop)
static void die(const char *message) { fprintf(stderr,"%s (Windows error %lu)\n",message,GetLastError()); exit(1); }
static int join(wchar_t *out, const wchar_t *root,const wchar_t *relative) {
    return _snwprintf(out,PATH_CAP,L"%ls\\%ls",root,relative)>0 && wcslen(root)+wcslen(relative)+1<PATH_CAP;
}
static int read_exact(FILE *f,void *out,size_t n) { return fread(out,1,n,f)==n; }
static int flush_file(FILE *f) { return fflush(f)==0 && FlushFileBuffers((HANDLE)_get_osfhandle(_fileno(f))); }
static int hash_bytes(const void *data,size_t n,unsigned char out[32]) {
    BCRYPT_ALG_HANDLE alg=NULL; BCRYPT_HASH_HANDLE h=NULL;
    int ok=BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0)==0
        && BCryptCreateHash(alg,&h,NULL,0,NULL,0,0)==0
        && BCryptHashData(h,(PUCHAR)data,(ULONG)n,0)==0 && BCryptFinishHash(h,out,32,0)==0;
    if(h) BCryptDestroyHash(h);if(alg) BCryptCloseAlgorithmProvider(alg,0);return ok;
}
static int file_hash(const wchar_t *path,unsigned char out[32]) {
    FILE *f=_wfopen(path,L"rb");if(!f)return 0;
    BCRYPT_ALG_HANDLE alg=NULL;BCRYPT_HASH_HANDLE h=NULL;unsigned char block[65536];size_t n;
    int ok=BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0)==0
        && BCryptCreateHash(alg,&h,NULL,0,NULL,0,0)==0;
    while(ok && (n=fread(block,1,sizeof(block),f)))ok=BCryptHashData(h,block,(ULONG)n,0)==0;
    ok=ok&&!ferror(f)&&BCryptFinishHash(h,out,32,0)==0;fclose(f);
    if(h)BCryptDestroyHash(h);if(alg)BCryptCloseAlgorithmProvider(alg,0);return ok;
}
static int same_hash(const wchar_t *path,const unsigned char expected[32]) { unsigned char got[32];return file_hash(path,got)&&!memcmp(got,expected,32); }
/* Every descendant must be a real directory/file, never a junction or symlink.
   Existing ancestors ABOVE the mod root (e.g. a Steam library link) are allowed. */
static int safe_tree(const wchar_t *root,const wchar_t *path,int create) {
    size_t n=wcslen(root);wchar_t buf[PATH_CAP];
    if(_wcsnicmp(root,path,n)||path[n]!=L'\\'||wcslen(path)>=PATH_CAP)return 0;
    wcscpy(buf,path);
    for(size_t i=n;i<=wcslen(path);i++) {
        if(buf[i]!=L'\\'&&buf[i]!=0)continue;
        wchar_t c=buf[i];buf[i]=0;DWORD attrs=GetFileAttributesW(buf);
        if(attrs==INVALID_FILE_ATTRIBUTES) {
            DWORD err=GetLastError();
            if(err!=ERROR_FILE_NOT_FOUND&&err!=ERROR_PATH_NOT_FOUND)return 0;
            if(create&&c&&!CreateDirectoryW(buf,NULL)&&GetLastError()!=ERROR_ALREADY_EXISTS)return 0;
        } else if((attrs&FILE_ATTRIBUTE_REPARSE_POINT)||(c&&!(attrs&FILE_ATTRIBUTE_DIRECTORY)))return 0;
        buf[i]=c;
    }
    return 1;
}
static int atomic_bytes(const wchar_t *root,const wchar_t *path,const void *data,size_t n) {
    wchar_t part[PATH_CAP];if(_snwprintf(part,PATH_CAP,L"%ls.part",path)<0||!safe_tree(root,part,1)||!safe_tree(root,path,1))return 0;
    FILE *f=_wfopen(part,L"wb");if(!f)return 0;
    int ok=fwrite(data,1,n,f)==n&&flush_file(f);if(fclose(f))ok=0;
    return ok&&MoveFileExW(part,path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
}
static int status_write(const Context *ctx,const char *phase,const char *detail) {
    char text[512];wchar_t path[PATH_CAP];int n=snprintf(text,sizeof(text),"%s %s %s",phase,ctx->nonce,detail?detail:"");
    return n>0&&n<(int)sizeof(text)&&join(path,ctx->root,STATUS)&&atomic_bytes(ctx->root,path,text,(size_t)n);
}
static int status_read(const Context *ctx,char *phase,size_t cap) {
    wchar_t path[PATH_CAP];char nonce[34]={0},state[32]={0};
    if(!join(path,ctx->root,STATUS)||!safe_tree(ctx->root,path,0))return 0;
    FILE *f=_wfopen(path,L"rb");if(!f)return 0;int n=fscanf(f,"%31s %33s",state,nonce);fclose(f);
    if(n!=2||strcmp(nonce,ctx->nonce)||strlen(state)>=cap)return 0;strcpy(phase,state);return 1;
}
static int load_context(const wchar_t *path,Context *ctx) {
    FILE *f=_wfopen(path,L"rb");if(!f)return 0;
    int ok=read_exact(f,ctx,sizeof(*ctx))&&fgetc(f)==EOF;fclose(f);
    if(!ok||memcmp(ctx->magic,"SKUC",4)||ctx->version!=1||!ctx->pid||ctx->nonce[32])return 0;
    for(int i=0;i<32;i++)if(!((ctx->nonce[i]>='0'&&ctx->nonce[i]<='9')||(ctx->nonce[i]>='a'&&ctx->nonce[i]<='f')))return 0;
    if(!wmemchr(ctx->root,0,PATH_CAP)||!wmemchr(ctx->image,0,PATH_CAP)||!wmemchr(ctx->cwd,0,PATH_CAP)||!wmemchr(ctx->command,0,32768))return 0;
    wchar_t expected[PATH_CAP];return join(expected,ctx->root,CONTEXT)&&!_wcsicmp(expected,path)&&safe_tree(ctx->root,path,0);
}
/* PID alone is unsafe after a reboot: bind both creation time and image. */
static HANDLE game_process(const Context *ctx) {
    HANDLE p=OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION,FALSE,ctx->pid);
    if(!p)return NULL;
    FILETIME created,exit,kernel,user;wchar_t image[PATH_CAP];DWORD n=PATH_CAP;
    if(!GetProcessTimes(p,&created,&exit,&kernel,&user)||memcmp(&created,&ctx->created,sizeof(created))
        ||!QueryFullProcessImageNameW(p,0,image,&n)) {CloseHandle(p);return NULL;}
    /* GetModuleFileName may carry the long-path prefix; compare canonical paths. */
    const wchar_t *a=ctx->image,*b=image;if(!wcsncmp(a,L"\\\\?\\",4))a+=4;if(!wcsncmp(b,L"\\\\?\\",4))b+=4;
    if(_wcsicmp(a,b)){CloseHandle(p);return NULL;}return p;
}
static HANDLE update_mutex(const Context *ctx,DWORD timeout) {
    uint64_t hash=UINT64_C(14695981039346656037);
    for(const wchar_t *p=ctx->root;*p;p++)hash=(hash^(uint16_t)towlower(*p))*UINT64_C(1099511628211);
    wchar_t name[80];swprintf(name,80,L"Local\\SkiEOModUpdate-%016llx",(unsigned long long)hash);
    HANDLE h=CreateMutexW(NULL,FALSE,name);if(!h)return NULL;
    DWORD wait=WaitForSingleObject(h,timeout);if(wait!=WAIT_OBJECT_0&&wait!=WAIT_ABANDONED){CloseHandle(h);return NULL;}return h;
}
static int launch(const wchar_t *exe,wchar_t *command,const wchar_t *cwd,PROCESS_INFORMATION *p) {
    STARTUPINFOW s={0};s.cb=sizeof(s);memset(p,0,sizeof(*p));
    return CreateProcessW(exe,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,cwd,&s,p)!=0;
}
#endif
