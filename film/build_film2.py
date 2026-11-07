import bpy, math, sys, os
from mathutils import Vector, Matrix, Quaternion
sys.path.insert(0, '/home/claude/film')
import model as M
from model import HS, ease, easeIO, lerp, clamp, OPS, QOP, POSES, FLAT, GRIP, FACES, NF

FPS = 24
OUT = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else '/home/claude/film/origami_robot_render.blend'
RES = (1280, 720)

# ------------------------------------------------------------------ scene reset + imports
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
for g in ('arm', 'crane'):
    bpy.ops.import_scene.gltf(filepath=f'/home/claude/blend/{g}.glb')
O = bpy.data.objects
c2b = lambda p: Vector((p[0], -p[2], p[1]))          # three.js -> blender
b2c = lambda v: Vector((v.x, v.z, -v.y))

arm_root = O['arm_root']; arm_root.location = c2b((4.6, 0, -2.2))
crane_root = O['crane_root']

# ------------------------------------------------------------------ materials
def sock(n, name, v):
    try: n.inputs[name].default_value = v
    except Exception: pass

def new_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    return m, nt

def N(nt, kind, **kw):
    n = nt.nodes.new(kind)
    for k, v in kw.items(): setattr(n, k, v)
    return n

def link(nt, a, ao, b, bi):
    nt.links.new(a.outputs[ao] if isinstance(ao, (int, str)) else ao, b.inputs[bi])

