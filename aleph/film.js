// 阿莱夫：一镜到底的循环缩放。A（地下室）⊃ 小球 = B（一切）⊃ 正中 = A ⊃ …
// 相机定义在 B1 坐标里：screen = z·R(roll)·p + o + 画面中心。其余各层的矩阵由嵌套关系推出来。
import { INK, PAPER, clamp, lerp, ss, TAU, rgba, hex, mix3, fbm, n2, rough, penStroke, handwrite, sparkle } from './engine.js';
import { A, B, cellar, aleph, circ } from './scenes.js';
import { monotone } from '/core/lib.js';

const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const SW = cv.width, SH = cv.height;
export const DUR = 20;
const sA = A.rS / B.R;                                     // B 页（半径 1000）装进半径 18 的小球
const rcA = 1341;                                          // 地下室作为 B 中心小图时，在 A 坐标里的可见半径
const sB = B.rc / rcA;                                     // A → B 中心的缩放
const PHI = B.phi;
const H = i => { const n = Math.sin(i * 91.17 + 7.3) * 43758.5453; return n - Math.floor(n); };
const seg = (t, a, b) => clamp((t - a) / (b - a));
const SILVER = [140, 142, 158], DARK = [26, 22, 20];

// ---------- 时间线 ----------
export const T = {
  aInk: [0.15, 2.9], note: [0.3, 1.0], born: 1.4, glint: 3.75, hold: 5.0, enter: 5.625, colour: [5.7, 8.6],
  sweep: [8.75, 12.5], whip: 10.0, back: 14.4, silence: [14.4, 15.0], dive: [15.0, 17.0], drain: [15.0, 16.3], title: [16.25, 16.6], sub: [16.5, 17.0],
};

// ---------- 相机 ----------
const K = [   // t, z, ox, oy, roll(°)
  [0.0, sA * 1.0, 70, 92, 0], [2.6, sA * 1.035, 40, 92, 0], [3.5, sA * 1.9, 30, 74, 0], [5.0, .5, 0, 0, 0], [5.6, .53, 0, 0, 0],
  [8.75, .64, 0, 0, 10], [10.0, 1.55, 0, 980, -30], [12.5, 1.6, 0, 1010, -150], [14.4, .5, 0, 0, -150], [15.0, .49, 0, 0, -150],
  [17.0, 1 / sB, 0, 0, -150], [20.0, 1.03 / sB, 0, 0, -150],
];
const fz = monotone(K.map(k => [k[0], Math.log2(k[1])])), fx = monotone(K.map(k => [k[0], k[2]])), fy = monotone(K.map(k => [k[0], k[3]])), fr = monotone(K.map(k => [k[0], k[4]]));
export function cam(t) { return { z: Math.pow(2, fz(t)), ox: fx(t), oy: fy(t), roll: fr(t) * Math.PI / 180 }; }

// ---------- 矩阵（canvas 的 a b c d e f） ----------
const mul = (M, N) => [M[0] * N[0] + M[2] * N[1], M[1] * N[0] + M[3] * N[1], M[0] * N[2] + M[2] * N[3], M[1] * N[2] + M[3] * N[3], M[0] * N[4] + M[2] * N[5] + M[4], M[1] * N[4] + M[3] * N[5] + M[5]];
const inv = M => { const d = M[0] * M[3] - M[1] * M[2]; return [M[3] / d, -M[1] / d, -M[2] / d, M[0] / d, (M[2] * M[5] - M[3] * M[4]) / d, (M[1] * M[4] - M[0] * M[5]) / d]; };
const ap = (M, [x, y]) => [M[0] * x + M[2] * y + M[4], M[1] * x + M[3] * y + M[5]];
const scl = M => Math.sqrt(Math.abs(M[0] * M[3] - M[1] * M[2]));
const T_AB = [sA, 0, 0, sA, A.sphere[0], A.sphere[1]];                  // B 坐标 → 外层 A 坐标
const T_BA = (() => { const c = Math.cos(PHI) * sB, s = Math.sin(PHI) * sB; return [c, s, -s, c, -(c * A.center[0] - s * A.center[1]), -(s * A.center[0] + c * A.center[1])]; })();   // A 坐标 → 外层 B 坐标

