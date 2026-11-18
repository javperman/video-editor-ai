#!/usr/bin/env python3
"""End-to-end OpenChatCut spike against the packaged offline MCP.

Scenario: create project, import screen/phone/voice, build a multi-track
timeline (screen + webcam PiP + audio), validate a rejected edit, split a clip,
add text overlay, commit the draft atomically, and read the committed project.

Every draft is either committed or discarded in this same process so the
project is never left with an orphaned offline editor.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from occ_mcp import ENDPOINT, Client  # noqa: E402

BASE = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = BASE / "tests" / "fixtures" / "spike"


def wait_for_server(timeout: float = 30.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{ENDPOINT.rsplit('/api/', 1)[0]}/api/keys", timeout=2)
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("OpenChatCut no responde en 127.0.0.1:5199")


def main() -> int:
    wait_for_server()
    client = Client()
    client.initialize()

    def call(name: str, args: dict):
        result = client.request("tools/call", {"name": name, "arguments": args})
        return result.get("result", {}).get("structuredContent", result.get("result"))

    def show(name: str, data, limit: int = 4000) -> None:
        print(f"### {name}")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:limit])

    created = call("create_project", {"name": f"Spike full {time.strftime('%H%M%S')}", "compositionWidth": 1920, "compositionHeight": 1080, "fps": 30})
    project = created["id"]
    sid = None
    applied = False
    try:
        show("target", call("target_project", {"projectId": project}))
        session = call("begin_edit_session", {"clientName": "video-editor-ai", "approvalMode": "auto", "editorProjectId": project})
        sid = session["editSessionId"]
        show("session", session)

        imported = call("import_assets", {
            "editSessionId": sid,
            "paths": [str(FIXTURES / name) for name in ("screen.mp4", "phone.mp4", "voice.wav")],
        })
        assets = {asset["name"]: asset for asset in imported["imported"]}
        show("imported", {name: asset["id"] for name, asset in assets.items()})

        for spec in (
            {"action": "create", "json": json.dumps({"trackType": "video", "name": "Webcam"})},
            {"action": "create", "json": json.dumps({"trackType": "video", "name": "Overlay"})},
            {"action": "create", "json": json.dumps({"trackType": "audio", "name": "Voice"})},
        ):
            call("edit_track", {**spec, "editSessionId": sid, "editorProjectId": project})
        show("tracks", call("read_timeline", {"editSessionId": sid})["tracks"])

        rejected = call("edit_item", {
            "editSessionId": sid,
            "validateOnly": True,
            "adds": [{"type": "video", "assetId": "asset-that-does-not-exist", "track": "V1", "fromFrame": 0, "durationInFrames": 30}],
        })
        show("invalid_edit_rejected", rejected)
        if rejected.get("ok") is not False and rejected.get("outcome") != "failed":
            print("ATENCION: la edición inválida no fue rechazada", file=sys.stderr)

        call("edit_item", {
            "editSessionId": sid,
            "adds": [
                {"type": "video", "assetId": assets["screen.mp4"]["id"], "track": "V1", "fromFrame": 0, "durationInFrames": 360},
                {"type": "video", "assetId": assets["phone.mp4"]["id"], "track": "V2", "fromFrame": 0, "durationInFrames": 360},
                {"type": "audio", "assetId": assets["voice.wav"]["id"], "track": "A1", "fromFrame": 0, "durationInFrames": 360},
            ],
        })
        timeline = call("read_timeline", {"editSessionId": sid})
        show("timeline_after_adds", timeline, 6000)

        items = {item["track"]: item for item in timeline["items"]}
        screen_item = items["V1"]["id"]
        phone_item = items["V2"]["id"]

        call("edit_item", {
            "editSessionId": sid,
            "updates": [{"type": "video", "itemId": phone_item, "transform": {"scale": 0.28, "x": 60, "y": -60}}],
        })
        call("split_item", {"editSessionId": sid, "itemId": screen_item, "atFrame": 150})
        split_timeline = call("read_timeline", {"editSessionId": sid})
        show("timeline_after_split", split_timeline, 6000)
        split_items = [item for item in split_timeline["items"] if item["track"] == "V1"]
        if len(split_items) >= 2:
            call("remove_item", {"editSessionId": sid, "itemId": split_items[1]["id"], "ripple": True})

        call("edit_item", {
            "editSessionId": sid,
            "adds": [{"type": "text", "text": "Paso 1", "track": "V3", "fromFrame": 30, "durationInFrames": 90, "fontSize": 72, "color": "#FFB000", "fontWeight": "bold"}],
        })
        show("timeline_before_commit", call("read_timeline", {"editSessionId": sid}), 8000)

        review = call("review_edit_session", {"editSessionId": sid, "editorProjectId": project, "summary": "Spike: pantalla, webcam PiP, voz, split y texto"})
        show("review", review)
        applied = review.get("status") == "applied"
        show("project_after_commit", call("read_project", {"editSessionId": sid}) if applied else review, 8000)
        print("PROJECT_ID", project)
        return 0 if applied else 1
    finally:
        if sid and not applied:
            try:
                call("discard_edit_session", {"editSessionId": sid, "editorProjectId": project})
                print("DISCARDED", project)
            except Exception as error:  # noqa: BLE001
                print("discard failed", error, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