def noise(nt, scale, detail=8, rough=.55, mapscale=(1, 1, 1), coord='Object', distort=0.0):
    tc = N(nt, 'ShaderNodeTexCoord'); mp = N(nt, 'ShaderNodeMapping')
    mp.inputs['Scale'].default_value = mapscale
    nt.links.new(tc.outputs[coord], mp.inputs['Vector'])
    nz = N(nt, 'ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = scale; nz.inputs['Detail'].default_value = detail
    nz.inputs['Roughness'].default_value = rough
    try: nz.inputs['Distortion'].default_value = distort
    except Exception: pass
    nt.links.new(mp.outputs['Vector'], nz.inputs['Vector'])
    return nz

def mix_rgb(nt, fac, a, b):
    m = N(nt, 'ShaderNodeMix', data_type='RGBA')
    m.inputs[0].default_value = fac if isinstance(fac, float) else 0.5
    if not isinstance(fac, float): nt.links.new(fac, m.inputs[0])
    for idx, v in ((6, a), (7, b)):
        if isinstance(v, tuple): m.inputs[idx].default_value = v
        else: nt.links.new(v, m.inputs[idx])
    return m, m.outputs[2]

def ramp(nt, src, stops):
    r = N(nt, 'ShaderNodeValToRGB')
    r.color_ramp.elements[0].position = stops[0][0]; r.color_ramp.elements[0].color = stops[0][1]
    r.color_ramp.elements[1].position = stops[1][0]; r.color_ramp.elements[1].color = stops[1][1]
    nt.links.new(src, r.inputs['Fac'])
    return r

def hexc(h, a=1.0):
    h = h.lstrip('#'); r, g, b = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
    f = lambda c: ((c + .055)/1.055)**2.4 if c > .04045 else c/12.92
    return (f(r), f(g), f(b), a)

def edge_mask(nt, radius=.012, lo=.965, hi=.998):
    bev = N(nt, 'ShaderNodeBevel', samples=6); bev.inputs['Radius'].default_value = radius
    geo = N(nt, 'ShaderNodeNewGeometry')
    dot = N(nt, 'ShaderNodeVectorMath', operation='DOT_PRODUCT')
    nt.links.new(geo.outputs['Normal'], dot.inputs[0]); nt.links.new(bev.outputs['Normal'], dot.inputs[1])
    r = ramp(nt, dot.outputs['Value'], [(lo, (1, 1, 1, 1)), (hi, (0, 0, 0, 1))])
    return r.outputs['Color'], bev.outputs['Normal']

def ao_dirt(nt, dist=.3):
    ao = N(nt, 'ShaderNodeAmbientOcclusion', samples=10); ao.inputs['Distance'].default_value = dist
    inv = N(nt, 'ShaderNodeMath', operation='SUBTRACT'); inv.inputs[0].default_value = 1.0
    nt.links.new(ao.outputs['AO'], inv.inputs[1])
    r = ramp(nt, inv.outputs[0], [(.15, (0, 0, 0, 1)), (.85, (1, 1, 1, 1))])
    return r.outputs['Color']

def finish(nt, shader):
    out = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(shader.outputs[0], out.inputs['Surface'])

def principled(nt, base=None, rough=.5, metal=0., **kw):
    p = N(nt, 'ShaderNodeBsdfPrincipled')
    if isinstance(base, tuple): sock(p, 'Base Color', base)
    elif base is not None: nt.links.new(base, p.inputs['Base Color'])
    sock(p, 'Roughness', rough); sock(p, 'Metallic', metal)
    for k, v in kw.items(): sock(p, k.replace('_', ' '), v)
    return p

def bump(nt, height, strength, dist, normal=None):
    b = N(nt, 'ShaderNodeBump'); b.inputs['Strength'].default_value = strength; b.inputs['Distance'].default_value = dist
    nt.links.new(height, b.inputs['Height'])
    if normal is not None: nt.links.new(normal, b.inputs['Normal'])
    return b.outputs['Normal']

MATS = {}
def build_materials():
    # --- yellow industrial paint: orange peel, chipped at the edges, dirt in crevices
    m, nt = new_mat('yellow'); MATS['yellow'] = m
    emask, bevn = edge_mask(nt, .014)
    chip = noise(nt, 18, 6, .6); chipr = ramp(nt, chip.outputs['Fac'], [(.42, (0, 0, 0, 1)), (.58, (1, 1, 1, 1))])
    wear = N(nt, 'ShaderNodeMath', operation='MULTIPLY'); nt.links.new(emask, wear.inputs[0]); nt.links.new(chipr.outputs['Color'], wear.inputs[1])
    dirt = ao_dirt(nt, .35)
    _, base = mix_rgb(nt, dirt, hexc('#e3a200'), hexc('#2a2008'))
    peel = noise(nt, 900, 3, .5)
    nrm = bump(nt, peel.outputs['Fac'], .35, .004, bevn)
    paint = principled(nt, base, .42, 0., Coat_Weight=.7, Coat_Roughness=.18); nt.links.new(nrm, paint.inputs['Normal'])
    nt.links.new(nrm, paint.inputs['Coat Normal']) if 'Coat Normal' in paint.inputs else None
    stl = principled(nt, hexc('#8b8f94'), .38, 1.)
    mix = N(nt, 'ShaderNodeMixShader'); nt.links.new(wear.outputs[0], mix.inputs[0]); nt.links.new(paint.outputs[0], mix.inputs[1]); nt.links.new(stl.outputs[0], mix.inputs[2])
    finish(nt, mix)

    # --- brushed machined steel
    def steel_like(name, col, rough, grime):
        m, nt = new_mat(name); MATS[name] = m
        emask, bevn = edge_mask(nt, .01)
        brush = noise(nt, 2, 4, .7, mapscale=(1, 260, 260), distort=.2)
        scr = noise(nt, 40, 5, .55)
        nrm = bump(nt, brush.outputs['Fac'], .55, .0025, bevn)
        dirt = ao_dirt(nt, .3)
        _, b0 = mix_rgb(nt, dirt, hexc(col), hexc(grime))
        _, b1 = mix_rgb(nt, emask, b0, hexc('#f0f1f2'))
        rr = ramp(nt, brush.outputs['Fac'], [(.3, (rough*.7,)*3 + (1,)), (.7, (rough*1.25,)*3 + (1,))])
        p = principled(nt, b1, .5, 1., Anisotropic=.6); nt.links.new(rr.outputs['Color'], p.inputs['Roughness']); nt.links.new(nrm, p.inputs['Normal'])
        finish(nt, p)
    steel_like('steel', '#c9ccd0', .34, '#50545a')
    steel_like('bolt', '#a9aeb3', .3, '#3d4146')
    steel_like('dark', '#4c5157', .45, '#14161a')

    # --- black cast iron / pebbled
    m, nt = new_mat('black'); MATS['black'] = m
    emask, bevn = edge_mask(nt, .012)
    peb = noise(nt, 160, 6, .6); nrm = bump(nt, peb.outputs['Fac'], .5, .003, bevn)
    dirt = ao_dirt(nt, .3); _, b0 = mix_rgb(nt, dirt, hexc('#1e2022'), hexc('#050505')); _, b1 = mix_rgb(nt, emask, b0, hexc('#5a5d60'))
    p = principled(nt, b1, .62, .4); nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)

    # --- rubber pads
    m, nt = new_mat('rubber'); MATS['rubber'] = m
    peb = noise(nt, 420, 7, .65); nrm = bump(nt, peb.outputs['Fac'], 1.0, .004)
    p = principled(nt, hexc('#141414'), .93, 0., Sheen_Weight=.4, Sheen_Roughness=.8); nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)

    # --- hoses and cable
    m, nt = new_mat('hose'); MATS['hose'] = m
    peb = noise(nt, 240, 5, .5); nrm = bump(nt, peb.outputs['Fac'], .25, .002)
    p = principled(nt, hexc('#17181a'), .5, 0., Coat_Weight=.3, Coat_Roughness=.35); nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)
    m, nt = new_mat('cable'); MATS['cable'] = m
    p = principled(nt, hexc('#e0620f'), .4, 0., Coat_Weight=.5, Coat_Roughness=.25); finish(nt, p)

    # --- olive cardstock (front carries the printed invitation, back is plain and darker)
    img = bpy.data.images.load('/home/claude/film/invitation2.png'); img.alpha_mode = 'STRAIGHT'; img.pack()
    img_back = bpy.data.images.load('/home/claude/film/invitation_back.png'); img_back.alpha_mode = 'STRAIGHT'; img_back.pack()
    qimg = {}
    for side in ('front', 'back'):
        for k in ('A', 'B'):
            im = bpy.data.images.load(f'/home/claude/film/q_{side}_{k}.png'); im.colorspace_settings.name = 'Non-Color'; im.pack(); qimg[(side, k)] = im
    COPPER = hexc('#c4804f')
    def paper(name, base_hex, printed, side=None, glow=True):
        m, nt = new_mat(name); MATS[name] = m
        tc0 = N(nt, 'ShaderNodeTexCoord')
        mott = noise(nt, 5, 6, .6); mr = ramp(nt, mott.outputs['Fac'], [(.3, (.86,)*3 + (1,)), (.7, (1.12,)*3 + (1,))])
        mul = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); mul.inputs[0].default_value = 1.0
        mul.inputs[6].default_value = hexc(base_hex); nt.links.new(mr.outputs['Color'], mul.inputs[7]); base = mul.outputs[2]
        if glow and printed:
            gm = N(nt, 'ShaderNodeMapping'); gm.inputs['Location'].default_value = (-.5, -.5, 0)
            nt.links.new(tc0.outputs['UV'], gm.inputs['Vector'])
            gr = N(nt, 'ShaderNodeTexGradient', gradient_type='SPHERICAL'); nt.links.new(gm.outputs['Vector'], gr.inputs['Vector'])
            gg = ramp(nt, gr.outputs['Fac'], [(0.0, (1.55,)*3 + (1,)), (.62, (.9,)*3 + (1,))])
            m2 = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); m2.inputs[0].default_value = 1.0
            nt.links.new(base, m2.inputs[6]); nt.links.new(gg.outputs['Color'], m2.inputs[7]); base = m2.outputs[2]
        vor = N(nt, 'ShaderNodeTexVoronoi'); vor.inputs['Scale'].default_value = 520; vor.inputs['Randomness'].default_value = 1.0
        tcb = N(nt, 'ShaderNodeTexCoord'); nt.links.new(tcb.outputs['Object'], vor.inputs['Vector'])
        fl = ramp(nt, vor.outputs['Distance'], [(.0, (1, 1, 1, 1)), (.07, (0, 0, 0, 1))])
        _, base = mix_rgb(nt, fl.outputs['Color'], base, hexc('#8c9a82'))
        fnz = noise(nt, 60, 3, .5, mapscale=(1, 40, 1)); fnz2 = noise(nt, 60, 3, .5, mapscale=(40, 1, 1))
        fz = N(nt, 'ShaderNodeMath', operation='ADD'); nt.links.new(fnz.outputs['Fac'], fz.inputs[0]); nt.links.new(fnz2.outputs['Fac'], fz.inputs[1])
        tooth = noise(nt, 1300, 12, .65)
        th = N(nt, 'ShaderNodeMath', operation='ADD'); nt.links.new(tooth.outputs['Fac'], th.inputs[0]); nt.links.new(fz.outputs[0], th.inputs[1])
        height = th.outputs[0]; ink = None
        def vmax(a_, b_):
            mx = N(nt, 'ShaderNodeMath', operation='MAXIMUM'); nt.links.new(a_, mx.inputs[0]); nt.links.new(b_, mx.inputs[1]); return mx.outputs[0]
        if printed:
            tc = N(nt, 'ShaderNodeTexCoord'); it = N(nt, 'ShaderNodeTexImage'); it.image = (printed if printed is not True else img); it.extension = 'CLIP'
            nt.links.new(tc.outputs['UV'], it.inputs['Vector']); ink = it.outputs['Alpha']
        if side:
            tcq = N(nt, 'ShaderNodeTexCoord'); total = None
            for k, grp in (('A', 0), ('B', 3)):
                qi = N(nt, 'ShaderNodeTexImage'); qi.image = qimg[(side, k)]; qi.extension = 'CLIP'; qi.interpolation = 'Linear'
                nt.links.new(tcq.outputs['UV'], qi.inputs['Vector'])
                sp = N(nt, 'ShaderNodeSeparateColor')
                nt.links.new(qi.outputs['Color'], sp.inputs['Color'])
                for c, ch in enumerate(('Red', 'Green', 'Blue')):
                    vis = N(nt, 'ShaderNodeValue'); vis.name = f'vis{grp + c}'; vis.label = vis.name; vis.outputs[0].default_value = 1.0
                    mu = N(nt, 'ShaderNodeMath', operation='MULTIPLY'); nt.links.new(sp.outputs[ch], mu.inputs[0]); nt.links.new(vis.outputs[0], mu.inputs[1])
                    total = mu.outputs[0] if total is None else vmax(total, mu.outputs[0])
            ink = total if ink is None else vmax(ink, total)
        rough = .9; metal_in = rough_in = None
        if ink is not None:
            _, base = mix_rgb(nt, ink, base, COPPER)
            hh = N(nt, 'ShaderNodeMath', operation='SUBTRACT'); nt.links.new(height, hh.inputs[0]); nt.links.new(ink, hh.inputs[1]); height = hh.outputs[0]   # engraved: pressed into the card
            mm = N(nt, 'ShaderNodeMath', operation='MULTIPLY'); mm.inputs[1].default_value = .85; nt.links.new(ink, mm.inputs[0]); metal_in = mm.outputs[0]
            rr = N(nt, 'ShaderNodeMath', operation='MULTIPLY_ADD'); rr.inputs[1].default_value = -.5; rr.inputs[2].default_value = .9; nt.links.new(ink, rr.inputs[0]); rough_in = rr.outputs[0]
        nrm = bump(nt, height, 1.4, .0055)
        p = principled(nt, base, rough, 0., Sheen_Weight=.12, Sheen_Roughness=.6, Subsurface_Weight=.05, Specular_IOR_Level=.1)
        sock(p, 'Subsurface Radius', (.25, .25, .12)); sock(p, 'Subsurface Scale', .012)
        if metal_in is not None: nt.links.new(metal_in, p.inputs['Metallic']); nt.links.new(rough_in, p.inputs['Roughness'])
        nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)
    paper('paper_front', '#344833', True, 'front')
    paper('paper_back', '#a7b39f', img_back, 'back', glow=False)
    # cut edge of the card shows its lighter core
    m, nt = new_mat('paper_edge'); MATS['paper_edge'] = m
    tooth = noise(nt, 600, 8, .6); nrm = bump(nt, tooth.outputs['Fac'], .6, .002)
    p = principled(nt, hexc('#b9c2ae'), .95, 0.); nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)
    # crane (same cardstock, olive both sides)
    paper('paper_crane', '#a7b39f', False)

    # --- table: warm matte card stock
    # --- low Japanese tea table (chabudai): warm walnut, hand-rubbed lacquer; dark tatami floor far below
    m, nt = new_mat('wood'); MATS['wood'] = m
    g1 = noise(nt, 7, 6, .6, mapscale=(1.0, .05, 1.0), distort=1.2); g2 = noise(nt, 1.6, 3, .5, mapscale=(1.0, .15, 1.0))
    gs = N(nt, 'ShaderNodeMath', operation='MULTIPLY_ADD'); gs.inputs[1].default_value = .6; nt.links.new(g2.outputs['Fac'], gs.inputs[0]); nt.links.new(g1.outputs['Fac'], gs.inputs[2])
    gr = ramp(nt, gs.outputs[0], [(.25, hexc('#2c2119')), (.7, hexc('#3d2c20')), (1.1, hexc('#503a28'))])
    fib = noise(nt, 60, 6, .6, mapscale=(1, .04, 1)); fb = ramp(nt, fib.outputs['Fac'], [(.3, (.88,)*3 + (1,)), (.7, (1.1,)*3 + (1,))])
    wmx = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); wmx.inputs[0].default_value = 1.0
    nt.links.new(gr.outputs['Color'], wmx.inputs[6]); nt.links.new(fb.outputs['Color'], wmx.inputs[7])
    pore = noise(nt, 300, 6, .6, mapscale=(1, .04, 1))
    nrm = bump(nt, pore.outputs['Fac'], .25, .0008)
    p = principled(nt, wmx.outputs[2], .5, 0., Coat_Weight=.35, Coat_Roughness=.28, Specular_IOR_Level=.3); nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)
    m, nt = new_mat('floor'); MATS['floor'] = m
    tcf = N(nt, 'ShaderNodeTexCoord'); br = N(nt, 'ShaderNodeTexBrick'); br.offset = .5; br.offset_frequency = 2; br.squash = 1.0; br.squash_frequency = 2
    br.inputs['Scale'].default_value = 1.0; br.inputs['Mortar Size'].default_value = .12; br.inputs['Mortar Smooth'].default_value = .05
    br.inputs['Bias'].default_value = 0.0; br.inputs['Brick Width'].default_value = 24.0; br.inputs['Row Height'].default_value = 12.0
    br.inputs['Color1'].default_value = hexc('#8c8160'); br.inputs['Color2'].default_value = hexc('#837856'); br.inputs['Mortar'].default_value = hexc('#2b281f')
    nt.links.new(tcf.outputs['Object'], br.inputs['Vector'])
    wvx = noise(nt, 90, 5, .6, mapscale=(1, .03, 1)); wvy = noise(nt, 90, 5, .6, mapscale=(.03, 1, 1))
    wsum = N(nt, 'ShaderNodeMath', operation='ADD'); nt.links.new(wvx.outputs['Fac'], wsum.inputs[0]); nt.links.new(wvy.outputs['Fac'], wsum.inputs[1])
    wr = ramp(nt, wsum.outputs[0], [(.6, (.85,)*3 + (1,)), (1.1, (1.1,)*3 + (1,))])
    fm = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); fm.inputs[0].default_value = 1.0
    nt.links.new(br.outputs['Color'], fm.inputs[6]); nt.links.new(wr.outputs['Color'], fm.inputs[7])
    nrm = bump(nt, wsum.outputs[0], .7, .012)
    p = principled(nt, fm.outputs[2], .9, 0.); nt.links.new(nrm, p.inputs['Normal']); finish(nt, p)
    m, nt = new_mat('table'); MATS['table'] = m
    big = noise(nt, .35, 4, .6, coord='Object'); mott = noise(nt, 3, 8, .6, coord='Object')
    bm = ramp(nt, big.outputs['Fac'], [(.25, (.62,)*3 + (1,)), (.75, (1.12,)*3 + (1,))])
    mr = ramp(nt, mott.outputs['Fac'], [(.3, (.82,)*3 + (1,)), (.7, (1.1,)*3 + (1,))])
    m1 = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); m1.inputs[0].default_value = 1.0
    m1.inputs[6].default_value = hexc('#9c9686'); nt.links.new(bm.outputs['Color'], m1.inputs[7])
    mul = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); mul.inputs[0].default_value = 1.0
    nt.links.new(m1.outputs[2], mul.inputs[6]); nt.links.new(mr.outputs['Color'], mul.inputs[7])
    grit = noise(nt, 2200, 6, .7, coord='Object'); mid = noise(nt, 120, 8, .65, coord='Object')
    scr = noise(nt, 40, 4, .5, coord='Object', mapscale=(1, 60, 1))
    hs = N(nt, 'ShaderNodeMath', operation='ADD'); nt.links.new(grit.outputs['Fac'], hs.inputs[0]); nt.links.new(mid.outputs['Fac'], hs.inputs[1])
    hs2 = N(nt, 'ShaderNodeMath', operation='ADD'); nt.links.new(hs.outputs[0], hs2.inputs[0]); nt.links.new(scr.outputs['Fac'], hs2.inputs[1])
    nrm = bump(nt, hs2.outputs[0], 1.3, .006)
    rgh = ramp(nt, mid.outputs['Fac'], [(.3, (.62,)*3 + (1,)), (.7, (.95,)*3 + (1,))])
    p = principled(nt, mul.outputs[2], .8, 0., Sheen_Weight=.1, Specular_IOR_Level=.25); nt.links.new(nrm, p.inputs['Normal']); nt.links.new(rgh.outputs['Color'], p.inputs['Roughness']); finish(nt, p)

