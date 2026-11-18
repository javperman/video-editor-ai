#!/usr/bin/env bash
# Genera el fixture de voz en español con espeak-ng y pausas reales.
set -euo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$BASE/tests/fixtures/spike/voice-es.wav}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v espeak-ng >/dev/null || {
  echo "falta espeak-ng; instálalo con: sudo pacman -S espeak-ng" >&2
  exit 1
}

espeak-ng -v es -s 150 -w "$TMP/part1.wav" "Hola. Este es un tutorial técnico de prueba."
espeak-ng -v es -s 150 -w "$TMP/part2.wav" "Primero abrimos la terminal."
espeak-ng -v es -s 150 -w "$TMP/part3.wav" "Después ejecutamos el comando. Este paso es importante y no debe eliminarse."

ffmpeg -hide_banner -loglevel error -y -f lavfi -i anullsrc=r=22050:cl=mono -t 1.5 -c:a pcm_s16le "$TMP/silence15.wav"
ffmpeg -hide_banner -loglevel error -y -f lavfi -i anullsrc=r=22050:cl=mono -t 1.0 -c:a pcm_s16le "$TMP/silence10.wav"

cat > "$TMP/list.txt" <<EOF
file '$TMP/part1.wav'
file '$TMP/silence15.wav'
file '$TMP/part2.wav'
file '$TMP/silence10.wav'
file '$TMP/part3.wav'
EOF
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$TMP/list.txt" -c:a pcm_s16le "$OUT"
echo "fixture=$OUT"
