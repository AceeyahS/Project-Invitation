"""Night assembly line: empty hall, two rows of 6-axis arms idling on a seamless loop.
Modelling is done with bmesh ops (extrude / inset / bisect loop-cuts) + non-destructive modifiers (Bevel, WeightedNormal, Array),
every part gets a clean UV map. Usage: python3 build_line.py -- out.blend   (env: RESX, RESY, SAMPLES, LOOP)"""
import bpy, bmesh, math, os, sys, random
from mathutils import Vector, Matrix, Euler

OUT = sys.argv[sys.argv.index('--') + 1] if '--' in sys.argv else '/home/claude/film/Line.blend'
RESX, RESY = int(os.environ.get('RESX', 1280)), int(os.environ.get('RESY', 720))
SAMPLES = int(os.environ.get('SAMPLES', 64)); LOOP = int(os.environ.get('LOOP', 480)); FPS = 24
rng = random.Random(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = bpy.data.collections.new('line'); scene.collection.children.link(COL)

# ------------------------------------------------------------------ material helpers
def hexc(h, a=1.0):
    h = h.lstrip('#'); c = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
    c = [((x + .055)/1.055)**2.4 if x > .04045 else x/12.92 for x in c]; return (*c, a)
def sock(n, name, v):
    try: n.inputs[name].default_value = v
    except Exception: pass
def new_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    return m, nt
def N(nt, kind, **kw):
    n = nt.nodes.new(kind)
    for k, v in kw.items(): setattr(n, k, v)
    return n
def noise(nt, scale, detail=6, rough=.55, mapscale=(1, 1, 1)):
    t = N(nt, 'ShaderNodeTexNoise'); t.inputs['Scale'].default_value = scale; t.inputs['Detail'].default_value = detail; t.inputs['Roughness'].default_value = rough
    c = N(nt, 'ShaderNodeTexCoord'); mp = N(nt, 'ShaderNodeMapping'); mp.inputs['Scale'].default_value = mapscale
    nt.links.new(c.outputs['Object'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], t.inputs['Vector']); return t
def ramp(nt, src, stops):
    r = N(nt, 'ShaderNodeValToRGB'); e = r.color_ramp.elements
    while len(e) > 2: e.remove(e[-1])
    for i, (p, c) in enumerate(stops):
        if i < 2: e[i].position = p; e[i].color = c
        else: ne = e.new(p); ne.color = c
    nt.links.new(src, r.inputs['Fac']); return r
def bump(nt, height, strength, dist):
    b = N(nt, 'ShaderNodeBump'); b.inputs['Strength'].default_value = strength; b.inputs['Distance'].default_value = dist
    nt.links.new(height, b.inputs['Height']); return b.outputs['Normal']
def pbsdf(nt, base, rough, metal, **kw):
    p = N(nt, 'ShaderNodeBsdfPrincipled'); sock(p, 'Base Color', base); sock(p, 'Roughness', rough); sock(p, 'Metallic', metal)
    for k, v in kw.items(): sock(p, k.replace('_', ' '), v)
    o = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(p.outputs[0], o.inputs['Surface']); return p

MAT = {}
SUBSURF = {}
def mats():
    m, nt = new_mat('paint'); n = noise(nt, 40, 8, .6); p = pbsdf(nt, hexc('#a8500f'), .3, 0, Coat_Weight=.7, Coat_Roughness=.08)
    rr = ramp(nt, n.outputs['Fac'], [(.3, (.32,)*3 + (1,)), (.75, (.6,)*3 + (1,))]); nt.links.new(rr.outputs['Color'], p.inputs['Roughness'])
    nt.links.new(bump(nt, noise(nt, 300, 5, .6).outputs['Fac'], .05, .004), p.inputs['Normal']); MAT['paint'] = m
    m, nt = new_mat('black'); n = noise(nt, 60, 6, .6); p = pbsdf(nt, hexc('#141416'), .34, .85); nt.links.new(bump(nt, n.outputs['Fac'], .12, .004), p.inputs['Normal']); MAT['black'] = m
    m, nt = new_mat('steel'); n = noise(nt, 18, 4, .5, mapscale=(60, 1, 1)); p = pbsdf(nt, hexc('#a3a9b2'), .3, 1.0); nt.links.new(bump(nt, n.outputs['Fac'], .18, .003), p.inputs['Normal']); MAT['steel'] = m
    m, nt = new_mat('rubber'); p = pbsdf(nt, hexc('#0d0d0e'), .62, 0); MAT['rubber'] = m
    m, nt = new_mat('concrete'); n = noise(nt, 2.5, 6, .55); n2 = noise(nt, 160, 6, .6)
    p = pbsdf(nt, hexc('#23272e'), .2, 0); rr = ramp(nt, n.outputs['Fac'], [(.3, (.10,)*3 + (1,)), (.7, (.38,)*3 + (1,))]); nt.links.new(rr.outputs['Color'], p.inputs['Roughness'])
    nt.links.new(bump(nt, n2.outputs['Fac'], .15, .01), p.inputs['Normal']); MAT['concrete'] = m
    m, nt = new_mat('wall'); n = noise(nt, 3, 5, .5); p = pbsdf(nt, hexc('#1b1f27'), .85, 0); nt.links.new(bump(nt, n.outputs['Fac'], .1, .01), p.inputs['Normal']); MAT['wall'] = m
    m, nt = new_mat('hazard'); c = N(nt, 'ShaderNodeTexCoord'); w = N(nt, 'ShaderNodeTexWave'); w.wave_type = 'BANDS'; w.bands_direction = 'DIAGONAL'; w.inputs['Scale'].default_value = 3.2
    w.inputs['Distortion'].default_value = .3; w.inputs['Detail'].default_value = 2
    nt.links.new(c.outputs['Object'], w.inputs['Vector']); rr = ramp(nt, w.outputs['Fac'], [(.48, hexc('#141414')), (.52, hexc('#e3b800'))])
    rr.color_ramp.interpolation = 'CONSTANT'; p = pbsdf(nt, hexc('#e3b800'), .45, 0); nt.links.new(rr.outputs['Color'], p.inputs['Base Color']); MAT['hazard'] = m
    m, nt = new_mat('yellow'); p = pbsdf(nt, hexc('#e0b400'), .45, 0); MAT['yellow'] = m
    for nm, col, st in (('tube', '#cfe0ff', 14.0), ('beacon', '#ffb347', 40.0), ('green', '#5dff9a', 18.0)):
        m, nt = new_mat(nm); e = N(nt, 'ShaderNodeEmission'); e.inputs['Color'].default_value = hexc(col); e.inputs['Strength'].default_value = st
        o = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(e.outputs[0], o.inputs[0]); MAT[nm] = m
mats()
m, nt = new_mat('moon'); c_ = N(nt, 'ShaderNodeTexCoord'); n_ = noise(nt, 1.2, 4, .6, mapscale=(1, 1, 1)); nt.links.new(c_.outputs['Object'], n_.inputs['Vector'])
rr_ = ramp(nt, n_.outputs['Fac'], [(.3, hexc('#0b1428')), (.7, hexc('#9db8e8'))]); e_ = N(nt, 'ShaderNodeEmission'); e_.inputs['Strength'].default_value = .55
nt.links.new(rr_.outputs['Color'], e_.inputs['Color']); o_ = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(e_.outputs[0], o_.inputs[0]); MAT['moon'] = m

# ------------------------------------------------------------------ modelling helpers (bmesh)
def to_obj(name, bm, mat, bevel=.02, segs=3, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), wn=True, mesh=None):
    if mesh is None:
        mesh = bpy.data.meshes.new(name); bm.to_mesh(mesh); bm.free()
        for p in mesh.polygons: p.use_smooth = True
        mesh.materials.append(MAT[mat])
        # clean UVs: smart-project each island set (the part is built in a UV-friendly way: planar rings + caps)
        ob0 = bpy.data.objects.new(name + '_tmp', mesh); COL.objects.link(ob0)
        bpy.context.view_layer.objects.active = ob0
        for o in bpy.context.view_layer.objects: o.select_set(False)
        ob0.select_set(True); bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.004, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode='OBJECT'); COL.objects.unlink(ob0); bpy.data.objects.remove(ob0)
    ob = bpy.data.objects.new(name, mesh); COL.objects.link(ob)
    if mesh.name in SUBSURF:
        sm = ob.modifiers.new('Sub', 'SUBSURF'); sm.levels = SUBSURF[mesh.name]; sm.render_levels = SUBSURF[mesh.name]; bevel = 0
    if bevel:
        b = ob.modifiers.new('Bevel', 'BEVEL'); b.width = bevel; b.segments = segs; b.limit_method = 'ANGLE'; b.angle_limit = math.radians(32); b.harden_normals = True
    if wn:
        w = ob.modifiers.new('WN', 'WEIGHTED_NORMAL'); w.keep_sharp = True; w.weight = 60
    ob.location = loc; ob.rotation_euler = rot
    if parent is not None: ob.parent = parent
    return ob

