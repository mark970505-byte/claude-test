// 两张"页"：A = 地下室速写（只有线条，小球是唯一的颜色）；B = 阿莱夫里的跨页（所有景象同时）。
// 每张页返回 { strokes: [{pts, w, t0?, order}], washes: [{poly, col, a}], texts: [...] }，坐标是页自己的坐标。
import { TAU, ellipse, hex } from './engine.js';

// ---------- 小工具 ----------
export const arc = (cx, cy, rx, ry, a0, a1, n = 24) => [...Array(n + 1)].map((_, i) => { const a = a0 + (a1 - a0) * i / n; return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]; });
export const circ = (cx, cy, r, n = 28) => arc(cx, cy, r, r, -Math.PI / 2, -Math.PI / 2 + TAU, n);
export const rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
const rectPoly = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
const wave = (x0, x1, y, amp, f, ph = 0, n = 30) => [...Array(n + 1)].map((_, i) => { const x = x0 + (x1 - x0) * i / n; return [x, y + Math.sin(x * f + ph) * amp]; });
function H(i) { const n = Math.sin(i * 91.17 + 7.3) * 43758.5453; return n - Math.floor(n); }

function page() {
  const S = [], W = [];
  return {
    S, W,
    ln(pts, w = 1, o = {}) { S.push({ pts, w, ...o }); },
    wash(poly, col, a = .5, o = {}) { W.push({ poly, col: typeof col === 'string' ? hex(col) : col, a, ...o }); },
  };
}

// ================= A：地下室 =================
export const A = { W: 1920, H: 1080, F: 860, sphere: [1000, 632], rS: 18, center: [960, 540] };

