import {
  WebGLRenderer, Scene, PerspectiveCamera, Vector2, Vector3, Quaternion, Matrix4, Color, Fog,
  BufferGeometry, BufferAttribute, Mesh, MeshStandardMaterial, PlaneGeometry, Plane, Raycaster,
  CanvasTexture, SRGBColorSpace, DirectionalLight, HemisphereLight, PCFShadowMap, Group, RepeatWrapping
} from 'three';

/* =====================================================================
   One sheet of paper. Swipe a creased strip and it rolls itself into a
   tapered paper cone. Each finished fold asks one question; answer it and
   the cone lifts off the sheet and joins the arm.
   ===================================================================== */

const W = 4.0, H = 2.8, PX = 520, ZB = 1.15;
const CFG = (typeof CONFIG !== 'undefined') ? CONFIG : { host: 'X' };
const $ = id => document.getElementById(id);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const easeOut = t => 1 - Math.pow(1 - t, 3);
const lerp = (a, b, t) => a + (b - a) * t;

/* ---------- the six strips: n panels, wide side sb, narrow side st, slant length l ---------- */
const STRIPS = [
  { k: 'base', n: 8, sb: .184, st: .0804, l: .34, label: 'BASE' },
  { k: 'up',   n: 6, sb: .115, st: .082,  l: .62, label: 'UPPER ARM' },
  { k: 'fore', n: 6, sb: .095, st: .065,  l: .54, label: 'FOREARM' },
  { k: 'wr',   n: 6, sb: .075, st: .055,  l: .22, label: 'WRIST' },
  { k: 'fa',   n: 3, sb: .069, st: .0139, l: .28, label: 'CLAW' },
  { k: 'fb',   n: 3, sb: .069, st: .0139, l: .28, label: '' }
];
{ // flat net geometry (a fan of trapezoids around the cone's apex) and layout on the sheet
  let cursor = -W / 2 + .12;
  for (const d of STRIPS) {
    d.r1 = d.l * d.sb / (d.sb - d.st); d.r0 = d.r1 - d.l;
    d.gamma = 2 * Math.asin(d.sb / (2 * d.r1));
    const Rb = d.sb / (2 * Math.sin(Math.PI / d.n)), beta = Math.asin(Rb / d.r1);
    const cosg = Math.cos(beta) ** 2 + Math.sin(beta) ** 2 * Math.cos(4 * Math.PI / d.n);
    d.psi = Math.PI - Math.acos((cosg - Math.cos(d.gamma) ** 2) / Math.sin(d.gamma) ** 2);   // exact dihedral for a regular frustum
    const half = Math.min(d.n * d.gamma / 2, Math.PI / 2), hw = d.r1 * Math.sin(half);
    d.cx = cursor + hw; cursor += 2 * hw + .07;
    d.zA = ZB - d.r1;                                  // apex of the fan (above the strip)
  }
}
const STEPS = [
  { k: 'age',      q: 'First, how old are you?', type: 'number', hint: 'A small thing before anything else.' },
  { k: 'name',     q: 'What name shall we write in the front of the book?', type: 'text', auto: 'name', max: 120 },
  { k: 'email',    q: 'Where can the invitation find you?', type: 'email', auto: 'email', hint: 'For your confirmation and the calendar invite.', max: 200 },
  { k: 'linkedin', q: 'Show us where you work in public.', type: 'url', ph: 'https://linkedin.com/in/…', hint: 'Your LinkedIn profile.', max: 300 },
  { k: 'links',    q: 'Anything else worth seeing?', type: 'area', optional: true, hint: 'A site, a paper, a repo. One per line. Optional.', max: 1200, rows: 3 },
  { k: 'answer',   q: CFG.question || 'You are handed a factory that can make anything except itself. What is the first machine you would build to change that, and which assumption in your answer is most likely to be wrong?', type: 'area', big: true, max: 1500, rows: 6, consent: true }
];