def loft(rings, cap_start=True):
    """rings: [(z, sx, sy, dx, dy)] rectangle cross-sections stacked along +Z. Built by extruding the first quad and re-sizing each ring."""
    bm = bmesh.new(); z0, sx, sy, dx, dy = rings[0]
    vs = [bm.verts.new((dx + a*sx/2, dy + b*sy/2, z0)) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    f = bm.faces.new(vs);
    if not cap_start: f.normal_flip()
    top = f
    for z, sx, sy, dx, dy in rings[1:]:
        ret = bmesh.ops.extrude_face_region(bm, geom=[top])
        nv = [e for e in ret['geom'] if isinstance(e, bmesh.types.BMVert)]; nf = [e for e in ret['geom'] if isinstance(e, bmesh.types.BMFace)]
        top = max(nf, key=lambda q: q.calc_center_median().z)
        # explicit corner placement by angle quadrant
        for v in nv:
            cx = sum(w.co.x for w in nv)/4; cy = sum(w.co.y for w in nv)/4
            a = 1 if v.co.x >= cx else -1; b = 1 if v.co.y >= cy else -1
            v.co = Vector((dx + a*sx/2, dy + b*sy/2, z))
    bm.normal_update(); return bm

def loopcut(bm, co, no):
    geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no, dist=1e-5)

def crease_caps(bm, val=1.0):
    cl = bm.edges.layers.float.get('crease_edge') or bm.edges.layers.float.new('crease_edge')
    for f in bm.faces:
        if abs(f.normal.z) > .98:
            for e in f.edges: e[cl] = val

def cyl(r, depth, axis='Z', seg=40, caps=True, bolt_inset=None, r2=None):
    bm = bmesh.new()
    rot = {'Z': Matrix.Identity(4), 'X': Matrix.Rotation(math.radians(90), 4, 'Y'), 'Y': Matrix.Rotation(math.radians(90), 4, 'X')}[axis]
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=seg, radius1=r, radius2=(r if r2 is None else r2), depth=depth, matrix=rot, calc_uvs=True)
    if bolt_inset:                                     # recessed, bolted end plates: inset the cap faces then extrude them back in
        ax = {'Z': Vector((0, 0, 1)), 'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0))}[axis]
        caps_f = [f for f in bm.faces if len(f.verts) == seg and abs(f.normal.dot(ax)) > .9]
        ret = bmesh.ops.inset_region(bm, faces=caps_f, thickness=r*bolt_inset, depth=0)
        ret2 = bmesh.ops.extrude_discrete_faces(bm, faces=caps_f)
        for f in ret2['faces']: bmesh.ops.translate(bm, verts=f.verts, vec=-f.normal*r*.06)
    return bm

def box(sx, sy, sz, off=(0, 0, 0)):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
    for v in bm.verts: v.co = Vector((v.co.x*sx + off[0], v.co.y*sy + off[1], v.co.z*sz + off[2]))
    return bm

def add_array(ob, count, offset, empty=None, constant=True):
    a = ob.modifiers.new('Array', 'ARRAY'); a.count = count; a.use_relative_offset = False; a.use_constant_offset = True; a.constant_offset_displace = offset; return a

def radial_array(ob, count, axis_empty_rot):
    """bolt ring: Array modifier driven by an empty rotated 360/count about the ring axis"""
    e = bpy.data.objects.new(ob.name + '_rot', None); COL.objects.link(e); e.parent = ob.parent; e.location = ob.location
    e.rotation_euler = axis_empty_rot; ob.parent_set = None
    a = ob.modifiers.new('Ring', 'ARRAY'); a.count = count; a.use_relative_offset = False; a.use_object_offset = True; a.offset_object = e
    return e

def empty(name, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), size=.1):
    e = bpy.data.objects.new(name, None); e.empty_display_size = size; COL.objects.link(e)
    e.location = loc; e.rotation_euler = rot
    if parent is not None: e.parent = parent
    return e

# ------------------------------------------------------------------ shared part meshes (instanced across all arms = linked duplicates)
P = {}
def mk(name, bm, mat, **kw):
    ob = to_obj(name, bm, mat, **kw); P[name] = (ob.data, kw); COL.objects.unlink(ob); bpy.data.objects.remove(ob)
def inst(name, mat_dummy, parent, loc=(0, 0, 0), rot=(0, 0, 0), tag=''):
    mesh, kw = P[name]; ob = to_obj(name + tag, None, mat_dummy, parent=parent, loc=loc, rot=rot, mesh=mesh, bevel=kw.get('bevel', .02), segs=kw.get('segs', 3)); return ob

