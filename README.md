# 中华文明 · 五千年的回响

A 2½-minute ink-wash style video about Chinese civilization with Chinese subtitles, generated entirely in code.

- **Video:** [`output/chinese_civilization.mp4`](output/chinese_civilization.mp4). It is 1280×720 at 24 fps and runs 2:24.
- **Subtitles:** burned into the picture. They are also embedded as a soft `mov_text` track (中文字幕) and written to [`output/chinese_civilization.srt`](output/chinese_civilization.srt).
- **Soundtrack:** a synthesized D-pentatonic guzheng-style melody with bass, a drone, drum hits at scene changes and reverb. There is no voice narration.

## Scenes

| # | 章节 | 内容 |
|---|------|------|
| 1 | 中华文明 | 开篇 |
| 2 | 文明曙光 | 黄河、长江，仰韶彩陶，良渚玉琮 |
| 3 | 夏商周 | 甲骨文，青铜鼎 |
| 4 | 春秋战国 | 竹简，百家争鸣（仁、道） |
| 5 | 秦汉 | 万里长城，丝绸之路 |
| 6 | 四大发明 | 造纸术、印刷术、火药、指南针 |
| 7 | 唐宋 | 李白《静夜思》，梅花 |
| 8 | 元明清 | 郑和宝船，紫禁城 |
| 9 | 走向未来 | 城市与星空 |
| 10 | 生生不息 | 结尾 |

## Regenerate

```bash
pip install pillow numpy imageio-ffmpeg
python3 make_video.py            # full render, about 2 minutes
python3 make_video.py --stills   # one preview PNG per scene in output/
```

On the first run the script downloads the fonts Ma Shan Zheng (brush script) and Noto Serif SC from Google Fonts. Both fonts use the SIL Open Font License.

---

# UNBROKEN · Chinese civilization in English

A second, English-language video on the same subject. It follows the style of a "blueprint montage" reference video: about 50 fast shots of line-art illustrations. The dynasties are drawn on aged parchment, and the night, space and future chapters switch to a dark gold-glow palette. Headlines land one word at a time, and a HUD shows the chapter, the year, a timeline and a Kardashev meter. The story is told in the first person ("WE TAMED THE FLOOD.", "THEN WE BUILT THE WALL.", "THEN WE LEFT."). It is framed by one motif, the glowing character 文 ("writing", half of 文明, "civilization"): Cangjie invents writing, "we never put down the brush", and the ending returns to "the ink is still wet".

- **Video:** `output/chinese_civilization_en.mp4`. It is 1280×720 at 30 fps and runs about 2:05. Every cut lands on the beat of a 120 BPM soundtrack.
- **Soundtrack:** synthesized, with no voice, in D pentatonic. It drives from the first frame: a sixteenth-note staccato string ostinato, an octave bass, four-on-the-floor kick with a snare backbeat and hi-hats, and taiko. A brass-like stab hits every cut, and each new chapter gets a snare fill and a crash. Layers pile on dynasty by dynasty (a dizi-like lead and guzheng from the Tang on). The night chapter turns half-time and heavy with an erhu-like line, and an accelerating snare roll runs into "5,000 YEARS."

| # | Chapter | Shots |
|---|---------|-------|
| — | Cold open | Song compass, the tracks of birds and beasts (Xu Shen's *Shuowen Jiezi*), Cangjie invents writing, "we never put down the brush" |
| I | 夏商 Xia · Shang | Yu tames the flood, oracle bones, the Houmuwu ding |
| II | 周 Zhou | Sun Tzu, Confucius's Analects, the Way |
| III | 秦 Qin | One empire and one script, the Great Wall, the Terracotta Army |
| IV | 汉 Han | The Silk Road, paper, Zhang Heng's seismoscope |
| V | 唐 Tang | Chang'an, Li Bai's *Quiet Night Thought*, the Diamond Sutra |
| VI | 宋 Song | Movable type, gunpowder, the compass, *Along the River During Qingming* |
| VII | 明 Ming | 1405, Zheng He's voyages to Africa, the giraffe, the Forbidden City, porcelain |
| VIII | 夜 Night | The doors close, the Old Summer Palace burns, Lu Xun keeps writing |
| IX | 复兴 Revival | The doors open, Shenzhen, 800,000,000 out of poverty, Three Gorges, high-speed rail |
| X | 天 Sky | Shenzhou 5, FAST, the far side of the Moon, Zhurong on Mars, Tiangong |
| XI | 火 Fire | The EAST tokamak |
| XII | 未来 Future | Kardashev Type II and III, a flip through 5,000 years, the ending |

```bash
pip install skia-python numpy pillow imageio-ffmpeg
python3 make_video_en.py             # full render, a few minutes on 4 cores
python3 make_video_en.py --stills    # contact sheets of every shot in output/
```

skia needs `libegl1` on Linux (`apt-get install libegl1`). On the first run the script downloads Cinzel, EB Garamond, IBM Plex Mono, Noto Serif SC and Ma Shan Zheng from Google Fonts. All of these fonts use the SIL Open Font License.