/* ---------- procedural paper ---------- */
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function makePaper(w, h, seed, base, mottle = 1) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const x = c.getContext('2d'), r = rng(seed);
  x.fillStyle = base || '#F2EDDF'; x.fillRect(0, 0, w, h);
  for (let i = 0; i < 60; i++) {
    const cx = r() * w, cy = r() * h, rad = (.1 + r() * .3) * Math.max(w, h), g = x.createRadialGradient(cx, cy, 0, cx, cy, rad);
    g.addColorStop(0, r() > .5 ? `rgba(190,165,120,${.035 * mottle})` : `rgba(255,255,250,${.05 * mottle})`); g.addColorStop(1, 'rgba(0,0,0,0)');
    x.fillStyle = g; x.fillRect(0, 0, w, h);
  }
  const img = x.getImageData(0, 0, w, h), d = img.data;
  for (let i = 0; i < d.length; i += 4) { const n = (r() - .5) * 9; d[i] += n; d[i + 1] += n; d[i + 2] += n * .9; }
  x.putImageData(img, 0, 0);
  for (let i = 0; i < w * h * .0001; i++) { x.fillStyle = `rgba(95,72,40,${.12 + r() * .3})`; const s = .6 + r() * 1.3; x.fillRect(r() * w, r() * h, s, s); }
  x.lineWidth = .6;
  for (let i = 0; i < 450; i++) {
    x.strokeStyle = `rgba(120,100,70,${.05 + r() * .07})`;
    const px = r() * w, py = r() * h, a = r() * 6.28, l = 6 + r() * 18;
    x.beginPath(); x.moveTo(px, py); x.quadraticCurveTo(px + Math.cos(a) * l / 2 + r() * 4, py + Math.sin(a) * l / 2 + r() * 4, px + Math.cos(a) * l, py + Math.sin(a) * l); x.stroke();
  }
  return c;
}
function makeBump(n) {   // paper tooth: fine noise + fibres, greyscale
  const c = document.createElement('canvas'); c.width = c.height = n; const x = c.getContext('2d'), r = rng(5);
  const img = x.createImageData(n, n); for (let i = 0; i < img.data.length; i += 4) { const v = 128 + (r() - .5) * 70; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255; }
  x.putImageData(img, 0, 0); x.lineWidth = 1;
  for (let i = 0; i < 1600; i++) { const px = r() * n, py = r() * n, a = r() * 6.28, l = 8 + r() * 28; x.strokeStyle = `rgba(${r() > .5 ? 255 : 0},${r() > .5 ? 255 : 0},${r() > .5 ? 255 : 0},.12)`; x.strokeStyle = r() > .5 ? 'rgba(255,255,255,.14)' : 'rgba(0,0,0,.14)'; x.beginPath(); x.moveTo(px, py); x.lineTo(px + Math.cos(a) * l, py + Math.sin(a) * l); x.stroke(); }
  return c;
}
const PXW = Math.round(W * PX), PXH = Math.round(H * PX), K = PX / 600;
const tx = u => (u + W / 2) * PX, tz = v => (v + H / 2) * PX;
let HOST_BOX = null;

/* flat corner points of panel k of a strip: [T0,T1,B1,B0] in sheet coordinates (x,z) */
function panelPts(d, k) {
  const f0 = -d.n * d.gamma / 2 + k * d.gamma, f1 = f0 + d.gamma, P = (r, f) => [d.cx + r * Math.sin(f), d.zA + r * Math.cos(f)];
  return [P(d.r0, f0), P(d.r0, f1), P(d.r1, f1), P(d.r1, f0)];
}
function netPath(x, d) { x.beginPath(); for (let k = 0; k < d.n; k++) { const p = panelPts(d, k); x.moveTo(tx(p[0][0]), tz(p[0][1])); for (const q of [p[1], p[2], p[3]]) x.lineTo(tx(q[0]), tz(q[1])); x.closePath(); } }

