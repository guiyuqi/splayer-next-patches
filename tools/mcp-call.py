#!/usr/bin/env python3
"""调用 MCP 工具，便于逐个验收。

用法：
    python3 mcp-call.py tools                 # 列出工具名
    python3 mcp-call.py call <tool> '<json>'  # 调用工具

默认打开发实例；验收 Windows 实例时：
    MCP_URL=http://192.168.192.1:14559/mcp MCP_KEY=<32位密钥> python3 mcp-call.py tools
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get("MCP_URL", "http://127.0.0.1:14559/mcp")
KEY = os.environ.get("MCP_KEY", "")
if not KEY:
    raise SystemExit(
        "请先设置 MCP_KEY（播放器「设置 → AI 集成」里可看到，或读 settings.json 的 mcp.accessKey）\n"
        "  例：MCP_URL=http://127.0.0.1:14559/mcp MCP_KEY=<key> python3 mcp-call.py tools"
    )


def post(payload, sid=None, timeout=180):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-MCP-Key": KEY,
    }
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
        return resp.headers.get("mcp-session-id"), body


def parse(body):
    if not body.strip():
        return None
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(body)


def open_session():
    sid, _ = post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "verify", "version": "1"},
            },
        }
    )
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    return sid


def main():
    mode = sys.argv[1]
    sid = open_session()
    if mode == "tools":
        _, body = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
        tools = parse(body)["result"]["tools"]
        print(f"共 {len(tools)} 个工具")
        for tool in tools:
            print(f"- {tool['name']}: {tool['title']}")
        return
    if mode == "resources":
        _, body = post({"jsonrpc": "2.0", "id": 2, "method": "resources/list"}, sid)
        for res in parse(body)["result"]["resources"]:
            print(f"- {res['uri']}: {res['title']}")
        return
    tool = sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    _, body = post(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool, "arguments": args}},
        sid,
    )
    result = parse(body)["result"]
    text = "".join(part.get("text", "") for part in result.get("content", []))
    try:
        print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(text)


if __name__ == "__main__":
    main()
