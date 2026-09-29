#!/usr/bin/env bash
# Turn a screen recording (.mov/.mp4) into a GIF small enough to embed in the README.
#
#   scripts/make_gif.sh recording.mov docs/gifs/retail-questions.gif [width] [fps]
#
# Record with Cmd+Shift+5 on macOS ("Record Selected Portion" around the browser page, not
# the tab bar). Two-pass palette keeps text sharp; width 1200 and 10 fps keep it a few MB.
set -euo pipefail

input=${1:?usage: make_gif.sh input.mov output.gif [width] [fps]}
output=${2:?usage: make_gif.sh input.mov output.gif [width] [fps]}
width=${3:-1200}
fps=${4:-10}

filters="fps=${fps},scale=${width}:-1:flags=lanczos"
ffmpeg -v error -y -i "$input" \
  -vf "${filters},split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" \
  "$output"
echo "$output: $(du -h "$output" | cut -f1)"
