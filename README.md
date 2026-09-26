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
