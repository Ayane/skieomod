#!/usr/bin/env python3
"""Rebuild the Fox Anatomy example's weighted rig and portable animation clips.

Requires numpy and Pillow. No Blender, Unreal editor or cooked game assets.
The original archive remains external; only skin and eyes enter the package.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageFilter

NS = {'c': 'http://www.collada.org/2005/11/COLLADASchema'}
ROOT = Path(__file__).resolve().parents[1]
SCALE = 48.0
CENTER = .7047095
CLIPS = [('idle', 3., True), ('walk', 1., True), ('trot', .65, True),
         ('sniff', 2., True), ('pounce', 1.2, False), ('feed', 2., True),
         ('bound', .7, True), ('play_bow', 1.1, True), ('shake', 1.6, False)]
GAITS = {'walk': (36., .68, 5., [0., .5, .75, .25]),
         'trot': (50., .52, 8., [0., .5, .5, 0.]),
         'bound': (60., .32, 10., [.35, .32, .20, .17])}


def snow_textures(output, vertices, normals, uv, triangles):
    """Bake a soft dorsal mask in UV space, with no face visibility cutoff."""
    image = Image.open(output / 'skin.png').convert('RGB')
    width, height = image.size
    mask = np.zeros((height, width))
    def smooth(t):
        t = np.clip(t, 0, 1)
        return t*t*(3-2*t)
    weights = smooth((normals[:, 2]+.05)/.8)*smooth((vertices[:, 2]-12)/13)
    pixels = uv*np.array([width-1, height-1])
    for ids in triangles.reshape(-1, 3):
        a, b, c = pixels[ids]
        low = np.maximum(0, np.floor(np.min([a,b,c], axis=0)).astype(int))
        high = np.minimum([width-1,height-1], np.ceil(np.max([a,b,c], axis=0)).astype(int))
        den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-8 or np.any(high<low): continue
        yy, xx = np.mgrid[low[1]:high[1]+1, low[0]:high[0]+1]
        u = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        v = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
        w = 1-u-v
        value = (u*weights[ids[0]]+v*weights[ids[1]]+w*weights[ids[2]])
        region = mask[low[1]:high[1]+1, low[0]:high[0]+1]
        np.maximum(region, np.where((u>=-.01)&(v>=-.01)&(w>=-.01), value, 0), out=region)
    mask = np.asarray(Image.fromarray((mask*255).astype('uint8')).filter(ImageFilter.GaussianBlur(1.2)))/255
    grain = np.random.default_rng(7521).uniform(.8, 1, mask.shape)
    mask *= grain*.82
    skin = (np.asarray(image)/255)**2.2
    snow = (np.array([230,239,246])/255)**2.2
    for level in range(1,17):
        amount = (mask*level/16)[:, :, None]
        color = np.clip((skin*(1-amount)+snow*amount)**(1/2.2)*255, 0, 255).astype('uint8')
        Image.fromarray(color).save(output / f'snow-coat-{level:02d}.png')


def coordinates(p):
    return np.column_stack((p[:, 0], CENTER - p[:, 2], p[:, 1] + .623725)) * SCALE


def geometry(root, identifier):
    mesh = root.find(f'.//c:geometry[@id="{identifier}"]/c:mesh', NS)
    arrays = {}
    for source in mesh.findall('c:source', NS):
        stride = int(source.find('c:technique_common/c:accessor', NS).get('stride'))
        arrays[source.get('id')] = np.fromstring(source.find('c:float_array', NS).text, sep=' ').reshape(-1, stride)
    poly = mesh.find('c:polylist', NS)
    assert set(poly.find('c:vcount', NS).text.split()) == {'3'}, 'Expected triangulated source'
    inputs = poly.findall('c:input', NS)
    stride = max(int(i.get('offset')) for i in inputs) + 1
    indices = np.fromstring(poly.find('c:p', NS).text, sep=' ', dtype=int).reshape(-1, stride)
    unique, inverse = np.unique(indices, axis=0, return_inverse=True)
    vertex_source = mesh.find('c:vertices/c:input', NS).get('source')[1:]
    values = {}
    for item in inputs:
        semantic = item.get('semantic')
        source = vertex_source if semantic == 'VERTEX' else item.get('source')[1:]
        values[semantic] = arrays[source][unique[:, int(item.get('offset'))]]
    pos = values['VERTEX']
    normals = values['NORMAL'][:, [0, 2, 1]].copy(); normals[:, 1] *= -1
    uv = values['TEXCOORD'][:, :2].copy(); uv[:, 1] = 1 - uv[:, 1]
    # Unreal's procedural mesh uses clockwise front faces, opposite Collada.
    triangles = inverse.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1)
    return pos, coordinates(pos), normals, uv, triangles


def rig():
    # Global rest pivots, in the original Collada coordinates. Bones/muscles in
    # the anatomy display are separate sculptures, not animation joints.
    joints = [('body', -1, (0, .12, CENTER)),
              ('neck', 0, (.40, .15, CENTER)), ('head', 1, (.66, .31, CENTER)),
              ('tail', 0, (-.53, .04, CENTER))]
    for label, x, depth in [('front_l', .34, .79), ('front_r', .34, .62),
                            ('rear_l', -.43, .79), ('rear_r', -.43, .62)]:
        parent = len(joints)
        joints.extend([(label, 0, (x, .03, depth)), (label + '_lower', parent, (x, -.34, depth))])
    joints.extend([('pelvis', 0, (-.36, .12, CENTER)),
                   ('spine', 0, (.12, .16, CENTER)),
                   ('tail_mid', 3, (-.83, -.03, CENTER)),
                   ('tail_tip', 14, (-1.08, -.18, CENTER))])
    for index in (3, 8, 10):
        name, _, pivot = joints[index]; joints[index] = (name, 12, pivot)
    for index in (1, 4, 6):
        name, _, pivot = joints[index]; joints[index] = (name, 13, pivot)
    return [{'name': name, 'parent': parent, 'pivot_cm': coordinates(np.array([p]))[0].tolist()}
            for name, parent, p in joints]


def weights(points, bones):
    w = np.zeros((len(points), len(bones)))
    for i, (x, y, z) in enumerate(points):
        if x < -.62:
            tail = np.clip((-.53-x)/.16, 0, 1)
            segment = np.clip((-.72-x)/.30, 0, 2)
            a, b = (3, 14) if segment < 1 else (14, 15)
            t = segment if segment < 1 else segment-1
            w[i, a] = tail*(1-t); w[i, b] = tail*t; w[i, 12] = 1-tail
        elif y < .10 and (x < -.20 or .18 < x < .58):
            b = (4 if x > 0 else 8) + (0 if z > CENTER else 2)
            limb = np.clip((.10-y)/.22, 0, 1)
            lower = np.clip((-.27-y)/.18, 0, 1)
            w[i, b] = limb*(1-lower); w[i, b+1] = limb*lower; w[i, 13 if x > 0 else 12] = 1-limb
        elif x > .40:
            neck = np.clip((x-.40)/.20, 0, 1)
            head = np.clip((x-.60)/.16, 0, 1)
            w[i, 13] = 1-neck; w[i, 1] = neck*(1-head); w[i, 2] = neck*head
        else:
            spine = np.clip((x+.35)/.70, 0, 1)
            w[i, 12] = 1-spine; w[i, 13] = spine
    assert np.allclose(w.sum(axis=1), 1)
    return w


def matrices(bones, clip, phase):
    angles = np.zeros((len(bones), 3))
    tau = 2*math.pi*phase
    angles[3, 2] = .12*math.sin(tau-.3)
    angles[14, 2] = .16*math.sin(tau-.8)
    angles[15, 2] = .20*math.sin(tau-1.3)
    angles[2, 2] = .045*math.sin(tau)
    angles[13, 0] = .012*math.sin(tau)
    angles[12, 0] = -.012*math.sin(tau)
    if clip in ('walk', 'trot', 'bound'):
        offsets = [0, .5, .75, .25] if clip == 'walk' else [0, .5, .5, 0]
        if clip == 'bound': offsets = [0, .06, .55, .61]
        strength = .38 if clip == 'walk' else .58
        for bone, offset in zip((4, 6, 8, 10), offsets):
            wave = math.sin(tau + offset*2*math.pi)
            angles[bone, 1] = strength*wave
            angles[bone+1, 1] = -.65*max(0, wave)
        angles[12, 2] = .07*math.sin(tau)
        angles[13, 2] = -.045*math.sin(tau)
        angles[12, 0] = .04*math.cos(tau)
        angles[13, 0] = -.025*math.cos(tau)
        angles[12, 1] = .055*math.cos(tau*2)
        angles[13, 1] = -.045*math.cos(tau*2)
        angles[1, 1] = .04*math.sin(tau*2)
        if clip == 'bound':
            angles[12, 1] = -.24*math.sin(tau)
            angles[13, 1] = .20*math.sin(tau)
            angles[3, 1] = -.28*math.sin(tau-.5)
    elif clip in ('sniff', 'feed', 'play_bow'):
        angles[1, 1] = .5 + .08*math.sin(tau)
        angles[2, 1] = .2 + .1*math.sin(tau*2)
        if clip == 'play_bow':
            angles[13, 1] = .22*(.7+.3*math.sin(tau))
            angles[4, 1] = angles[6, 1] = -.6
            angles[5, 1] = angles[7, 1] = .65
            angles[3, 2] = .35*math.sin(tau*2)
    elif clip == 'pounce':
        crouch = math.sin(math.pi*phase)**2
        angles[1, 1] = .3*crouch
        angles[12, 1] = -.18*crouch
        angles[13, 1] = .22*crouch
        for bone in (4, 6, 8, 10):
            angles[bone, 1] = -.65*crouch; angles[bone+1, 1] = 1.1*crouch
    elif clip == 'shake':
        envelope = math.sin(math.pi*phase)**2
        for bone, lag in [(2, 0), (1, .3), (13, .6), (12, 1.), (3, 1.4), (14, 1.8), (15, 2.2)]:
            angles[bone, 0] = .28*envelope*math.sin(tau*5-lag)
            angles[bone, 2] = .07*envelope*math.sin(tau*5-lag)
    result = [None]*len(bones)
    def transform(bone):
        if result[bone] is not None: return result[bone]
        ax, ay, az = angles[bone]
        rx = np.array([[1,0,0],[0,math.cos(ax),-math.sin(ax)],[0,math.sin(ax),math.cos(ax)]])
        ry = np.array([[math.cos(ay),0,math.sin(ay)],[0,1,0],[-math.sin(ay),0,math.cos(ay)]])
        rz = np.array([[math.cos(az),-math.sin(az),0],[math.sin(az),math.cos(az),0],[0,0,1]])
        rotation = rz @ ry @ rx
        matrix = np.eye(4); matrix[:3,:3] = rotation
        joint = bones[bone]; pivot = np.array(joint['pivot_cm'])
        matrix[:3,3] = pivot - rotation @ pivot
        if joint['parent'] >= 0: matrix = transform(joint['parent']) @ matrix
        result[bone] = matrix
        return matrix
    for bone in range(len(bones)): transform(bone)
    return result


def pose(vertices, normals, skin, transforms, ground_shift=0):
    v, n = np.zeros_like(vertices), np.zeros_like(normals)
    for b, matrix in enumerate(transforms):
        weight = skin[:, b:b+1]
        v += weight * (vertices @ matrix[:3,:3].T + matrix[:3,3])
        n += weight * (normals @ matrix[:3,:3].T)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-8)
    # Apply the body's grounding to every section, including eyes. Grounding
    # each section separately would detach the eyes and put them at paw height.
    v[:, 2] -= ground_shift
    # A tail tip may touch the support plane; it must not lift all four paws
    # just because it is the lowest point of the animated bounding box.
    v[:, 2] = np.maximum(0, v[:, 2])
    return v, n


def build(archive, output):
    source = Path(archive).read_bytes()
    with ZipFile(io.BytesIO(source)) as outer:
        with ZipFile(io.BytesIO(outer.read('source/model.zip'))) as inner:
            root = ET.fromstring(inner.read('model/model.dae'))
        textures = {name: outer.read('textures/Fox_Model_(Walk_Anim)_v2_' + name + '_BaseColor.png')
                    for name in ['Skin']}
        textures['Eyeballs'] = outer.read('textures/Fox_Model_(Walk_Anim)_v2_Eyeballs_BaseColo.png')
    assert root.find('c:library_animations', NS) is None
    bones = rig()
    reference, body, body_normals, _, _ = geometry(root, 'meshId0')
    body_skin = weights(reference, bones)
    paws = []
    for b in (4, 6, 8, 10):
        ids = np.where(body_skin[:, b]+body_skin[:, b+1] > .5)[0]
        sole = ids[body[ids, 2] < body[ids, 2].min()+1.8]
        center = np.array([body[sole, 0].mean(), body[sole, 1].mean(), body[sole, 2].min()])
        members = []
        for i in np.where(body_skin[:, b]+body_skin[:, b+1] > .001)[0]:
            members.append([int(i)+1, float(body_skin[i,b]), float(body_skin[i,b+1]),
                            float(np.clip((8-body[i,2])/6,0,1)),
                            *(body[i]-center).tolist(), *body_normals[i].tolist()])
        faces = geometry(root, 'meshId0')[4].reshape(-1,3)
        sole_set = set(sole.tolist())
        sole_faces = [f.tolist() for f in faces if all(int(i) in sole_set for i in f)
                      and body_normals[f,2].mean() < -.1]
        assert sole_faces, 'Missing projected paw sole'
        paws.append({'bone':b, 'sole':(sole+1).tolist(), 'rest':center.tolist(),
                     'vertices':members, 'triangles':[[i+1 for i in f] for f in sole_faces], 'frames':{}})
    soles = np.concatenate([np.array(p['sole'])-1 for p in paws])
    poses = {}
    for name, _, loop in CLIPS:
        for frame in range(24):
            transforms = matrices(bones, name, frame/(24 if loop else 23))
            v, _ = pose(body, body_normals, body_skin, transforms)
            shift = v[soles, 2].min()
            poses[name, frame] = transforms, shift
            for paw in paws:
                b=paw['bone']
                anchors=[]
                for index in (b,b+1):
                    p=transforms[index] @ np.array([*bones[index]['pivot_cm'],1.])
                    p[2]-=shift; anchors.extend(p[:3].tolist())
                paw['frames'].setdefault(name,[]).append(anchors)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    binary = bytearray(struct.pack('<4sIII', b'SKAN', 1, 3, len(CLIPS)))
    rig_data = {'format': 'skieo-fox-rig', 'version': 1, 'source_sha256': hashlib.sha256(source).hexdigest(),
                'scale_cm': SCALE, 'bones': bones, 'clips': CLIPS, 'meshes': []}
    for identifier, texture in [('meshId0', 'Skin'), ('meshId1', 'Eyeballs'), ('meshId0', 'Snow')]:
        original, vertices, normals, uv, triangles = geometry(root, identifier)
        skin = weights(original, bones)
        if texture == 'Snow':
            # A thin, independently removable coat on upward torso/head faces.
            # Snowless skin avoids the native prop material displacing the
            # animal itself by the terrain snow depth for a second time.
            faces = triangles.reshape(-1,3)
            keep = (normals[faces,2].mean(axis=1)>.55) & (vertices[faces,2].min(axis=1)>20)
            faces = faces[keep]
            used = np.unique(faces)
            remap = np.zeros(len(vertices),dtype=int);remap[used]=np.arange(len(used))
            triangles=remap[faces].reshape(-1)
            original,vertices,normals,uv,skin = original[used],vertices[used],normals[used],uv[used],skin[used]
            vertices=vertices+normals*.35
        rig_data['meshes'].append({'source': identifier, 'weights': skin.round(6).tolist()})
        binary.extend(struct.pack('<II', len(vertices), len(triangles)))
        binary.extend(np.column_stack((vertices, normals, uv)).astype('<f4').tobytes())
        binary.extend(triangles.astype('<u4').tobytes())
        for name, duration, loop in CLIPS:
            frames = 24
            binary.extend(struct.pack('<16sfII', name.encode(), duration, frames, loop))
            for frame in range(frames):
                transforms, shift = poses[name, frame]
                v, n = pose(vertices, normals, skin, transforms, shift)
                binary.extend(np.column_stack((v, n)).astype('<f4').tobytes())
        im = Image.new('RGB',(8,8),(230,239,246)) if texture=='Snow' else Image.open(io.BytesIO(textures[texture])).convert('RGB')
        im.thumbnail((512, 512), Image.Resampling.LANCZOS)
        im.save(output / (texture.lower() + '.png'))
    (output / 'fox.skan').write_bytes(binary)
    _, vertices, normals, uv, triangles = geometry(root, 'meshId0')
    snow_textures(output, vertices, normals, uv, triangles)
    # Both eyeballs are separate closed meshes within section two. Pupils are
    # in the texture: rotating each globe around its own centre moves the gaze.
    _, eyes, _, _, _ = geometry(root, 'meshId1')
    groups = []
    for side in (-1, 1):
        indices = np.where(eyes[:, 1] * side > 0)[0]
        points = eyes[indices]
        groups.append({'section': 2, 'vertices': (indices + 1).tolist(),
                       'x_pair': (indices[[points[:, 0].argmin(), points[:, 0].argmax()]] + 1).tolist(),
                       'z_pair': (indices[[points[:, 2].argmin(), points[:, 2].argmax()]] + 1).tolist(),
                       'yaw_limit': 16, 'pitch_limit': 10})
    (output / 'fox-eyes.json').write_text(json.dumps(
        {'format': 'skieo-aim-rig', 'version': 1, 'groups': groups}, separators=(',', ':')) + '\n')
    contact = {'format':'skieo-ground-rig','version':1,'section':1,
               'leg_height_cm':float(max(bones[p['bone']]['pivot_cm'][2]-p['rest'][2] for p in paws)),
               'paw_spacing':0.82,
               'paws':paws,'clips':{name:{'duration':duration,'loop':loop,
                   **({'stride':GAITS[name][0],'stance':GAITS[name][1],
                       'lift':GAITS[name][2],'offsets':GAITS[name][3]} if name in GAITS else {})}
                   for name,duration,loop in CLIPS}}
    # This small runtime rig contains sole vertices and two joint anchors per
    # leg, rather than the full authoring skeleton/weights.
    (output/'fox-ground.json').write_text(json.dumps(contact,separators=(',',':'))+'\n')
    rig_data['aim_rig'] = 'fox-eyes.json'
    (output / 'fox-rig.json').write_text(json.dumps(rig_data, separators=(',', ':'))+'\n')
    print(f'{output}/fox.skan: {len(binary):,} bytes; 16 weighted joints, {len(CLIPS)} clips')
    return rig_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'mod/SkiEO-Foxes/Assets')
    args = parser.parse_args()
    build(args.archive, args.output)
