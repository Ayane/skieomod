#!/usr/bin/env python3
"""Assemble cached envelope batches and conform simplification border chords."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource

import numpy as np
from scipy.spatial import cKDTree

from tools.implicit_rock import unit
from tools.prepare_sculpted_massif import NativeMassif, compact, FRONT
from tools.export_sculpted_massif import geometry_sums
from tools.embed_rock_sculpture import audit


def conform(points,normals,uvs,faces,baseline,labels=None):
    """Remove zero-domain caps, then split unmatched edges on native knots.

    Locked collinear boundary vertices can acquire tiny cap triangles during
    QEM reduction. Two independently reduced batches can then share an
    interior chord four times. The portable reference is an XY heightfield;
    a triangle with zero reference XY area covers no terrain domain.
    """
    area=np.cross(baseline[faces[:,1]]-baseline[faces[:,0]],baseline[faces[:,2]]-baseline[faces[:,0]])[:,2]
    keep=np.abs(area)>1e-10
    removed=int((~keep).sum());faces=faces[keep]
    if labels is not None: labels=labels[keep]
    geo,representative,weld=np.unique(np.round(points,9),axis=0,return_index=True,return_inverse=True)
    gfaces=weld[faces]
    directed=np.stack([gfaces[:,[0,1]],gfaces[:,[1,2]],gfaces[:,[2,0]]],axis=1)
    edges,inverse,counts=np.unique(np.sort(directed.reshape(-1,2),axis=1),axis=0,return_inverse=True,return_counts=True)
    used=np.unique(gfaces)
    tree=cKDTree(baseline[representative[used],:2])
    splits={}
    for edge_id in np.flatnonzero(counts==1):
        a,b=edges[edge_id];pa,pb=baseline[representative[[a,b]],:2]
        delta=pb-pa;length=np.linalg.norm(delta)
        if length<1e-10:continue
        ids=used[np.asarray(tree.query_ball_point((pa+pb)/2,length/2+1e-8),dtype=int)]
        q=baseline[representative[ids],:2]
        t=(q-pa)@delta/length**2
        on=(t>1e-8)&(t<1-1e-8)&(np.linalg.norm(q-pa-t[:,None]*delta,axis=1)<1e-8)
        # The reference edge can curve vertically. Its middle knot need not
        # lie on the simplified 3D chord: restore the shared native curve using
        # the reference XY parameter, including its actual sculpted position.
        ids,t=ids[on],t[on]
        if len(ids):splits[edge_id]=ids[np.argsort(t)]
    new_p=[];new_n=[];new_uv=[];new_base=[];new_faces=[]
    masks=np.array([any(i in splits for i in row) for row in inverse.reshape(-1,3)])
    result=[faces[~masks]]
    result_labels=[] if labels is None else [labels[~masks]]
    for fid in np.flatnonzero(masks):
        face=faces[fid];polygon=[]
        for corner,edge_id in enumerate(inverse.reshape(-1,3)[fid]):
            polygon.append(int(face[corner]))
            if edge_id in splits:
                ids=splits[edge_id]
                if directed[fid,corner,0]!=edges[edge_id,0]:ids=ids[::-1]
                polygon.extend(representative[ids].tolist())
        center=len(points)+len(new_p)
        new_p.append(points[face].mean(0));new_n.append(unit(normals[face].mean(0)))
        new_uv.append(uvs[face].mean(0));new_base.append(baseline[face].mean(0))
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            new_faces.append([a,b,center])
            if labels is not None: result_labels.append(np.array([labels[fid]]))
    if new_p:
        points=np.concatenate([points,new_p]);normals=np.concatenate([normals,new_n])
        uvs=np.concatenate([uvs,new_uv]);baseline=np.concatenate([baseline,new_base])
        result.append(np.asarray(new_faces,dtype=np.uint32))
    faces=np.concatenate(result)
    used,remap=np.unique(faces,return_inverse=True)
    result=(points[used],normals[used],uvs[used],remap.reshape(-1,3).astype(np.uint32),baseline[used])
    metric=dict(
        removed_zero_reference_area_triangles=removed,conformed_edges=len(splits))
    if labels is not None: return result,metric,np.concatenate(result_labels)
    return result,metric


def reconcile(output):
    """Make all reference knots authoritative before closing part interfaces.

    Native UV copies can carry different eligibility at a reverse-chart edge.
    Choose the least displaced copy at each reference knot, so a pinned native
    edge stays pinned rather than being averaged into the rock. This also
    conforms different subdivisions without changing the extraction caches.
    """
    directories=sorted(output.glob('s*-p*'));arrays=[[],[],[],[],[]];labels=[];count=0
    for index,directory in enumerate(directories):
        with np.load(directory/'geometry.npz',allow_pickle=False) as data:
            values=[data[k].copy() for k in ('points','normals','uvs','faces','baseline')]
        for k,(target,value) in enumerate(zip(arrays,values)):target.append(value+count if k==3 else value)
        labels.append(np.full(len(values[3]),index,dtype=np.uint8));count+=len(values[0])
    p,n,uv,f,base=[np.concatenate(a) for a in arrays];del arrays
    _,weld=np.unique(np.round(base,8),axis=0,return_inverse=True)
    depth=np.linalg.norm(p-base,axis=1)
    order=np.lexsort((np.arange(len(p)),depth,weld))
    first=np.r_[True,weld[order][1:]!=weld[order][:-1]]
    representative=order[first]
    canonical=representative[weld]
    correction=np.linalg.norm(p-p[canonical],axis=1)
    maximum=float(correction.max());changed=int((correction>1e-7).sum())
    p=p[canonical];n=n[canonical];base=base[canonical]
    result,repair,tags=conform(p,n,uv,f,base,np.concatenate(labels))
    del p,n,uv,f,base,order,weld,canonical,correction
    p,n,uv,f,base=result
    geometry_sums(p,base,f)
    for index,directory in enumerate(directories):
        faces=f[tags==index];used,remap=np.unique(faces,return_inverse=True)
        values=compact(p[used],n[used],uv[used],remap.reshape(-1,3).astype(np.uint32),base[used],np.array([-1512.,1008.,2000.]))
        points,normals,texture,faces,baseline=values
        geometry_sums(points,baseline,faces)
        np.savez(directory/'geometry.npz',points=points,normals=normals,uvs=texture,faces=faces,baseline=baseline)
        summary=json.loads((directory/'audit.json').read_text())
        summary.update(vertices=len(points),triangles=len(faces),global_knots_reconciled=True,
            topology=audit(points,faces))
        (directory/'audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    report=dict(reference_knots_reconciled=changed,maximum_interface_correction_meters=maximum,**repair,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    (output/'reconciliation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


def assemble(sources,output,profile_path=Path('maps/veymont/limestone-sculpture.json'),
        erosion_path=Path('maps/veymont/limestone-erosion.json'),spacing=1.5,generator_source=None):
    native=NativeMassif(sources)
    profile=json.loads(profile_path.read_text())
    erosion=json.loads(erosion_path.read_text())
    generator_source=generator_source or Path('tools/prepare_sculpted_massif.py')
    key=hashlib.sha256(json.dumps(dict(profile=profile,erosion=erosion,spacing=spacing,surface_mode='envelope',
        sources=native.fingerprints,generator=hashlib.sha256(generator_source.read_bytes()).hexdigest(),
        refinement=hashlib.sha256(Path('tools/prepare_nanite_tile.py').read_bytes()).hexdigest()),sort_keys=True).encode()).hexdigest()
    origin=np.array([-1512.,1008.,2000.]);summaries=[]
    for section in native.sections:
        own=np.flatnonzero(native.face_sections==section)
        p=native.points[native.faces[own]].reshape(-1,3);lo,hi=p.min(0),p.max(0)
        xy=np.minimum(((native.centers[own,:2]-lo[:2])/(hi[:2]-lo[:2])*4).astype(int),3)
        group=xy[:,0]+4*xy[:,1]
        for pid in range(16):
            directory=output/f's{section}-p{pid:02d}'
            checkpoint=directory/'micro'/key[:16]
            expected=list(range(0,int((group==pid).sum()),32))
            if [int(p.stem) for p in sorted(checkpoint.glob('*.npz'))]!=expected:
                raise ValueError(f'incomplete cached envelope {section}/{pid}')
            arrays=[[],[],[],[],[]];count=0;metrics=[]
            for start in expected:
                with np.load(checkpoint/f'{start:05d}.npz',allow_pickle=False) as data:
                    values=[data[k].copy() for k in ('points','normals','uvs','faces','baseline')]
                    metrics.append(json.loads(str(data['metric'])))
                for index,(target,value) in enumerate(zip(arrays,values)):
                    target.append(value+count if index==3 else value)
                count+=len(values[0])
            result,repair=conform(*[np.concatenate(a) for a in arrays])
            result=compact(*result,origin)
            p,n,uv,f,base=result
            geometry_sums(p,base,f)
            topology=audit(p-origin,f)
            if topology['nonmanifold_edges'] or topology['degenerate_triangles']:
                raise ValueError(f'encoded envelope {section}/{pid}: {topology}')
            if len(p)>1_000_000 or len(f)>2_000_000:raise ValueError('portable mesh budget exceeded')
            np.savez(directory/'geometry.npz',points=p,normals=n,uvs=uv,faces=f,baseline=base)
            selected=own[group==pid]
            summary=dict(generation_key=key,surface_mode='envelope',section=int(section),part=pid,parts=16,
                vertices=len(p),triangles=len(f),original_faces=len(selected),topology=topology,repair=repair,
                eligible_cliff_area_m2=float(native.area[selected[native.active[selected]]].sum()),
                maximum_outset_meters=float(np.sum((p-base)*FRONT,axis=1).max()),
                maximum_recession_meters=float(-np.sum((p-base)*FRONT,axis=1).min()),
                maximum_microvolume_samples=max(m['samples'] for m in metrics),
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
            (directory/'audit.json').write_text(json.dumps(summary,indent=2)+'\n');summaries.append(summary)
            print(json.dumps(summary),flush=True)
    (output/'assembled.json').write_text(json.dumps(summaries,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',type=Path,nargs='+');parser.add_argument('--geometry-dir',type=Path,required=True)
    parser.add_argument('--reconcile-only',action='store_true')
    parser.add_argument('--profile',type=Path,default=Path('maps/veymont/limestone-sculpture.json'))
    parser.add_argument('--erosion',type=Path,default=Path('maps/veymont/limestone-erosion.json'))
    parser.add_argument('--edge-spacing',type=float,default=1.5)
    parser.add_argument('--generator-source',type=Path,help='Exact source snapshot used to calculate cached batches')
    args=parser.parse_args();resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    if not args.reconcile_only:
        assemble(args.sources,args.geometry_dir,args.profile,args.erosion,args.edge_spacing,args.generator_source)
    reconcile(args.geometry_dir)


if __name__=='__main__':main()
