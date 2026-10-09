"""阿莱夫：配乐 + 音效 + 混音 → out/mix.wav
96 BPM, 4/4, 一小节 2.5 s。节拍与 film.js 的时间线一致（TREATMENT.md §6）。
"""
import json, os, sys
import numpy as np, soundfile as sf
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.environ.get('LIB') or sys.exit('set LIB to the library folder')
sys.path.insert(0, os.path.join(LIB, 'core', 'audio'))
import sfx as X
from sfx import SR, add
import pluck as P

DUR = 20.0
N = int(DUR * SR)
BEAT = 60 / 96; BAR = BEAT * 4; S16 = BEAT / 4
ev = json.load(open(os.path.join(HERE, 'events.json')))['ev']
rng = np.random.default_rng(5)

def buf(): return np.zeros((N, 2))
music, foley, amb = buf(), buf(), buf()

def env_fade(x, a, r):
    n = len(x); e = np.ones(n); ia, ir = int(a * SR), int(r * SR)
    if ia: e[:ia] = np.linspace(0, 1, ia)
    if ir: e[-ir:] = np.linspace(1, 0, ir)
    return x * e

# ---------------- 音乐 ----------------
def g(p, t, d=2.5, v=.6, pan=0, preset='nylon_guitar', **kw):
    add(music, P.pluck(preset, p, d, vel=v, **kw), t, 1.0, pan)

# 小节 1–2：E 小调米隆加低音（3-3-2）
for bar, (root, fifth, chord) in enumerate([('E2', 'B2', ['G3', 'B3', 'E4']), ('B1', 'F#2', ['A3', 'B3', 'D#4'])]):
    t0 = bar * BAR
    for half in (0, 1):
        th = t0 + half * BAR / 2
        g(root, th, 1.2, .55, -.15); g(fifth, th + 3 * S16, 1.0, .42, -.1); g(root if half == 0 else fifth, th + 6 * S16, .8, .45, -.1)
        if half == 1 or bar == 1:
            for k, n in enumerate(chord): g(n, th + 3 * S16 + .012 * k, 1.0, .25, .2)
g('B4', 1.4, 2.0, .5, .35, preset='harp')                    # 第一点颜色
g('E6', 3.75, 2.4, .45, .4, preset='harp')                     # 小球闪光
g('G4', 2 * BAR - BEAT, 1.0, .35, .25); g('F#4', 2 * BAR - BEAT / 2, 1.0, .3, .25)

# 5.625：进入
t_in = 5.625
g('E1', t_in, 4.0, .9, 0, preset='upright_bass_pizz')
for k, n in enumerate(['E2', 'B2', 'E3', 'G3', 'B3', 'F#4', 'B4']): g(n, t_in + k * .018, 3.5, .55, -.3 + k * .1)
for k, n in enumerate(['E5', 'G5', 'B5', 'D6', 'F#6', 'B6']): g(n, t_in + .15 + k * .05, 2.0, .35, .5, preset='harp')

# 小节 3 后半到 6：十六分音符琶音，越来越密
prog = [(6.25, ['E3', 'B3', 'E4', 'G4', 'B4', 'G4', 'E4', 'B3'], 'E2'), (7.5, ['C3', 'G3', 'C4', 'E4', 'G4', 'E4', 'C4', 'G3'], 'C2'),
        (8.75, ['A2', 'E3', 'A3', 'C4', 'E4', 'C4', 'A3', 'E3'], 'A1'), (10.0, ['B2', 'F#3', 'A3', 'D#4', 'F#4', 'D#4', 'A3', 'F#3'], 'B1'),
        (11.25, ['E3', 'B3', 'E4', 'G4', 'B4', 'G4', 'E4', 'B3'], 'E2'), (12.5, ['C3', 'G3', 'C4', 'E4', 'G4', 'E4', 'C4', 'G3'], 'C2'),
        (13.75, ['A2', 'E3', 'A3', 'C4', 'E4', 'C4', 'A3', 'E3'], 'A1')]