# pedestal: drum + base plate (bolt ring built with a radial Array modifier on the instance)
bm = cyl(.52, .86, 'Z', 48, bolt_inset=.13); [setattr(v, 'co', v.co + Vector((0, 0, .43))) for v in bm.verts]; mk('pedestal', bm, 'steel', bevel=.015)
bm = box(1.5, 1.5, .07, (0, 0, .035)); mk('plate', bm, 'black', bevel=.012)
bm = cyl(.045, .09, 'Z', 12); [setattr(v, 'co', v.co + Vector((.62, 0, .115))) for v in bm.verts]; mk('anchor', bm, 'steel', bevel=.006, segs=2)
# turret: lofted + loop-cut, shoulder cylinder along Y
rings = [(0, 1.0, .9, 0, 0), (.22, .98, .88, 0, 0), (.46, .78, .74, -.06, 0), (.62, .72, .7, -.1, 0)]
bm = loft(rings); loopcut(bm, Vector((0, 0, .11)), Vector((0, 0, 1))); loopcut(bm, Vector((0, 0, .54)), Vector((0, 0, 1)))
top = [f for f in bm.faces if f.normal.z > .9 and f.calc_center_median().z > .6]
if top:
    r_ = bmesh.ops.inset_region(bm, faces=top, thickness=.06, depth=0); bmesh.ops.translate(bm, verts=[v for f in top for v in f.verts], vec=(0, 0, -.015))
crease_caps(bm); SUBSURF['turret'] = 2; mk('turret', bm, 'paint', bevel=0)
bm = cyl(.3, .84, 'Y', 48, bolt_inset=.16); mk('shoulder', bm, 'paint', bevel=.012)
bm = cyl(.312, .05, 'Y', 48); mk('shcap', bm, 'black', bevel=.008)
# lower arm: tapered loft with loop cuts at both joint bosses and a shallow top rib extruded out of the surface
rings = [(0, .6, .52, 0, 0), (.3, .52, .44, 0, 0), (1.0, .36, .3, -.03, 0), (1.5, .34, .3, -.02, 0), (1.72, .4, .38, 0, 0)]
bm = loft(rings); [loopcut(bm, Vector((0, 0, z)), Vector((0, 0, 1))) for z in (.1, .55, 1.6)]
side = [f for f in bm.faces if f.normal.x < -.8 and .35 < f.calc_center_median().z < 1.35]
if side:
    r_ = bmesh.ops.inset_region(bm, faces=side, thickness=.05, depth=.0)
    ex = bmesh.ops.extrude_discrete_faces(bm, faces=side)
    for f in ex['faces']: bmesh.ops.translate(bm, verts=f.verts, vec=f.normal*.022)
crease_caps(bm); SUBSURF['lower'] = 2; mk('lower', bm, 'paint', bevel=0)
bm = cyl(.27, .64, 'Y', 48, bolt_inset=.15); mk('elbow', bm, 'paint', bevel=.012)
bm = cyl(.282, .05, 'Y', 48); mk('elcap', bm, 'black', bevel=.008)
bm = cyl(.024, .03, 'Y', 10); mk('bolt', bm, 'steel', bevel=.004, segs=2)
bm = cyl(.52, .05, 'Z', 48); mk('ringBase', bm, 'black', bevel=.006)
bm = cyl(.285, .07, 'X', 40); mk('ringUp', bm, 'black', bevel=.006)
bm = cyl(.19, .05, 'X', 36); mk('ringW1', bm, 'black', bevel=.005)
bm = cyl(.15, .05, 'X', 32); mk('ringW2', bm, 'black', bevel=.005)
# upper arm (along +X): build as a Z-loft then rotate its verts so the extrusion axis becomes X
rings = [(0, .38, .46, 0, 0), (.25, .36, .42, 0, 0), (1.05, .27, .3, 0, 0), (1.45, .26, .27, 0, 0)]
bm = loft(rings); [loopcut(bm, Vector((0, 0, z)), Vector((0, 0, 1))) for z in (.15, .7, 1.3)]
bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, 'Y'))
crease_caps(bm); SUBSURF['upper'] = 2; mk('upper', bm, 'paint', bevel=0)
bm = cyl(.17, .44, 'X', 40, bolt_inset=.18); mk('motor', bm, 'black', bevel=.01)
bm = cyl(.17, .42, 'X', 40, bolt_inset=.16); mk('wrist1', bm, 'paint', bevel=.01)
bm = cyl(.145, .3, 'Y', 40, bolt_inset=.18); mk('wrist2', bm, 'black', bevel=.01)
bm = cyl(.1, .1, 'X', 32); mk('flange', bm, 'steel', bevel=.008)
bm = box(.2, .22, .12, (.1, 0, 0)); mk('gripbody', bm, 'black', bevel=.01)
bm = box(.16, .03, .05, (.08, 0, 0)); [setattr(v, 'co', v.co + Vector((.2, 0, 0))) for v in bm.verts]; mk('finger', bm, 'steel', bevel=.005, segs=2)
bm = box(.07, .04, .2, (0, 0, -.1)); mk('tip', bm, 'rubber', bevel=.004, segs=2)

bm = box(.34, .5, .17, (0, 0, 0)); mk('servo', bm, 'black', bevel=.012)
bm = cyl(.035, .16, 'X', 16); mk('conn', bm, 'steel', bevel=.004, segs=2)
bm = cyl(.065, .78, 'Y', 24); [setattr(v, 'co', v.co + Vector((0, .39, 0))) for v in bm.verts]; mk('spring', bm, 'black', bevel=.006, segs=2)
bm = cyl(.032, .62, 'Y', 16); [setattr(v, 'co', v.co + Vector((0, .31, 0))) for v in bm.verts]; mk('rod', bm, 'steel', bevel=.003, segs=2)
bm = box(.16, .01, .09); mk('label', bm, 'yellow', bevel=0, wn=False)