// 层：0 = A0，1 = B1，2 = A2，3 = B3 …
function levels(t) {
  const c = cam(t), M1 = [c.z * Math.cos(c.roll), c.z * Math.sin(c.roll), -c.z * Math.sin(c.roll), c.z * Math.cos(c.roll), c.ox + SW / 2, c.oy + SH / 2];
  const L = [{ k: 'A', M: mul(M1, inv(T_AB)) }, { k: 'B', M: M1 }];
  while (L.length < 9) { const p = L[L.length - 1], M = mul(p.M, p.k === 'A' ? T_AB : T_BA); L.push({ k: p.k === 'A' ? 'B' : 'A', M }); if (discR(L[L.length - 1]) < 1.2) break; }
  return L;
}
function discR(l) { return (l.k === 'B' ? B.R : rcA * .9) * scl(l.M); }
function discC(l) { return ap(l.M, l.k === 'B' ? [0, 0] : A.center); }
function covers(l) { const [cx, cy] = discC(l), r = discR(l); return [[0, 0], [SW, 0], [0, SH], [SW, SH]].every(([x, y]) => Math.hypot(x - cx, y - cy) < r - 2); }

// ---------- 预备：笔触、水彩 ----------
function prepStroke(s, i) {
  const st = penStroke(s.pts, { w: s.w, wob: s.wob ?? Math.min(1.2, s.w * .45), over: s.over ?? s.w * 2.2, gap: s.gap ?? .35, seed: 17 + i * 13, smooth: s.smooth });
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const [x, y] of st.P) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  const col = s.col === 'silver' ? SILVER : s.col === 'dark' ? DARK : INK;
  return { ...s, st, bb: [x0, y0, x1, y1], col, alpha: s.alpha ?? 1, id: i };
}
function prepWash(w, i) {
  const j = w.j ?? 5, L = 3, layers = [];
  for (let l = 0; l < L; l++) layers.push(rough(w.poly.map(p => [p[0] + j * .35, p[1] + j * .2]), j * (1 + l * .35), 31 + i * 7 + l * 31, w.step ?? Math.max(3, j * 1.2), w.freq ?? .02 / Math.max(.5, j / 6)));
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const [x, y] of layers[2]) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return { ...w, layers, bb: [x0 - j, y0 - j, x1 + j, y1 + j], id: i };
}

