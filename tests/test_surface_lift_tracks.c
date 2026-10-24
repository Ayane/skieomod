#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include "../native/SkiEOSurfaceLifts/track_policy.h"
int main(void){
 Previous *history=calloc(HISTORY_SIZE,sizeof *history);assert(history);
 uint32_t a[4]={1,2,3,4},b[4]={5,6,7,8},c[4]={9,10,11,12};double p[3]={0},v[3];
 assert(!towing_velocity(history,(uint8_t *)a,p,.1,100,v));
 assert(!towing_velocity(history,(uint8_t *)b,p,.1,100,v));
 /* A different batch with a different size must preserve guest A's history. */
 assert(!towing_velocity(history,(uint8_t *)c,p,.1,150,v));
 p[0]=30;p[2]=5;assert(towing_velocity(history,(uint8_t *)a,p,.1,200,v));
 assert(fabs(v[0]-300)<.01&&fabs(v[2]-50)<.01);
 assert(towing_velocity(history,(uint8_t *)b,p,.1,200,v));
 assert(!towing_velocity(history,(uint8_t *)b,p,.1,250,v)); /* stopped */
 p[0]=5000;assert(!towing_velocity(history,(uint8_t *)a,p,.1,300,v)); /* teleport */
 p[0]+=30;assert(towing_velocity(history,(uint8_t *)a,p,.1,400,v));
 p[0]+=30;assert(!towing_velocity(history,(uint8_t *)a,p,.1,6000,v)); /* stale */
 p[0]+=30;assert(!towing_velocity(history,(uint8_t *)a,p,0,6100,v)); /* paused */
 free(history);puts("Native tow tracks: changing batches, GUIDs, velocity, stops, teleports and pauses OK");return 0;
}
