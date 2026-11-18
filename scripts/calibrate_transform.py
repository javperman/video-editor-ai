#!/usr/bin/env python3
"""Calibra la semántica de `transform` de OpenChatCut midiendo un render real.

Crea dos capas de color sólido (fondo negro en V1, capa magenta en V2), aplica
transformaciones conocidas y mide la caja del magenta en el fotograma exportado.
Así se deduce la relación entre `translate(x%,y%) scale(s)` y la posición real.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))

import numpy as np  # noqa: E402

from video_ai.occ_client import OccClient, export_project  # noqa: E402

WORK = BASE / "data" / "calibration"
DB = BASE / "data" / "home" / ".openchatcut" / "project-store-v1.sqlite3"
W, H, FPS, DUR = 640, 360, 30, 60


def make_assets() -> dict[str, Path]:
    WORK.mkdir(parents=True, exist_ok=True)
    black = WORK / "black.mp4"
    magenta = WORK / "magenta.mp4"
    if not black.is_file():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", f"color=c=black:s={W}x{H}:d=2:r={FPS}", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(black)], check=True)
    if not magenta.is_file():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", f"color=c=magenta:s={W}x{H}:d=2:r={FPS}", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(magenta)], check=True)
    return {"black": black, "magenta": magenta}


def magenta_box(video: Path) -> dict[str, float]:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.5", "-i", str(video),
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frame = np.frombuffer(raw, dtype=np.uint8)[: W * H * 3].reshape((H, W, 3))
    mask = (frame[:, :, 0].astype(int) > 90) & (frame[:, :, 2].astype(int) > 90) & \
           (frame[:, :, 1].astype(int) + 30 < frame[:, :, 0].astype(int)) & \
           (frame[:, :, 1].astype(int) + 30 < frame[:, :, 2].astype(int))
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0, "pixels": 0.0}
    return {
        "x": round(xs.min() / W, 4),
        "y": round(ys.min() / H, 4),
        "width": round((xs.max() - xs.min() + 1) / W, 4),
        "height": round((ys.max() - ys.min() + 1) / H, 4),
        "pixels": float(len(xs)),
    }


def project_item_count(project_id: str) -> int:
    try:
        connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = connection.execute("select v from kv where k = ?", (f"project:{project_id}",)).fetchone()
        connection.close()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    document = json.loads(row[0])
    timeline_id = document.get("activeTimelineId")
    timeline = next((t for t in document.get("timelines", []) if t.get("id") == timeline_id), None)
    if timeline is None:
        return 0
    tracks = timeline.get("tracks") or timeline.get("items") or []
    if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict) and "items" in tracks[0]:
        return sum(len(t.get("items", [])) for t in tracks)
    return len(tracks) if isinstance(tracks, list) else 0


def wait_for_items(project_id: str, minimum: int = 2, timeout: float = 15.0) -> int:
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        count = project_item_count(project_id)
        if count >= minimum:
            return count
        time.sleep(0.4)
    return count


def run_case(assets: dict[str, Path], transform: dict[str, float]) -> dict[str, float]:
    client = OccClient()
    client.initialize()
    created = client.call("create_project", {
        "name": f"calib-{transform['scale']}-{transform['x']}-{transform['y']}-{int(time.time() * 1000) % 100000}",
        "compositionWidth": W, "compositionHeight": H, "fps": float(FPS),
        "description": "calibración de transform",
    })
    if "id" not in created:
        raise RuntimeError(f"create_project no devolvió id: {created}")
    project_id = created["id"]
    client.call("target_project", {"projectId": project_id})
    session = client.call("begin_edit_session", {"clientName": "calib", "approvalMode": "auto",
                                                 "editorProjectId": project_id})
    sid = session["editSessionId"]
    imported = client.call("import_assets", {"editSessionId": sid,
                                             "paths": [str(assets["black"].resolve()), str(assets["magenta"].resolve())]})
    by_name = {asset["name"]: asset for asset in imported["imported"]}
    timeline = client.call("read_timeline", {"editSessionId": sid})
    existing = {track["alias"] for track in timeline.get("tracks", [])}
    for alias in ("V1", "V2"):
        if alias not in existing:
            client.call("edit_track", {"action": "create",
                                       "json": '{"trackType":"video","name":"%s"}' % alias,
                                       "editSessionId": sid, "editorProjectId": project_id})
    client.call("edit_item", {"editSessionId": sid, "adds": [
        {"type": "video", "assetId": by_name["black.mp4"]["id"], "track": "V1", "fromFrame": 0, "durationInFrames": DUR},
        {"type": "video", "assetId": by_name["magenta.mp4"]["id"], "track": "V2", "fromFrame": 0, "durationInFrames": DUR},
    ]})
    timeline = client.call("read_timeline", {"editSessionId": sid})
    magenta_item = next(item["id"] for item in timeline["items"] if item["track"] == "V2")
    client.call("edit_item", {"editSessionId": sid,
                              "updates": [{"type": "video", "itemId": magenta_item, "transform": transform}]})
    client.call("review_edit_session", {"editSessionId": sid, "editorProjectId": project_id,
                                        "summary": f"transform {transform}"})
    items = wait_for_items(project_id, minimum=2)
    out = WORK / f"render-{transform['scale']}-{transform['x']}-{transform['y']}.mp4"
    export_project(project_id, out, DB)
    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"export vacío para {transform}")
    box = magenta_box(out)
    box["items"] = items  # type: ignore[assignment]
    return box


def main() -> int:
    assets = make_assets()
    cases = [
        {"scale": 1.0, "x": 0, "y": 0},
        {"scale": 0.5, "x": 0, "y": 0},
        {"scale": 0.5, "x": 50, "y": 0},
        {"scale": 0.5, "x": 0, "y": 50},
        {"scale": 0.28, "x": 60, "y": -60},
    ]
    results = []
    for case in cases:
        box = run_case(assets, case)
        results.append({"transform": case, "box": box})
        print("caso", case, "->", box, flush=True)
    report = {"canvas": [W, H], "results": results}
    (WORK / "calibration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