function printInvitation(c) {
  const x = c.getContext('2d'), cx = PXW / 2;
  const SERIF = '"Cormorant Garamond","Cormorant",Georgia,serif', MONO = '"IBM Plex Mono",ui-monospace,Menlo,monospace';
  const ls = v => { if ('letterSpacing' in x) x.letterSpacing = v + 'px'; };
  const spaced = (txt, y, size, col, sp) => { x.font = `400 ${size * K}px ${MONO}`; x.fillStyle = col; x.textAlign = 'center'; x.textBaseline = 'alphabetic'; ls(sp * K); x.fillText(txt, cx + sp * K / 2, y * K); ls(0); };
  const emboss = (txt, y, font) => { x.font = font; x.textAlign = 'center'; x.textBaseline = 'alphabetic'; x.fillStyle = 'rgba(255,255,255,.75)'; x.fillText(txt, cx, y * K + 2.5); x.fillStyle = 'rgba(0,0,0,.22)'; x.fillText(txt, cx, y * K - 1.2); x.fillStyle = '#27241F'; x.fillText(txt, cx, y * K); };
  x.strokeStyle = 'rgba(38,35,31,.6)'; x.lineWidth = 2; x.strokeRect(52, 52, PXW - 104, PXH - 104);
  x.strokeStyle = 'rgba(38,35,31,.25)'; x.lineWidth = 1.5; x.strokeRect(63, 63, PXW - 126, PXH - 126);
  x.strokeStyle = '#A6935F'; x.lineWidth = 2; x.fillStyle = '#F2EDDF';
  for (const [px, py] of [[52, 52], [PXW - 52, 52], [52, PXH - 52], [PXW - 52, PXH - 52]]) { x.save(); x.translate(px, py); x.rotate(Math.PI / 4); x.fillRect(-8, -8, 16, 16); x.strokeRect(-8, -8, 16, 16); x.restore(); }
  const orn = y => { y *= K; x.strokeStyle = '#A6935F'; x.lineWidth = 2; x.beginPath(); x.moveTo(cx - 260 * K, y); x.lineTo(cx - 22 * K, y); x.moveTo(cx + 22 * K, y); x.lineTo(cx + 260 * K, y); x.stroke(); x.save(); x.translate(cx, y); x.rotate(Math.PI / 4); x.strokeRect(-6, -6, 12, 12); x.restore(); };
  spaced('VOL. I  ·  AN INVITATION', 140, 24, '#625D53', 7); orn(188);
  emboss('Reading Group', 372, `500 ${180 * K}px ${SERIF}`);
  emboss('Invite', 512, `italic 400 ${150 * K}px ${SERIF}`);
  orn(566); spaced('HOSTED BY', 632, 22, '#625D53', 6);
  const host = CFG.host || 'X', fs = 58 * K, by = 698 * K;
  x.font = `italic 400 ${fs}px ${SERIF}`; x.fillStyle = '#4a463e'; x.textAlign = 'center'; x.fillText(host, cx, by);
  const tw = x.measureText(host).width;
  if (CFG.hostUrl) { x.strokeStyle = '#A6935F'; x.lineWidth = 2; x.beginPath(); x.moveTo(cx - tw / 2, by + 9 * K); x.lineTo(cx + tw / 2, by + 9 * K); x.stroke(); }
  HOST_BOX = { u0: (cx - tw / 2) / PX - W / 2, u1: (cx + tw / 2) / PX - W / 2, z0: (by - fs * .85) / PX - H / 2, z1: (by + 14 * K) / PX - H / 2 };
  // crease pattern, drafted in blueprint ink
  x.fillStyle = 'rgba(46,68,87,.8)';
  for (const d of STRIPS) {
    x.strokeStyle = 'rgba(46,68,87,.72)'; x.lineWidth = 1.6; x.setLineDash([]); netPath(x, d); x.stroke();
    x.setLineDash([12, 8]); x.lineWidth = 1.4;
    for (let k = 1; k < d.n; k++) { const p = panelPts(d, k); x.beginPath(); x.moveTo(tx(p[0][0]), tz(p[0][1])); x.lineTo(tx(p[3][0]), tz(p[3][1])); x.stroke(); }
    x.setLineDash([]);
    if (d.label) { x.font = `400 ${15 * K}px ${MONO}`; x.textAlign = 'center'; ls(3 * K); x.fillText(d.label, tx(d.cx), tz(ZB) + 30 * K); ls(0); }
  }
  x.font = `400 ${15 * K}px ${MONO}`; x.textAlign = 'left'; ls(3 * K); x.fillText('FOLD ALONG THE DASHES', tx(-W / 2 + .14), tz(ZB - 1.05)); ls(0);
}
function drawCreasesOnBack(c) {      // soft ridge lines where the paper has been folded
  const x = c.getContext('2d'); x.lineCap = 'round';
  for (const d of STRIPS) for (let k = 1; k < d.n; k++) {
    const p = panelPts(d, k), X0 = tx(p[0][0]), Z0 = tz(p[0][1]), X1 = tx(p[3][0]), Z1 = tz(p[3][1]);
    x.strokeStyle = 'rgba(70,52,28,.20)'; x.lineWidth = 5; x.beginPath(); x.moveTo(X0, Z0); x.lineTo(X1, Z1); x.stroke();
    x.strokeStyle = 'rgba(70,52,28,.38)'; x.lineWidth = 1.3; x.beginPath(); x.moveTo(X0, Z0); x.lineTo(X1, Z1); x.stroke();
    x.strokeStyle = 'rgba(255,255,255,.55)'; x.lineWidth = 1.2; x.beginPath(); x.moveTo(X0 + 2, Z0); x.lineTo(X1 + 2, Z1); x.stroke();
  }
}