# ---- end-of-arm tools (axis +X out of the flange): spot-weld gun, MIG torch, vacuum lifter, sealant gun; claw gripper uses gripbody/finger/tip above
bm = box(.26, .2, .24, (.13, 0, 0)); mk('gun_body', bm, 'black', bevel=.012)
bm = cyl(.085, .34, 'X', 32, bolt_inset=.16); [setattr(v, 'co', v.co + Vector((.05, 0, .17))) for v in bm.verts]; mk('gun_act', bm, 'steel', bevel=.008)
bm = box(.1, .11, .62, (.34, 0, -.2)); mk('gun_c', bm, 'black', bevel=.014)
bm = box(.34, .11, .1, (.18, 0, .12)); mk('gun_arm_top', bm, 'black', bevel=.012)
bm = cyl(.045, .24, 'Z', 20); [setattr(v, 'co', v.co + Vector((0, 0, -.12))) for v in bm.verts]; mk('electrode', bm, 'steel', bevel=.004, segs=2)
bm = cyl(.075, .3, 'X', 28, bolt_inset=.15); [setattr(v, 'co', v.co + Vector((.15, 0, 0))) for v in bm.verts]; mk('torch_body', bm, 'black', bevel=.01)
bm = cyl(.05, .34, 'Z', 20, r2=.03); mk('torch_neck', bm, 'steel', bevel=.006, segs=2)
bm = cyl(.034, .16, 'Z', 20, r2=.02); mk('torch_tip', bm, 'steel', bevel=.004, segs=2)
bm = box(.04, .6, .46, (.02, 0, 0)); mk('vac_plate', bm, 'black', bevel=.01)
bm = cyl(.075, .08, 'X', 24, r2=.045); [setattr(v, 'co', v.co + Vector((.08, 0, 0))) for v in bm.verts]; mk('vac_cup', bm, 'rubber', bevel=.004, segs=2)
bm = cyl(.065, .4, 'X', 28, bolt_inset=.14); [setattr(v, 'co', v.co + Vector((.2, 0, 0))) for v in bm.verts]; mk('seal_cart', bm, 'steel', bevel=.008)
bm = cyl(.05, .26, 'X', 24, r2=.012); [setattr(v, 'co', v.co + Vector((.52, 0, 0))) for v in bm.verts]; mk('seal_nozzle', bm, 'black', bevel=.004, segs=2)
bm = box(.2, .02, .08, (.1, 0, 0)); [setattr(v, 'co', v.co + Vector((.05, 0, 0))) for v in bm.verts]; mk('claw_tip', bm, 'steel', bevel=.004, segs=2)

# ------------------------------------------------------------------ one arm (joint empties are the rig; meshes ride on them)
JOINTS = {}; HOSES = []
def build_arm(i, loc, yaw, tag):
    root = empty(f'arm{tag}', loc=loc, rot=(0, 0, yaw), size=.3)
    inst('plate', None, root, tag=tag) if False else None
    pl = to_obj(f'plate{tag}', None, 'black', parent=root, mesh=P['plate'][0], bevel=.012)
    for k in range(4):
        a = to_obj(f'anchor{tag}_{k}', None, 'steel', parent=root, rot=(0, 0, math.radians(90*k)), mesh=P['anchor'][0], bevel=.006, segs=2)
    ped = to_obj(f'pedestal{tag}', None, 'steel', parent=root, mesh=P['pedestal'][0], bevel=.015)
    j1 = empty(f'J1{tag}', root, (0, 0, .86)); tu = to_obj(f'turret{tag}', None, 'paint', parent=j1, mesh=P['turret'][0], bevel=.035, segs=4)
    j2 = empty(f'J2{tag}', j1, (0, 0, .62))
    sh = to_obj(f'shoulder{tag}', None, 'paint', parent=j2, mesh=P['shoulder'][0], bevel=.012)
    for s in (-1, 1): to_obj(f'shcap{tag}{s}', None, 'black', parent=j2, loc=(0, s*.435, 0), mesh=P['shcap'][0], bevel=.008)
    lo = to_obj(f'lower{tag}', None, 'paint', parent=j2, loc=(.0, 0, .0), mesh=P['lower'][0], bevel=.03, segs=4)
    j3 = empty(f'J3{tag}', j2, (0, 0, 1.72))
    to_obj(f'elbow{tag}', None, 'paint', parent=j3, mesh=P['elbow'][0], bevel=.012)
    for s in (-1, 1): to_obj(f'elcap{tag}{s}', None, 'black', parent=j3, loc=(0, s*.345, 0), mesh=P['elcap'][0], bevel=.008)
    for s in (-1, 1):
        for q in range(10):
            a_ = q*math.pi/5
            to_obj(f'bs{tag}{s}{q}', None, 'steel', parent=j2, loc=(.2*math.cos(a_), s*.46, .2*math.sin(a_)), mesh=P['bolt'][0], bevel=.004, segs=2)
            to_obj(f'be{tag}{s}{q}', None, 'steel', parent=j3, loc=(.17*math.cos(a_), s*.37, .17*math.sin(a_)), mesh=P['bolt'][0], bevel=.004, segs=2)
    up = to_obj(f'upper{tag}', None, 'paint', parent=j3, loc=(.1, 0, 0), mesh=P['upper'][0], bevel=.025, segs=4)
    to_obj(f'rBase{tag}', None, 'black', parent=j1, loc=(0, 0, .0), mesh=P['ringBase'][0], bevel=.006)
    to_obj(f'rUp{tag}', None, 'black', parent=j3, loc=(.14, 0, 0), mesh=P['ringUp'][0], bevel=.006)
    to_obj(f'motor{tag}', None, 'black', parent=j3, loc=(-.42, 0, 0), mesh=P['motor'][0], bevel=.01)
    j4 = empty(f'J4{tag}', j3, (1.55, 0, 0))
    to_obj(f'wrist1{tag}', None, 'steel', parent=j4, loc=(.18, 0, 0), mesh=P['wrist1'][0], bevel=.01)
    to_obj(f'rW1{tag}', None, 'black', parent=j4, loc=(.0, 0, 0), mesh=P['ringW1'][0], bevel=.005)
    j5 = empty(f'J5{tag}', j4, (.42, 0, 0))
    to_obj(f'wrist2{tag}', None, 'black', parent=j5, mesh=P['wrist2'][0], bevel=.01)
    to_obj(f'rW2{tag}', None, 'black', parent=j5, loc=(.12, 0, 0), mesh=P['ringW2'][0], bevel=.005)
    j6 = empty(f'J6{tag}', j5, (.16, 0, 0))
    to_obj(f'flange{tag}', None, 'steel', parent=j6, loc=(.05, 0, 0), mesh=P['flange'][0], bevel=.008)
    tool = (0, 1, 0, 2, 0, 3, 0, 4)[i % 8]; fingers = []; fax = (1, .045, .035)          # (axis, open base, amplitude) of the moving tool parts
    if tool == 0:                                              # two-finger claw with hooked tips
        to_obj(f'gripbody{tag}', None, 'black', parent=j6, loc=(.1, 0, 0), mesh=P['gripbody'][0], bevel=.01)
        for s_ in (-1, 1):
            fe = empty(f'fing{tag}{s_}', j6, (.2, s_*.07, 0))
            to_obj(f'finger{tag}{s_}', None, 'steel', parent=fe, mesh=P['finger'][0], bevel=.005, segs=2)
            to_obj(f'tip{tag}{s_}', None, 'rubber', parent=fe, loc=(.18, 0, -.03), mesh=P['tip'][0], bevel=.004, segs=2)
            to_obj(f'ctip{tag}{s_}', None, 'steel', parent=fe, loc=(.2, -s_*.03, .0), rot=(0, 0, math.radians(-s_*28)), mesh=P['claw_tip'][0], bevel=.004, segs=2); fingers.append(fe)
    elif tool == 1:                                            # C-type spot-weld gun: actuator, C-frame, two electrodes closing on each other
        to_obj(f'gunb{tag}', None, 'black', parent=j6, loc=(.08, 0, 0), mesh=P['gun_body'][0], bevel=.012)
        to_obj(f'guna{tag}', None, 'steel', parent=j6, loc=(.14, 0, 0), mesh=P['gun_act'][0], bevel=.008)
        to_obj(f'gunc{tag}', None, 'black', parent=j6, loc=(.08, 0, 0), mesh=P['gun_c'][0], bevel=.014)
        to_obj(f'guntop{tag}', None, 'black', parent=j6, loc=(.08, 0, 0), mesh=P['gun_arm_top'][0], bevel=.012)
        for s_ in (-1, 1):
            fe = empty(f'fing{tag}{s_}', j6, (.5, 0, s_*.2 + (-.22 if s_ < 0 else .0)))
            to_obj(f'electrode{tag}{s_}', None, 'steel', parent=fe, rot=(math.radians(180 if s_ > 0 else 0), 0, 0), mesh=P['electrode'][0], bevel=.004, segs=2); fingers.append(fe)
        fax = (2, .0, .03)
    elif tool == 2:                                            # MIG welding torch on a gooseneck
        to_obj(f'tbody{tag}', None, 'black', parent=j6, loc=(.05, 0, 0), mesh=P['torch_body'][0], bevel=.01)
        ne = empty(f'tneck{tag}', j6, (.36, 0, 0), rot=(0, math.radians(35), 0))
        to_obj(f'tneckm{tag}', None, 'steel', parent=ne, loc=(0, 0, -.17), mesh=P['torch_neck'][0], bevel=.006, segs=2)
        to_obj(f'ttip{tag}', None, 'steel', parent=ne, loc=(0, 0, -.42), mesh=P['torch_tip'][0], bevel=.004, segs=2)
        fax = (1, .0, .0)
    elif tool == 3:                                            # vacuum lifter plate with four suction cups
        to_obj(f'vplate{tag}', None, 'black', parent=j6, loc=(.14, 0, 0), mesh=P['vac_plate'][0], bevel=.01)
        for yy in (-.2, .2):
            for zz in (-.14, .14):
                to_obj(f'vcup{tag}{yy}{zz}', None, 'rubber', parent=j6, loc=(.16, yy, zz), mesh=P['vac_cup'][0], bevel=.004, segs=2)
        fax = (1, .0, .0)
    else:                                                      # sealant cartridge gun with a fine nozzle
        to_obj(f'scart{tag}', None, 'steel', parent=j6, loc=(.02, 0, 0), mesh=P['seal_cart'][0], bevel=.008)
        to_obj(f'snoz{tag}', None, 'black', parent=j6, loc=(.02, 0, 0), mesh=P['seal_nozzle'][0], bevel=.004, segs=2)
        fax = (1, .0, .0)
    # black servo/controller boxes on the shoulder with connector barrels, as on the cast KUKA-type arms
    for k, z in enumerate((.12, .3, .48)):
        to_obj(f'servo{tag}_{k}', None, 'black', parent=j1, loc=(-.66, .0, z), mesh=P['servo'][0], bevel=.012)
        for sy in (-.1, .1): to_obj(f'conn{tag}_{k}{sy}', None, 'steel', parent=j1, loc=(-.86, sy, z), mesh=P['conn'][0], bevel=.004, segs=2)
    # gas-spring counterbalance: tube on the turret, rod on the lower arm, each tracking the other's anchor
    aT = empty(f'aT{tag}', j1, (-.42, 0, .2), size=.05); aR = empty(f'aR{tag}', j2, (-.3, 0, .72), size=.05)
    tb = to_obj(f'spring{tag}', None, 'black', parent=aT, mesh=P['spring'][0], bevel=.008); rd = to_obj(f'rod{tag}', None, 'steel', parent=aR, mesh=P['rod'][0], bevel=.004, segs=2)
    for ob_, tg in ((tb, aR), (rd, aT)):
        c = ob_.constraints.new('DAMPED_TRACK'); c.target = tg; c.track_axis = 'TRACK_Y'
    # hazard label + status plate on the turret
    to_obj(f'label{tag}', None, 'yellow', parent=j1, loc=(.0, -.4, .3), rot=(math.radians(90), 0, 0), mesh=P['label'][0], bevel=0, wn=False)
    HOSES.append(dict(tag=tag, hooks=[(j1, (-.55, .26, .4)), (j2, (-.6, .3, .8)), (j2, (-.5, .34, 1.6)), (j3, (.35, .34, .34)), (j3, (1.2, .3, .3)), (j5, (.05, .22, .12))]))
    JOINTS[tag] = dict(j1=j1, j2=j2, j3=j3, j4=j4, j5=j5, j6=j6, fingers=fingers, fax=fax)
    return root