const cel = cellar(), alf = aleph();
const AS = cel.S.map(prepStroke);
{ // A 的笔顺：按出现顺序一笔接一笔，时长按长度分
  const tot = AS.reduce((a, s) => a + s.st.L + 60, 0); let acc = 0; const [a, b] = T.aInk;
  for (const s of AS) { s.t0 = a + (b - a) * acc / tot; s.dur = Math.max(.03, (b - a) * s.st.L / tot); acc += s.st.L + 60; }
}
const BS = alf.S.map(prepStroke), BW = alf.W.filter(w => w.a > 0).map(prepWash);
const BRes = (alf.reserves || []).map(pl => rough(pl, 3, 5));
{ // B：所有景象同时开画；每个景象自己的笔顺
  const groups = new Map();
  for (const s of BS) { const g = s.item; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(s); }
  for (const [g, list] of groups) {
    if (g === -2) { list.forEach((s, i) => { s.t0 = 5.9 + H(i + 400) * 2.3; s.dur = .12 + H(i + 500) * .15; }); continue; }
    if (g === -3) { list.forEach((s, i) => { s.t0 = 5.5 + i * .12; s.dur = .5; }); continue; }
    const ring = alf.items[g].ring, start = (ring === 1 ? 5.45 : 5.75) + H(g + 77) * .3, len = ring === 1 ? 2.3 : 2.5;
    const tot = list.reduce((a, s) => a + s.st.L + 20, 0); let acc = 0;
    for (const s of list) { s.t0 = start + len * acc / tot; s.dur = Math.max(.03, len * s.st.L / tot); acc += s.st.L + 20; }
  }
}
// 小球的轮廓（A 坐标）
const SPH = penStroke(circ(A.sphere[0], A.sphere[1], A.rS, 26).concat([circ(A.sphere[0], A.sphere[1], A.rS, 26)[1]]), { w: 1.5, wob: .5, over: 3, gap: .6, seed: 5 });
const IRIS = ['#5b7fc0', '#8a5aa8', '#e2b04a', '#4f9a92', '#c9573f', '#d97fa0'].map(hex);
const SPW = (() => {   // 小球的水彩（A 坐标，半径 rS）
  const [x, y] = A.sphere, r = A.rS, out = { swirl: [], rim: [], shade: [] };
  const ring = (a0, a1, r0, r1) => { const P = []; for (let k = 0; k <= 24; k++) { const a = a0 + (a1 - a0) * k / 24; P.push([x + Math.cos(a) * r1, y + Math.sin(a) * r1]); } for (let k = 24; k >= 0; k--) { const a = a0 + (a1 - a0) * k / 24; P.push([x + Math.cos(a) * r0, y + Math.sin(a) * r0]); } return P; };
  for (let k = 0; k < 7; k++) { const a0 = k / 7 * TAU + H(k) * .3; out.rim.push(prepWash({ poly: ring(a0, a0 + TAU / 7 + .6, r * .88 + H(k) * r * .03, r * 1.03), col: IRIS[k % 6], a: .38, j: r * .07, step: r * .06, freq: .5 / r * 4 }, 900 + k)); }
  for (let k = 0; k < 11; k++) { const an = k / 11 * TAU * 1.7, rr = r * (.15 + H(k + 3) * .6); out.swirl.push(prepWash({ poly: circ(x + Math.cos(an) * rr, y + Math.sin(an) * rr, r * (.14 + H(k + 7) * .14), 14), col: IRIS[k % 6], a: .34, j: r * .07, step: r * .05, freq: .5 / r * 4 }, 920 + k)); }
  const cres = []; for (let k = 0; k <= 16; k++) { const a = -.3 + k / 16 * 2.2; cres.push([x + Math.cos(a) * r * .98, y + Math.sin(a) * r * .98]); } for (let k = 16; k >= 0; k--) { const a = -.3 + k / 16 * 2.2; cres.push([x + Math.cos(a) * r * .7 + r * .12, y + Math.sin(a) * r * .7 + r * .1]); }
  out.shade.push(prepWash({ poly: cres, col: hex('#6c6a9a'), a: .35, j: r * .05, step: r * .06, freq: .5 / r * 4 }, 950));
  out.hi = rough(circ(x - r * .38, y - r * .42, r * .2, 12).map(([px, py]) => [x - r * .38 + (px - x + r * .38) * 1.4, py]), r * .04, 7, r * .05, .5 / r * 4);
  return out;
})();

