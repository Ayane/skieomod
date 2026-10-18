#!/usr/bin/env python3
"""Rebuild the Featured map from public Swiss terrain, OSM and MeteoSwiss data.

Run --fetch once to populate build/super-st-bernard; subsequent builds are offline.
The immutable source inventory and raw checksums remain in the map's Data folder.
"""
from pathlib import Path
import argparse, calendar, csv, hashlib, json, math, sys, urllib.request
import xml.etree.ElementTree as ET
import numpy as np
from osgeo import gdal, osr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.prepare_heightmap import encode_unreal, write_preview
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'build/super-st-bernard';MAP=ROOT/'mod/SkiEO-SuperSaintBernard'
# Preserve the original world centre so existing station coordinates stay valid.
BOUNDS=(2576704,1078516,2586304,1086516);SPACING=4;NX,NY=2401,2001
REGIONAL_URL='https://data.geo.admin.ch/ch.swisstopo.swissaltiregio/swissaltiregio/swissaltiregio_2056_5728.tif'

def download(url,path,fetch):
    if path.exists(): return
    if not fetch: raise FileNotFoundError(f'{path}: run --fetch to acquire public source data')
    path.parent.mkdir(parents=True,exist_ok=True)
    request=urllib.request.Request(url,headers={'User-Agent':'skieomod map authoring'})
    with urllib.request.urlopen(request,timeout=90) as response: data=response.read()
    temporary=path.with_suffix(path.suffix+'.part');temporary.write_bytes(data);temporary.replace(path)

def transform(src,dst):
    a,b=osr.SpatialReference(),osr.SpatialReference();a.ImportFromEPSG(src);b.ImportFromEPSG(dst)
    for s in (a,b):s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(a,b)