for (t0, arp, bass) in prog:
    dens = 1.0 if 7.5 <= t0 < 12.5 else .6
    vel = {6.25: .3, 7.5: .38, 8.75: .45, 10.0: .55, 11.25: .5, 12.5: .36, 13.75: .24}[t0]
    add(music, P.pluck('upright_bass_pizz', bass, 1.4, vel=vel + .25), t0, 1.0, 0)
    add(music, P.pluck('upright_bass_pizz', bass, 1.0, vel=vel + .1), t0 + 6 * S16, 1.0, 0)
    for i in range(8):
        if dens < 1 and i % 2: continue
        tt = t0 + i * S16
        if tt >= 14.3: break
        g(arp[i], tt, 1.2, vel, -.25 + .07 * i)
    if t0 >= 8.75 and t0 < 12.5:   # 竖琴高八度，错开一个十六分
        for i in range(0, 8, 2):
            n = arp[i]; up = n[:-1] + str(int(n[-1]) + 1)
            add(music, P.pluck('harp', up, 1.2, vel=vel * .7), t0 + (i + 1) * S16, 1.0, .45)
for k, n in enumerate(['B2', 'F#3', 'B3', 'D#4', 'F#4', 'A4']): g(n, 10.0 + k * .012, 2.0, .7, -.2 + k * .08)   # 10.0 重音
# 14.4 前收住：一切切断
fade = np.ones(N); a, b = int(14.15 * SR), int(14.4 * SR); fade[a:b] = np.linspace(1, 0, b - a); fade[b:int(15.0 * SR)] = 0
a, b = int(4.8 * SR), int(5.02 * SR); fade[a:b] = np.linspace(1, 0, b - a); fade[b:int(5.62 * SR)] = 0
music *= fade[:, None]

# 15.0：静默后的第一声
g('E2', 15.0, 3.0, .8, -.1); add(music, P.pluck('upright_bass_pizz', 'E1', 3.0, vel=.8), 15.0, 1.0, 0)
add(music, P.pluck('harp', 'E6', 3.0, vel=.5), 15.0, 1.0, .4)
for t, n in [(15.625, 'B5'), (16.25, 'G5'), (16.875, 'E5')]: add(music, P.pluck('harp', n, 2.5, vel=.42), t, 1.0, .3)
# 17.5：E 大调（皮卡迪三度）
for k, n in enumerate(['E2', 'B2', 'E3', 'G#3', 'B3', 'E4']): g(n, 17.5 + k * .03, 3.0, .55, -.25 + k * .1)
add(music, P.pluck('harp', 'G#5', 3.0, vel=.4), 17.56, 1.0, .4); add(music, P.pluck('harp', 'E6', 3.0, vel=.35), 17.68, 1.0, .45)
music = X.hp(music.T, 45).T

# ---------------- 环境 ----------------
def bed(fn, t0, t1, fi, fo, gain, pan=0):
    x = env_fade(fn(t1 - t0), fi, fo); add(amb, x, t0, gain, pan)
room = lambda d: X.lp(X.brown(d), 300) * .6 + X.bp(X.noise(d), 2000, 6000) * .02
bed(room, 0, 5.05, .3, .12, .5); bed(room, 16.4, 20, .6, .5, .5)                # 地下室；16.4 提前回来（J-cut）
def sea(d):
    t = X.t_(d); sw = .55 + .45 * np.sin(TAU * t / 2.6) ** 2
    return X.lp(X.noise(d), 900) * sw * .5 + X.bp(X.noise(d), 2500, 7000) * sw ** 3 * .08
TAU = 2 * np.pi
bed(sea, 5.625, 14.4, .25, .9, .45, -.3)
def crowd(d):
    t = X.t_(d); return X.bp(X.noise(d), 300, 1800) * (.6 + .4 * np.sin(TAU * 3.1 * t) * np.sin(TAU * .7 * t)) * .5
