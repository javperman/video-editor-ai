#!/usr/bin/env bash
# Graba la posición del cursor durante una captura en Hyprland.
#
# Uso (en otra terminal, mientras se graba la pantalla):
#   scripts/record_cursor.sh /tmp/cursor.jsonl
#
# Cada línea es un JSON {t, x, y, w, h} con t en segundos desde el inicio.
# Duración y frecuencia por variables de entorno: DURATION (s), HZ (muestras/s).
set -euo pipefail
OUT="${1:-/tmp/cursor.jsonl}"
DURATION="${DURATION:-0}"   # 0 = sin límite
HZ="${HZ:-30}"

command -v hyprctl >/dev/null || { echo "hyprctl no disponible (¿no es Hyprland?)" >&2; exit 1; }

monitors="$(hyprctl -j monitors)"
w="$(python3 -c 'import json,sys;m=json.load(sys.stdin);print(int(m[0]["width"]))' <<<"$monitors")"
h="$(python3 -c 'import json,sys;m=json.load(sys.stdin);print(int(m[0]["height"]))' <<<"$monitors")"
interval="$(python3 -c "print(1/$HZ)")"

: > "$OUT"
start="$(date +%s.%N)"
while :; do
  now="$(date +%s.%N)"
  t="$(python3 -c "print(round($now-$start,4))")"
  if [[ "$DURATION" != "0" ]] && python3 -c "import sys; sys.exit(0 if $t >= $DURATION else 1)"; then
    break
  fi
  pos="$(hyprctl -j cursorpos)"
  printf '{"t": %s, "x": %s, "y": %s, "w": %s, "h": %s}\n' \
    "$t" \
    "$(python3 -c 'import json,sys;print(json.load(sys.stdin)["x"])' <<<"$pos")" \
    "$(python3 -c 'import json,sys;print(json.load(sys.stdin)["y"])' <<<"$pos")" \
    "$w" "$h" >> "$OUT"
  python3 -c "import time; time.sleep($interval)"
done
echo "cursor_samples=$OUT"
