#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma pack(push,1)
typedef struct Job {
    char magic[4]; uint32_t version; uint64_t destination,cache;
    uint32_t width,height,target_width,target_height,flags;
    double spacing,scale,x,y,max_x,max_y;
    float z,max_z,spacing_x,spacing_y;
} Job;
#pragma pack(pop)

int main(void)
{
    HMODULE module=LoadLibraryW(L"skieo_native_terrain.dll");
    int (*copy)(void *)=module?(void *)GetProcAddress(module,"skieo_copy_heightmap"):NULL;
    if (!copy) return 2;
    const size_t count=2017U*2017U;
    uint16_t *samples=malloc(count*2);
    uint8_t cache[0x400]={0},before[sizeof(cache)];
    if (!samples) return 3;
    const char *names[]={"visible-valley","refined-valley","legacy-source","stage-only",
        "truncated-job","missing-topology","truncated-key","duplicate-key",
        "out-of-range-key","invalid-subdivision","reserved-word","unbounded-keys",
        "unknown-flags","trailing-data","invalid-derived-grid"};
    FILE *results=fopen("results.json","wb");if (!results) return 4;
    fputs("[\n",results);
    for (unsigned test=0;test<sizeof(names)/sizeof(names[0]);test++) {
        memset(samples,0xA5,count*2);memset(cache,0,sizeof(cache));
        uint64_t address=(uint64_t)(uintptr_t)samples;uint32_t width=2017;
        memcpy(cache+0x48,&address,8);memcpy(cache+0x80,&width,4);memcpy(cache+0x84,&width,4);
        uint32_t coarse=test==14?1:3;
        memcpy(cache+0xF4,&coarse,4);memcpy(cache+0xF8,&coarse,4);
        memcpy(before,cache,sizeof(cache));
        uint16_t source[9]={1000,1000,1000,1000,0,1000,1000,1000,1000};
        FILE *f=fopen("native_terrain.r16","wb");if(!f)return 5;
        fwrite(source,2,9,f);fclose(f);
        Job job={{'S','K','N','T'},5,address,(uint64_t)(uintptr_t)cache,
            3,3,2017,2017,1,200,1,-200,-200,200,200,0,65536,400.f/2016,400.f/2016};
        uint32_t topology[4]={2,1,0,0},keys[2]={1,1};size_t key_count=0;
        if(test==1){topology[2]=1;key_count=1;}
        if(test==2)job.version=3;
        if(test==3){job.version=6;job.destination=job.cache=0;}
        if(test==6){topology[2]=1;}
        if(test==7){topology[2]=2;key_count=2;}
        if(test==8){topology[2]=1;keys[0]=2;key_count=1;}
        if(test==9)topology[1]=0;
        if(test==10)topology[3]=1;
        if(test==11)topology[2]=16385;
        if(test==12)job.flags=4;
        f=fopen("native_terrain.job","wb");if(!f)return 6;
        fwrite(&job,1,sizeof(job)-(test==4?1:0),f);
        if(test!=2&&test!=4&&test!=5)fwrite(topology,4,4,f);
        if(key_count)fwrite(keys,4,key_count,f);
        if(test==13)fputc(0,f);
        fclose(f);DeleteFileA("native_terrain.status");
        copy(NULL);
        char status[512]={0};f=fopen("native_terrain.status","rb");
        if(!f)return 7;
        fread(status,1,sizeof(status)-1,f);fclose(f);
        int valid=test<4,passed=(strncmp(status,valid?"ok:":"error:",valid?3:6)==0);
        if(valid&&test!=3) {
            passed=passed&&samples[1008*2017+1008]==(test==0?1000:0);
            if(test==0)for(size_t i=0;i<count;i++)if(samples[i]!=1000){passed=0;break;}
        } else {
            passed=passed&&!memcmp(cache,before,sizeof(cache));
            for(size_t i=0;i<count;i++)if(samples[i]!=0xA5A5){passed=0;break;}
        }
        fprintf(results,"%s{\"case\":\"%s\",\"passed\":%s}",test?",\n":"",names[test],passed?"true":"false");
        printf("%s: %s (%s)\n",names[test],passed?"pass":"FAIL",status);fflush(stdout);
        if(!passed){fclose(results);return 10;}
    }
    fputs("\n]\n",results);fclose(results);free(samples);FreeLibrary(module);return 0;
}
