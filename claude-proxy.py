#!/usr/bin/env python3
"""
Local proxy: wraps Claude Code CLI as an Anthropic-compatible API.
BAML calls this instead of api.anthropic.com → uses your Max subscription.

Usage:
    uv run python proxy.py              # starts on port 8199
    uv run python proxy.py --port 8200  # custom port

Then in clients.baml, use ClaudeLocal instead of Claude.
"""

import argparse
import json
import subprocess
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


class ClaudeProxyHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))

        # Extract system prompt and messages from Anthropic Messages API format
        system = body.get("system", "")
        messages = body.get("messages", [])

        # Build a single prompt for `claude -p`
        prompt_parts = []
        if system:
            if isinstance(system, list):
                system = "\n".join(
                    block.get("text", "") for block in system
                    if isinstance(block, dict)
                )
            prompt_parts.append(system)

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            prompt_parts.append(content)

        full_prompt = "\n\n".join(prompt_parts)

        # Call claude -p (non-interactive pipe mode, uses Max subscription)
        try:
            result = subprocess.run(
                ["claude", "-p", "--output-format", "text"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=180,
            )
            response_text = result.stdout.strip()
            if result.returncode != 0:
                err = result.stderr.strip()[:500]
                print(f"[proxy] claude error (rc={result.returncode}): {err}", file=sys.stderr)
                response_text = f"Error from Claude CLI: {err}"
        except subprocess.TimeoutExpired:
            response_text = "Error: Claude CLI timed out after 180s"
        except FileNotFoundError:
            response_text = "Error: 'claude' CLI not found in PATH"

        # Return Anthropic Messages API format
        response = {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}],
            "model": body.get("model", "claude-sonnet-4-6"),
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        print(f"[proxy] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="Claude Code CLI → Anthropic API proxy")
    parser.add_argument("--port", type=int, default=8199, help="Port to listen on")
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), ClaudeProxyHandler)
    print(f"Claude Code proxy on http://127.0.0.1:{args.port}")
    print("BAML → proxy → claude -p (Max subscription, $0 API cost)")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