/* ---------- a strip that folds by rigid rotation about each (non-parallel) crease ---------- */
const _m = new Matrix4(), _r = new Matrix4(), _t = new Matrix4(), _v = new Vector3(), _a = new Vector3(), _b = new Vector3(), _u = new Vector3();
class Strip {
  constructor(d, frontMat, backMat) {
    Object.assign(this, d); this.f = 0; this.fT = 0; this.dirty = true; this.asm = 0; this.frontMat = frontMat;
    const vN = d.n * 6; this.pos = new Float32Array(vN * 3); this.uv = new Float32Array(vN * 2); this.col = new Float32Array(vN * 3);
    const r = rng(d.n * 31 + Math.round(d.cx * 100)); let o = 0;
    this.flat = []; for (let k = 0; k < d.n; k++) this.flat.push(panelPts(d, k));
    for (let k = 0; k < d.n; k++) { const sh = .965 + r() * .05; for (let i = 0; i < 6; i++) { this.col[o * 3] = this.col[o * 3 + 1] = this.col[o * 3 + 2] = sh; o++; } }
    this.geo = new BufferGeometry();
    this.geo.setAttribute('position', new BufferAttribute(this.pos, 3)); this.geo.setAttribute('uv', new BufferAttribute(this.uv, 2)); this.geo.setAttribute('color', new BufferAttribute(this.col, 3));
    this.group = new Group();
    for (const m of [frontMat, backMat]) { const mesh = new Mesh(this.geo, m); mesh.castShadow = true; mesh.receiveShadow = true; mesh.frustumCulled = false; this.group.add(mesh); }
    this.hinges = []; for (let k = 0; k < d.n - 1; k++) { const p = this.flat[k]; this.hinges.push({ a: new Vector3(p[1][0], 0, p[1][1]), u: new Vector3(p[2][0] - p[1][0], 0, p[2][1] - p[1][1]).normalize() }); }
    // bounding box of the flat net (for hit testing)
    let x0 = 9, x1 = -9, z0 = 9, z1 = -9; for (const p of this.flat) for (const q of p) { x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); z0 = Math.min(z0, q[1]); z1 = Math.max(z1, q[1]); }
    this.box = { x0, x1, z0, z1 };
    this.apply(1); const rings = this.rings; this.botC = rings.bot; this.axis = rings.top.clone().sub(rings.bot); this.h = this.axis.length(); this.axis.normalize();
    this.closure = this.closureError(); this.apply(0);
  }
  apply(f) {
    const d = this, M = new Matrix4(), P = this.pos, UV = this.uv; let o = 0;
    const top = new Vector3(), bot = new Vector3();
    for (let k = 0; k < d.n; k++) {
      const p = this.flat[k], w = [0, 1, 2, 3].map(i => new Vector3(p[i][0], 0, p[i][1]).applyMatrix4(M));
      top.add(w[0]); bot.add(w[3]);
      const uvs = p.map(q => [(q[0] + W / 2) / W, 1 - (q[1] + H / 2) / H]);
      for (const i of [0, 3, 2, 0, 2, 1]) { P[o * 3] = w[i].x; P[o * 3 + 1] = w[i].y; P[o * 3 + 2] = w[i].z; UV[o * 2] = uvs[i][0]; UV[o * 2 + 1] = uvs[i][1]; o++; }
      if (k < d.n - 1) { const h = this.hinges[k]; _t.makeTranslation(-h.a.x, 0, -h.a.z); _r.makeRotationAxis(h.u, d.psi * f); _m.makeTranslation(h.a.x, 0, h.a.z).multiply(_r).multiply(_t); M.multiply(_m); }
      if (k === d.n - 1) this.lastM = M.clone();
    }
    this.rings = { top: top.divideScalar(d.n), bot: bot.divideScalar(d.n) };
    this.geo.attributes.position.needsUpdate = true; this.geo.attributes.uv.needsUpdate = true; this.geo.attributes.color.needsUpdate = true;
    this.geo.computeVertexNormals();
  }
  closureError() {          // how well does the last panel meet the first when fully folded?
    const p = this.flat[this.n - 1], M = this.lastM;
    const t1 = new Vector3(p[1][0], 0, p[1][1]).applyMatrix4(M), b1 = new Vector3(p[2][0], 0, p[2][1]).applyMatrix4(M);
    const t0 = new Vector3(this.flat[0][0][0], 0, this.flat[0][0][1]), b0 = new Vector3(this.flat[0][3][0], 0, this.flat[0][3][1]);
    return t1.distanceTo(t0) + b1.distanceTo(b0);
  }
  update() { if (Math.abs(this.f - this.fT) > 1e-4 || this.dirty) { this.f = this.fT; this.apply(this.f); this.dirty = false; } }
  place(B, D, s) {     // B: bottom-centre in the arm, D: axis direction. s=0 lying on the sheet, s=1 in the arm
    const q = new Quaternion().setFromUnitVectors(this.axis, D), p = B.clone().sub(this.botC.clone().applyQuaternion(q));
    this.group.position.set(p.x * s, p.y * s + Math.sin(Math.PI * s) * .85, p.z * s);
    this.group.quaternion.identity().slerp(q, s);
  }
}

