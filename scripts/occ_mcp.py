#!/usr/bin/env python3
"""Minimal Streamable HTTP MCP client for a locally running OpenChatCut.

Usage:
  python3 scripts/occ_mcp.py list
  python3 scripts/occ_mcp.py call <tool> '<json-args>'

Reads the bearer token from $OPENCHATCUT_MCP_TOKEN or
$HOME/.openchatcut/mcp-token. Never prints the token.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = os.environ.get("OPENCHATCUT_EDITOR_URL", "http://127.0.0.1:5199").rstrip("/")
ENDPOINT = f"{URL}/api/external-mcp/mcp"


def token() -> str:
    env = os.environ.get("OPENCHATCUT_MCP_TOKEN")
    if env:
        return env.strip()
    path = Path(os.environ.get("HOME", str(Path.home()))) / ".openchatcut" / "mcp-token"
    return path.read_text(encoding="utf-8").strip()


class Client:
    def __init__(self) -> None:
        self.token = token()
        self.session: str | None = None
        self._id = 0

    def post(self, payload: dict, *, notify: bool = False) -> dict | None:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["mcp-session-id"] = self.session
        request = urllib.request.Request(ENDPOINT, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                self.session = response.headers.get("mcp-session-id") or self.session
                if notify:
                    return None
                body = response.read().decode("utf-8", "replace")
                content_type = response.headers.get("content-type", "")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            raise SystemExit(f"HTTP {error.code}: {body[:500]}") from error
        if content_type.startswith("text/event-stream") or body.lstrip().startswith("event:"):
            messages = [
                json.loads(line[len("data:"):].strip())
                for line in body.splitlines()
                if line.startswith("data:")
            ]
            if not messages:
                return None
            payload_out = messages[-1]
        else:
            payload_out = json.loads(body)
        if not notify and "error" in payload_out:
            raise SystemExit(json.dumps(payload_out["error"], ensure_ascii=False))
        return payload_out

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        result = self.post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        assert result is not None
        return result

    def initialize(self) -> dict:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "video-editor-ai-probe", "version": "0.1"},
            },
        )
        self.post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            notify=True,
        )
        return result


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    client = Client()
    info = client.initialize()
    if sys.argv[1] == "list":
        tools = client.request("tools/list")["result"]["tools"]
        for tool in tools:
            description = (tool.get("description") or "").splitlines()[0]
            print(f"{tool['name']}\t{description}")
        print(f"TOTAL\t{len(tools)}", file=sys.stderr)
        return 0
    if sys.argv[1] == "call":
        tool = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        result = client.request("tools/call", {"name": tool, "arguments": args})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if sys.argv[1] == "info":
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    if sys.argv[1] == "schema":
        tools = client.request("tools/list")["result"]["tools"]
        wanted = sys.argv[2] if len(sys.argv) > 2 else None
        for tool in tools:
            if wanted and tool["name"] != wanted:
                continue
            print(json.dumps({"name": tool["name"], "inputSchema": tool.get("inputSchema")}, ensure_ascii=False, indent=2))
        return 0
    print(f"unknown command: {sys.argv[1]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