ROWS = (-3.5, 3.5); XS = [-8 + 5*k for k in range(7)]
n = 0
for yi, y in enumerate(ROWS):
    for xi, x in enumerate(XS):
        build_arm(n, (x + (1.2 if yi else 0), y, 0), math.radians(90 if y < 0 else -90), f'_{n}'); n += 1

# ------------------------------------------------------------------ the hall
def static(name, bm, mat, loc=(0, 0, 0), bevel=.02, segs=2, rot=(0, 0, 0)):
    return to_obj(name, bm, mat, loc=loc, bevel=bevel, segs=segs, rot=rot)
HX0, HX1, HW, HZ = -24, 36, 8, 8.5
fl = static('floor', box(HX1 - HX0, HW*2, .1, ((HX0 + HX1)/2, 0, -.05)), 'concrete', bevel=0, wn=False) if False else None
bm = box(HX1 - HX0, HW*2, .1, ((HX0 + HX1)/2, 0, -.05)); fl = to_obj('floor', bm, 'concrete', bevel=0, wn=False)
for s, nm in ((-1, 'wallA'), (1, 'wallB')):
    to_obj(nm, box(HX1 - HX0, .3, HZ, ((HX0 + HX1)/2, s*HW, HZ/2)), 'wall', bevel=0, wn=False)
to_obj('wallEnd', box(.3, HW*2, HZ, (HX1, 0, HZ/2)), 'wall', bevel=0, wn=False)
to_obj('wallStart', box(.3, HW*2, HZ, (HX0, 0, HZ/2)), 'wall', bevel=0, wn=False)
to_obj('ceiling', box(HX1 - HX0, HW*2, .3, ((HX0 + HX1)/2, 0, HZ)), 'wall', bevel=0, wn=False)
# centre bed: rails + sleepers (Array), hazard lane borders
for s in (-1, 1):
    r = to_obj(f'rail{s}', box(48, .14, .16, (6, s*.75, .13)), 'steel', bevel=.012)
    h = to_obj(f'lane{s}', box(48, .5, .012, (6, s*1.5, .006)), 'hazard', bevel=0, wn=False)
