#!/usr/bin/env python3
"""
gesher.py — Anthropic-compatible API bridge
Sits on the VPS. Accepts Anthropic Messages API format,
translates to OpenAI format, forwards to llama-server,
translates response back. Claude Code points here directly.

Run:  python3 gesher.py
Port: 8182 (nginx routes /v1/messages here)

llama-server on 8181 stays untouched.
This is the Gesher-el bridge layer.
"""

import json
import time
import uuid
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading

# Where llama-server lives
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8181")
BRIDGE_PORT = int(os.environ.get("GESHER_PORT", "8182"))

# We use urllib to avoid requiring 'requests' on the VPS
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def translate_request(anthropic_body):
    """Anthropic Messages API → OpenAI Chat Completions."""
    messages = []

    # System message
    system = anthropic_body.get("system")
    if system:
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            # Anthropic allows system as array of content blocks
            text = " ".join(b.get("text", "") for b in system if b.get("type") == "text")
            if text:
                messages.append({"role": "system", "content": text})

    # Convert messages
    for msg in anthropic_body.get("messages", []):
        role = msg["role"]
        content = msg.get("content", "")

        # Anthropic content can be string or array of content blocks
        if isinstance(content, list):
            # Extract text blocks, skip images/tool_use for now
            text_parts = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        text_parts.append(json.dumps(block.get("content", "")))
                    elif block.get("type") == "tool_use":
                        # Pass tool calls through as text for now
                        text_parts.append(f"[tool_use: {block.get('name', '')}({json.dumps(block.get('input', {}))})]")
            content = "\n".join(text_parts)

        messages.append({"role": role, "content": content})

    openai_body = {
        "messages": messages,
        "max_tokens": anthropic_body.get("max_tokens", 4096),
        "temperature": anthropic_body.get("temperature", 0.7),
        "stream": anthropic_body.get("stream", False),
    }

    # Model — pass through but llama-server ignores it
    model = anthropic_body.get("model", "default")
    openai_body["model"] = model

    # Top-p
    if "top_p" in anthropic_body:
        openai_body["top_p"] = anthropic_body["top_p"]

    # Stop sequences
    if "stop_sequences" in anthropic_body:
        openai_body["stop"] = anthropic_body["stop_sequences"]

    return openai_body


def translate_response(openai_resp, model="sovereign"):
    """OpenAI Chat Completions response → Anthropic Messages API response."""
    choices = openai_resp.get("choices", [])
    if not choices:
        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": ""}],
            "model": model,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    choice = choices[0]
    message = choice.get("message", {})
    # Some models (GLM-4.7) put text in reasoning_content instead of content
    text = message.get("content", "") or message.get("reasoning_content", "") or ""

    # Map finish_reason
    fr = choice.get("finish_reason", "stop")
    stop_reason_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }
    stop_reason = stop_reason_map.get(fr, "end_turn")

    usage = openai_resp.get("usage", {})

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def translate_stream_event(openai_chunk, model="sovereign"):
    """Translate a single OpenAI SSE chunk to Anthropic SSE format."""
    choices = openai_chunk.get("choices", [])
    if not choices:
        return None

    delta = choices[0].get("delta", {})
    finish = choices[0].get("finish_reason")
    content = delta.get("content", "")

    if finish:
        return {
            "type": "content_block_stop",
            "index": 0,
        }

    if content:
        return {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": content},
        }

    return None


class GesherHandler(BaseHTTPRequestHandler):
    """Handles Anthropic Messages API and proxies to llama-server."""

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/v1/messages":
            self._handle_messages()
        else:
            self.send_error(404, f"Not found: {path}")

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/v1/models":
            # Proxy models endpoint, translate to Anthropic-ish format
            self._proxy_models()
        elif path == "/health" or path == "/":
            self._json_response({"status": "ok", "bridge": "gesher-el", "upstream": LLAMA_URL})
        else:
            self.send_error(404)

    def _handle_messages(self):
        """POST /v1/messages — the main bridge."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            anthropic_body = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        is_stream = anthropic_body.get("stream", False)
        model = anthropic_body.get("model", "sovereign")

        # Translate to OpenAI format (always non-stream to upstream;
        # we simulate Anthropic SSE from the full response)
        openai_body = translate_request(anthropic_body)
        openai_body["stream"] = False

        # Forward to llama-server
        try:
            req = Request(
                f"{LLAMA_URL}/v1/chat/completions",
                data=json.dumps(openai_body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=300)
        except (URLError, HTTPError) as e:
            error_msg = str(e)
            self._json_response(
                {
                    "type": "error",
                    "error": {"type": "api_error", "message": f"Upstream error: {error_msg}"},
                },
                status=502,
            )
            return

        if is_stream:
            self._handle_stream(resp, model)
        else:
            # Non-streaming
            resp_body = resp.read().decode()
            try:
                openai_resp = json.loads(resp_body)
            except json.JSONDecodeError:
                self._json_response(
                    {"type": "error", "error": {"type": "api_error", "message": "Bad upstream response"}},
                    status=502,
                )
                return

            anthropic_resp = translate_response(openai_resp, model)
            self._json_response(anthropic_resp)

    def _handle_stream(self, resp, model):
        """Simulate Anthropic SSE stream from a non-streaming upstream response."""
        # Read full response from llama-server (non-streaming)
        resp_body = resp.read().decode()
        try:
            openai_resp = json.loads(resp_body)
        except json.JSONDecodeError:
            self._json_response(
                {"type": "error", "error": {"type": "api_error", "message": "Bad upstream response"}},
                status=502,
            )
            return

        # Extract text (GLM-4.7 uses reasoning_content instead of content)
        choices = openai_resp.get("choices", [])
        text = ""
        if choices:
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or msg.get("reasoning_content", "") or ""
        usage = openai_resp.get("usage", {})

        # Now emit Anthropic SSE events
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        msg_id = f"msg_{uuid.uuid4().hex[:24]}"

        # message_start
        self._send_sse("message_start", {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": 0,
                },
            },
        })

        # content_block_start
        self._send_sse("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        })

        # Emit text in chunks to simulate streaming
        chunk_size = 12  # characters per delta event
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            self._send_sse("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": chunk},
            })

        # content_block_stop
        self._send_sse("content_block_stop", {"type": "content_block_stop", "index": 0})

        # message_delta
        self._send_sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": usage.get("completion_tokens", 0)},
        })

        # message_stop
        self._send_sse("message_stop", {"type": "message_stop"})

    def _send_sse(self, event_type, data):
        """Send a single SSE event."""
        try:
            line = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(line.encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _proxy_models(self):
        """GET /v1/models — return what llama-server has."""
        try:
            req = Request(f"{LLAMA_URL}/v1/models")
            resp = urlopen(req, timeout=10)
            models_data = json.loads(resp.read().decode())
            self._json_response(models_data)
        except Exception:
            self._json_response({"data": [], "object": "list"})

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quiet by default. Uncomment for debug:
        # print(f"[gesher] {args[0]}", flush=True)
        pass


def main():
    print(f"Gesher-el bridge starting on :{BRIDGE_PORT}")
    print(f"  Upstream: {LLAMA_URL}")
    print(f"  Accepts:  POST /v1/messages (Anthropic format)")
    print(f"  Proxies:  → {LLAMA_URL}/v1/chat/completions (OpenAI format)")
    print(f"  Health:   GET /health")
    print()

    server = HTTPServer(("0.0.0.0", BRIDGE_PORT), GesherHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGesher-el bridge stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