export function cellar() {
  const p = page(), F = A.F, x0 = 260, y0 = 110, run = 40, rise = 30, N = 25;
  // 楼梯：从上往下按笔顺，每段三四级一笔
  let k = 1;
  while (k <= N) {
    const pts = [];
    const kEnd = Math.min(N, k + 3);
    for (let j = k; j <= kEnd; j++) {
      const tx = x0 + (j - 1) * run, ty = y0 + (j - 1) * rise;
      if (j === k) pts.push([tx - 2, ty]);
      pts.push([tx + run, ty]); pts.push([tx + run, ty + rise]);
    }
    p.ln(pts, 2.5, { smooth: false, group: 0 });
    k = kEnd + 1;
  }
  const nose = x => y0 + (x - x0) * .75;
  p.ln([[x0 - 30, nose(x0) + 34 - 22], [1205, F]], 2.2, { group: 0 });                       // 斜梁
  p.ln([[x0 - 10, nose(x0) + 72], [1150, F - 4]], 1.6, { group: 0, alpha: .75 });              // 梁底
  // 扶手 + 立柱
  p.ln([[x0 + 30, y0 - 62], [1250, nose(1250) - 70]], 2.2, { group: 1 });
  p.ln([[1250, nose(1250) - 76], [1252, F]], 2.4, { group: 1 });
  p.ln([[1262, nose(1250) - 72], [1263, F]], 1.6, { group: 1 });
  for (let j = 3; j <= 23; j += 2) {
    const x = x0 + (j - .5) * run, ty = y0 + (j - 1) * rise;
    p.ln([[x, ty], [x + 1, nose(x) - 66]], 1.3, { group: 1, alpha: .85 });
  }
  // 天花板与楼板开口
  p.ln([[60, 38], [210, 40]], 2.2, { group: 2 }); p.ln([[480, 40], [1880, 36]], 2.2, { group: 2 });
  p.ln([[70, 72], [205, 74]], 1.5, { group: 2 }); p.ln([[485, 74], [1870, 70]], 1.5, { group: 2 });
  for (let x = 90; x < 1860; x += 46) if (x < 200 || x > 500) p.ln([[x, 42], [x + 14, 70]], 1, { group: 2, alpha: .6 });
  p.ln([[210, 40], [212, 74]], 1.6, { group: 2 }); p.ln([[480, 40], [482, 74]], 1.6, { group: 2 });
  for (let i = 0; i < 4; i++) p.ln([[260 + i * 52, 8], [228 + i * 52, 64]], 1, { group: 2, alpha: .5 });   // 开口漏下来的光
  // 灯泡
  p.ln([[1480, 72], [1481, 214]], 1.3, { group: 3 });
  p.ln(rect(1472, 214, 1490, 232), 1.6, { group: 3, smooth: false });
  p.ln([[1474, 232], [1462, 250], [1460, 268], [1470, 284], [1481, 288], [1492, 284], [1501, 268], [1499, 250], [1488, 232]], 1.6, { group: 3 });
  for (let i = 0; i < 7; i++) { const a = -.2 + i / 6 * (Math.PI + .4); p.ln([[1481 + Math.cos(a) * 34, 262 + Math.sin(a) * 34], [1481 + Math.cos(a) * 50, 262 + Math.sin(a) * 50]], 1, { group: 3, alpha: .6 }); }
  // 架子、罐子、瓶子
  p.ln([[1590, 380], [1880, 378]], 2, { group: 4 }); p.ln([[1594, 388], [1878, 386]], 1, { group: 4 });
  p.ln([[1590, 528], [1880, 526]], 2, { group: 4 }); p.ln([[1594, 536], [1878, 534]], 1, { group: 4 });
  for (const x of [1630, 1820]) { p.ln([[x, 388], [x + 24, 412]], 1.2, { group: 4 }); p.ln([[x, 536], [x + 24, 560]], 1.2, { group: 4 }); }
  for (const [x, w, h] of [[1612, 46, 54], [1676, 38, 40], [1730, 52, 62]]) { p.ln([[x, 378], [x, 378 - h], [x + w, 378 - h], [x + w, 378]], 1.5, { group: 4, smooth: false }); p.ln(arc(x + w / 2, 378 - h, w / 2, 5, 0, TAU, 14), 1, { group: 4 }); }
  for (const [x, h] of [[1620, 92], [1650, 80], [1694, 104], [1760, 70], [1800, 96]]) p.ln([[x, 526], [x, 526 - h * .55], [x + 5, 526 - h * .75], [x + 5, 526 - h], [x + 13, 526 - h], [x + 13, 526 - h * .75], [x + 18, 526 - h * .55], [x + 18, 526]], 1.4, { group: 4, smooth: false });
  // 砖墙（只给几块）
  const bricks = (bx, by, cols, rows, seed) => { for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) { if (H(seed + r * 7 + c) < .45) continue; const x = bx + c * 70 + (r % 2) * 35, y = by + r * 30; p.ln([[x, y], [x + 62, y + 1], [x + 62, y + 24]], 1, { group: 5, alpha: .55, smooth: false }); } };
  bricks(1130, 230, 5, 6, 3); bricks(1500, 640, 4, 4, 11); bricks(80, 150, 2, 4, 21);
  // 箱子
  p.ln([[1720, 762], [1860, 760], [1862, 860]], 1.8, { group: 6, smooth: false }); p.ln([[1720, 762], [1718, 860]], 1.8, { group: 6 });
  p.ln([[1722, 812], [1860, 810]], 1.1, { group: 6 }); p.ln([[1724, 764], [1858, 858]], 1, { group: 6, alpha: .7 });
  // 躺着的人：仰面，头枕一卷麻袋，望向第十九级台阶
  p.ln(ellipse(1316, 846, 34, 11, 16), 1.4, { group: 7 });
  p.ln(circ(1334, 820, 17, 18), 1.7, { group: 7 });
  p.ln([[1340, 803], [1346, 798], [1343, 806]], 1.1, { group: 7, smooth: false });                     // 鼻尖
  p.ln([[1351, 826], [1380, 824], [1430, 820], [1488, 826]], 1.8, { group: 7 });                       // 胸背上沿
  p.ln([[1352, 840], [1420, 846], [1490, 846]], 1.7, { group: 7 });
  p.ln([[1372, 828], [1405, 806], [1442, 820]], 1.5, { group: 7 });                                    // 手臂搭在胸口
  p.ln([[1488, 826], [1560, 784], [1628, 846]], 1.8, { group: 7 }); p.ln([[1490, 846], [1562, 800], [1612, 848]], 1.5, { group: 7 });   // 屈起的腿
  p.ln([[1490, 840], [1600, 846], [1690, 848]], 1.8, { group: 7 }); p.ln([[1690, 836], [1702, 846], [1690, 852]], 1.4, { group: 7 });
  // 地面
  p.ln([[80, F + 2], [700, F]], 2.2, { group: 8 }); p.ln([[690, F], [1300, F + 1]], 2.2, { group: 8 }); p.ln([[1290, F + 1], [1890, F - 2]], 2.2, { group: 8 });
  for (let i = 0; i < 9; i++) { const x = 160 + i * 190 + H(i) * 60; p.ln([[x, 892 + H(i + 3) * 40], [x + 60 + H(i + 5) * 70, 896 + H(i + 3) * 40]], 1, { group: 8, alpha: .45 }); }
  // 小球的轮廓与"光线"另画（film.js），这里给它脚下的一笔投影
  p.ln([[A.sphere[0] - 22, 650 - 3], [A.sphere[0] + 26, 650 - 2]], 1.1, { group: 9, alpha: .7 });
  return p;
}