// ---------- 画 ----------
let curWmul = 1, curS = 1;
function strokeDraw(st, p, col, alpha, dx = 0, dy = 0) {
  if (p <= 0) return;
  const end = st.L * clamp(p);
  let sw = st.W[1] * curS * curWmul;
  if (sw < .45) { alpha *= Math.max(.7, sw / .45); }
  if (alpha < .03) return;
  ctx.strokeStyle = rgba(col, alpha * st.alpha);
  const P = st.P, S = st.S, n = P.length;
  let i = 1;
  while (i < n && S[i - 1] <= end) {
    const g = st.gaps.length && st.gaps.some(q => S[i] / st.L > q[0] && S[i] / st.L < q[1]);
    if (g) { i++; continue; }
    const w = Math.max(st.W[i] * curWmul, .45 / curS);
    ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(P[i - 1][0] + dx, P[i - 1][1] + dy);
    let k = 0;
    while (i < n && k < 4 && S[i - 1] <= end) {
      let [x, y] = P[i];
      if (S[i] > end) { const f = (end - S[i - 1]) / (S[i] - S[i - 1] || 1); x = lerp(P[i - 1][0], x, f); y = lerp(P[i - 1][1], y, f); }
      ctx.lineTo(x + dx, y + dy); i++; k++;
      if (st.gaps.length && st.gaps.some(q => S[i] / st.L > q[0] && S[i] / st.L < q[1])) break;
    }
    ctx.stroke();
  }
}
function pathPoly(poly, dx = 0, dy = 0) { ctx.beginPath(); ctx.moveTo(poly[0][0] + dx, poly[0][1] + dy); for (let i = 1; i < poly.length; i++) ctx.lineTo(poly[i][0] + dx, poly[i][1] + dy); ctx.closePath(); }
function washDraw(w, aMul, dx = 0, dy = 0) {
  const L = w.layers.length;
  for (let l = 0; l < L; l++) { ctx.fillStyle = rgba(w.col, w.a * aMul / L * (1.25 - l * .15)); pathPoly(w.layers[l], dx, dy); ctx.fill(); }
  ctx.strokeStyle = rgba(mix3(w.col, [60, 50, 40], .2), w.a * aMul * .32); ctx.lineWidth = 1.6 * curWmul; pathPoly(w.layers[L - 1], dx, dy); ctx.stroke();
}
const visible = (bb, V) => !(bb[2] < V[0] || bb[0] > V[2] || bb[3] < V[1] || bb[1] > V[3]) && (Math.max(bb[2] - bb[0], bb[3] - bb[1]) * curS > .8);
function viewBox(M) { const I = inv(M); let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9; for (const p of [[0, 0], [SW, 0], [0, SH], [SW, SH]]) { const [x, y] = ap(I, p); x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); } return [x0, y0, x1, y1]; }
const setM = M => ctx.setTransform(M[0], M[1], M[2], M[3], M[4], M[5]);
const wmulOf = s => s > 1 ? Math.pow(s, -.7) : 1;

function noisyCircle(cx, cy, R, amp, seed, n = 96) { const P = []; for (let i = 0; i < n; i++) { const a = i / n * TAU, r = R * (1 + (fbm(Math.cos(a) * 1.6 + 5, Math.sin(a) * 1.6 + 5, seed, 3) - .5) * 2 * amp); P.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); } return P; }
const MINI_EDGE = noisyCircle(A.center[0], A.center[1], rcA, .07, 41);

function discPath(l) { if (l.k === 'B') { ctx.beginPath(); ctx.arc(0, 0, B.R, 0, TAU); } else pathPoly(MINI_EDGE); }