/* ---------- arm kinematics: cones nested inside one another ---------- */
const dirA = a => new Vector3(-Math.sin(a), Math.cos(a), 0);
const X0 = -1.0, ZA = .25, OV = [0, .075, .075, .06, .05, .05];
function chain(strips, a1, a2, a3, op) {
  const out = [], up = new Vector3(0, 1, 0);
  let B = new Vector3(X0, 0, ZA), D = up.clone();
  out.push({ B: B.clone(), D: D.clone() });
  let T = B.clone().addScaledVector(D, strips[0].h);
  const angs = [a1, a1 + a2, a1 + a2 + a3];
  for (let i = 1; i <= 3; i++) { D = dirA(angs[i - 1]); B = T.clone().addScaledVector(D, -OV[i]); out.push({ B: B.clone(), D: D.clone() }); T = B.clone().addScaledVector(D, strips[i].h); }
  const a = angs[2], perp = new Vector3(Math.cos(a), Math.sin(a), 0);
  for (const sg of [1, -1]) { const Dd = dirA(a - sg * op), Bf = T.clone().addScaledVector(Dd, -OV[4]).addScaledVector(perp, sg * .018); out.push({ B: Bf, D: Dd }); }
  return out;
}

/* ---------- boot ---------- */
async function boot() {
  const canvas = $('gl'); if (!canvas) return false;
  let renderer;
  try { renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false }); } catch (e) { return false; }
  try { await Promise.race([Promise.all([document.fonts.load('500 180px "Cormorant Garamond"'), document.fonts.load('italic 400 150px "Cormorant Garamond"'), document.fonts.load('400 24px "IBM Plex Mono"')]), new Promise(r => setTimeout(r, 2500))]); } catch (e) {}

  renderer.shadowMap.enabled = true; renderer.shadowMap.type = PCFShadowMap;
  const scene = new Scene(); scene.background = new Color('#cfc9b9'); scene.fog = new Fog('#cfc9b9', 10, 22);
  const camera = new PerspectiveCamera(27, 1, .1, 60);
  const aniso = renderer.capabilities.getMaxAnisotropy();
  const tex = (c, srgb = true) => { const t = new CanvasTexture(c); if (srgb) t.colorSpace = SRGBColorSpace; t.anisotropy = aniso; return t; };

  const front = makePaper(PXW, PXH, 7, '#F1EEE3'); printInvitation(front);
  const back = makePaper(PXW, PXH, 21, '#ECE8DA'); drawCreasesOnBack(back);
  const holes = document.createElement('canvas'); holes.width = PXW; holes.height = PXH;
  { const g = holes.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, PXW, PXH); g.fillStyle = '#000'; g.strokeStyle = '#000'; g.lineWidth = 2; for (const d of STRIPS) { netPath(g, d); g.fill(); g.stroke(); } }
  const frontTex = tex(front), backTex = tex(back), bumpTex = tex(makeBump(1024), false); bumpTex.wrapS = bumpTex.wrapT = RepeatWrapping; bumpTex.repeat.set(5, 3.5);
  const tableTex = tex(makePaper(1024, 1024, 99, '#B9B2A1', 0)); tableTex.wrapS = tableTex.wrapT = RepeatWrapping; tableTex.repeat.set(10, 10);

  const paper = (extra) => new MeshStandardMaterial({ roughness: 1, metalness: 0, bumpMap: bumpTex, bumpScale: .55, vertexColors: true, ...extra });
  const backMat = paper({ map: backTex, side: 1 });
  const table = new Mesh(new PlaneGeometry(60, 60), new MeshStandardMaterial({ map: tableTex, roughness: 1 })); table.rotation.x = -Math.PI / 2; table.position.y = -.004; table.receiveShadow = true; scene.add(table);
  const sheetGeo = new PlaneGeometry(W, H); sheetGeo.rotateX(-Math.PI / 2);
  const sheet = new Mesh(sheetGeo, new MeshStandardMaterial({ map: frontTex, alphaMap: tex(holes, false), alphaTest: .5, roughness: 1, bumpMap: bumpTex, bumpScale: .4 })); sheet.receiveShadow = true; scene.add(sheet);

  const strips = STRIPS.map(d => { const fm = paper({ map: frontTex, side: 0, emissive: new Color('#e2cf93'), emissiveIntensity: 0 }); const s = new Strip(d, fm, backMat); scene.add(s.group); return s; });

  const sun = new DirectionalLight(0xfff9f0, 2.3); sun.position.set(-3, 5.5, 3); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); const sc = sun.shadow.camera; sc.left = -4; sc.right = 4; sc.top = 4; sc.bottom = -4; sc.near = .5; sc.far = 16;
  sun.shadow.bias = -.0004; sun.shadow.normalBias = .012; sun.shadow.radius = 6; if ('intensity' in sun.shadow) sun.shadow.intensity = .62; scene.add(sun);
  scene.add(new HemisphereLight(0xfffaf3, 0xd6cfbf, 2.2));

  /* ---------- view ---------- */
  let vw = 0, vh = 0, d0 = 6, dArm = 6, narrow = false, shift = 0, shiftT = 0, camC = 0, camT = 0;
  function resize() {
    vw = innerWidth; vh = innerHeight; narrow = vw < 800;
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setSize(vw, vh, false);
    camera.aspect = vw / vh; camera.updateProjectionMatrix();
    const t = Math.tan(camera.fov * Math.PI / 360), a = vw / vh;
    d0 = Math.max((W * 1.16 / 2) / (t * a), (H * 1.24 / 2) / t); dArm = Math.max(6.4, (3.4 * 1.2 / 2) / (t * a));
    /* fog must scale with camera distance: on a narrow phone the camera sits ~3x farther than on desktop,
       and a fixed 10-22 range washed the whole sheet into the backdrop */
    const dm = Math.max(d0, dArm); scene.fog.near = dm * 1.4; scene.fog.far = dm * 3.05;
  }
  const KEY = [   // completed folds -> camera: polar, azimuth, distance, target
    [0.0001, 0.00, () => d0,         [0, 0, 0]],
    [0.55,   0.05, () => d0 * .98,   [0, 0, .1]],
    [0.78,   0.12, () => d0 * 1.0,   [-.1, .25, .2]],
    [0.88,   0.20, () => d0 * 1.08,  [-.3, .55, .2]],
    [0.95,   0.30, () => d0 * 1.12,  [-.4, .5, .2]],
    [1.00,   0.45, () => dArm * 1.0, [-.2, .6, .25]],
    [1.06,   0.75, () => dArm * .92, [.1, .62, .3]]
  ];
  function camAt(c) {
    const i = Math.min(Math.floor(c), KEY.length - 2), t = ease(clamp(c - i)), A = KEY[i], B = KEY[i + 1];
    const pol = lerp(A[0], B[0], t), az = lerp(A[1], B[1], t), d = lerp(A[2](), B[2](), t);
    const T = new Vector3(lerp(A[3][0], B[3][0], t), lerp(A[3][1], B[3][1], t), lerp(A[3][2], B[3][2], t));
    camera.position.set(T.x + d * Math.sin(pol) * Math.sin(az), T.y + d * Math.cos(pol), T.z + d * Math.sin(pol) * Math.cos(az));
    const s = clamp(pol / .25); camera.up.set(0, s, -(1 - s)).normalize(); camera.lookAt(T);
    if (Math.abs(shift) > .5) { if (narrow) camera.setViewOffset(vw, vh, 0, shift, vw, vh); else camera.setViewOffset(vw, vh, shift, 0, vw, vh); } else camera.clearViewOffset();
  }
  const proj = (x, y, z) => { _v.set(x, y, z).project(camera); return [(_v.x + 1) / 2 * vw, (1 - _v.y) / 2 * vh]; };

  /* ---------- state ---------- */
  const answers = {}; let step = 0, state = 'idle', art = 0, op = .06, clock = 0, anims = [];
  const ray = new Raycaster(), plane = new Plane(new Vector3(0, 1, 0), 0), hit = new Vector3(), ndc = new Vector2();
  const ground = (cx, cy) => { ndc.set(cx / vw * 2 - 1, -(cy / vh) * 2 + 1); ray.setFromCamera(ndc, camera); return ray.ray.intersectPlane(plane, hit) ? hit : null; };
  const anim = (dur, fn, done, ez = ease) => anims.push({ t0: performance.now(), dur, fn, done, ez });
  const hudFig = $('hudFig'), hudCap = $('hudCap'), hudN = $('hudN'), tip = $('tip'), hostLink = $('hostLink'), ask = $('ask'), askK = $('askK'), askQ = $('askQ'), askBody = $('askBody'), askErr = $('askErr'), askGo = $('askGo'), askConsent = $('askConsent'), consentBox = $('consentBox'), openBtn = $('open');
  const total = STRIPS.length;
  function hud() {
    let n = 0, all = 0; strips.forEach(s => { n += s.f * (s.n - 1); all += s.n - 1; });
    hudN.textContent = String(Math.round(n)).padStart(2, '0'); $('hudAll').textContent = String(all);
    if (state === 'done') { hudFig.textContent = 'Fig. 7 — The arm'; hudCap.textContent = 'One sheet of paper, folded into a machine.'; }
    else if (state === 'blocked') { hudFig.textContent = 'Closed'; hudCap.textContent = ''; }
    else { hudFig.textContent = `Fold ${Math.min(step + 1, total)} of ${total} — ${STRIPS[Math.min(step, total - 1)].label || 'CLAW'}`; hudCap.textContent = state === 'ask' ? 'Answer to continue.' : 'Swipe across the glowing strip to fold it.'; }
  }

  /* ---------- the question card ---------- */
  function openAsk(i) {
    const S = STEPS[i]; state = 'ask'; shiftT = narrow ? vh * .22 : vw * .17; hud();
    askK.textContent = `Fold ${i + 1} of ${total}`; askQ.textContent = S.q; askErr.textContent = ''; askBody.innerHTML = '';
    let el;
    if (S.type === 'area') { el = document.createElement('textarea'); el.rows = S.rows || 3; if (S.big) el.className = 'big'; }
    else { el = document.createElement('input'); el.type = S.type; if (S.type === 'number') { el.min = 1; el.max = 120; el.inputMode = 'numeric'; el.style.maxWidth = '140px'; } }
    el.id = 'askField'; el.maxLength = S.max || 200; if (S.auto) el.autocomplete = S.auto; else el.autocomplete = 'off'; if (S.ph) el.placeholder = S.ph; if (answers[S.k] != null) el.value = answers[S.k];
    el.setAttribute('aria-label', S.q); askBody.appendChild(el);
    if (S.hint) { const h = document.createElement('p'); h.className = 'note'; h.textContent = S.hint; askBody.appendChild(h); }
    askConsent.hidden = !S.consent; askGo.textContent = i === total - 1 ? 'Request a seat' : (S.optional ? 'Continue' : 'Continue'); askGo.disabled = false;
    ask.hidden = false; ask.classList.remove('in'); void ask.offsetWidth; ask.classList.add('in');
    setTimeout(() => { try { el.focus({ preventScroll: true }); } catch (e) {} }, 350);
  }
  function validate(i, v) {
    v = (v || '').trim(); const S = STEPS[i];
    if (S.k === 'age') { const n = Number(v); if (!v || !Number.isInteger(n) || n < 1 || n > 120) return 'Please enter your age as a whole number.'; }
    if (S.k === 'name' && v.length < 2) return 'Please add your name.';
    if (S.k === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return 'That email doesn’t look right.';
    if (S.k === 'linkedin' && !/^(https?:\/\/)?([\w-]+\.)?linkedin\.com\/.+/i.test(v)) return 'Please add your LinkedIn profile link.';
    if (S.k === 'answer') { if (v.length < 40) return 'Give the question a real answer, a few sentences at least.'; if (!consentBox.checked) return 'Please tick the box so we can email you.'; }
    return '';
  }
  async function submitAsk() {
    if (state !== 'ask') return; const i = step, S = STEPS[i], val = $('askField').value.trim(), msg = validate(i, val);
    if (msg) { askErr.textContent = msg; return; }
    if (S.k === 'age') {
      if (Number(val) <= 12) { return block(); }
    }
    answers[S.k] = S.k === 'age' ? Number(val) : val;
    if (i === total - 1) {
      askGo.disabled = true; askGo.textContent = 'Sending…'; askErr.textContent = '';
      try { await window.sendRegistration({ name: answers.name, email: answers.email, age: answers.age, linkedin: answers.linkedin, links: answers.links || '', answer: answers.answer, ts: new Date().toISOString() }); }
      catch (e) { askErr.textContent = (e && e.message ? e.message : 'Something went wrong.') + ' Please try again in a moment.'; askGo.disabled = false; askGo.textContent = 'Request a seat'; return; }
    }
    ask.hidden = true; shiftT = 0; state = 'asm';
    const s = strips[i]; anim(1500, t => { s.asm = t; }, () => {
      s.asm = 1; step++; camT = step;
      if (step >= total) finish(); else { state = 'idle'; hud(); }
    }, ease);
    hud();
  }
  function block() {      // 12 and under: nothing is kept, the fold springs back open
    state = 'blocked'; for (const k in answers) delete answers[k];
    askK.textContent = 'Closed'; askQ.textContent = 'This group is for readers 13 and older.'; askBody.innerHTML = '<p class="note">Nothing you typed has been saved or sent anywhere. Thank you for stopping by.</p>'; askErr.textContent = ''; askConsent.hidden = true; askGo.hidden = true;
    const s = strips[0]; const f0 = s.f; anim(1400, t => { s.fT = f0 * (1 - t); }, () => { s.fT = 0; });
    hud();
  }
  function finish() {
    state = 'done'; hud();
    anim(2600, t => { art = t; }, null, ease);
    anim(3400, t => { op = .06 + .5 * Math.sin(Math.PI * t); }, null, x => x);
    setTimeout(() => {
      askK.textContent = 'Received'; askQ.textContent = 'Your name is in the book.'; askBody.innerHTML = `<p class="note">A confirmation is on its way to <b></b>. If you’re accepted, the date lands on your calendar the moment it’s confirmed, and we’ll check in 48 hours before.</p>`;
      askBody.querySelector('b').textContent = answers.email; askErr.textContent = ''; askConsent.hidden = true; askGo.hidden = true; shiftT = narrow ? vh * .22 : vw * .17;
      ask.hidden = false; ask.classList.remove('in'); void ask.offsetWidth; ask.classList.add('in');
    }, 2200);
  }
  askGo.addEventListener('click', submitAsk);
  ask.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') { e.preventDefault(); submitAsk(); } });

  /* ---------- pointer: swipe the glowing strip ---------- */
  let drag = null;
  const active = () => (state === 'idle' && step < total) ? strips[step] : null;
  function overStrip(cx, cy) {
    const s = active(); if (!s) return false; const g = ground(cx, cy); if (!g) return false; const pad = s.n === 3 ? .35 : .16;
    return g.x > s.box.x0 - pad && g.x < s.box.x1 + pad && g.z > s.box.z0 - pad && g.z < s.box.z1 + pad;
  }
  function autoFold(s) {
    state = 'fold'; const f0 = s.fT; anim(1100 * (1 - f0) + 250, t => { s.fT = lerp(f0, 1, t); }, () => { s.fT = 1; setTimeout(() => openAsk(step), 250); });
  }
  canvas.addEventListener('pointerdown', e => {
    const s = active(); if (!s || !overStrip(e.clientX, e.clientY)) return;
    const [xa] = proj(s.box.x0, 0, s.box.z1), [xb] = proj(s.box.x1, 0, s.box.z1);
    drag = { id: e.pointerId, x0: e.clientX, span: Math.max(Math.abs(xb - xa) * .9, 130), moved: false, s }; state = 'drag';
    try { canvas.setPointerCapture(e.pointerId); } catch (_) {} canvas.style.cursor = 'grabbing';
  });
  canvas.addEventListener('pointermove', e => {
    if (drag && e.pointerId === drag.id) { const dx = e.clientX - drag.x0; if (Math.abs(dx) > 6) drag.moved = true; drag.s.fT = clamp(dx / drag.span); }
    else if (!drag) canvas.style.cursor = overStrip(e.clientX, e.clientY) ? 'grab' : 'default';
  });
  const end = e => {
    if (!drag || e.pointerId !== drag.id) return; const s = drag.s, ok = !drag.moved || s.fT > .5; drag = null; canvas.style.cursor = 'default';
    if (ok) autoFold(s); else { state = 'fold'; const f0 = s.fT; anim(380, t => { s.fT = f0 * (1 - t); }, () => { s.fT = 0; state = 'idle'; }, easeOut); }
  };
  canvas.addEventListener('pointerup', end); canvas.addEventListener('pointercancel', end);
  openBtn.addEventListener('click', () => { const s = active(); if (s) autoFold(s); });

  /* ---------- frame loop ---------- */
  function frame(now) {
    requestAnimationFrame(frame);
    if (scrollY > vh * 1.05) return;
    clock = now / 1000;
    anims = anims.filter(a => { const t = clamp((now - a.t0) / a.dur); a.fn(a.ez(t)); if (t >= 1) { a.done && a.done(); return false; } return true; });
    camC += (camT - camC) * (1 - Math.exp(-2.4 * (1 / 60))); shift += (shiftT - shift) * (1 - Math.exp(-5 * (1 / 60)));
    // strips
    const act = active();
    strips.forEach((s, i) => {
      s.update();
      const pulse = (act === s && s.f < .02) ? .08 + .09 * (.5 + .5 * Math.sin(clock * 3.2)) : 0; s.frontMat.emissiveIntensity = pulse;
    });
    const a1 = -.55 * art, a2 = -1.15 * art, a3 = -.6 * art, ch = chain(strips, a1, a2, a3, op);
    strips.forEach((s, i) => s.place(ch[i].B, ch[i].D, s.asm));
    camAt(camC); renderer.render(scene, camera);
    // overlays
    const showTip = act && state === 'idle';
    if (showTip) { const [tx_, ty_] = proj(act.cx, 0, act.box.z0 - .06); tip.style.transform = `translate(${tx_}px,${ty_}px) translate(-50%,-100%)`; }
    tip.classList.toggle('on', !!showTip);
    if (HOST_BOX && camC < .05 && state !== 'ask' && !shift) {
      const [xa, ya] = proj(HOST_BOX.u0, 0, HOST_BOX.z0), [xb, yb] = proj(HOST_BOX.u1, 0, HOST_BOX.z1);
      Object.assign(hostLink.style, { left: xa + 'px', top: ya + 'px', width: (xb - xa) + 'px', height: (yb - ya) + 'px' }); hostLink.classList.add('on');
    } else hostLink.classList.remove('on');
    hud();
    if (state === 'idle' && step === 0) openBtn.classList.add('on'); else openBtn.classList.remove('on');
  }
  addEventListener('resize', resize);
  resize(); hud(); requestAnimationFrame(frame);
  document.documentElement.classList.add('gl-ready');
  window.__origami = { strips, camera, scene, renderer, get state() { return state; }, get step() { return step; }, setArt: v => { art = v; op = .3; camC = 6; camT = 6; }, setState: (s, st) => { state = s; step = st; camT = st; } };
  return true;
}
boot().then(ok => { if (!ok) document.documentElement.classList.add('fallback'); }).catch(e => { console.error(e); document.documentElement.classList.add('fallback'); });
if (matchMedia('(prefers-reduced-motion:reduce)').matches) document.documentElement.classList.add('fallback');
