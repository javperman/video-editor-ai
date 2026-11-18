#!/usr/bin/env bash
# Genera fixtures para las pruebas de visión: cortes duros, imagen con texto y vídeo con secreto.
set -euo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$BASE/tests/fixtures/vision}"
FONT="${FONT:-/usr/share/fonts/noto/NotoSans-Regular.ttf}"
mkdir -p "$OUT"

if [[ ! -f "$FONT" ]]; then
  echo "falta el tipo de letra: $FONT" >&2
  exit 1
fi

# 1) Cortes duros: negro 2 s, blanco 2 s, negro 2 s.
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=black:s=640x360:d=2:r=30" \
  -f lavfi -i "color=c=white:s=640x360:d=2:r=30" \
  -f lavfi -i "color=c=black:s=640x360:d=2:r=30" \
  -filter_complex "[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]" -map "[out]" \
  -c:v libx264 -pix_fmt yuv420p "$OUT/cuts.mp4"

# 2) Imagen con texto sensible de laboratorio.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf 'api_key = sk-ABCDEF1234567890XYZ\n' > "$TMP/l1.txt"
printf 'contacto: ana@example.com\n' > "$TMP/l2.txt"
printf 'usuario y contrasena\n' > "$TMP/l3.txt"
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "color=c=white:s=1000x320:d=1" \
  -vf "drawtext=fontfile=$FONT:textfile=$TMP/l1.txt:fontcolor=black:fontsize=40:x=30:y=30,drawtext=fontfile=$FONT:textfile=$TMP/l2.txt:fontcolor=black:fontsize=40:x=30:y=120,drawtext=fontfile=$FONT:textfile=$TMP/l3.txt:fontcolor=black:fontsize=40:x=30:y=210" \
  -frames:v 1 "$OUT/text.png"

# 3) Vídeo con el secreto visible 3 s.
ffmpeg -hide_banner -loglevel error -y -loop 1 -i "$OUT/text.png" -t 3 -r 30 \
  -vf "scale=1000:320" -c:v libx264 -pix_fmt yuv420p "$OUT/secret.mp4"

echo "fixtures=$OUT"
ls -la "$OUT"