build_materials()

# assign by name to imported meshes
for o in O:
    if o.type != 'MESH': continue
    for s in o.material_slots:
        nm = s.material.name.split('.')[0] if s.material else 'steel'
        if o.name.split('.')[0] in ('body_L', 'body_R', 'head_a', 'head_b', 'neck_a', 'neck_b', 'tail_a', 'tail_b', 'wing_L', 'wing_R'): nm = 'paper_crane'
        s.material = MATS.get(nm, MATS['steel'])
    for p in o.data.polygons: p.use_smooth = True if o.name.startswith(('Cylinder', 'fore_', 'upper_', 'grip_h', 'grip_c')) else p.use_smooth

# ------------------------------------------------------------------ table
# --- zataku: low rectangular tea table, slab top on two solid side panels each pierced by a round window (as in the reference photos)
TC = (2.3, 1.1); TL = 12.6; TW = 7.8; TT = .42; TZ = 4.5      # centre xy, length (x), width (y), top thickness, total height
FLOOR_Z = -.004 - TZ
bpy.ops.mesh.primitive_cube_add(size=1, location=(TC[0], TC[1], -.004 - TT/2)); table = bpy.context.active_object; table.name = 'table'
table.scale = (TL, TW, TT); bpy.ops.object.transform_apply(scale=True)
bv = table.modifiers.new('bevel', 'BEVEL'); bv.width = .06; bv.segments = 3
table.data.materials.append(MATS['wood'])
for sx in (-1, 1):
    px_ = TC[0] + sx*(TL/2 - 1.15); ph = TZ - TT
    bpy.ops.mesh.primitive_cube_add(size=1, location=(px_, TC[1], -.004 - TT - ph/2)); pn = bpy.context.active_object; pn.name = f'tpanel{sx}'
    pn.scale = (.55, TW - .5, ph); bpy.ops.object.transform_apply(scale=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=1.25, depth=2.0, vertices=64, location=(px_, TC[1], -.004 - TT - ph/2 + .15), rotation=(0, math.radians(90), 0)); cut = bpy.context.active_object
    bo = pn.modifiers.new('hole', 'BOOLEAN'); bo.operation = 'DIFFERENCE'; bo.object = cut
    bpy.context.view_layer.objects.active = pn; bpy.ops.object.modifier_apply(modifier='hole'); bpy.data.objects.remove(cut, do_unlink=True)
    bw = pn.modifiers.new('bevel', 'BEVEL'); bw.width = .05; bw.segments = 2
    pn.data.materials.clear(); pn.data.materials.append(MATS['wood'])
    for p_ in pn.data.polygons: p_.material_index = 0; p_.use_smooth = False
RY = 11.0                                            # inner face of the shoji wall (blender y)
bpy.ops.mesh.primitive_plane_add(size=1, location=(5, (RY - 34)/2, FLOOR_Z)); flo = bpy.context.active_object; flo.name = 'floor'; flo.scale = (42, RY + 34, 1)
bpy.ops.object.transform_apply(scale=True); flo.data.materials.append(MATS['floor'])
def run_cable(name, pts, radius, mat):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = radius; cu.bevel_resolution = 5; cu.use_fill_caps = True
    sp = cu.splines.new('BEZIER'); sp.bezier_points.add(len(pts) - 1)
    for bp, pt in zip(sp.bezier_points, pts):
        bp.co = pt; bp.handle_left_type = bp.handle_right_type = 'AUTO'
    ob = bpy.data.objects.new(name, cu); scene.collection.objects.link(ob); cu.materials.append(MATS[mat])
    return ob