bed(crowd, 7.5, 14.2, 1.2, 1.4, .25, .4)
wind = lambda d: X.bp(X.noise(d), 500, 1500) * .5
bed(wind, 8.6, 13.0, .6, 1.2, .18, .1)
amb[int(14.4 * SR):int(15.0 * SR)] = 0                                          # 真正的静默
fz = np.ones(N); a = int(5.0 * SR); fz[a:int(5.6 * SR)] = 0
amb *= fz[:, None]

# ---------------- 拟音 ----------------
def pen(d, bright=1.0):
    d = round(max(.03, min(d, .6)), 4); n = X.noise(d); x = X.bp(n, 1600, 7500)
    t = np.arange(len(x)) / SR; d = len(x) / SR; fib = 1 + .5 * np.sin(TAU * (40 + 30 * rng.random()) * t + rng.random() * 6)
    clicks = (rng.random(len(x)) < 30 / SR) * rng.standard_normal(len(x)) * 3
    e = np.minimum(1, t / .008) * np.minimum(1, (d - t) / .02)
    return (x * fib + X.hp(clicks, 2000)) * e * bright
nB = 0
for e in ev:
    if e['type'] == 'pen':
        if e.get('b'):
            nB += 1; g_ = .05 * (1 if e['len'] > 40 else .6)
        else: g_ = .22
        add(foley, pen(e['dur'], 1.0), e['t'], g_, e.get('pan', 0) * .7)
    elif e['type'] == 'write':
        t = e['t']
        while t < e['t'] + e['dur']:
            d = .05 + rng.random() * .08; add(foley, pen(d, .8), t, .25, e['pan']); t += d + .02
# 湿笔晕开 + 滴水
bloom = X.lp(X.noise(1.6), 1800) * np.exp(-X.t_(1.6) / .55) * np.minimum(1, X.t_(1.6) / .05)
add(foley, bloom, 5.625, .55, 0)
def drip(f=1400):
    d = .18; t = X.t_(d); fr = f * (1 + 1.5 * np.exp(-t / .02))
    return np.sin(TAU * np.cumsum(fr) / SR) * np.exp(-t / .04)
for t, f, p in [(6.4, 1300, -.4), (7.1, 1650, .3), (7.9, 1200, .5), (9.3, 1500, -.2)]: add(foley, drip(f), t, .22, p)
for t, gn in [(1.4, .25), (3.75, .35)]: add(foley, X.ding(.6), t, gn * .5, .2)
add(foley, X.whoosh(.5, 1.0), 9.85, .3, -.4)                                  # 10.0 的甩镜
add(foley, X.whoosh(1.2, .7), 2.9, .12, .1)                                    # 推进
add(foley, X.whoosh(1.6, .6), 15.2, .12, 0)                                    # 推入循环
foley = X.hp(foley.T, 90).T
foley[int(14.4 * SR):int(15.0 * SR)] = 0; foley[int(5.02 * SR):int(5.6 * SR)] = 0

# ---------------- 混音 ----------------
def rms(x): return np.sqrt(np.mean(x ** 2) + 1e-12)
mix = music * 1.0 + foley * 1.0 + amb * .8
# 关键拟音处压一点音乐（ducking）
duck = np.ones(N)
for t in (5.625, 10.0):
    i = int(t * SR); duck[i:i + int(.25 * SR)] = .8
mix = music * duck[:, None] + foley + amb * .8
mix = np.stack([X.limit(mix[:, 0], .95), X.limit(mix[:, 1], .95)], 1)
os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
sf.write(os.path.join(HERE, 'out', 'mix.wav'), mix.astype(np.float32), SR)
print('mix.wav', f'{N / SR:.2f}s', 'B pens', nB, 'rms', f'{rms(mix):.3f}')