sl = to_obj('sleeper', box(.22, 2.0, .09, (0, 0, .045)), 'black', bevel=.01); sl.location = (-18, 0, 0); add_array(sl, 62, (.85, 0, 0))
for k, s in enumerate((-1, 1)):
    # arm lane markings in front of each pedestal row
    to_obj(f'edge{s}', box(48, .12, .012, (6, s*2.55, .006)), 'yellow', bevel=0, wn=False)
# columns + roof trusses + tube lights
col = box(.35, .6, HZ, (0, 0, HZ/2)); colmesh = bpy.data.meshes.new('colmesh'); col.to_mesh(colmesh); col.free(); colmesh.materials.append(MAT['steel'])
for s in (-1, 1):
    for k in range(7):
        o = bpy.data.objects.new(f'col{s}_{k}', colmesh); COL.objects.link(o); o.location = (-20 + 9*k, s*(HW - .8), 0)
        b = o.modifiers.new('Bevel', 'BEVEL'); b.width = .02; b.segments = 2; b.limit_method = 'ANGLE'
for k in range(14):
    bm = box(.3, HW*2 - 1, .4, (0, 0, 0)); o = to_obj(f'truss{k}', bm, 'black', loc=(-22 + 4.4*k, 0, HZ - .6), bevel=.015)
    tube = box(.18, 6.2, .06, (0, 0, 0)); to_obj(f'tubeL{k}', tube, 'tube', loc=(-22 + 4.4*k, -3.2, HZ - 1.85), bevel=0, wn=False)
    to_obj(f'tubeR{k}', box(.18, 6.2, .06, (0, 0, 0)), 'tube', loc=(-22 + 4.4*k, 3.2, HZ - 1.85), bevel=0, wn=False)

# ---- hall dressing to match the reference: tall moonlit windows, riveted wall ribs, cable trays + pipe runs, control cabinets, guard rails, truss lattice, crane beams with hook, hanging lamps
CX = (HX0 + HX1)/2; LEN = HX1 - HX0 - .6
def arr(o, n, off): add_array(o, n, off); return o
for s in (-1, 1):
    yw = s*(HW - .2)
    to_obj(f'glass{s}', box(LEN, .04, 4.8, (CX, yw, 4.9)), 'moon', loc=(0, 0, 0), bevel=0, wn=False)
    ym = s*(HW - .28)
    m_ = to_obj(f'mull{s}', box(.1, .1, 4.9, (0, 0, 0)), 'black', loc=(HX0 + .6, ym, 4.9), bevel=.01); arr(m_, int(LEN/1.1), (1.1, 0, 0))
    for k in range(5): to_obj(f'tran{s}_{k}', box(LEN, .14, .12, (CX, ym, 2.5 + 1.2*k)), 'black', bevel=.01)
    for k in range(2): to_obj(f'rib{s}_{k}', box(.14, .12, 2.5, (0, 0, 0)), 'steel', loc=(HX0 + .9 + .5*k, s*(HW - .25), 1.25), bevel=.01); 
    rb = to_obj(f'wribs{s}', box(.16, .12, 2.5, (0, 0, 0)), 'steel', loc=(HX0 + .9, s*(HW - .25), 1.25), bevel=.01); arr(rb, int(LEN/1.5), (1.5, 0, 0))
    to_obj(f'wbar{s}', box(LEN, .1, .14, (CX, s*(HW - .24), 1.05)), 'steel', bevel=.01)
    # cable tray with bundled cable, two pipe runs, brackets
    to_obj(f'tray{s}', box(LEN, .6, .08, (CX, s*(HW - .6), 2.55)), 'steel', bevel=.01)
    to_obj(f'trayc{s}', box(LEN, .42, .12, (CX, s*(HW - .6), 2.65)), 'rubber', bevel=.02)
    to_obj(f'pipeA{s}', cyl(.11, LEN, 'X', 24), 'steel', loc=(CX, s*(HW - .55), 2.1), bevel=0)
    to_obj(f'pipeB{s}', cyl(.07, LEN, 'X', 20), 'black', loc=(CX, s*(HW - .55), 1.8), bevel=0)
    br = to_obj(f'brk{s}', box(.08, .4, 1.1, (0, 0, 0)), 'black', loc=(HX0 + 1.5, s*(HW - .5), 2.0), bevel=.01); arr(br, int(LEN/3.0), (3.0, 0, 0))
    # control cabinets with indicator lights
    cb = to_obj(f'cab{s}', box(1.1, .6, 2.1, (0, 0, 0)), 'black', loc=(-19, s*(HW - 1.45), 1.05), bevel=.02); arr(cb, 9, (6.5, 0, 0))
    for k in range(3):
        li = to_obj(f'cabl{s}_{k}', box(.07, .02, .07, (0, 0, 0)), 'tube' if k != 1 else 'green', loc=(-19.35 + .35*k, s*(HW - 1.45) - s*.31, 1.75), bevel=0, wn=False); arr(li, 9, (6.5, 0, 0))
    # yellow guard rails in front of every pedestal
    for yi, yy in enumerate((-2.75, 2.75)):
        if (yy < 0) != (s < 0): continue
        for post in (-1.3, 1.3):
            pp = to_obj(f'post{s}{post}', cyl(.04, 1.0, 'Z', 14), 'yellow', loc=(-8 + post + (1.2 if yi else 0), yy, .5), bevel=0); arr(pp, 7, (5, 0, 0))
        for zb in (.55, .95):
            gb = to_obj(f'gbar{s}{zb}', box(2.6, .05, .05, (0, 0, 0)), 'yellow', loc=(-8 + (1.2 if yi else 0), yy, zb), bevel=.005); arr(gb, 7, (5, 0, 0))