// --- A：地下室 ---
function drawA(i, l, t, V) {
  const live = i === 0;
  for (const s of AS) { if (!visible(s.bb, V)) continue; const p = live ? seg(t, s.t0, s.t0 + s.dur) : 1; strokeDraw(s.st, p, s.col, s.alpha); }
  const np = live ? seg(t, T.note[0], T.note[1]) : 1;
  if (np > 0 && 46 * curS > 1.5) handwrite(ctx, '地下室', 120, 1000, 46, np, { font: 'Long Cang' });
  if (i >= 2 && t > T.title[0] && 120 * curS > 2) {
    handwrite(ctx, '阿莱夫', 128, 640, 124, seg(t, T.title[0], T.title[1]), { font: 'Long Cang' });
    handwrite(ctx, '包含一切的一点', 134, 724, 50, seg(t, T.sub[0], T.sub[1]), { font: 'Long Cang', alpha: .8 });
  }
}
function sphereBorn(i, t) { return i === 0 ? ss(seg(t, T.born, T.born + .35)) : 1; }
function sphereUnder(i, t) {   // 子层之前：纸色的光晕（留白）
  const a = sphereBorn(i, t); if (a <= 0) return;
  const [x, y] = A.sphere, r = A.rS, g = ctx.createRadialGradient(x, y, r * .9, x, y, r * 2.6);
  g.addColorStop(0, `rgba(255,253,246,${.92 * a})`); g.addColorStop(1, 'rgba(255,253,246,0)');
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 2.6, 0, TAU); ctx.fill();
}
function sphereOver(i, t) {
  const a = sphereBorn(i, t); if (a <= 0) return;
  const [x, y] = A.sphere, r = A.rS * (i === 0 ? lerp(.3, 1, a) : 1), sr = r * curS;
  const swirl = i === 0 ? a * (1 - ss(seg(t, 5.4, 7.2))) : (t > 18 ? lerp(.85, .55, seg(t, 18, 19.5)) : .85);
  const big = 1 - .8 * ss((sr - 140) / 420);          // 镜头进到球里时，球面的釉色退开
  ctx.save(); ctx.beginPath(); ctx.arc(x, y, r * 1.04, 0, TAU); ctx.clip();
  ctx.globalCompositeOperation = 'multiply';
  ctx.translate(x, y); ctx.scale(r / A.rS, r / A.rS); ctx.translate(-x, -y);
  if (swirl > 0) {   // 球里流转的颜色：几块湿的水彩
    ctx.save(); ctx.translate(x, y); ctx.rotate(t * .5); ctx.translate(-x, -y);
    for (const w of SPW.swirl) washDraw(w, swirl);
    ctx.restore();
  }
  for (const w of SPW.rim) washDraw(w, a * big);
  for (const w of SPW.shade) washDraw(w, a * big);
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = `rgba(252,249,240,${.85 * a * big})`; pathPoly(SPW.hi); ctx.fill();
  ctx.restore();
  // 轮廓与光线
  const ow = curWmul; curWmul = ow;
  if (i === 0) { const p = seg(t, T.born, T.born + .4); if (p > 0) strokeDraw(SPH, p, INK, .9); } else strokeDraw(SPH, 1, INK, .9);
  if (sr < 120) {
    const f = Math.floor(t * 12), fade = clamp((120 - sr) / 60) * a;
    for (let k = 0; k < 14; k++) {
      if (H(f * 3 + k) < .3) continue;
      const an = k / 14 * TAU + H(k) * .2, r0 = r * (1.35 + H(f + k * 5) * .2), r1 = r * (1.75 + H(k + 9) * .4);
      ctx.strokeStyle = rgba(INK, .7 * fade); ctx.lineWidth = Math.max(.9 / curS, 1.1 * curWmul); ctx.beginPath(); ctx.moveTo(x + Math.cos(an) * r0, y + Math.sin(an) * r0); ctx.lineTo(x + Math.cos(an) * r1, y + Math.sin(an) * r1); ctx.stroke();
    }
  }
  if (i === 0) {   // 3.75 秒的一次闪光
    const g = seg(t, T.glint - .1, T.glint + .5); if (g > 0 && g < 1) {
      const k = Math.sin(g * Math.PI), st = sparkle(x - r * .4, y - r * .45, r * 1.5 * k, .2);
      ctx.fillStyle = `rgba(255,253,246,${.95 * k})`; pathPoly(st); ctx.fill(); ctx.strokeStyle = rgba(INK, .8 * k); ctx.lineWidth = Math.max(.8 / curS, 1.2 * curWmul); pathPoly(st); ctx.stroke();
    }
  }
}