# cables leave the base, wander over the slab, and drape over the +y long edge to the floor (they never cross the wood)
m_wall_, _nt = new_mat('plaster'); _pw = principled(_nt, hexc('#262b36'), .95, 0.); _bw = noise(_nt, 25, 6, .6); _nt.links.new(bump(_nt, _bw.outputs['Fac'], .3, .01), _pw.inputs['Normal']); finish(_nt, _pw)
EDGE_X = TC[0] + TL/2
def cable_path(off, wob, r):
    bx, by = 4.6, 2.2; y0 = by - .3 + off
    top = [(bx + .85, by + .15 + off*.4, .22), (bx + 1.7, y0 + wob, .07), (bx + 2.6, y0 - wob*.8, .07), (bx + 3.3, y0 + wob*.5, .07), (EDGE_X - .5, y0, .07)]
    drop = [(EDGE_X + .02 + r, y0, .05), (EDGE_X + .16 + r, y0, -.2), (EDGE_X + .24 + r, y0, -1.4), (EDGE_X + .45 + r, y0 - .3, FLOOR_Z + r)]
    run = [(EDGE_X + 1.3 + wob, y0 - 2.5, FLOOR_Z + r), (EDGE_X + 1.0 - wob, y0 - 6.5, FLOOR_Z + r), (EDGE_X + 2.0 + wob, y0 - 11, FLOOR_Z + r), (EDGE_X + 1.4, y0 - 17, FLOOR_Z + r), (EDGE_X + 2.4, y0 - 26, FLOOR_Z + r)]
    return top + drop + run
run_cable('cable_power', cable_path(.1, .35, .085), .085, 'hose')
run_cable('cable_signal', cable_path(-.5, -.25, .045), .045, 'cable')
EDGE_XL = TC[0] - TL/2
def cable_path_L(off, wob, r):
    bx, by = -3.2, 2.4; y0 = by - .3 + off; X = EDGE_XL
    top = [(bx - .85, by + .15 + off*.4, .22), (bx - 1.7, y0 + wob, .07), (X + 3.3, y0 - wob*.8, .07), (X + 1.8, y0 + wob*.5, .07), (X + .5, y0, .07)]
    drop = [(X - .02 - r, y0, .05), (X - .16 - r, y0, -.2), (X - .24 - r, y0, -1.4), (X - .45 - r, y0 - .3, FLOOR_Z + r)]
    run = [(X - 1.3 - wob, y0 - 2.5, FLOOR_Z + r), (X - 1.0 + wob, y0 - 6.5, FLOOR_Z + r), (X - 2.0 - wob, y0 - 11, FLOOR_Z + r), (X - 1.4, y0 - 17, FLOOR_Z + r), (X - 2.4, y0 - 26, FLOOR_Z + r)]
    return top + drop + run
run_cable('cable_power_B', cable_path_L(.1, .3, .085), .085, 'hose')
run_cable('cable_signal_B', cable_path_L(-.5, -.2, .045), .045, 'cable')
# side walls (blank plaster, ready for the event flyers)
for nm, xa, xb in (('wall_L', -16.7, -16.0), ('wall_R', 26.0, 26.7)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((xa + xb)/2, (RY - 34 + RY + .7)/2, (FLOOR_Z + 16)/2)); wo = bpy.context.active_object; wo.name = nm
    wo.scale = (xb - xa, RY + .7 + 34, 16 - FLOOR_Z); bpy.ops.object.transform_apply(scale=True); wo.data.materials.append(m_wall_)
# --- shoji window wall behind the table: moonlight enters through the lattice and throws its shadow on the table, the arm and the paper
def box(name, x0, x1, y0, y1, z0, z1, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0+x1)/2, (y0+y1)/2, (z0+z1)/2)); o = bpy.context.active_object; o.name = name
    o.scale = (x1-x0, y1-y0, z1-z0); bpy.ops.object.transform_apply(scale=True); o.data.materials.append(mat); return o
m_wall = m_wall_
m_sho, nt = new_mat('shoji_wood'); ps = principled(nt, hexc('#7a6547'), .55, 0., Coat_Weight=.15); finish(nt, ps)
WX0, WX1, WZ0, WZ1 = -1.0, 15.0, -2.0, 9.5
for nm, a_, b_, c_, d_ in (('wl', -16, WX0, FLOOR_Z, 16), ('wr', WX1, 26, FLOOR_Z, 16), ('wb', WX0, WX1, FLOOR_Z, WZ0), ('wt', WX0, WX1, WZ1, 16)):
    box(nm, a_, b_, RY, RY + .7, c_, d_, m_wall)
for k in range(9):                                      # vertical kumiko bars
    x = WX0 + k*(WX1 - WX0)/8; box(f'kv{k}', x - .09, x + .09, RY - .05, RY + .35, WZ0, WZ1, m_sho)
for k, z in enumerate((WZ0, .3, 2.6, 4.9, 7.2, WZ1)):   # horizontal rails
    box(f'kh{k}', WX0, WX1, RY - .05, RY + .35, z - .09, z + .09, m_sho)
for k in range(1, 8):                                   # fine intermediate lattice in the top pane
    zz = 7.2 + k*(WZ1 - 7.2)/8; box(f'kf{k}', WX0, WX1, RY, RY + .3, zz - .035, zz + .035, m_sho)
m_pap, nt = new_mat('shoji_paper'); em = N(nt, 'ShaderNodeEmission'); n_ = noise(nt, 14, 6, .6, mapscale=(1, 1, 1)); n_ = noise(nt, 2.2, 4, .5); rr_ = ramp(nt, n_.outputs['Fac'], [(.25, hexc('#7f95c2')), (.8, hexc('#b7c7ea'))]); fb_ = noise(nt, 380, 8, .75, mapscale=(1, 1, 1)); fbr = ramp(nt, fb_.outputs['Fac'], [(.35, (.82,)*3 + (1,)), (.7, (1.08,)*3 + (1,))])
fbm = N(nt, 'ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY'); fbm.inputs[0].default_value = 1.0; nt.links.new(rr_.outputs['Color'], fbm.inputs[6]); nt.links.new(fbr.outputs['Color'], fbm.inputs[7])
nt.links.new(fbm.outputs[2], em.inputs['Color']); em.inputs['Strength'].default_value = 1.5
oo = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(em.outputs[0], oo.inputs[0])
bpy.ops.mesh.primitive_plane_add(size=1, location=((WX0 + WX1)/2, RY + .5, (WZ0 + WZ1)/2), rotation=(math.radians(90), 0, 0)); pp = bpy.context.active_object; pp.name = 'shoji_paper'
pp.scale = (WX1 - WX0, WZ1 - WZ0, 1); bpy.ops.object.transform_apply(scale=True); pp.data.materials.append(m_pap); pp.visible_shadow = False

# --- faint room haze: catches the moonlight as soft beams and gives the dust something to float in
bpy.ops.mesh.primitive_cube_add(size=1, location=(5, (RY - 14)/2 - .5, 5)); hz = bpy.context.active_object; hz.name = 'haze'
hz.scale = (42, RY + 14 - 1, 20); bpy.ops.object.transform_apply(scale=True); hz.display_type = 'WIRE'; hz.visible_shadow = False
m_hz, nt = new_mat('haze'); vs_ = N(nt, 'ShaderNodeVolumePrincipled'); vs_.inputs['Density'].default_value = .006; sock(vs_, 'Anisotropy', .55)
sock(vs_, 'Color', (.92, .94, 1.0, 1)); oo = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(vs_.outputs[0], oo.inputs['Volume']); hz.data.materials.append(m_hz)

# --- warm floor lantern in the corner (small warm light against the cool moonlight) and a woven zabuton beside the table
al = bpy.data.lights.new('andon', 'POINT'); al.energy = 260; al.color = (1.0, .66, .36); al.shadow_soft_size = .5
ao = bpy.data.objects.new('andon', al); scene.collection.objects.link(ao); ao.location = (14.5, 8.2, FLOOR_Z + 2.2)
bpy.ops.mesh.primitive_uv_sphere_add(radius=.5, segments=24, ring_count=12, location=(14.5, 8.2, FLOOR_Z + 2.2)); lant = bpy.context.active_object; lant.name = 'lantern'
m_lan, nt = new_mat('lantern'); e2 = N(nt, 'ShaderNodeEmission'); e2.inputs['Color'].default_value = hexc('#ffb36b'); e2.inputs['Strength'].default_value = 6.0
o2 = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(e2.outputs[0], o2.inputs[0]); lant.data.materials.append(m_lan); lant.visible_shadow = False
bpy.ops.mesh.primitive_cylinder_add(radius=.08, depth=2.0, vertices=12, location=(14.5, 8.2, FLOOR_Z + 1.0)); pole = bpy.context.active_object; pole.data.materials.append(MATS['wood'])
m_cu, nt = new_mat('cushion'); cn = noise(nt, 160, 6, .6, mapscale=(1, 1, 1)); cr = ramp(nt, cn.outputs['Fac'], [(.3, hexc('#4a3a2c')), (.8, hexc('#6b5843'))])
cb = noise(nt, 700, 4, .6, mapscale=(1, .2, 1)); cp = principled(nt, cr.outputs['Color'], .95, 0., Sheen_Weight=.4); nt.links.new(bump(nt, cb.outputs['Fac'], 1.2, .01), cp.inputs['Normal']); finish(nt, cp)
bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=48, ring_count=24, location=(-8.3, 2.0, FLOOR_Z + .55)); cu_ = bpy.context.active_object; cu_.name = 'zabuton'
cu_.scale = (1.9, 1.9, .55); bpy.ops.object.transform_apply(scale=True); cu_.data.materials.append(m_cu)
for p_ in cu_.data.polygons: p_.use_smooth = True