// ================= B：阿莱夫里的跨页 =================
export const B = { R: 1000, rc: 110, phi: 150 * Math.PI / 180 };
const C = {
  sea: '#7fa6b8', sky: '#9fbcd6', gold: '#e2b04a', dawn: '#e9b27a', red: '#c9573f', rust: '#b8483e', violet: '#7d6f9c', shadow: '#8b93a6',
  sand: '#e3cf9a', stone: '#d8c6a0', brass: '#c8a86b', leaf: '#7fa04a', lawn: '#c3c96f', grape: '#6b4f8a', tiger: '#d98a3a', horse: '#8a5a3c',
  night: '#3d3a4a', teal: '#4f9a92', rose: '#c4506a', iris: '#6f8f6a', cream: '#efe0b6', terra: '#c9734f',
};

// 每个景象画在 [-100,100] 的框里，y 向下；返回 page
const V = {
  sea() { // 同时的黎明与黄昏，海
    const p = page();
    p.wash([[-96, -70], [0, -78], [0, 0], [-96, 0]], C.dawn, .5); p.wash([[0, -78], [96, -66], [96, 0], [0, 0]], C.red, .42);
    p.wash([[-98, 0], [98, 0], [92, 62], [-90, 66]], C.sea, .55);
    p.wash(arc(-52, 0, 20, 20, Math.PI, TAU, 14), C.gold, .75); p.wash(arc(54, 0, 18, 18, Math.PI, TAU, 14), C.rust, .7);
    p.ln([[-98, 0], [98, 1]], 1.6);
    p.ln(arc(-52, 0, 20, 20, Math.PI, TAU, 14), 1.4); p.ln(arc(54, 0, 18, 18, Math.PI, TAU, 14), 1.4);
    for (let i = 0; i < 6; i++) { const a = Math.PI + (i + .5) / 6 * Math.PI; p.ln([[-52 + Math.cos(a) * 26, Math.sin(a) * 26], [-52 + Math.cos(a) * 36, Math.sin(a) * 36]], 1, { alpha: .8 }); }
    for (let i = 0; i < 5; i++) p.ln(wave(-90 + i * 6, 90 - i * 8, 12 + i * 11, 2.5 - i * .3, .18, i * 2), 1.1, { alpha: .9 - i * .1 });
    p.ln([[-20, -42], [-14, -38], [-8, -43]], 1, { smooth: false }); p.ln([[10, -52], [15, -48], [21, -53]], 1, { smooth: false });
    return p;
  },
  pyramid() { // 黑色金字塔中心的银色蛛网
    const p = page();
    p.wash([[-84, 62], [0, -82], [18, 62]], C.night, .62); p.wash([[18, 62], [0, -82], [84, 62]], C.night, .85);
    p.wash(circ(0, 12, 34, 20), [255, 255, 255], .0);
    p.ln([[-84, 62], [0, -82], [84, 62], [-84, 62]], 1.8, { smooth: false }); p.ln([[0, -82], [18, 62]], 1.3);
    for (let i = 0; i < 8; i++) { const a = i / 8 * TAU; p.ln([[0, 12], [Math.cos(a) * 30, 12 + Math.sin(a) * 30]], .9, { col: 'silver' }); }
    for (const r of [9, 17, 26]) p.ln([...Array(9)].map((_, i) => [Math.cos(i / 8 * TAU) * r, 12 + Math.sin(i / 8 * TAU) * r]), .8, { col: 'silver', smooth: false });
    p.ln([[-96, 64], [96, 64]], 1.2, { alpha: .7 });
    p.reserve = [circ(0, 12, 33, 20)];
    return p;
  },
  globe() { // 两面镜子之间无穷复制的地球仪
    const p = page();
    for (const s of [-1, 1]) { p.wash(rectPoly(s * 58, -72, s * 96, 72), C.sky, .3); p.ln(rect(Math.min(s * 58, s * 96), -72, Math.max(s * 58, s * 96), 72), 1.5, { smooth: false }); }
    const g = (x, r, a) => { p.wash(circ(x, -6, r, 18), C.sky, .55 * a); p.wash(ellipse(x - r * .25, -6 - r * .15, r * .45, r * .3, 10), C.lawn, .7 * a); p.ln(circ(x, -6, r, 22), Math.max(.5, r / 26), { alpha: a }); p.ln(arc(x, -6, r * .45, r, -Math.PI / 2, Math.PI / 2, 12), Math.max(.4, r / 40), { alpha: a }); p.ln([[x - r, -6], [x + r, -6]], Math.max(.4, r / 40), { alpha: a }); };
    g(0, 34, 1); p.ln([[0, 28], [0, 50], [-18, 56], [18, 56]], 1.5, { smooth: false }); p.ln(arc(0, -6, 42, 42, -2.2, .9, 16), 1.2);
    for (let i = 0; i < 4; i++) { const r = 14 * Math.pow(.62, i), off = 66 + i * 9; g(-off - 6, r, 1 - i * .18); g(off + 6, r, 1 - i * .18); }
    return p;
  },
  labyrinth() { // 破碎的迷宫
    const p = page();
    p.wash(circ(0, 0, 88, 26), C.stone, .45); p.wash(circ(0, 0, 16, 14), C.rust, .55);
    [22, 42, 62, 82].forEach((r, i) => { const g = H(i + 4) * TAU; p.ln(arc(0, 0, r, r, g + .5, g + TAU - .3, 30), 1.4); p.ln(arc(0, 0, r, r, g + .1, g + .3, 3), 1.4); });
    for (let i = 0; i < 7; i++) { const a = H(i + 20) * TAU, r0 = 22 + (i % 3) * 20; p.ln([[Math.cos(a) * r0, Math.sin(a) * r0], [Math.cos(a) * (r0 + 20), Math.sin(a) * (r0 + 20)]], 1.3); }
    return p;
  },
  eye() { // 无数注视我的眼睛
    const p = page();
    const e = (x, y, s, w) => { p.wash(circ(x, y, 22 * s, 16), C.iris, .65); p.wash(circ(x, y, 9 * s, 10), C.night, .9);
      p.ln(arc(x, y + 34 * s, 70 * s, 62 * s, -Math.PI * .82, -Math.PI * .18, 18), w); p.ln(arc(x, y - 34 * s, 70 * s, 62 * s, Math.PI * .18, Math.PI * .82, 18), w);
      p.ln(circ(x, y, 22 * s, 18), w * .8); for (let i = 0; i < 6; i++) { const a = -Math.PI * .78 + i / 5 * Math.PI * .56; p.ln([[x + Math.cos(a) * 70 * s, y + 34 * s + Math.sin(a) * 62 * s], [x + Math.cos(a) * 80 * s, y + 34 * s + Math.sin(a) * 72 * s]], w * .7); } };
    e(0, 0, 1, 1.6); e(-64, -64, .3, .9); e(66, -60, .28, .9); e(-70, 62, .26, .9); e(64, 66, .3, .9);
    return p;
  },
  astrolabe() { // 波斯星盘
    const p = page();
    p.wash(circ(0, 6, 80, 28), C.brass, .55); p.wash(circ(0, 6, 64, 24), C.gold, .25);
    p.ln(circ(0, 6, 80, 32), 1.7); p.ln(circ(0, 6, 68, 30), 1.1);
    for (let i = 0; i < 24; i++) { const a = i / 24 * TAU; p.ln([[Math.cos(a) * 68, 6 + Math.sin(a) * 68], [Math.cos(a) * 78, 6 + Math.sin(a) * 78]], .8, { alpha: .8 }); }
    p.ln(circ(0, -76, 9, 12), 1.4); p.ln(arc(18, 6, 46, 46, -2.2, 2.2, 20), 1.1);
    for (let i = 0; i < 5; i++) { const a = i / 5 * TAU + .3; p.ln([[0, 6], [Math.cos(a) * 30, 6 + Math.sin(a) * 30], [Math.cos(a + .25) * 52, 6 + Math.sin(a + .25) * 52]], 1); }
    p.ln([[-74, 30], [74, -18]], 1.6);
    return p;
  },
  tiger() {
    const p = page();
    const body = [[-62, -18], [-30, -30], [20, -30], [52, -22], [60, 4], [44, 22], [-40, 22], [-64, 6]];
    p.wash(body, C.tiger, .62); p.wash(circ(70, -14, 21, 14), C.tiger, .62); p.wash([[-40, 14], [40, 14], [36, 22], [-36, 22]], [255, 255, 255], .0);
    p.ln([...body, body[0]], 1.7); p.ln(circ(70, -14, 21, 16), 1.6);
    p.ln([[60, -32], [64, -42], [70, -34]], 1.2, { smooth: false }); p.ln([[76, -34], [82, -42], [85, -30]], 1.2, { smooth: false });
    p.ln([[84, -12], [92, -10], [86, -6]], 1, { smooth: false });
    for (const [a, b] of [[[-46, 18], [-52, 62]], [[-28, 20], [-22, 62]], [[28, 20], [22, 62]], [[44, 16], [54, 60]]]) { p.ln([a, b], 1.8); p.ln([b, [b[0] + 8, b[1]]], 1.4); }
    p.ln([[-62, -12], [-84, -36], [-96, -22]], 1.5);
    for (let i = 0; i < 8; i++) { const x = -48 + i * 13; p.ln([[x, -29], [x + 4, -16], [x - 1, -4]], 1.6, { col: 'dark' }); }
    return p;
  },
  horses() { // 里海海滩上鬃毛飞扬的马
    const p = page();
    p.wash([[-98, -80], [98, -80], [98, -34], [-98, -30]], C.dawn, .4); p.wash([[-98, -30], [98, -34], [98, -10], [-98, -6]], C.sea, .55); p.wash([[-98, -6], [98, -10], [96, 74], [-96, 74]], C.sand, .5);
    p.ln([[-98, -30], [98, -34]], 1.2); p.ln(wave(-96, 96, -8, 2, .2, 1), 1, { alpha: .8 });
    const horse = (x, y, s) => {
      const Q = pts => pts.map(([u, v]) => [x + u * s, y + v * s]);
      const body = [[-42, -8], [-20, -14], [24, -14], [34, -24], [46, -42], [52, -50], [54, -42], [70, -30], [66, -24], [56, -26], [42, -12], [38, 6], [-28, 10], [-44, 2]];
      p.wash(Q(body), C.horse, .65);
      p.ln(Q([...body, body[0]]), 1.5 * s);
      for (const L of [[[32, 6], [46, 18], [58, 14]], [[26, 8], [20, 24], [28, 36]], [[-26, 8], [-40, 22], [-54, 22]], [[-34, 6], [-28, 22], [-36, 36]]]) p.ln(Q(L), 1.5 * s);
      for (let i = 0; i < 4; i++) p.ln(Q([[44 - i * 5, -40 + i * 7], [30 - i * 6, -46 + i * 8], [36 - i * 6, -54 + i * 8]]), 1.1 * s, { col: 'dark' });
      p.ln(Q([[-42, -6], [-60, -4], [-70, 10], [-62, 4]]), 1.3 * s, { col: 'dark' });
    };
    horse(-26, 6, .9); horse(38, 28, .62);
    return p;
  },
  ants() { // 地球上所有的蚂蚁
    const p = page();
    p.wash(circ(0, 0, 90, 24), C.stone, .3);
    p.wash([[-34, 72], [0, 40], [34, 72]], C.terra, .5); p.ln([[-38, 74], [-8, 42], [8, 42], [38, 74]], 1.4);
    let n = 0;
    for (let i = 0; i < 46; i++) {
      const a = i * .34, r = 12 + i * 1.75, x = Math.cos(a) * r, y = Math.sin(a) * r - 6, d = a + Math.PI / 2;
      const c = Math.cos(d), s = Math.sin(d), q = (u, v) => [x + c * u - s * v, y + s * u + c * v];
      p.ln([q(-4, 0), q(4, 0)], 2.4, { col: 'dark', smooth: false, over: 0 });
      p.ln([q(-2, -3), q(2, 3)], .6, { smooth: false, over: 0 }); p.ln([q(2, -3), q(-2, 3)], .6, { smooth: false, over: 0 }); n++;
    }
    return p;
  },
  tarot() { // 米尔扎布尔一家店橱窗里的塔罗牌
    const p = page();
    p.wash(rectPoly(-80, -86, 80, 86), C.sky, .28); p.ln(rect(-80, -86, 80, 86), 1.8, { smooth: false }); p.ln([[0, -86], [0, 86]], 1.1); p.ln([[-80, 0], [80, 0]], 1.1);
    const card = [[-30, -54], [26, -60], [36, 56], [-22, 62]];
    p.wash(card, C.cream, .65); p.wash([[-24, -46], [20, -51], [28, 48], [-16, 53]], C.rust, .3);
    p.ln([...card, card[0]], 1.5, { smooth: false });
    const sx = 3, sy = 0; const star = [...Array(11)].map((_, i) => { const a = i / 10 * TAU - Math.PI / 2, r = i % 2 ? 9 : 22; return [sx + Math.cos(a) * r, sy + Math.sin(a) * r]; });
    p.wash(star, C.gold, .8); p.ln(star, 1.2, { smooth: false });
    p.ln([[-60, 70], [-40, 70]], 1, { alpha: .6 }); p.ln([[50, -70], [66, -70]], 1, { alpha: .6 });
    return p;
  },
  hand() { // 一只手精巧的骨骼
    const p = page();
    p.wash(ellipse(0, 18, 58, 70, 20), C.shadow, .22);
    for (let i = 0; i < 6; i++) p.ln(circ(-18 + (i % 3) * 18, 54 + (i / 3 | 0) * 14, 7, 10), 1);
    const fing = [[-44, 30, -2.05, [26, 20, 14]], [-22, 36, -1.78, [36, 24, 16]], [0, 38, -1.57, [40, 26, 18]], [20, 36, -1.36, [36, 24, 16]], [38, 34, -1.15, [30, 20, 14]]];
    for (const [x, y, a, L] of fing) { let px = x, py = y; const c = Math.cos(a), s = Math.sin(a);
      for (const l of [26, ...L]) { const nx = px + c * l, ny = py + s * l; p.ln([[px, py], [nx, ny]], 1.6); p.ln(circ(nx, ny, 2.5, 6), .8); px = nx + c * 3; py = ny + s * 3; } }
    p.ln([[-10, 76], [-12, 98]], 1.6); p.ln([[12, 76], [14, 98]], 1.6);
    return p;
  },
  grapes() { // 葡萄、雪
    const p = page();
    p.wash([[-6, -60], [-44, -82], [-60, -54], [-24, -44]], C.leaf, .55); p.ln([[-6, -60], [-44, -82], [-60, -54], [-24, -44], [-6, -60]], 1.2);
    p.ln([[0, -78], [-2, -50]], 1.6);
    const g = [[0, -40], [-16, -34], [16, -34], [-24, -18], [-6, -20], [12, -18], [28, -20], [-16, -2], [2, -2], [20, -4], [-8, 14], [10, 14], [0, 30]];
    for (const [x, y] of g) { p.wash(circ(x, y, 10, 10), C.grape, .6); p.ln(circ(x, y, 10, 12), 1); }
    for (let i = 0; i < 9; i++) { const x = -86 + H(i + 40) * 172, y = -86 + H(i + 60) * 172; if (Math.hypot(x, y + 10) < 52) continue; for (let k = 0; k < 3; k++) { const a = k / 3 * Math.PI; p.ln([[x - Math.cos(a) * 6, y - Math.sin(a) * 6], [x + Math.cos(a) * 6, y + Math.sin(a) * 6]], .8, { smooth: false, over: 0 }); } }
    return p;
  },
  fern() { // 温室地板上蕨类斜斜的影子
    const p = page();
    p.wash([[-90, -40], [90, -40], [100, 80], [-100, 80]], C.terra, .3);
    for (let i = 0; i < 6; i++) p.ln([[-90 + i * 36, -40], [-100 + i * 40, 80]], .9, { alpha: .7 }); for (let j = 0; j < 4; j++) p.ln([[-92 - j * 2.5, -40 + j * 40], [92 + j * 2.5, -40 + j * 40]], .9, { alpha: .7 });
    const frond = (x, y, a, L, wash) => { const c = Math.cos(a), s = Math.sin(a); const pts = []; for (let i = 0; i <= 12; i++) { const u = i / 12 * L; pts.push([x + c * u + Math.sin(u * .05) * 6 * -s, y + s * u]); }
      if (wash) { for (let i = 1; i < 12; i++) { const [px, py] = pts[i], l = (1 - i / 12) * 22 + 4; p.wash(ellipse(px - s * l * .5, py + c * l * .5, l * .55, 3.5, 6, a + 1.1), C.violet, .4); p.wash(ellipse(px + s * l * .5, py - c * l * .5, l * .55, 3.5, 6, a - 1.1), C.violet, .4); } }
      else { p.ln(pts, 1.4); for (let i = 1; i < 12; i++) { const [px, py] = pts[i], l = (1 - i / 12) * 22 + 4; p.ln([[px, py], [px - s * l + c * l * .4, py + c * l + s * l * .4]], .9); p.ln([[px, py], [px + s * l + c * l * .4, py - c * l + s * l * .4]], .9); } } };
    frond(-60, 20, -.35, 130, true); frond(-40, 60, -.55, 110, true);
    frond(-70, -30, -1.2, 70, false);
    p.wash(ellipse(-70, -26, 12, 6, 10), C.leaf, .0);
    return p;
  },
  crowd() { // 美洲稠密的人群——胡萝卜小人
    const p = page();
    p.ln([[-96, -20], [-70, -22], [-66, -48], [-40, -48], [-38, -30], [-10, -32], [-6, -60], [20, -60], [22, -26], [60, -28], [62, -44], [96, -42]], 1.3, { smooth: false, alpha: .8 });
    p.wash([[-96, -20], [-66, -48], [-40, -48], [-10, -32], [-6, -60], [20, -60], [60, -28], [96, -42], [96, -12], [-96, -10]], C.shadow, .3);
    const cols = [C.rust, C.sky, C.gold, C.teal, C.violet, C.red, C.leaf];
    for (let i = 0; i < 34; i++) { const x = -90 + H(i + 100) * 180, y = -6 + H(i + 200) * 84, s = .6 + (y + 6) / 84 * .7;
      p.wash(ellipse(x, y, 5 * s, 9 * s, 8), cols[i % cols.length], .6); p.ln(circ(x, y - 13 * s, 2.6 * s, 6), .9 * s);
      p.ln([[x - 2 * s, y + 8 * s], [x - 3 * s, y + 20 * s]], .9 * s, { over: 0 }); p.ln([[x + 2 * s, y + 8 * s], [x + 3 * s, y + 20 * s]], .9 * s, { over: 0 }); }
    return p;
  },
  book() { // 普林尼的第一个英译本：每一页的每一个字母
    const p = page();
    const L = [[-90, -50], [-2, -58], [-2, 62], [-86, 68]], R = [[2, -58], [90, -50], [86, 68], [2, 62]];
    p.wash(L, C.cream, .55); p.wash(R, C.cream, .55); p.wash([[-94, 66], [-2, 60], [2, 60], [94, 66], [96, 74], [-96, 74]], C.rust, .55);
    p.ln([...L, L[0]], 1.4, { smooth: false }); p.ln([...R, R[0]], 1.4, { smooth: false });
    for (let side = -1; side <= 1; side += 2) for (let r = 0; r < 12; r++) { const y = -46 + r * 9, x0 = side < 0 ? -80 : 12, x1 = side < 0 ? -12 : 78; const pts = []; for (let x = x0; x <= x1; x += 3) pts.push([x, y + (H(x * 3 + r) - .5) * 3]); p.ln(pts, .55, { smooth: false, over: 0, alpha: .8 }); }
    return p;
  },
  rose() { // 克雷塔罗的落日映出孟加拉一朵玫瑰的颜色
    const p = page();
    p.wash(circ(0, 0, 86, 24), C.gold, .35); p.wash(arc(0, 30, 90, 70, Math.PI, TAU, 20), C.dawn, .4);
    p.wash(circ(0, -6, 34, 16), C.rose, .7);
    const sp = []; for (let i = 0; i < 70; i++) { const a = i * .3, r = 2 + i * .45; sp.push([Math.cos(a) * r, -6 + Math.sin(a) * r * .85]); } p.ln(sp, 1.2);
    p.ln([[0, 28], [4, 60], [0, 92]], 1.5); p.wash([[4, 56], [30, 44], [40, 58], [12, 64]], C.leaf, .6); p.ln([[4, 56], [30, 44], [40, 58], [12, 64], [4, 56]], 1);
    return p;
  },
};