// --- B：阿莱夫里 ---
function colourR(i, t) { if (i !== 1) return 1200; const a = 1150 * ss(seg(t, T.colour[0], T.colour[1])), d = 1 - ss(seg(t, T.drain[0], T.drain[1])); return a * d; }
function inkP(i, s, t) { return i === 1 ? seg(t, s.t0, s.t0 + s.dur) : 1; }
function drawB(i, l, t, V) {
  const f = Math.floor(t * 12), R = colourR(i, t);
  if (R > 2) {
    const edge = noisyCircle(0, 0, R, .09, 9 + (i === 1 ? 0 : 3), 64);
    ctx.save(); pathPoly(edge); ctx.clip(); ctx.globalCompositeOperation = 'multiply';
    for (const w of BW) { if (!visible(w.bb, V)) continue; const dx = (H(f * 13 + w.id) - .5) * 1.4, dy = (H(f * 17 + w.id) - .5) * 1.4; washDraw(w, 1, dx, dy); }
    ctx.globalCompositeOperation = 'source-over'; ctx.fillStyle = 'rgba(250,247,238,.9)'; for (const r of BRes) { pathPoly(r); ctx.fill(); }
    ctx.restore();
    if (R < 1140 && i === 1) {   // 湿的前沿：前沿后面一圈颜色更深
      const inner = noisyCircle(0, 0, Math.max(0, R - 38), .09, 9, 64);
      ctx.save(); ctx.beginPath(); for (const P of [edge, inner.slice().reverse()]) { ctx.moveTo(P[0][0], P[0][1]); for (const p of P) ctx.lineTo(p[0], p[1]); ctx.closePath(); } ctx.clip('evenodd');
      ctx.globalCompositeOperation = 'multiply'; for (const w of BW) { if (!visible(w.bb, V)) continue; washDraw(w, .55); } ctx.restore();
    }
  }
  for (const s of BS) {
    if (!visible(s.bb, V)) continue; const p = inkP(i, s, t); if (p <= 0) continue;
    const dx = (H(f * 13 + s.id) - .5) * 1.3, dy = (H(f * 29 + s.id) - .5) * 1.3;
    strokeDraw(s.st, p, s.col, s.alpha, dx, dy);
  }
}

function drawLevel(L, i, t, root) {
  const l = L[i], M = l.M; curS = scl(M); curWmul = wmulOf(curS);
  ctx.save(); setM(M);
  if (!root) { discPath(l); ctx.clip(); ctx.fillStyle = rgba(PAPER); discPath(l); ctx.fill(); }
  const V = viewBox(M);
  if (l.k === 'A') drawA(i, l, t, V); else drawB(i, l, t, V);
  const child = L[i + 1];
  if (l.k === 'A') sphereUnder(i, t);
  if (child && discR(child) > 1.2 && (l.k === 'B' || sphereBorn(i, t) > .5)) drawLevel(L, i + 1, t, false);
  curS = scl(M); curWmul = wmulOf(curS); setM(M);
  if (l.k === 'A') sphereOver(i, t);
  ctx.restore();
}