# end-wall windows
to_obj('glassEnd', box(.04, 2*HW - 1.5, 4.6, (HX1 - .2, 0, 4.2)), 'moon', bevel=0, wn=False)
ev = to_obj('mullEnd', box(.1, .1, 4.7, (0, 0, 0)), 'black', loc=(HX1 - .26, -(HW - .75), 4.2), bevel=.01); arr(ev, 14, ((2*HW - 1.5)/13, 0, 0)) if False else None
ev.modifiers.new('Array', 'ARRAY'); ev.modifiers['Array'].count = 14; ev.modifiers['Array'].use_relative_offset = False; ev.modifiers['Array'].use_constant_offset = True; ev.modifiers['Array'].constant_offset_displace = (0, (2*HW - 1.5)/13, 0)
for k in range(5): to_obj(f'tranE{k}', box(.1, 2*HW - 1.5, .12, (HX1 - .26, 0, 1.9 + 1.2*k)), 'black', bevel=.01)
to_obj('doorEnd', box(.12, 5, 2.8, (HX1 - .22, 0, 1.4)), 'black', bevel=.02)
# roof: purlins, lattice trusses (bottom chord, verticals, X braces), crane runway + two crane beams + hook block, hanging lamps
for yy in (-7, -5, -3, -1, 1, 3, 5, 7): to_obj(f'purlin{yy}', box(LEN, .12, .14, (CX, yy, HZ - .42)), 'black', bevel=.01)
TW = 2*HW - 1
for k in range(14):
    x = -22 + 4.4*k
    to_obj(f'bchord{k}', box(.2, TW, .2, (0, 0, 0)), 'black', loc=(x, 0, HZ - 1.7), bevel=.015)
    v = to_obj(f'tvert{k}', box(.1, .1, 1.1, (0, 0, 0)), 'black', loc=(x, -TW/2 + .7, HZ - 1.15), bevel=.01); arr(v, 11, (0, 1.4, 0))
    for sg in (1, -1):
        bd = box(.1, 1.78, .1, (0, 0, 0)); an = sg*math.radians(38)
        for v_ in bd.verts: v_.co = Vector((v_.co.x, v_.co.y*math.cos(an) - v_.co.z*math.sin(an), v_.co.y*math.sin(an) + v_.co.z*math.cos(an)))
        d = to_obj(f'tdiag{k}_{sg}', bd, 'black', loc=(x, -TW/2 + .7, HZ - 1.15), bevel=.01); arr(d, 10, (0, 1.4, 0))
for s in (-1, 1): to_obj(f'runway{s}', box(LEN, .4, .5, (CX, s*(HW - .6), HZ - 1.3)), 'steel', bevel=.015)
for k, xc in enumerate((-4, 20)):
    to_obj(f'crane{k}', box(.55, 2*HW - 1.2, .7, (0, 0, 0)), 'black', loc=(xc, 0, HZ - 1.45), bevel=.02)
    to_obj(f'craneH{k}', box(.57, 2*HW - 1.2, .06, (0, 0, 0)), 'hazard', loc=(xc, 0, HZ - 1.82), bevel=0, wn=False)
    for s in (-1, 1): to_obj(f'carr{k}{s}', box(.9, .5, .6, (0, 0, 0)), 'steel', loc=(xc, s*(HW - .6), HZ - 1.3), bevel=.02)
to_obj('hookBlock', box(.42, .5, .7, (0, 0, 0)), 'hazard', loc=(-4, 0, HZ - 4.2), bevel=.03)
to_obj('hookRope', cyl(.02, 2.4, 'Z', 8), 'black', loc=(-4, 0, HZ - 2.6), bevel=0)
to_obj('hookTop', box(.5, .6, .25, (0, 0, 0)), 'steel', loc=(-4, 0, HZ - 2.0), bevel=.02)
to_obj('hookCone', cyl(.12, .35, 'Z', 16, r2=.04), 'steel', loc=(-4, 0, HZ - 4.75), bevel=.005)
for k in range(9):
    for s in (-1, 1):
        x = -19 + 6.5*k; y = s*4.6
        to_obj(f'lampP{k}{s}', cyl(.02, 1.0, 'Z', 8), 'black', loc=(x, y, HZ - 2.0 - .0), bevel=0)
        to_obj(f'lampS{k}{s}', cyl(.5, .3, 'Z', 28, r2=.12), 'black', loc=(x, y, HZ - 2.55), bevel=.01)
        to_obj(f'lampG{k}{s}', cyl(.38, .03, 'Z', 24), 'tube', loc=(x, y, HZ - 2.71), bevel=0, wn=False)
# status beacons on a few pedestals
for k, x in enumerate((-8, 7, 22, 12)):
    to_obj(f'beacon{k}', cyl(.07, .14, 'Z', 16), 'beacon' if k % 2 else 'green', loc=(x + (1.2 if k % 2 else 0), -4.0 if k % 2 == 0 else 5.0, 1.5), bevel=0, wn=False)

# ------------------------------------------------------------------ lights (low, cool, pooled) + hall haze
def light(name, kind, loc, target, energy, size, color=(.75, .85, 1), spot=None):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy; ld.color = color
    if kind == 'AREA': ld.shape = 'RECTANGLE'; ld.size = size[0]; ld.size_y = size[1]
    if kind == 'SPOT': ld.spot_size = math.radians(spot or 50); ld.spot_blend = .8; ld.shadow_soft_size = .2
    o = bpy.data.objects.new(name, ld); COL.objects.link(o); o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler(); return o
for k in range(14):
    x = -22 + 4.4*k
    for s in (-1, 1): light(f'tl{k}_{s}', 'AREA', (x, s*3.2, HZ - 1.95), (x, s*3.2, 0), 260, (.2, 6.0), (.7, .82, 1))
for k, x in enumerate(XS):
    light(f'pool{k}', 'SPOT', (x + 1, 0, 6.5), (x + 1, 0, 0), 7000, None, (.8, .88, 1), spot=34)
light('far_glow', 'AREA', (HX1 - 1, 0, 3.8), (HX0, 0, 3.8), 1800, (7.0, 3.2), (.55, .72, 1))
w = bpy.data.worlds.new('w'); scene.world = w; w.use_nodes = True; w.node_tree.nodes['Background'].inputs['Color'].default_value = hexc('#0a1020'); w.node_tree.nodes['Background'].inputs['Strength'].default_value = .03
# haze volume: one large scatter cube (cheap at low step rate), lets the lights bloom into beams
bpy.ops.mesh.primitive_cube_add(size=1, location=((HX0 + HX1)/2, 0, HZ/2)); hz = bpy.context.active_object; hz.name = 'haze'; hz.scale = (HX1 - HX0 - .5, HW*2 - .5, HZ - .2); hz.display_type = 'WIRE'
hm, nt = new_mat('haze'); vs = N(nt, 'ShaderNodeVolumeScatter'); vs.inputs['Density'].default_value = .005; vs.inputs['Anisotropy'].default_value = .35; vs.inputs['Color'].default_value = (.7, .8, 1, 1)
o = N(nt, 'ShaderNodeOutputMaterial'); nt.links.new(vs.outputs[0], o.inputs['Volume']); hz.data.materials.append(hm); hz.visible_shadow = False