const RING1 = ['sea', 'pyramid', 'globe', 'labyrinth', 'eye', 'astrolabe'];
const RING2 = ['tiger', 'horses', 'ants', 'tarot', 'hand', 'grapes', 'fern', 'crowd', 'book', 'rose'];

export function aleph() {
  const out = page(), items = [];
  const place = (name, R, ang, r, ring, idx) => {
    const v = V[name](), sc = r / 100, c = Math.cos(ang), s = Math.sin(ang), cx = Math.sin(ang) * R, cy = -Math.cos(ang) * R;
    const T = ([x, y]) => [cx + (x * c - y * s) * sc, cy + (x * s + y * c) * sc];
    const id = items.length; items.push({ name, cx, cy, r, ring });
    for (const st of v.S) out.S.push({ ...st, pts: st.pts.map(T), w: st.w * sc * 1.25, item: id, ring });
    for (const w of v.W) out.W.push({ ...w, poly: w.poly.map(T), item: id, j: (w.j ?? 5) * sc });
    if (v.reserve) out.reserves = (out.reserves || []).concat(v.reserve.map(pl => pl.map(T)));
  };
  RING1.forEach((n, i) => place(n, 300, i / RING1.length * TAU + .3, 108, 1, i));
  RING2.forEach((n, i) => place(n, 640, i / RING2.length * TAU + .05, 152, 2, i));
  // 大块的淡底色，把整页连起来
  const big = [C.sky, C.gold, C.rose, C.teal, C.dawn, C.violet];
  for (let i = 0; i < 6; i++) { const a = i / 6 * TAU + .2; out.wash(ellipse(Math.sin(a) * 520, -Math.cos(a) * 520, 300, 190, 18, a), big[i], .13, { j: 40, item: -1 }); }
  // 外圈：所有其余的东西，小到只剩一个记号
  const marks = [C.rust, C.sky, C.gold, C.teal, C.violet, C.leaf, C.rose];
  for (let i = 0; i < 90; i++) {
    const a = i / 90 * TAU + H(i) * .05, R = 850 + H(i + 300) * 110, x = Math.sin(a) * R, y = -Math.cos(a) * R, k = i % 6, s = 14 + H(i + 9) * 10;
    if (k === 0) out.ln(circ(x, y, s * .5, 10), 1.1, { item: -2 });
    else if (k === 1) out.ln(wave(x - s, x + s, y, 3, .5, i), 1, { item: -2 });
    else if (k === 2) { out.ln([[x - s * .6, y], [x + s * .6, y]], 1, { item: -2 }); out.ln([[x, y - s * .6], [x, y + s * .6]], 1, { item: -2 }); }
    else if (k === 3) out.ln(arc(x, y, s * .7, s * .4, Math.PI * .1, Math.PI * .9, 8), 1, { item: -2 });
    else if (k === 4) out.ln([[x - s * .6, y + s * .4], [x, y - s * .5], [x + s * .6, y + s * .4], [x - s * .6, y + s * .4]], 1, { item: -2, smooth: false });
    else { const pts = []; for (let j = 0; j < 6; j++) pts.push([x - s + j * s * .4, y + (j % 2 ? -3 : 3)]); out.ln(pts, .9, { item: -2, smooth: false }); }
    out.wash(ellipse(x + 4, y + 3, s * .7, s * .55, 9, a), marks[i % marks.length], .4, { j: 3, item: -2 });
  }
  // 几圈断开的细线，像曼陀罗的格子
  for (const R of [190, 470, 805]) for (let k = 0; k < 3; k++) { const a0 = k / 3 * TAU + R * .01; out.ln(arc(0, 0, R, R, a0, a0 + TAU / 3 - .25, 40), .9, { item: -3, alpha: .55 }); }
  return { ...out, items };
}