# --- bonsai in the corner
BX, BY = 12.0, 7.2
m_pot, nt = new_mat('pot'); pt_ = principled(nt, hexc('#1b2431'), .3, 0., Coat_Weight=.7, Coat_Roughness=.12); finish(nt, pt_)
m_soil, nt = new_mat('soil'); sl_ = principled(nt, hexc('#2a1f17'), .95, 0.); nt.links.new(bump(nt, noise(nt, 300, 6, .7).outputs['Fac'], 1.0, .01), sl_.inputs['Normal']); finish(nt, sl_)
m_bark, nt = new_mat('bark'); bk_ = principled(nt, hexc('#3b2d22'), .85, 0.); nt.links.new(bump(nt, noise(nt, 55, 8, .65, mapscale=(1, 1, .12)).outputs['Fac'], 1.6, .02), bk_.inputs['Normal']); finish(nt, bk_)
m_leaf, nt = new_mat('leaf'); lf = noise(nt, 9, 6, .6); lr = ramp(nt, lf.outputs['Fac'], [(.25, hexc('#1a3320')), (.55, hexc('#2c5230')), (.85, hexc('#4a7a3c'))])
lp = principled(nt, lr.outputs['Color'], .6, 0., Subsurface_Weight=.2); nt.links.new(bump(nt, noise(nt, 160, 5, .6).outputs['Fac'], .8, .015), lp.inputs['Normal']); finish(nt, lp)
bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=.7, vertices=48, location=(BX, BY, FLOOR_Z + .35)); pot = bpy.context.active_object; pot.name = 'pot'
bv = pot.modifiers.new('b', 'BEVEL'); bv.width = .08; bv.segments = 3; pot.data.materials.append(m_pot)
for p_ in pot.data.polygons: p_.use_smooth = True
bpy.ops.mesh.primitive_cylinder_add(radius=.9, depth=.05, vertices=48, location=(BX, BY, FLOOR_Z + .68)); sd = bpy.context.active_object; sd.name = 'soil'; sd.data.materials.append(m_soil)
def branch(name, pts, rad):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = rad; cu.bevel_resolution = 4; cu.use_fill_caps = True
    sp = cu.splines.new('BEZIER'); sp.bezier_points.add(len(pts) - 1)
    for bp, pt in zip(sp.bezier_points, pts): bp.co = pt; bp.handle_left_type = bp.handle_right_type = 'AUTO'
    ob = bpy.data.objects.new(name, cu); scene.collection.objects.link(ob); cu.materials.append(m_bark); return ob
G = FLOOR_Z + .7
branch('trunk', [(BX, BY, G), (BX + .3, BY + .1, G + .9), (BX - .35, BY - .1, G + 1.8), (BX + .25, BY + .15, G + 2.6), (BX + .9, BY + .1, G + 3.2)], .17)
branch('br1', [(BX - .3, BY - .08, G + 1.7), (BX - 1.0, BY - .2, G + 2.1), (BX - 1.7, BY - .1, G + 2.3)], .09)
branch('br2', [(BX + .25, BY + .14, G + 2.5), (BX + .9, BY + .5, G + 2.8), (BX + 1.5, BY + .7, G + 2.7)], .08)
import bmesh, random as _rnd
_rl = _rnd.Random(5); bm = bmesh.new()
m_core, nt = new_mat('leafcore'); pc_ = principled(nt, hexc('#10201a'), .9, 0.); finish(nt, pc_)
PADS = ((1.0, .1, 3.4, 1.0, .5), (-1.9, -.1, 2.5, .95, .42), (1.7, .75, 2.9, .85, .4), (-.2, .2, 2.9, .8, .38), (.2, -.3, 3.7, .6, .3))
for k, (dx, dy, dz, sx_, sz_) in enumerate(PADS):
    c = Vector((BX + dx, BY + dy, G + dz))
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0, location=c); core = bpy.context.active_object; core.name = f'core{k}'
    core.scale = (sx_*.7, sx_*.7, sz_*.7); bpy.ops.object.transform_apply(scale=True); core.data.materials.append(m_core)
    for n in range(300):
        u = Vector((_rl.gauss(0, 1), _rl.gauss(0, 1), _rl.gauss(0, 1) * .8)); u.normalize(); r = .55 + .45*_rl.random()**.6
        if u.z < -.35: continue
        p0 = c + Vector((u.x*sx_*r, u.y*sx_*r, u.z*sz_*r))
        d = (u + Vector((_rl.uniform(-.6, .6), _rl.uniform(-.6, .6), _rl.uniform(-.2, .7)))).normalized()
        q = d.to_track_quat('Y', 'Z'); L = _rl.uniform(.17, .27); W = L*.45; H = L*.18
        loc = [Vector((0, 0, 0)), Vector((-W, L*.45, H*.2)), Vector((0, L*.5, H)), Vector((W, L*.45, H*.2)), Vector((0, L, -H*.3))]
        vs = [bm.verts.new(p0 + q @ v) for v in loc]
        for tri in ((0, 1, 2), (0, 2, 3), (1, 4, 2), (2, 4, 3)): bm.faces.new([vs[i] for i in tri])
    # a few twigs inside the pad so the leaves hang off something
mesh = bpy.data.meshes.new('leaves'); bm.to_mesh(mesh); bm.free(); lo = bpy.data.objects.new('leaves', mesh); scene.collection.objects.link(lo)
lo.data.materials.append(m_leaf)
for p_ in mesh.polygons: p_.use_smooth = True

# ------------------------------------------------------------------ paper mesh (own verts per face; shape keys driven per frame)
me = bpy.data.meshes.new('paper'); paper = bpy.data.objects.new('paper', me); scene.collection.objects.link(paper)
def pose_to_coords(pos): return [c2b((pos[i*9+v*3]*HS, pos[i*9+v*3+1]*HS, pos[i*9+v*3+2]*HS)) for i in range(NF) for v in range(3)]
base = pose_to_coords(POSES[0])
faces = []; vmap = []
flipped = 0
for i in range(NF):
    p0, p1, p2 = base[i*3], base[i*3+1], base[i*3+2]
    cz = (p1.x-p0.x)*(p2.y-p0.y) - (p1.y-p0.y)*(p2.x-p0.x)
    if cz < 0: order = (0, 2, 1); flipped += 1
    else: order = (0, 1, 2)
    faces.append(tuple(i*3 + k for k in order)); vmap.append(order)
print('flipped faces', flipped)
me.from_pydata([tuple(v) for v in base], [], faces)
uvl = me.uv_layers.new(name='UVMap')
for i, f in enumerate(FACES):
    for k in range(3):
        q = f['p'][vmap[i][k]]; uvl.data[i*3+k].uv = ((q[0]+1)/2, (q[1]+1)/2)
for p in me.polygons: p.use_smooth = False
# front normal must face +z in the flat start pose
for poly in me.polygons:
    if poly.normal.z < 0:
        pass
me.update()
paper.data.materials.append(MATS['paper_front']); paper.data.materials.append(MATS['paper_back']); paper.data.materials.append(MATS['paper_edge'])
# lightweight cardstock: subdivide the flat facets and add a slow, soft bow so it reads as thin paper, not a rigid plate
sub = paper.modifiers.new('sub', 'SUBSURF'); sub.subdivision_type = 'SIMPLE'; sub.levels = 3; sub.render_levels = 4
_tx = bpy.data.textures.new('bow', 'CLOUDS'); _tx.noise_scale = 2.2; _tx.noise_depth = 1
dsp = paper.modifiers.new('bow', 'DISPLACE'); dsp.texture = _tx; dsp.strength = .004; dsp.mid_level = 0.0; dsp.direction = 'NORMAL'
sol = paper.modifiers.new('thick', 'SOLIDIFY'); sol.thickness = .006; sol.offset = -1; sol.use_even_offset = True
sol.material_offset = 1; sol.material_offset_rim = 2
# cardstock face colour jitter
import random; rnd = random.Random(3)
bpy.context.view_layer.objects.active = paper

