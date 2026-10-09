#!/bin/sh
# 一条命令出片：sh build.sh
set -e
LIB=${LIB:-/root/lemo-opuscar}
HERE=$(cd "$(dirname "$0")" && pwd)
export LIB
[ -f "$LIB/core/render/video.mjs" ] || { echo "set LIB to the library folder"; exit 1; }
[ -x /opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell ] && export PLAYWRIGHT_CHROME=${PLAYWRIGHT_CHROME:-/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell}
cd "$LIB"
node core/render/events.mjs "$HERE"
node core/render/video.mjs "$HERE" --fps 24 --workers 4 --out "$HERE/out/video.mp4"
"$LIB/.venv/bin/python" "$HERE/mix.py"
# 母带：两遍 loudnorm 到 −14 LUFS / −1.2 dBTP，再与画面合成，加一点胶片颗粒
# （不用 core/render/mux.sh：ffmpeg 6.1 的 loudnorm 有 3 秒缓冲，短片会被它的"解码时长"检查误判为损坏）
J=$(ffmpeg -hide_banner -nostats -i "$HERE/out/mix.wav" -af loudnorm=I=-14:TP=-1.6:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
v() { echo "$J" | grep "\"$1\"" | sed 's/.*: "\(.*\)".*/\1/'; }
ffmpeg -loglevel error -y -i "$HERE/out/video.mp4" -i "$HERE/out/mix.wav" \
  -filter_complex "[0:v]noise=alls=2:allf=t,format=yuv420p[v];[1:a]loudnorm=I=-14:TP=-1.6:LRA=11:measured_I=$(v input_i):measured_TP=$(v input_tp):measured_LRA=$(v input_lra):measured_thresh=$(v input_thresh):offset=$(v target_offset):linear=true,aresample=48000[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 21 -r 24 -c:a aac -b:a 256k -t 20 -movflags +faststart "$HERE/aleph.mp4"
ffmpeg -hide_banner -nostats -i "$HERE/aleph.mp4" -af ebur128=peak=true -f null - 2>&1 | grep -E "^ +(I|Peak):" | tr -s ' '
ffmpeg -loglevel error -y -ss 18.5 -i "$HERE/aleph.mp4" -frames:v 1 -q:v 3 "$HERE/poster.jpg"