// ---------- 纸 ----------
function tileNoise(N, P, seed, oct) {   // 可平铺的值噪声
  const g = (x, y, s) => { x = ((x % P) + P) % P; y = ((y % P) + P) % P; const n = Math.sin(x * 127.1 + y * 311.7 + s * 74.7) * 43758.5453; return n - Math.floor(n); };
  const out = new Float32Array(N * N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    let a = 0, w = .5, f = 1, tot = 0;
    for (let o = 0; o < oct; o++) { const x = i / N * P * f, y = j / N * P * f, xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi, u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), pp = P * f;
      const G = (X, Y) => { X = ((X % pp) + pp) % pp; Y = ((Y % pp) + pp) % pp; const n = Math.sin(X * 127.1 + Y * 311.7 + (seed + o) * 74.7) * 43758.5453; return n - Math.floor(n); };
      const A_ = G(xi, yi), B_ = G(xi + 1, yi), C_ = G(xi, yi + 1), D_ = G(xi + 1, yi + 1);
      a += w * (A_ + (B_ - A_) * u + (C_ - A_) * v + (A_ - B_ - C_ + D_) * u * v); tot += w; w *= .5; f *= 2; }
    out[j * N + i] = a / tot;
  }
  return out;
}
function texCanvas(N, fn) { const c = document.createElement('canvas'); c.width = c.height = N; const g = c.getContext('2d'), im = g.createImageData(N, N); for (let i = 0; i < N * N; i++) { const [r, gg, b] = fn(i); im.data[i * 4] = r; im.data[i * 4 + 1] = gg; im.data[i * 4 + 2] = b; im.data[i * 4 + 3] = 255; } g.putImageData(im, 0, 0); return c; }
const toothN = tileNoise(256, 64, 3, 2), mottN = tileNoise(512, 4, 8, 3);
const tooth = texCanvas(256, i => { const v = 255 - Math.max(0, (toothN[i] - .5)) * 36 - (H(i) < .01 ? 10 : 0); return [v, v * .995, v * .985]; });
const mott = texCanvas(512, i => { const v = 255 - (mottN[i]) * 17; return [v, v * .993, v * .975]; });
const toothP = ctx.createPattern(tooth, 'repeat'), mottP = ctx.createPattern(mott, 'repeat');
function paper(t) {
  const c = cam(t), L = Math.log2(c.z) + 12, f = L - Math.floor(L), ox = c.ox + SW / 2, oy = c.oy + SH / 2;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = 'multiply';
  for (const [k, w] of [[Math.pow(2, f), 1 - f], [Math.pow(2, f - 1), f]]) {
    const s = 1.6 * k, co = Math.cos(c.roll) * s, si = Math.sin(c.roll) * s;
    mottP.setTransform(new DOMMatrix([co, si, -si, co, ox, oy])); ctx.globalAlpha = w; ctx.fillStyle = mottP; ctx.fillRect(0, 0, SW, SH);
  }
  ctx.globalAlpha = .55; ctx.fillStyle = toothP; ctx.fillRect(0, 0, SW, SH);
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  // 纸边：四周一点点暗角
  const g = ctx.createRadialGradient(SW / 2, SH / 2, SH * .55, SW / 2, SH / 2, SW * .62); g.addColorStop(0, 'rgba(120,100,70,0)'); g.addColorStop(1, 'rgba(120,100,70,.10)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, SW, SH);
}

export function render(t) {
  const L = levels(t);
  let root = 0; for (let i = 1; i < L.length; i++) if (covers(L[i])) root = i;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
  ctx.fillStyle = rgba(PAPER); ctx.fillRect(0, 0, SW, SH);
  drawLevel(L, root, t, true);
  paper(t);
}

// ---------- 给混音和检查用 ----------
export function events() {
  const EV = [];
  for (const s of AS) EV.push({ t: +s.t0.toFixed(4), type: 'pen', dur: +s.dur.toFixed(4), len: Math.round(s.st.L), pan: +(((s.bb[0] + s.bb[2]) / 2 / A.W) * 2 - 1).toFixed(2) });
  for (const s of BS) EV.push({ t: +s.t0.toFixed(4), type: 'pen', dur: +s.dur.toFixed(4), len: Math.round(s.st.L * .55), pan: +clamp(((s.bb[0] + s.bb[2]) / 2) * .55 / 960, -1, 1).toFixed(2), b: 1 });
  EV.push({ t: T.note[0], type: 'write', dur: T.note[1] - T.note[0], pan: -.8 });
  EV.push({ t: T.title[0], type: 'write', dur: T.title[1] - T.title[0], pan: -.7 }, { t: T.sub[0], type: 'write', dur: T.sub[1] - T.sub[0], pan: -.7 });
  return EV.sort((a, b) => a.t - b.t);
}
export function texts(t) {
  const L = levels(t), out = [];
  let root = 0; for (let i = 1; i < L.length; i++) if (covers(L[i])) root = i;
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  const box = (M, id, text, x, y, size, p) => { if (p <= 0) return; const s = scl(M); if (size * s < 16) return; ctx.font = `400 ${size}px 'Long Cang'`; const w = ctx.measureText(text).width; const P = [[x, y - size], [x + w, y - size], [x, y + size * .3], [x + w, y + size * .3]].map(q => ap(M, q)); out.push({ id, text, x0: Math.min(...P.map(q => q[0])), y0: Math.min(...P.map(q => q[1])), x1: Math.max(...P.map(q => q[0])), y1: Math.max(...P.map(q => q[1])) }); };
  for (let i = root; i < L.length; i++) {
    const l = L[i]; if (l.k !== 'A') continue;
    box(l.M, 'note' + i, '地下室', 120, 1000, 46, i === 0 ? seg(t, T.note[0], T.note[1]) : 1);
    if (i >= 2 && t > T.title[0]) { box(l.M, 'title', '阿莱夫', 128, 640, 124, 1); box(l.M, 'sub', '包含一切的一点', 134, 724, 50, t > T.sub[0] ? 1 : 0); }
  }
  ctx.restore();
  return out;
}