# ------------------------------------------------------------------ the timeline (simulate; keyframe as we go)
# ------------------------------------------------------------------ two arms: one folds, one holds the paper flat
OPS = list(OPS) + [(10, 11), (11, 12)]; GRIP = list(GRIP) + [(0, 0), (0, 0)]
UP = Vector((0, 0, 1))
def basis_world(d):
    x = d.normalized(); z = (UP - x*x.dot(UP)).normalized(); y = z.cross(x)
    return Matrix((x, y, z)).transposed()

def clone_tree(root, sfx):
    objs = [root] + list(root.children_recursive); mp = {}
    for o in objs:
        c = o.copy(); c.name = o.name + sfx; scene.collection.objects.link(c); mp[o] = c
    for o in objs:
        c = mp[o]; c.parent = mp.get(o.parent); c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
    return mp[root]
arm2_root = clone_tree(arm_root, '_B'); arm2_root.location = c2b((-3.2, 0, -2.4))

def mk_arm(root, sfx):
    g = lambda n: O[n + sfx]
    A = dict(root=root, turn=g('turntable'), sh=g('shoulder'), up=g('upper'), fore=g('fore'), wr=g('wrist'), fl=g('finger_L'), fr=g('finger_R'), P0=root.location.copy())
    for k in ('turn', 'up', 'fore', 'wr'): A[k].rotation_mode = 'QUATERNION'
    return A
ARM1 = mk_arm(arm_root, ''); ARM2 = mk_arm(arm2_root, '_B')
L1, L2, DROP = 3.5, 3.3, 2.05
SH_LOC = Vector(ARM1['sh'].location); TURN_LOC = Vector(ARM1['turn'].location)

def solve_arm(A, tip3, openv, yaw, frame):
    tip = c2b(tip3); W = tip + Vector((0, 0, DROP)); P0 = A['P0']
    dh = Vector((W.x - P0.x, W.y - P0.y, 0)); dh.normalize()
    Rt = basis_world(dh); Pt = P0 + TURN_LOC; S = Pt + Rt @ SH_LOC
    dx = math.hypot(W.x - S.x, W.y - S.y); dy = W.z - S.z
    D = math.hypot(dx, dy); D = clamp(D, abs(L1 - L2) + .1, L1 + L2 - .03)
    a1 = math.atan2(dy, dx) + math.acos(clamp((L1*L1 + D*D - L2*L2)/(2*L1*D), -1, 1))
    E = Vector((S.x + dh.x*math.cos(a1)*L1, S.y + dh.y*math.cos(a1)*L1, S.z + math.sin(a1)*L1))
    Ru = basis_world(E - S); Wc = (W - E).normalized()*L2 + E; Rf = basis_world(Wc - E); Rw = Matrix.Rotation(yaw, 3, 'Z')
    A['turn'].rotation_quaternion = Rt.to_quaternion()
    A['up'].rotation_quaternion = (Rt.inverted() @ Ru).to_quaternion()
    A['fore'].rotation_quaternion = (Ru.inverted() @ Rf).to_quaternion()
    A['wr'].rotation_quaternion = (Rf.inverted() @ Rw).to_quaternion()
    gap = .05 + openv*.3; A['fl'].location.x = -gap; A['fr'].location.x = gap
    for o, dp in ((A['turn'], 'rotation_quaternion'), (A['up'], 'rotation_quaternion'), (A['fore'], 'rotation_quaternion'), (A['wr'], 'rotation_quaternion'), (A['fl'], 'location'), (A['fr'], 'location')):
        o.keyframe_insert(dp, frame=frame)
# crane
HP = {'hinge_neck': ('y', 8, -64), 'hinge_head': ('y', 0, 55), 'hinge_tail': ('y', -8, 58), 'hinge_wingL': ('x', 86, 24), 'hinge_wingR': ('x', 94, 156)}
AX = {'x': Vector((1, 0, 0)), 'y': Vector((0, 1, 0)), 'z': Vector((0, 0, 1))}
for nme in HP: O[nme].rotation_mode = 'QUATERNION'
crane_root.rotation_mode = 'XYZ'
def crane_pose(i, t, frame=None):
    e = easeIO(clamp(t))
    z = {8: lerp(.18, 1, e)}.get(i, 1.0)
    hv = dict(hinge_neck=0, hinge_tail=0, hinge_head=0, hinge_wingL=0, hinge_wingR=0)
    if i == 9: hv.update(hinge_neck=e, hinge_tail=e)
    if i >= 10: hv.update(hinge_neck=1, hinge_tail=1)
    if i == 10: hv['hinge_head'] = e
    if i >= 11: hv['hinge_head'] = 1
    if i == 11: hv.update(hinge_wingL=e, hinge_wingR=e)
    crane_root.scale = (HS, HS, HS*z); crane_root.rotation_euler = (0, 0, M.CRANE_YAW)
    for nme, tt in hv.items():
        ax, a, b = HP[nme]; O[nme].rotation_quaternion = Quaternion(AX[ax], math.radians(lerp(a, b, tt)))
    if frame is not None:
        crane_root.keyframe_insert('scale', frame=frame)
        for nme in hv: O[nme].keyframe_insert('rotation_quaternion', frame=frame)

def _bbc(o):
    mw = o.matrix_world; pts = [mw @ Vector(c) for c in o.bound_box]
    return b2c(sum(pts, Vector())/8)
CR_ARM1 = {8: 'hinge_neck', 9: 'hinge_neck', 10: 'hinge_head', 11: 'wing_L'}
CR_ARM2 = {8: 'hinge_tail', 9: 'hinge_tail', 10: 'hinge_tail', 11: 'wing_R'}
def crane_grip(i, t, arm=1):
    crane_pose(i, t); bpy.context.view_layer.update()
    nm = (CR_ARM1 if arm == 1 else CR_ARM2)[i]
    if nm.startswith('hinge'): return b2c(O[nm].matrix_world.translation.copy())
    return _bbc(O[nm])

# ------------------------------------------------------------------ camera: one smooth, monotone move per question (no lag filter, no cuts)
def pose_centroid(pi):
    P = POSES[pi]; xs = [P[i*9+v*3] for i in range(NF) for v in range(3)]; zs = [P[i*9+v*3+2] for i in range(NF) for v in range(3)]
    return (sum(xs)/len(xs)*HS, .12, sum(zs)/len(zs)*HS)
ASK = [dict(az=-.28, el=.5, zoom=1.22, f=(.7, 1.2, -.5)), dict(az=-.15, el=1.05, zoom=.85, f=(0.3, .1, 0)),
       dict(az=.1, el=1.1, zoom=.8, f=pose_centroid(3)), dict(az=-.1, el=1.1, zoom=.7, f=pose_centroid(5)),
       dict(az=.15, el=1.1, zoom=.7, f=pose_centroid(6)), dict(az=-.15, el=1.05, zoom=.7, f=pose_centroid(8))]
FINAL = dict(az=.2, el=.6, zoom=.8, f='crane')
KEYS = ASK + [FINAL]
DIST = max(7.4/(math.tan(math.radians(15))*(16/9))*.78, (3.4/2)/math.tan(math.radians(15))*1.5)
cam_data = bpy.data.cameras.new('cam'); cam = bpy.data.objects.new('cam', cam_data); scene.collection.objects.link(cam); scene.camera = cam
cam_data.sensor_fit = 'VERTICAL'; cam_data.angle = math.radians(30); cam_data.clip_start = .1; cam_data.clip_end = 200
cam_data.shift_x = .17
cam.rotation_mode = 'QUATERNION'
focus_obj = bpy.data.objects.new('focus', None); scene.collection.objects.link(focus_obj)
cam_data.dof.use_dof = True; cam_data.dof.focus_object = focus_obj; cam_data.dof.aperture_fstop = 8.0

PARK1 = Vector((2.6, 2.4, -1.6)); PARK2 = Vector((-1.6, 2.4, -1.8))
def shot_focus(sh):
    if sh['f'] == 'crane': return Vector((0, .55, 0))
    return Vector(sh['f'])
def place_camera(focus3, az, el, zoom, frame):
    d = DIST*zoom
    pos3 = Vector((focus3.x + math.sin(az)*math.cos(el)*d, focus3.y + math.sin(el)*d, focus3.z + math.cos(az)*math.cos(el)*d))
    pb = c2b(pos3); fb = c2b(focus3)
    cam.location = pb; cam.rotation_quaternion = (fb - pb).to_track_quat('-Z', 'Y'); focus_obj.location = fb
    cam.keyframe_insert('location', frame=frame); cam.keyframe_insert('rotation_quaternion', frame=frame); focus_obj.keyframe_insert('location', frame=frame)

