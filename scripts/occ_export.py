#!/usr/bin/env python3
"""Exporta headless un proyecto OpenChatCut guardado en la librería local.

El MCP offline de OpenChatCut no expone render/export. La app empaquetada sí
sirve `POST /export`, que acepta el documento de proyecto y un timelineId y
devuelve el MP4. Este script lee el documento desde la base SQLite aislada y
lo envía al servidor local.

Uso:
  python3 scripts/occ_export.py <project-id> <salida.mp4> [timeline-id]
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import urllib.request

BASE = pathlib.Path(__file__).resolve().parents[1]
DB = BASE / "data" / "home" / ".openchatcut" / "project-store-v1.sqlite3"
URL = "http://127.0.0.1:5199/export"


def load_project(project_id: str) -> dict:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = connection.execute("select v from kv where k = ?", (f"project:{project_id}",)).fetchone()
    if row is None:
        raise SystemExit(f"proyecto {project_id} no encontrado en {DB}")
    return json.loads(row[0])


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    project_id, output = sys.argv[1], pathlib.Path(sys.argv[2])
    document = load_project(project_id)
    timeline_id = sys.argv[3] if len(sys.argv) > 3 else document["activeTimelineId"]
    timeline = next((item for item in document["timelines"] if item["id"] == timeline_id), None)
    if timeline is None:
        raise SystemExit(f"timeline {timeline_id} no encontrada")
    body = json.dumps({
        "state": timeline,
        "project": document,
        "timelineId": timeline_id,
        "format": "video",
        "codec": "h264",
        "resolution": "1080p",
        "fps": timeline.get("fps", 30),
        "name": output.stem,
    }).encode("utf-8")
    request = urllib.request.Request(
        URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:5199",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=3600) as response:
        output.write_bytes(response.read())
    print(f"exportado={output} bytes={output.stat().st_size} timeline={timeline_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