def lua(value):
    if isinstance(value,dict):return '{'+','.join('['+lua(k)+']='+lua(v) for k,v in value.items())+'}'
    if isinstance(value,list):return '{'+','.join(map(lua,value))+'}'
    if isinstance(value,str):return json.dumps(value,ensure_ascii=False)
    if isinstance(value,bool):return 'true' if value else 'false'
    if value is None:return 'nil'
    return str(value)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fetch',action='store_true');args=p.parse_args()
    gdal.UseExceptions();CACHE.mkdir(parents=True,exist_ok=True)
    for folder in ('Terrain','Data','Preview','Scripts'):(MAP/folder).mkdir(parents=True,exist_ok=True)
    inventory=json.loads((ROOT/'maps/super-st-bernard/expanded-terrain-sources.json').read_text())
    tiles=[];sources=[]
    for tile in inventory['tiles']:
        x,y=map(int,tile['id'].split('_')[-1].split('-'))
        if x*1000<BOUNDS[2]+2 and (x+1)*1000>BOUNDS[0]-2 and y*1000<BOUNDS[3]+2 and (y+1)*1000>BOUNDS[1]-2:
            asset=next(a for a in tile['assets'] if '_2_' in a['name'])
            path=CACHE/'tiles'/asset['name'];download(asset['url'],path,args.fetch)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            assert asset['checksum'][4:].lower()==digest,'terrain checksum mismatch'
            tiles.append(str(path));sources.append({'url':asset['url'],'sha256':digest})
    vrt=gdal.BuildVRT(str(CACHE/'map-terrain.vrt'),tiles);vrt=None
    x0,y0,x1,y1=BOUNDS
    terrain=gdal.Warp(str(CACHE/'map-terrain.tif'),str(CACHE/'map-terrain.vrt'),format='GTiff',
        dstSRS='EPSG:2056',outputBounds=(x0-2,y0-2,x1+2,y1+2),width=NX,height=NY,
        resampleAlg='bilinear',dstNodata=-9999,creationOptions=['COMPRESS=DEFLATE','TILED=YES'])
    values=terrain.ReadAsArray();missing=values==-9999
    regional=CACHE/'regional-terrain-32km.tif'
    if not regional.exists():
        if not args.fetch:raise FileNotFoundError('run --fetch to acquire the regional terrain crop')
        gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN','EMPTY_DIR')
        gdal.SetConfigOption('GDAL_HTTP_TIMEOUT','120')
        crop=gdal.Translate(str(regional),'/vsicurl/'+REGIONAL_URL,
            projWin=[2565300,1099500,2597300,1067500],creationOptions=['COMPRESS=DEFLATE','TILED=YES'])
        crop=None
    regional_grid=gdal.Warp('',str(regional),format='MEM',dstSRS='EPSG:2056',
        outputBounds=(x0-2,y0-2,x1+2,y1+2),width=NX,height=NY,resampleAlg='bilinear')
    regional_values=regional_grid.ReadAsArray()
    assert np.isfinite(regional_values).all() and (regional_values>0).all(),'regional terrain incomplete'
    # Blend over 80 m at the national coverage seam; missing Italy samples
    # come from measured regional data rather than long-distance hole filling.
    valid=gdal.GetDriverByName('MEM').Create('',NX,NY,1,gdal.GDT_Byte)
    valid.GetRasterBand(1).WriteArray((~missing).astype(np.uint8))
    distance=gdal.GetDriverByName('MEM').Create('',NX,NY,1,gdal.GDT_Float32)
    gdal.ComputeProximity(valid.GetRasterBand(1),distance.GetRasterBand(1),['VALUES=0','DISTUNITS=PIXEL'])
    weight=np.clip(distance.ReadAsArray()/20,0,1)
    values=np.where(missing,regional_values,values*weight+regional_values*(1-weight))
    assert np.isfinite(values).all() and (values>0).all(),'unfilled terrain gap'
    encoded,meta=encode_unreal(values,SPACING)
    (MAP/'Terrain/heightmap.r16').write_bytes(encoded.tobytes())
    centre=((x0+x1)/2,(y0+y1)/2);geo=transform(4326,2056)
    def xy(lon,lat):
        x,y,_=geo.TransformPoint(lon,lat);return [round((x-centre[0])*100,2),round((centre[1]-y)*100,2)]
    def altitude(lon,lat):
        x,y,_=geo.TransformPoint(lon,lat)
        return float(values[round((y1-y)/SPACING),round((x-x0)/SPACING)])
    osm_url='https://www.openstreetmap.org/api/0.6/map?bbox=7.177,45.878,7.22,45.918'
    osm=CACHE/'osm.xml';download(osm_url,osm,args.fetch)
    xml=ET.fromstring(osm.read_bytes());nodes={n.get('id'):(float(n.get('lon')),float(n.get('lat'))) for n in xml.findall('node')}
    ways={int(w.get('id')):[nodes[n.get('ref')] for n in w.findall('nd')] for w in xml.findall('way')}
    menouve=ways[1093148125];plan=ways[1093148124]
    base=menouve[0];top=menouve[-1];pl_top=plan[-1]
    guid=lambda n:{'A':0x53534203,'B':0,'C':0,'D':n}
    hub=guid(100);objects=[];asset_ids={};names={'menouve':'Menouve','plan_du_jeu':'Plan du Jeu'}
    for n,key,path,bottom,upper,capacity,dispatch in [
        (1,'menouve','Gondola',base,top,4,24),
        (2,'plan_du_jeu','FixedChair1',plan[0],pl_top,1,4)]:
        objects.append({'id':key,'name':names[key]+' · 1962','class':f'/Game/Blueprints/Lifts/BP_{path}.BP_{path}_C',
            'kind':'lift','position_cm':xy(*bottom),'end_position_cm':xy(*upper),'guid':guid(n),'hub':hub,
            'top_hub':guid(100+n),'capacity':capacity,'dispatch_seconds':dispatch})
        asset_ids[f'535342030000000000000000{n:08x}']=key
    for n,path,name,offset in [(3,'TicketOffice','Super Saint-Bernard Ticket Office',[-30,20]),
        (4,'SnowcatShed','Snowcat Garage',[-70,30]),(5,'FrenchChaletRestaurant','Super Saint-Bernard Restaurant',[-45,-25]),
        (6,'SkiPatrolHut','Super Saint-Bernard Ski Patrol',[15,-35]),
        (7,'Maintenance','Super Saint-Bernard Maintenance',[-95,-25])]:
        position=xy(*base);position=[position[0]+offset[0]*100,position[1]+offset[1]*100]
        objects.append({'id':path,'class':f'/Game/Blueprints/Buildings/BP_{path}.BP_{path}_C','kind':'building',
            'name':name,'position_cm':position,'guid':guid(n),'hub':hub})
    # Historical open-data fragments supplemented by authored, terrain-following
    # connections to the lower terminal. No fictional Italian return lift.
    main_route=list(ways[78191781])+[(7.2049,45.8872),(7.2034,45.8910),(7.2003,45.8955),(7.1975,45.8987),base]
    tscholaire=[top]+ways[79045095]+[(7.1900,45.8900),(7.1920,45.8945),(7.1943,45.8980),base]
    plan_route=[pl_top,(7.2116,45.9005),(7.2088,45.9010),(7.2055,45.9011),(7.2015,45.9010),plan[0]]
    plan_direct=[pl_top,(7.2102,45.8993),(7.2068,45.8990),(7.2030,45.8994),plan[0]]
    trails=[{'name':name,'difficulty':difficulty,'width':width,'points':[xy(*p) for p in points]} for name,difficulty,width,points in [
        ('Menouve',2,2400,main_route),('Tscholaire',2,2600,tscholaire),
        ('Plan du Jeu',0,3200,plan_route),('Plan du Jeu Return',1,2800,plan_direct)]]
    costs={'*':{'multiplier':25,'operating_multiplier':10},
        'OnePersonFixed':{'build':2000000},'Gondola':{'build':10000000},
        'TicketOffice':{'build':180000},'SnowcatShed':{'build':450000},'FrenchChaletRestaurant':{'build':350000},
        'MaintenanceShop':{'build':250000},'SkiPatrolHut':{'build':180000}}
    class_costs={'BP_Gondola_C':10000000,'BP_FixedChair1_C':2000000,'BP_FixedChair2_C':3500000,
        'BP_FixedChair4_C':4500000,'BP_HighSpeedQuad_C':6000000,'BP_HighSpeedSix_C':8000000,
        'BP_AerialTram_C':15000000,'BP_TicketOffice_C':180000,'BP_SnowcatShed_C':450000,
        'BP_FrenchChaletRestaurant_C':350000,'BP_Maintenance_C':250000,'BP_SkiPatrolHut_C':180000}
    hub_names=[{'name':name,'x':xy(*point)[0],'y':xy(*point)[1]} for name,point in [
        ('Bourg-Saint-Bernard',base),('Col de Menouve',top),('Plan du Jeu',pl_top),
        ('Mont Vélan',(7.25169,45.89182)),('Monts Telliers',(7.1439,45.8989))]]
    station={'objects':objects,'trails':trails,'asset_ids':asset_ids,'names':names,'costs':costs,'class_costs':class_costs,'hub_names':hub_names}
    (MAP/'Scripts/station.lua').write_text('local data='+lua(station)+'''\nfunction data.month_days(year,month)
    if month==2 then return (year%4==0 and (year%100~=0 or year%400==0)) and 29 or 28 end
    return ({31,28,31,30,31,30,31,31,30,31,30,31})[month]
end
return data
''')
    weather_url='https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/gsb/ogd-smn_gsb_d_historical.csv'
    weather_file=CACHE/'ogd-smn_gsb_d_historical.csv';download(weather_url,weather_file,args.fetch)
    days=[];gaps={}
    with weather_file.open() as stream:
        for raw in csv.DictReader(stream,delimiter=';'):
            date=raw['reference_timestamp'];year=int(date[6:10])
            if not 2003<=year<=2011:continue
            def number(key):
                if not raw[key]:gaps[key]=gaps.get(key,0)+1;return None
                return float(raw[key])
            temp=number('tre200d0');precip=number('rre150d0');wind=number('fkl010d1');humidity=number('ure200d0');sun=number('sre000d0')
            assert temp is not None and precip is not None,'missing required weather measurement'
            kind=3 if precip>=1 and temp<=1 and wind is not None and wind>=20 else 2 if precip>=1 else 1 if humidity>=80 or sun is not None and sun<120 else 0
            days.append({'date':f'{year:04d}-{int(date[3:5]):02d}-{int(date[:2]):02d}',
                'temperature':temp,'precipitation_mm':precip,'wind_max_ms':wind,'weather':kind})
    assert len(days)==3287 and len({d['date'] for d in days})==3287,'historical daily coverage incomplete'
    weather={'station':'GSB · Col du Grand St-Bernard','elevation_m':2472,'source':weather_url,'license':'CC BY MeteoSwiss',
        'missing_measurements':gaps,'mapping':'Daily mean temperature, 06–06 UTC precipitation, one-second gust maximum. Days are compressed by native month progress. Base temperature = GSB + 3.2 C. Blizzard: precipitation >=1mm, T<=1C and gust>=20m/s; missing gusts do not cause closures.','days':days}
    (MAP/'Data/weather-2003-2011.json').write_text(json.dumps(weather,ensure_ascii=False,separators=(',',':'))+'\n')
    provenance={'terrain':{'product':'swissALTI3D 2024, 2 m resampled at 4 m; swissALTIRegio 10 m across the border','attribution':'© swisstopo','horizontal_epsg':2056,'vertical_epsg':5728,'bounds':BOUNDS,'tiles':sources,
        'regional_samples':int(missing.sum()),'total_samples':int(values.size),'coverage_seam_blend_meters':80,
        'regional_source':REGIONAL_URL,'regional_crop_sha256':hashlib.sha256(regional.read_bytes()).hexdigest(),
        'regional_attribution':'Bundesamt für Landestopografie swisstopo; Tarquini S., I. Isola, M. Favalli, A. Battistini, G. Dotta (2023). TINITALY 1.1, INGV, https://doi.org/10.13127/tinitaly/1.1; DGM Österreich, geoland.at; DGM1 Bayern, www.geodaten.bayern.de; DGM1 Baden-Württemberg, LGL, dl-de/by-2-0; RGEAlti, IGN, July 2023',
        'vertical_note':'LN02 in Switzerland; original national height systems abroad, as distributed by swissALTIRegio' },
        'layout':{'source':osm_url,'sha256':hashlib.sha256(osm.read_bytes()).hexdigest(),'license':'OpenStreetMap ODbL 1.0',
            'lift_ways':[1093148125,1093148124],'piste_ways':[78191781,79045095],
            'limitations':'Four reconstructed Swiss-side trails; missing historical connections authored. Tscholaire tunnel represented on the surface. Italian itinerary omitted. Plan du Jeu uses the game one-seat chair model because a platter model is unavailable.'},
        'weather':{'source':weather_url,'raw_sha256':hashlib.sha256(weather_file.read_bytes()).hexdigest(),'license':'CC BY MeteoSwiss','years':[2003,2011]},
        'scenario':{'reference':'docs/super-st-bernard-crisis.md','sha256':hashlib.sha256((ROOT/'docs/super-st-bernard-crisis.md').read_bytes()).hexdigest(),
            'capital_chf':250000,'regulatory_refit_chf':1000000,'gondola_replacement_chf':10000000,
            'assumptions':'Condition gauges, wear, recurring expenses, twelve visitors per rendered guest, construction prices other than Menouve and matching rescue contribution are game calibration, not historical accounts.'}}
    (MAP/'Data/sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    write_preview(values,MAP/'Preview/terrain.png',SPACING)
    # Real terrain illustration for the Featured browser/loading card.
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    fig=plt.figure(figsize=(12.8,7.2),dpi=100,facecolor='#192f40');ax=fig.add_subplot(111,projection='3d',facecolor='#192f40')
    step=16;yy,xx=np.mgrid[0:NY:step,0:NX:step];z=values[::step,::step]
    colours=LightSource(315,45).shade(z,cmap=plt.get_cmap('bone'),vert_exag=1.4,blend_mode='soft')
    ax.plot_surface(xx*4,yy*4,z,facecolors=colours,rstride=1,cstride=1,shade=False,linewidth=0)
    ax.view_init(elev=35,azim=-60);ax.set_box_aspect((x1-x0,y1-y0,3000));ax.set_axis_off()
    fig.text(.055,.90,'SUPER SAINT-BERNARD',fontsize=26,color='white',weight='bold')
    fig.text(.055,.84,'THE REPRIEVE  ·  2003—2011',fontsize=16,color='#d6b694')
    fig.text(.055,.08,'Maintain. Invest. Save the resort.',fontsize=15,color='white')
    fig.text(.055,.035,'Real terrain © swisstopo  ·  Historical MeteoSwiss weather',fontsize=9,color='#b4c3ce')
    fig.subplots_adjust(left=0,right=1,bottom=0,top=.86);fig.savefig(MAP/'Preview/super-saint-bernard.png',facecolor=fig.get_facecolor())
    # The loading card occupies the left half of the screen. Keep that space
    # clear and use the native panel for all text.
    for text in list(fig.texts):text.remove()
    ax.set_position([.50,.06,.49,.88])
    fig.savefig(MAP/'Preview/loading.png',facecolor=fig.get_facecolor());plt.close(fig)
    # A square cartographic icon uses a different composition from the wide
    # loading backdrop and remains readable in the browser and loading card.
    fig,ax=plt.subplots(figsize=(6,6),dpi=120,facecolor='#193343')
    ax.imshow(LightSource(315,45).shade(values,cmap=plt.get_cmap('bone'),vert_exag=2,
        dx=4,dy=4,blend_mode='soft'),extent=(-(x1-x0)/2,(x1-x0)/2,-(y1-y0)/2,(y1-y0)/2))
    for trail in trails:
        pts=np.array(trail['points'])/100
        ax.plot(pts[:,0],-pts[:,1],color='#b9d6df',linewidth=1.2,alpha=.65)
    for lift in objects[:2]:
        pts=np.array([lift['position_cm'],lift['end_position_cm']])/100
        ax.plot(pts[:,0],-pts[:,1],color='#efaa7a',linewidth=3,solid_capstyle='round')
        ax.scatter(pts[:,0],-pts[:,1],color='#f0e9db',s=25,edgecolors='#193343',linewidths=1,zorder=4)
    ax.set_xlim(-(x1-x0)/2,(x1-x0)/2);ax.set_ylim(-(y1-y0)/2,(y1-y0)/2);ax.set_axis_off()
    fig.subplots_adjust(left=0,right=1,bottom=0,top=1)
    fig.savefig(MAP/'Preview/icon.png',facecolor=fig.get_facecolor());plt.close(fig)
    # A coarse real terrain ring keeps the playable map out of a void.
    bg_bounds=(centre[0]-15000,centre[1]-15000,centre[0]+15000,centre[1]+15000)
    background=gdal.Warp('',str(regional),format='MEM',dstSRS='EPSG:2056',
        outputBounds=(bg_bounds[0]-50,bg_bounds[1]-50,bg_bounds[2]+50,bg_bounds[3]+50),
        width=301,height=301,resampleAlg='bilinear').ReadAsArray()
    assert np.isfinite(background).all() and (background>0).all(),'scenery terrain incomplete'
    bg_encoded,bg_meta=encode_unreal(background,100)
    (MAP/'Terrain/background.r16').write_bytes(bg_encoded.tobytes())
    scenery={'size_meters':[30000,30000],'origin_centimeters':[-1500000,-1500000,0],
        'source':{'file':'Terrain/background.r16','format':'r16le','vertices':[301,301],'spacing_meters':100,
            'row_order':'north_to_south','height_scale_meters':bg_meta['landscape_scale_z']/12800,
            'height_offset_meters':bg_meta['actor_location_z_centimeters']/100-32768*bg_meta['landscape_scale_z']/12800},
        'elevation_meters':[float(background.min()),float(background.max())],
        'material':'/Game/Materials/Backgrounds/M_Snow.M_Snow'}
    lon,lat,_=transform(2056,4326).TransformPoint(*centre)
    manifest={'$schema':'https://skieo.community/schemas/custom-map-1.json','format':{'name':'skieo-map','version':'1.4.0'},
        'id':'community.super-saint-bernard','metadata':{'name':'Super Saint-Bernard','version':'0.2.4','authors':['SkiEO Community'],
            'description':'Take over in late 2003 and save the 2010–2011 season. Maintain ageing lifts, fund safety upgrades and face historical MeteoSwiss weather. Expand across real terrain from Monts Telliers to Mont Vélan.',
            'language':'en','players':{'min':1,'max':1},'tags':['Alps','Switzerland','History','Survival','Scenario'],
            'license':'© swisstopo; TINITALY 1.1 © INGV; MeteoSwiss CC BY; OpenStreetMap ODbL 1.0'},
        'terrain':{'size_meters':[x1-x0,y1-y0],'elevation_meters':[round(float(values.min()),3),round(float(values.max()),3)],
            'origin_centimeters':[-(x1-x0)*50,-(y1-y0)*50,0],
            'source':{'file':'Terrain/heightmap.r16','format':'r16le','vertices':[NX,NY],'spacing_meters':SPACING,
                'row_order':'north_to_south','height_scale_meters':meta['landscape_scale_z']/12800,
                'height_offset_meters':meta['actor_location_z_centimeters']/100-32768*meta['landscape_scale_z']/12800},
            'runtime':{'sample_step':4,'tile_quads':63,'uv_tile_meters':20,'snow_material':'/Game/Materials/Snow/M_Snow.M_Snow','snow_offset_centimeters':30,'placeable_clearance_centimeters':20},
            'preview':{'samples':np.round((values[np.ix_(np.linspace(0,NY-1,17).astype(int),np.linspace(0,NX-1,17).astype(int))]-values.min())/(values.max()-values.min()),4).tolist()}},
        'location':{'latitude':lat,'longitude':lon,'world_map_uv':[0.476,0.269],'label':'Bourg-Saint-Pierre, Valais, Suisse'},
        'content':{'assets':['Terrain/background.r16','Scripts/station.lua','Scripts/furnishings.lua','Scripts/survival.lua','Scripts/finance.lua','Scripts/economy.lua','Data/weather-2003-2011.json','Data/sources.json','Preview/super-saint-bernard.png','Preview/icon.png','Preview/loading.png','Preview/terrain.png']},
        'script':{'language':'lua','api':'1.1','entry':'Scripts/main.lua','permissions':['gameplay']},
        'build':{'triggers':{'file':'Triggers/triggers.json'}},
        'editor':{'coordinate_system':{'horizontal':'EPSG:2056','vertical':'LN02 / EPSG:5728','axis_order':'east,north,up'}},
        'extensions':{'community.skieo.scenery':scenery,'community.skieo.presentation':{'image':'Preview/icon.png','loading_image':'Preview/loading.png','trails':4,'lifts':2,'difficulties':['beginner','intermediate','expert']},
            'community.skieo.scenario':{'minimum_loader':'1.19.3','start':'2003-11','goal':'2011-04','currency':'CHF'},
            'community.skieo.data-sources':{'terrain':'swissALTI3D 2024 + swissALTIRegio © swisstopo / TINITALY','layout':'OSM + reconstructed historical connections','weather':'MeteoSwiss GSB 2003–2011'}}}
    (MAP/'custom-map.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'maps/super-st-bernard/map.json').write_text(json.dumps({'name':'Super Saint-Bernard','terrain':{'bounds_east_north':BOUNDS,'vertices_x':NX,'vertices_y':NY,'extent_meters':[x1-x0,y1-y0],'spacing_meters':SPACING},'horizontal_epsg':2056,'vertical_epsg':5728},indent=2)+'\n')
    print('Terrain',values.shape,values.min(),values.max(),'filled',int(missing.sum()),'weather',len(days))
    print('Lift elevations',altitude(*base),altitude(*top),altitude(*pl_top))
if __name__=='__main__':main()
