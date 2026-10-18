#ifndef SKIEO_RATING_RESOLVER_H
#define SKIEO_RATING_RESOLVER_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "rating_profile.h"

enum { RATING_CODE=1, RATING_CONST=2, RATING_DATA=4 };
enum { RATING_COLOR_BYTES=205 };
typedef struct RatingSection {
    const uint8_t *data;
    uint32_t rva, size, kind;
} RatingSection;
typedef struct RatingImage { const RatingSection *sections; size_t count; } RatingImage;
typedef struct RatingResolution { uint32_t calculate, palette, color, style; } RatingResolution;

static const uint8_t *rating_read(const RatingImage *image, uint32_t rva, size_t size, unsigned kind)
{
    for (size_t i=0;i<image->count;++i) {
        const RatingSection *s=&image->sections[i];
        if ((s->kind & kind) && rva>=s->rva && rva-s->rva<=s->size && size<=s->size-(rva-s->rva))
            return s->data+(rva-s->rva);
    }
    return NULL;
}

static uint32_t rating_u32(const uint8_t *p) { uint32_t v;memcpy(&v,p,4);return v; }
static uint32_t rating_relative(uint32_t start, unsigned end, const uint8_t *p)
{
    int32_t displacement;memcpy(&displacement,p,4);
    int64_t rva=(int64_t)start+end+displacement;
    return rva>=0 && rva<UINT32_MAX ? (uint32_t)rva : UINT32_MAX;
}

/* Ignore only address operands. Opcodes, branches, grade values and layout
   remain exact. Every ignored operand is checked independently below. */
static int rating_shape(const uint8_t *code, const uint8_t *guard, size_t size,
    const unsigned *addresses, size_t count)
{
    for (size_t i=0;i<size;++i) {
        int address=0;
        for(size_t j=0;j<count;++j) if(i>=addresses[j] && i-addresses[j]<4) {address=1;break;}
        if (!address && code[i]!=guard[i]) return 0;
    }
    return 1;
}

static int rating_candidate(const RatingImage *image, unsigned feature, uint32_t rva,
    uint32_t palette, uint32_t *style)
{
    static const unsigned slope_refs[]={3,15,27}, palette_refs[]={27,43,56};
    static const unsigned color_refs[]={13,32,39,189};
    const uint8_t *code;
    if (feature==0) {
        code=rating_read(image,rva,sizeof(rating_calculate_guard),RATING_CODE);
        if(!code || !rating_shape(code,rating_calculate_guard,sizeof(rating_calculate_guard),slope_refs,3))return 0;
        float previous=91;
        for(unsigned i=0;i<3;++i) {
            uint32_t target=rating_relative(rva,slope_refs[i]+4,code+slope_refs[i]);
            const uint8_t *value=rating_read(image,target,4,RATING_CONST);
            float threshold;
            if(!value)return 0;
            memcpy(&threshold,value,4);
            if(!isfinite(threshold) || threshold<=0 || threshold>90 || threshold>=previous)return 0;
            previous=threshold;
        }
        return 1;
    }
    if (feature==1) {
        code=rating_read(image,rva,sizeof(rating_palette_guard),RATING_CODE);
        if(!code || !rating_shape(code,rating_palette_guard,sizeof(rating_palette_guard),palette_refs,3))return 0;
        uint32_t cache=0;
        for(unsigned i=0;i<3;++i) {
            uint32_t target=rating_relative(rva,palette_refs[i]+5,code+palette_refs[i]);
            const uint8_t *value=rating_read(image,target,1,RATING_DATA);
            if(!value || *value>3 || (i && cache!=target))return 0;
            cache=target;
        }
        *style=cache;return cache!=0;
    }
    /* Complete getter through RET, with seven independently verified targets.
       Do not pin padding, the next function or the table's own location. */
    code=rating_read(image,rva,RATING_COLOR_BYTES,RATING_CODE);
    if(!palette || !code || !rating_shape(code,rating_color_guard,RATING_COLOR_BYTES,color_refs,4))return 0;
    if(rating_relative(rva,17,code+13)!=palette || rating_relative(rva,36,code+32)!=0)return 0;
    const uint8_t *table=rating_read(image,rating_u32(code+39),28,RATING_CODE);
    static const unsigned cases[]={0x30,0x4c,0x68,0x84,0xba,0x84,0x9c};
    if(!table)return 0;
    for(unsigned i=0;i<7;++i) if((uint64_t)rva+cases[i]!=rating_u32(table+i*4))return 0;
    const uint8_t *fallback=rating_read(image,rating_relative(rva,193,code+189),16,RATING_CONST);
    static const float white[]={1,1,1,1};
    return fallback && !memcmp(fallback,white,16);
}

static RatingResolution rating_resolve(const RatingImage *image)
{
    RatingResolution result={0};
    if(!image || !image->sections || !image->count || image->count>96)return result;
    for(size_t i=0;i<image->count;++i) {
        const RatingSection *s=&image->sections[i];
        if(!s->data || !s->size || (uint64_t)s->rva+s->size>UINT32_MAX ||
            (s->kind!=RATING_CODE && s->kind!=RATING_CONST && s->kind!=RATING_DATA))return result;
        for(size_t j=0;j<i;++j) {
            const RatingSection *other=&image->sections[j];
            if((uint64_t)s->rva+ s->size>other->rva && (uint64_t)other->rva+other->size>s->rva)return result;
        }
    }
    /* Palette first: the color getter's direct CALL must resolve to it. */
    static const unsigned order[]={1,0,2};
    for(unsigned pass=0;pass<3;++pass) {
        unsigned feature=order[pass],matches=0;
        uint32_t candidate=0,style=0;
        for(size_t i=0;i<image->count;++i) {
            const RatingSection *s=&image->sections[i];
            if(!(s->kind & RATING_CODE))continue;
            /* All reviewed entries are 16-byte aligned. Reject a matching
               byte sequence embedded in the middle of another instruction. */
            for(uint64_t at=((uint64_t)s->rva+15)&~UINT64_C(15);at<(uint64_t)s->rva+s->size;at+=16) {
                uint32_t cache=0;
                const uint8_t *first=rating_read(image,(uint32_t)at,1,RATING_CODE);
                uint8_t lead=feature==0 ? 0x0f : feature==1 ? 0x0f : 0x40;
                if(!first || *first!=lead || !rating_candidate(image,feature,(uint32_t)at,result.palette,&cache))continue;
                candidate=(uint32_t)at;style=cache;
                if(++matches>1)break;
            }
            if(matches>1)break;
        }
        if(matches!=1)continue;
        if(feature==0)result.calculate=candidate;
        else if(feature==1){result.palette=candidate;result.style=style;}
        else result.color=candidate;
    }
    return result;
}
#endif