# ------------------------------------------------------------------ choreography
T_HS, T_HE = .5, 1.4
T_MOVE1, T_MOVE, T_CLOSE, T_CARRY, T_REL, T_RETPARK, T_LAST = 1.0, .9, .25, 2.3, .25, .8, 1.2
CRANE_CARRY = 2.6
def op_time(op, first):
    return (T_MOVE1 if first else T_MOVE) + T_CLOSE + (CRANE_CARRY if op >= 8 else T_CARRY) + T_REL
segments = []
for j in range(6):
    s0 = QOP[j]; e0 = QOP[j+1] if j < 5 else len(OPS)
    segments.append((j, list(range(s0, e0))))

frame = 1; marks = []
pose_frames = []; crane_vis = []
S = dict(tip1=PARK1.copy(), o1=1.0, y1=0.0, tip2=PARK2.copy(), o2=1.0, pose=(0, 0, 0), crane=None)
kyaw = 1 - (1 - .08)**(60/FPS)
def step_yaw(op):
    g = GRIP[op]; o = g[0]*9 + g[1]*3; A = POSES[OPS[op][0]]; B = POSES[OPS[op][1]]
    dx, dz = B[o]-A[o], B[o+2]-A[o+2]
    if math.hypot(dx, dz) > .01:
        jx, jz = -dz, dx; S['y1'] += (math.atan2(-jz, jx) - S['y1'])*kyaw
def grip_paper(op, a, b, p):
    pos = M.paper_pose(a, b, p); g = GRIP[op]; o = g[0]*9 + g[1]*3
    return Vector((pos[o]*HS, pos[o+1]*HS, pos[o+2]*HS))
P2B = arm2_root.location.copy()
def pin_for(op, a, b):
    """a vertex that barely moves during this fold, far from the folding hand and comfortably in the left arm's reach"""
    p0 = M.paper_pose(a, b, 0.0); p1 = M.paper_pose(a, b, 1.0); g0 = grip_paper(op, a, b, 0.0)
    cands = []
    for k in range(NF*3):
        o = k*3; v0 = Vector((p0[o]*HS, p0[o+1]*HS, p0[o+2]*HS)); v1 = Vector((p1[o]*HS, p1[o+1]*HS, p1[o+2]*HS))
        disp = (v1 - v0).length; bb = c2b(v0); hd = math.hypot(bb.x - P2B.x, bb.y - P2B.y)
        dg = math.hypot(v0.x - g0.x, v0.z - g0.z)
        cands.append((disp, dg, hd, v0))
    ok = [c for c in cands if c[0] < .04*HS and 1.8 <= c[2] <= 5.4]
    if ok: best = max(ok, key=lambda c: c[1])
    else:
        ok = [c for c in cands if 1.8 <= c[2] <= 5.6] or cands
        best = min(ok, key=lambda c: c[0] - .05*c[1])
    return best[3] + Vector((0, .03, 0))

def arc(a, b, e, h):
    return Vector((lerp(a.x, b.x, e), lerp(a.y, b.y, e) + math.sin(math.pi*e)*h, lerp(a.z, b.z, e)))

def run_segment(j, ops):
    global frame
    A_, B_ = KEYS[j], KEYS[j+1]
    total = T_HS + sum(op_time(op, i == 0) for i, op in enumerate(ops)) + T_RETPARK + T_HE
    nf_total = int(round(total*FPS)); nf_total += (nf_total % 2)          # even length -> every segment starts on an odd frame (step 2)
    seg_start = frame; t0 = T_HS*FPS; t1 = nf_total - T_LAST*FPS
    fA, fB = shot_focus(A_), shot_focus(B_)
    def rec():
        global frame
        k = frame - seg_start
        u = easeIO(clamp((k - t0)/max(1, (t1 - t0))))
        place_camera(fA.lerp(fB, u), lerp(A_['az'], B_['az'], u), lerp(A_['el'], B_['el'], u), lerp(A_['zoom'], B_['zoom'], u), frame)
        solve_arm(ARM1, S['tip1'], S['o1'], S['y1'], frame)
        solve_arm(ARM2, S['tip2'], S['o2'], 0.0, frame)
        pose_frames.append((frame, S['pose']))
        if S['crane'] is not None: crane_pose(S['crane'][0], S['crane'][1], frame)
        crane_vis.append((frame, S['crane'] is not None))
        frame += 1
    def phase(sec, fn):
        nf = max(1, int(round(sec*FPS)))
        for k in range(nf):
            fn(k/nf); rec()
    phase(T_HS, lambda t: None)
    for idx, op in enumerate(ops):
        a, b = OPS[op]; is_crane = op >= 8; first = idx == 0
        if is_crane and op > 8: S['crane'] = (op, 0.0)
        gp = crane_grip(op, 0.0) if is_crane else grip_paper(op, a, b, 0.0)
        gp2 = crane_grip(op, 0.0, 2) if is_crane else None
        tip1_0 = S['tip1'].copy(); tip2_0 = S['tip2'].copy(); o2_0 = S['o2']
        pin = None if is_crane else pin_for(op, a, b)
        if not is_crane: S['pose'] = (a, b, 0)
        # --- both hands go to the paper at the same time (the holder arrives first)
        def mv(t, gp2=gp2, gp=gp, tip1_0=tip1_0, tip2_0=tip2_0, pin=pin, o2_0=o2_0, is_crane=is_crane, op=op):
            e = easeIO(ease(t)); S['tip1'] = arc(tip1_0, Vector((gp.x, gp.y + .02, gp.z)), e, .55); S['o1'] = 1.0
            if not is_crane: step_yaw(op)
            e2 = easeIO(ease(clamp(t/.8)))
            if is_crane: S['tip2'] = arc(tip2_0, Vector((gp2.x, gp2.y + .02, gp2.z)), e2, .5); S['o2'] = 1.0
            else: S['tip2'] = arc(tip2_0, pin, e2, .5); S['o2'] = lerp(o2_0 if o2_0 < 1 else 1.0, 1.0, 1.0)
        phase(T_MOVE1 if first else T_MOVE, mv)
        def cl(t, gp2=gp2, gp=gp, pin=pin, is_crane=is_crane, op=op):
            S['tip1'] = Vector((gp.x, gp.y + .02, gp.z)); S['o1'] = 1 - ease(t)
            if not is_crane: step_yaw(op); S['o2'] = 1 - .8*ease(t)
            else: S['tip2'] = Vector((gp2.x, gp2.y + .02, gp2.z)); S['o2'] = 1 - ease(t)
        phase(T_CLOSE, cl)
        def ca(t, a=a, b=b, op=op, is_crane=is_crane):
            p = easeIO(t); S['o1'] = 0.0
            if is_crane:
                g3 = crane_grip(op, p); S['crane'] = (op, p); S['tip2'] = crane_grip(op, p, 2) + Vector((0, .02, 0)); S['o2'] = 0.0
            else:
                g3 = grip_paper(op, a, b, p); S['pose'] = (a, b, p); step_yaw(op)
            S['tip1'] = g3 + Vector((0, .02, 0))
        phase(CRANE_CARRY if is_crane else T_CARRY, ca)
        def rl(t, a=a, b=b, op=op, is_crane=is_crane):
            S['o1'] = ease(t)
            if is_crane:
                g3 = crane_grip(op, 1.0); S['crane'] = (op, 1.0); S['tip2'] = crane_grip(op, 1.0, 2) + Vector((0, .02, 0)); S['o2'] = ease(t)
            else:
                g3 = grip_paper(op, a, b, 1.0); S['pose'] = (a, b, 1.0)
            S['tip1'] = g3 + Vector((0, .02, 0))
        phase(T_REL, rl)
        if not is_crane: S['pose'] = (a, b, 1.0)
    # --- both hands rise to their rest positions while the camera settles
    tip1_r = S['tip1'].copy(); tip2_r = S['tip2'].copy()
    def rp(t):
        e = easeIO(ease(t)); S['tip1'] = arc(tip1_r, PARK1, e, .5); S['tip2'] = arc(tip2_r, PARK2, e, .5); S['o1'] = 1.0; S['o2'] = 1.0
    phase(T_RETPARK, rp)
    S['tip1'] = PARK1.copy(); S['tip2'] = PARK2.copy()
    while frame - seg_start < nf_total: rec()
    marks.append((j, seg_start, frame - 1))

for j, ops in segments:
    run_segment(j, ops)
scene.frame_start = 1; scene.frame_end = frame - 1
print('SEGMENTS', marks, 'frames', frame - 1)


