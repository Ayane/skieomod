#ifndef SKIEO_TOW_TRACK_POLICY_H
#define SKIEO_TOW_TRACK_POLICY_H
#include <stdint.h>
#include <string.h>
#include <math.h>
#define HISTORY_SIZE 65536u
typedef struct Previous {uint32_t id[4];double x,y,z;uint64_t seen;} Previous;
/* Native collection batches change size and order. A bounded GUID table also
   prevents a recycled array slot from joining two unrelated guests' tracks. */
static int towing_velocity(Previous *history,const uint8_t *id,const double *p,
                           float dt,uint64_t now,double *velocity)
{
    uint32_t key=2166136261u;for(int k=0;k<16;k++)key=(key^id[k])*16777619u;
    Previous *old=history+(key&(HISTORY_SIZE-1));
    for(unsigned k=0;k<16;k++) {
        Previous *candidate=history+((key+k)&(HISTORY_SIZE-1));
        if(!candidate->seen||!memcmp(candidate->id,id,16)){old=candidate;break;}
        if(candidate->seen<old->seen)old=candidate;
    }
    int moved=0;
    if(dt>0&&dt<5&&old->seen&&now-old->seen<5000&&!memcmp(old->id,id,16)) {
        double dx=p[0]-old->x,dy=p[1]-old->y,dz=p[2]-old->z;
        double d2=dx*dx+dy*dy;
        if(isfinite(d2)&&isfinite(dz)&&d2>.01&&d2<(700*dt+100)*(700*dt+100)) {
            velocity[0]=dx/dt;velocity[1]=dy/dt;velocity[2]=dz/dt;moved=1;
        }
    }
    memcpy(old->id,id,16);old->x=p[0];old->y=p[1];old->z=p[2];old->seen=now;
    return moved;
}
#endif
