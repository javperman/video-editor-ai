#!/usr/bin/env bash
# Arranca OpenChatCut aislado: HOME/XDG propios y servidor MCP solo en loopback.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${OCC_ROOT:-$BASE/vendor/openchatcut/appimage/root}"

if [[ ! -x "$ROOT/AppRun" ]]; then
  echo "No existe $ROOT/AppRun. Extrae primero la AppImage en vendor/openchatcut." >&2
  exit 1
fi

mkdir -p "$BASE/data/home" "$BASE/data/config" "$BASE/data/share" "$BASE/data/cache" "$BASE/logs"

export HOME="$BASE/data/home"
export XDG_CONFIG_HOME="$BASE/data/config"
export XDG_DATA_HOME="$BASE/data/share"
export XDG_CACHE_HOME="$BASE/data/cache"

# Usa el FFmpeg del sistema (con NVENC/VAAPI) en lugar del binario empaquetado.
export OPENCHATCUT_FFMPEG="${OPENCHATCUT_FFMPEG:-/usr/bin/ffmpeg}"
export OPENCHATCUT_FFPROBE="${OPENCHATCUT_FFPROBE:-/usr/bin/ffprobe}"

cd "$ROOT"
exec ./AppRun --no-sandbox "$@"