# ------------------------------------------------------------------ idle choreography: seamless LOOP, plateau-and-sweep motion, each arm on its own clock
def plateau(x, k=2.3): return math.tanh(k*math.sin(x))/math.tanh(k)      # dwells near both extremes, then sweeps
KEY_EVERY = 4
for n_, (tag, J) in enumerate(JOINTS.items()):
    ph = rng.uniform(0, 2*math.pi); w1 = rng.choice((1, 1, 2)); w2 = rng.choice((1, 2, 3)); w3 = rng.choice((1, 2))
    amp = dict(j1=rng.uniform(14, 26), j2=rng.uniform(7, 14), j3=rng.uniform(10, 20), j4=rng.uniform(30, 70), j5=rng.uniform(18, 32), j6=rng.uniform(60, 120))
    base = dict(j1=(8 if n_ < 7 else -8), j2=-30, j3=72, j4=0, j5=-38, j6=0)          # ready stance: upper arm out over the line, tool angled down
    ax = dict(j1=2, j2=1, j3=1, j4=0, j5=1, j6=0)                 # rotation axis index
    fr = dict(j1=w1, j2=w3, j3=w2, j4=w2, j5=w1, j6=w3)
    for key, jo in J.items():
        if key in ('fingers', 'fax'): continue
        jo.rotation_mode = 'XYZ'
    for f in range(1, LOOP + 2, KEY_EVERY):
        th = 2*math.pi*(f - 1)/LOOP
        for key in ('j1', 'j2', 'j3', 'j4', 'j5', 'j6'):
            jo = J[key]; ang = base[key] + amp[key]*plateau(fr[key]*th + ph + {'j1': 0, 'j2': 1.1, 'j3': 2.3, 'j4': .7, 'j5': 3.1, 'j6': 1.8}[key] + n_*.37)
            e = list(jo.rotation_euler); e[ax[key]] = math.radians(ang); jo.rotation_euler = e
            jo.keyframe_insert('rotation_euler', index=ax[key], frame=f)
        g = .5 + .5*plateau(th*2 + ph*1.3)
        axi, b0, am = J['fax']
        for fe, s in zip(J['fingers'], (-1, 1)):
            loc_ = list(fe.location)
            if axi == 2: loc_[2] = (-.2 if s < 0 else 0.0) + s*(.2 - am*g) * (1 if s > 0 else 0) + (-s*am*g if s < 0 else 0)
            else: loc_[axi] = s*(b0 + am*g)
            fe.location = loc_; fe.keyframe_insert('location', index=axi, frame=f)

def smooth_all():
    for act in bpy.data.actions:
        for layer in getattr(act, 'layers', []):
            for strip in layer.strips:
                for slot in act.slots:
                    cb = strip.channelbag(slot)
                    if cb:
                        for fc in cb.fcurves:
                            for kp in fc.keyframe_points: kp.interpolation = 'BEZIER'; kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'
smooth_all()


# ------------------------------------------------------------------ dress-pack hoses: NURBS conduit, each control point hooked to an empty riding a different link (stretches/bows as the arm moves)
hm_, nt_ = new_mat('hose'); c_ = N(nt_, 'ShaderNodeTexCoord'); wv = N(nt_, 'ShaderNodeTexWave'); wv.wave_type = 'BANDS'; wv.bands_direction = 'X'; wv.inputs['Scale'].default_value = 70; wv.inputs['Distortion'].default_value = 0
nt_.links.new(c_.outputs['UV'], wv.inputs['Vector']); hp = pbsdf(nt_, hexc('#101113'), .5, 0); nt_.links.new(bump(nt_, wv.outputs['Fac'], .9, .01), hp.inputs['Normal']); MAT['hose'] = hm_
scene.frame_set(1); bpy.context.view_layer.update()
for hs in HOSES:
    tag = hs['tag']; hooks = []
    for k, (par, off) in enumerate(hs['hooks']):
        he = empty(f'hk{tag}_{k}', par, off, size=.04); hooks.append(he)
    bpy.context.view_layer.update()
    cu = bpy.data.curves.new(f'hose{tag}', 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = .06; cu.bevel_resolution = 4; cu.use_fill_caps = True
    sp = cu.splines.new('NURBS'); sp.points.add(len(hooks) - 1); sp.order_u = 4; sp.use_endpoint_u = True
    for p, he in zip(sp.points, hooks): w_ = he.matrix_world.translation; p.co = (w_.x, w_.y, w_.z, 1.0)
    ob = bpy.data.objects.new(f'hose{tag}', cu); COL.objects.link(ob); cu.materials.append(MAT['hose'])
    for k, he in enumerate(hooks):
        m = ob.modifiers.new(f'Hook{k}', 'HOOK'); m.object = he; m.vertex_indices_set([k]); m.matrix_inverse = he.matrix_world.inverted()

# ------------------------------------------------------------------ camera: low, one-point perspective down the line, looping sway, shallow DOF; subject sits left of centre (room for the form card on the right)
cam_d = bpy.data.cameras.new('cam'); cam_d.lens = 24; cam_d.sensor_width = 36; cam_d.shift_x = 0
cam_d.dof.use_dof = True; cam_d.dof.aperture_fstop = 3.6
cam = bpy.data.objects.new('cam', cam_d); COL.objects.link(cam); scene.camera = cam
tgt = bpy.data.objects.new('tgt', None); COL.objects.link(tgt); foc = bpy.data.objects.new('foc', None); COL.objects.link(foc); foc.location = (-3.5, 0, 1.6); cam_d.dof.focus_object = foc
tr = cam.constraints.new('TRACK_TO'); tr.target = tgt; tr.track_axis = 'TRACK_NEGATIVE_Z'; tr.up_axis = 'UP_Y'
for f in range(1, LOOP + 2, KEY_EVERY):
    th = 2*math.pi*(f - 1)/LOOP
    cam.location = (-12.8 + .5*math.sin(th), .2*math.sin(th + 1.0), 1.3 + .12*math.sin(2*th + .4)); cam.keyframe_insert('location', frame=f)
    tgt.location = (10.0, .15*math.sin(th + .5), 2.3 + .1*math.sin(th)); tgt.keyframe_insert('location', frame=f)
smooth_all()

# ------------------------------------------------------------------ render settings (neutral render; the cyanotype grade is applied in post so it can be tuned without re-rendering)
scene.frame_start, scene.frame_end = 1, LOOP
r = scene.render; r.engine = 'CYCLES'; r.resolution_x, r.resolution_y = RESX, RESY; r.fps = FPS
cy = scene.cycles; cy.samples = SAMPLES; cy.use_denoising = True; cy.denoiser = 'OPENIMAGEDENOISE'; cy.use_adaptive_sampling = True; cy.adaptive_threshold = .03
cy.max_bounces = 6; cy.diffuse_bounces = 2; cy.glossy_bounces = 4; cy.volume_bounces = 1; cy.volume_step_rate = 4.0; cy.sample_clamp_indirect = 6; cy.device = 'GPU'
scene.view_settings.view_transform = 'AgX'; scene.view_settings.exposure = float(os.environ.get('EXPO', -0.4))
r.image_settings.file_format = 'PNG'; r.image_settings.color_depth = '16'; r.filepath = '//line_frames/f_'
r.use_motion_blur = False; scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=OUT); print('SAVED', OUT, 'objects', len(bpy.data.objects))