# ------------------------------------------------------------------ paper shape keys from recorded poses
def key_of(pose):
    a, b, p = pose
    return (a, b, round(p, 5))
runs = []  # (key, f0, f1)
for f, pose in pose_frames:
    k = key_of(pose)
    # pose value normalisation: p<=0 -> a-pose, p>=1 -> b-pose
    a, b, p = pose
    if p <= 0: k = ('P', a)
    elif p >= 1: k = ('P', b)
    if runs and runs[-1][0] == k and runs[-1][2] == f - 1: runs[-1][2] = f
    else: runs.append([k, f, f])
# after op 8 the paper is hidden; keep poses (cheap), but we do not need keys for them
print('paper runs', len(runs))
paper.shape_key_add(name='Basis', from_mix=False)
keyobjs = []
cache = {}
for idx, (k, f0, f1) in enumerate(runs):
    if k[0] == 'P': pos = POSES[k[1]]
    else: pos = M.paper_pose(*k)
    kb = paper.shape_key_add(name=f'k{idx}', from_mix=False)
    co = pose_to_coords(pos)
    for vi, v in enumerate(co): kb.data[vi].co = v
    kb.value = 0
    kb.keyframe_insert('value', frame=max(0, f0 - 1)) if False else None
    keyobjs.append((kb, f0, f1))
sk = paper.data.shape_keys
for kb, f0, f1 in keyobjs:
    dp = f'key_blocks["{kb.name}"].value'
    pts = [(f0 - 1, 0.0), (f0, 1.0), (f1, 1.0), (f1 + 1, 0.0)]
    seen = set()
    for fr, val in pts:
        if fr in seen: continue
        seen.add(fr); kb.value = val; kb.keyframe_insert('value', frame=fr)
paper.active_shape_key_index = 0

# first-pose basis = pose 0; set basis from pose 0 (already). Hide paper when the crane takes over.
op8_first = min([f for f, c in crane_vis if c] or [10**9])
for ob, hidden_before in ((paper, op8_first), ):
    ob.hide_render = False; ob.keyframe_insert('hide_render', frame=1)
    ob.hide_render = True; ob.keyframe_insert('hide_render', frame=op8_first)
crane_all = [crane_root] + [o for o in O if o.parent and o.type == 'MESH' and o.name.split('.')[0] in ('body_L', 'body_R', 'head_a', 'head_b', 'neck_a', 'neck_b', 'tail_a', 'tail_b', 'wing_L', 'wing_R')]
for ob in crane_all:
    ob.hide_render = True; ob.keyframe_insert('hide_render', frame=1)
    ob.hide_render = False; ob.keyframe_insert('hide_render', frame=op8_first)

# the engraved questions fade away once answered (each clip begins just after its question is answered)
for j, s0, e0 in marks:
    prev_end = marks[j-1][2] if j > 0 else None
    for mn in ('paper_front', 'paper_back'):
        nt = MATS[mn].node_tree; node = nt.nodes[f'vis{j}']; dp = f'nodes["vis{j}"].outputs[0].default_value'
        keys = [(1, 1.0), (s0, 1.0), (s0 + 34, 0.0)] if j == 0 else [(1, 0.0), (prev_end - 46, 0.0), (prev_end - 12, 1.0), (s0, 1.0), (s0 + 34, 0.0)]
        for fr, val in keys:
            node.outputs[0].default_value = val; nt.keyframe_insert(data_path=dp, frame=fr)
        node.outputs[0].default_value = 0.0
# linear interpolation for all anim data, constant for visibility
def fix_fcurves(idb, const_paths=('hide_render',)):
    ad = getattr(idb, 'animation_data', None)
    if not ad or not ad.action: return
    act = ad.action
    fcs = []
    try: fcs = list(act.fcurves)
    except Exception:
        for layer in act.layers:
            for strip in layer.strips:
                for cb in strip.channelbags: fcs += list(cb.fcurves)
    for fc in fcs:
        kind = 'CONSTANT' if fc.data_path in const_paths else 'LINEAR'
        for kp in fc.keyframe_points: kp.interpolation = kind
for ob in list(O) + [cam, focus_obj, sk, MATS['paper_front'].node_tree, MATS['paper_back'].node_tree]: fix_fcurves(ob)

# ------------------------------------------------------------------ lights, world, render settings
def add_light(name, kind, loc, target, energy, size, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy; ld.color = color
    if kind == 'AREA': ld.size = size
    if kind == 'SUN': ld.angle = size
    lo = bpy.data.objects.new(name, ld); scene.collection.objects.link(lo); lo.location = loc
    d = Vector(target) - Vector(loc); lo.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return lo
lamp = add_light('key', 'SPOT', (-3.2, -9.0, 7.0), (1.0, .6, .3), 30000, 0, (1.0, .9, .78))
lamp.data.spot_size = math.radians(58); lamp.data.spot_blend = .9; lamp.data.shadow_soft_size = .7
add_light('moon', 'AREA', (6, 27, 16), (2.3, 1.1, 0), 20000, 1.6, (.62, .74, 1.0))
# dust motes drifting through the lamp beam
import random as _r; _rr = _r.Random(11)
dm = bpy.data.meshes.new('mote'); import bmesh as _bm; _b = _bm.new(); _bm.ops.create_icosphere(_b, subdivisions=1, radius=1.0); _b.to_mesh(dm); _b.free()
mm_, nt_ = new_mat('mote'); 
_bsdf = nt_.nodes.get('Principled BSDF')
if _bsdf is None:
    _bsdf = N(nt_, 'ShaderNodeBsdfPrincipled')
    _out = nt_.nodes.get('Material Output') or N(nt_, 'ShaderNodeOutputMaterial'); nt_.links.new(_bsdf.outputs[0], _out.inputs[0])
_bsdf.inputs['Base Color'].default_value = (.95, .9, .8, 1); sock(_bsdf, 'Emission Color', (1, .9, .75, 1)); sock(_bsdf, 'Emission Strength', 0.0)
dm.materials.append(mm_)
for k in range(55):
    t = _rr.random()
    p0 = Vector((_rr.uniform(-5, 5.5), _rr.uniform(-4.5, 4), _rr.uniform(.15, 5.5)))
    ob = bpy.data.objects.new(f'mote{k}', dm); scene.collection.objects.link(ob)
    r_ = _rr.uniform(.003, .007); ob.scale = (r_, r_, r_)
    ob.location = p0; ob.keyframe_insert('location', frame=1)
    ob.location = p0 + Vector((_rr.uniform(-.5, .5), _rr.uniform(-.5, .5), _rr.uniform(-.1, .35))); ob.keyframe_insert('location', frame=1632)
    fix_fcurves(ob)
    ob.visible_shadow = False
w = bpy.data.worlds.new('world'); scene.world = w; w.use_nodes = True
bg = w.node_tree.nodes['Background']; bg.inputs['Color'].default_value = hexc('#2b3a58'); bg.inputs['Strength'].default_value = .42

r = scene.render; r.engine = 'CYCLES'; r.resolution_x, r.resolution_y = RES; r.resolution_percentage = 100; r.fps = FPS
cy = scene.cycles; cy.samples = 40; cy.use_denoising = True; cy.denoiser = 'OPENIMAGEDENOISE'; cy.device = 'GPU'
cy.use_adaptive_sampling = True; cy.adaptive_threshold = .03; cy.volume_bounces = 1; cy.volume_step_rate = 3.0; cy.max_bounces = 4; cy.diffuse_bounces = 2; cy.glossy_bounces = 3; cy.transmission_bounces = 2
cy.sample_clamp_indirect = 8
r.use_motion_blur = False
scene.view_settings.view_transform = 'AgX'; scene.view_settings.exposure = -.7
try:
    r.image_settings.media_type = 'VIDEO'; r.image_settings.file_format = 'FFMPEG'; r.ffmpeg.format = 'MPEG4'; r.ffmpeg.codec = 'H264'; r.ffmpeg.constant_rate_factor = 'HIGH'; r.ffmpeg.ffmpeg_preset = 'GOOD'
    print('OUTPUT: ffmpeg')
except Exception as ex:
    r.image_settings.file_format = 'PNG'; print('OUTPUT: png (this bpy has no ffmpeg)')
r.filepath = '//render2/film_'
r.use_compositing = False
try: scene.use_nodes = False; scene.compositing_node_group = None
except Exception: pass
scene.frame_step = 2; r.fps = 12

for ob in (cam, focus_obj): ob.select_set(False)
scene.frame_set(1072)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
import json as _j; scene['marks'] = _j.dumps(marks)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print('SAVED', OUT)
