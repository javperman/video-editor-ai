"""Cliente MCP mínimo y export headless para OpenChatCut."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:5199"


class OccError(RuntimeError):
    pass


class OccClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("OPENCHATCUT_EDITOR_URL") or DEFAULT_BASE).rstrip("/")
        self.endpoint = f"{self.base_url}/api/external-mcp/mcp"
        self.token = token or os.environ.get("OPENCHATCUT_MCP_TOKEN") or self._read_token()
        self.session_id: str | None = None
        self._id = 0

    @staticmethod
    def _read_token() -> str:
        home = Path(os.environ.get("HOME", str(Path.home())))
        return (home / ".openchatcut" / "mcp-token").read_text(encoding="utf-8").strip()

    def _post(self, payload: dict[str, Any], notify: bool = False) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                self.session_id = response.headers.get("mcp-session-id") or self.session_id
                body = response.read().decode("utf-8", "replace")
                content_type = response.headers.get("content-type", "")
        except urllib.error.HTTPError as error:
            raise OccError(f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:500]}") from error
        if notify:
            return None
        if content_type.startswith("text/event-stream") or body.lstrip().startswith("event:"):
            messages = [json.loads(line[len("data:"):]) for line in body.splitlines() if line.startswith("data:")]
            if not messages:
                return None
            result = messages[-1]
        else:
            result = json.loads(body)
        if "error" in result:
            raise OccError(json.dumps(result["error"], ensure_ascii=False))
        return result

    def initialize(self) -> dict[str, Any]:
        self._id += 1
        result = self._post({"jsonrpc": "2.0", "id": self._id, "method": "initialize",
                             "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "video-editor-ai", "version": "0.1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, notify=True)
        assert result is not None
        return result

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        result = self._post({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                             "params": {"name": tool, "arguments": arguments}})
        assert result is not None
        return result.get("result", {}).get("structuredContent", result.get("result"))


def export_project(project_id: str, output: Path, db_path: Path, resolution: str = "1080p") -> Path:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = connection.execute("select v from kv where k = ?", (f"project:{project_id}",)).fetchone()
    if row is None:
        raise OccError(f"proyecto {project_id} no encontrado en {db_path}")
    document = json.loads(row[0])
    timeline_id = document["activeTimelineId"]
    timeline = next(item for item in document["timelines"] if item["id"] == timeline_id)
    body = json.dumps({"state": timeline, "project": document, "timelineId": timeline_id,
                       "format": "video", "codec": "h264", "resolution": resolution,
                       "fps": timeline.get("fps", 30), "name": output.stem}).encode()
    request = urllib.request.Request(f"{DEFAULT_BASE}/export", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Origin": DEFAULT_BASE,
                                              "Sec-Fetch-Site": "same-origin"})
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=3600) as response:
        output.write_bytes(response.read())
    return output
