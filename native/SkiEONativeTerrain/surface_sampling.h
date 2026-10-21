#ifndef SKIEO_SURFACE_SAMPLING_H
#define SKIEO_SURFACE_SAMPLING_H

#include <math.h>
#include <stddef.h>
#include <stdint.h>

/* Same triangle/fan topology as terrain_mesh.lua. Rasterize the visible,
   collidable surface for native consumers instead of resurrecting omitted
   heightmap detail underneath guests, tracks and terrain brushes. */
typedef struct SkiEOSurface {
    const uint8_t *bytes, *refined;
    uint32_t width, height, step, fine, columns, rows, flags;
} SkiEOSurface;

static double skieo_surface_vertex(const SkiEOSurface *s, uint32_t x, uint32_t y)
{
    if (s->flags & 2) y=s->height-1-y;
    size_t i=((size_t)y*s->width+x)*2;
    return (s->flags & 1) ? s->bytes[i]+s->bytes[i+1]*256
        : s->bytes[i]*256+s->bytes[i+1];
}

static double skieo_surface_bilinear(const SkiEOSurface *s, double x, double y)
{
    uint32_t x0=(uint32_t)floor(x),y0=(uint32_t)floor(y);
    uint32_t x1=x0+1<s->width?x0+1:x0,y1=y0+1<s->height?y0+1:y0;
    double tx=x-x0,ty=y-y0;
    return (skieo_surface_vertex(s,x0,y0)*(1-tx)+skieo_surface_vertex(s,x1,y0)*tx)*(1-ty)
        +(skieo_surface_vertex(s,x0,y1)*(1-tx)+skieo_surface_vertex(s,x1,y1)*tx)*ty;
}

static int skieo_surface_refined(const SkiEOSurface *s, int x, int y)
{
    if (!s->refined || x<0 || y<0 || x>=(int)s->columns || y>=(int)s->rows) return 0;
    size_t i=(size_t)y*s->columns+x;
    return (s->refined[i/8]>>(i%8))&1;
}

static double skieo_surface_quad(const SkiEOSurface *s, double x, double y,
    double x0, double x1, double y0, double y1)
{
    double tx=(x-x0)/(x1-x0),ty=(y-y0)/(y1-y0);
    double b=skieo_surface_bilinear(s,x0,y1),c=skieo_surface_bilinear(s,x1,y0);
    if (tx+ty<=1)
        return skieo_surface_bilinear(s,x0,y0)*(1-tx-ty)+b*ty+c*tx;
    return c*(1-ty)+b*(1-tx)+skieo_surface_bilinear(s,x1,y1)*(tx+ty-1);
}

static double skieo_surface_sample(const SkiEOSurface *s, double x, double y)
{
    if (!s->step) return skieo_surface_bilinear(s,x,y);
    int ix=(int)fmin(floor(x/s->step),s->columns-1);
    int iy=(int)fmin(floor(y/s->step),s->rows-1);
    double x0=ix*s->step,y0=iy*s->step;
    double x1=fmin(x0+s->step,s->width-1),y1=fmin(y0+s->step,s->height-1);
    if (skieo_surface_refined(s,ix,iy)) {
        x0+=fmin(floor((x-x0)/s->fine),ceil((x1-x0)/s->fine)-1)*s->fine;
        y0+=fmin(floor((y-y0)/s->fine),ceil((y1-y0)/s->fine)-1)*s->fine;
        return skieo_surface_quad(s,x,y,x0,fmin(x0+s->fine,x1),y0,fmin(y0+s->fine,y1));
    }
    int neighbors[4]={skieo_surface_refined(s,ix-1,iy),skieo_surface_refined(s,ix,iy+1),
        skieo_surface_refined(s,ix+1,iy),skieo_surface_refined(s,ix,iy-1)};
    if (!(neighbors[0]||neighbors[1]||neighbors[2]||neighbors[3]))
        return skieo_surface_quad(s,x,y,x0,x1,y0,y1);
    /* Build the same clockwise perimeter, omitting each edge's final point.
       Four subdivisions per edge plus partial cells need at most 20 points. */
    double points[24][2]; unsigned count=0;
    for (unsigned edge=0;edge<4;edge++) {
        double first=(edge%2)?x0:y0,last=(edge%2)?x1:y1;
        double step=neighbors[edge]?s->fine:last-first;
        unsigned segments=(unsigned)ceil((last-first)/step);
        for (unsigned i=0;i<segments;i++) {
            double value=edge>=2?fmin(last,first+(segments-i)*step):first+i*step;
            points[count][0]=(edge%2)?value:(edge==0?x0:x1);
            points[count++][1]=(edge%2)?(edge==1?y1:y0):value;
        }
    }
    double cx=(x0+x1)/2,cy=(y0+y1)/2;
    double center=skieo_surface_bilinear(s,cx,cy);
    for (unsigned i=0;i<count;i++) {
        const double *a=points[i],*b=points[(i+1)%count];
        double ax=a[0]-cx,ay=a[1]-cy,bx=b[0]-cx,by=b[1]-cy;
        double determinant=ax*by-ay*bx;
        double u=((x-cx)*by-(y-cy)*bx)/determinant;
        double v=(ax*(y-cy)-ay*(x-cx))/determinant;
        if (u>=-1e-10&&v>=-1e-10&&u+v<=1+1e-10)
            return center*(1-u-v)+skieo_surface_bilinear(s,a[0],a[1])*u
                +skieo_surface_bilinear(s,b[0],b[1])*v;
    }
    return NAN; /* Invalid topology must fail before any cache is changed. */
}

#endif
