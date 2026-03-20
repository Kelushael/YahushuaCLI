#!/usr/bin/env python3
"""
sovereign-agent/api.py
Tiny HTTP API server. Exposes agent state as JSON endpoints.
The dashboard window connects here. No dependencies beyond stdlib + existing modules.
"""

import os
import sys
import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import memory as mem
import context_engine
import tool_registry
import platform as plat

API_PORT = 7777
SCRIPT_DIR = Path(__file__).parent
LOG_PATH = Path.home() / ".config" / "sovereign-agent" / "log.jsonl"


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serves dashboard.html + JSON API endpoints."""

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/dashboard":
            self._serve_file(SCRIPT_DIR / "dashboard.html", "text/html")
        elif path == "/api/status":
            self._json_response(self._get_status())
        elif path == "/api/tools":
            self._json_response(self._get_tools())
        elif path == "/api/memory":
            self._json_response(self._get_memory())
        elif path == "/api/context":
            self._json_response(self._get_context())
        elif path == "/api/log":
            self._json_response(self._get_log())
        elif path == "/api/discards":
            self._json_response(self._get_discards())
        else:
            self.send_error(404)

    def _json_response(self, data):
        body = json.dumps(data, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filepath, content_type):
        if not filepath.exists():
            self.send_error(404, f"Not found: {filepath.name}")
            return
        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _get_status(self):
        cfg = config.load()
        token = config.read_token()
        pi = plat.platform_info()
        dt = tool_registry.list_dynamic_tools()
        mc = mem.count()

        try:
            cs = context_engine.stats()
        except Exception:
            cs = {"indexed_chunks": 0, "active_chunks": 0, "keeps": 0, "discards": 0, "purges": 0}

        try:
            pressure = context_engine.check_pressure()
        except Exception:
            pressure = {"pressure": 0, "status": "unknown"}

        model_cfg = cfg.get("model", {})
        remote_cfg = cfg.get("remote", {})

        return {
            "timestamp": datetime.now().isoformat(),
            "platform": pi,
            "token": {"present": token is not None, "preview": (token[:6] + "..." + token[-4:]) if token else None},
            "model": {
                "host": model_cfg.get("host", "127.0.0.1"),
                "port": model_cfg.get("port", 8181),
            },
            "remote": {
                "enabled": remote_cfg.get("enabled", False),
                "url": remote_cfg.get("url", ""),
            },
            "tools": {
                "builtin": 18,
                "dynamic": len(dt),
                "total": 18 + len(dt),
                "dynamic_names": [t["name"] for t in dt],
            },
            "memory": {"count": mc},
            "context": cs,
            "pressure": pressure,
            "config_version": cfg.get("version", "?"),
        }

    def _get_tools(self):
        from agent import BUILTIN_TOOLS
        builtin = []
        for t in BUILTIN_TOOLS:
            fn = t["function"]
            builtin.append({"name": fn["name"], "description": fn["description"], "type": "builtin"})
        dynamic = []
        for t in tool_registry.list_dynamic_tools():
            dynamic.append({"name": t["name"], "description": t["description"], "type": "dynamic", "path": t["path"]})
        return {"builtin": builtin, "dynamic": dynamic, "total": len(builtin) + len(dynamic)}

    def _get_memory(self):
        mems = mem.list_memories()
        return {"count": len(mems), "memories": mems}

    def _get_context(self):
        try:
            cs = context_engine.stats()
            active = context_engine.get_active_context()
            pressure = context_engine.check_pressure()
            return {"stats": cs, "active": active, "pressure": pressure}
        except Exception as e:
            return {"error": str(e)}

    def _get_log(self):
        if not LOG_PATH.exists():
            return {"entries": [], "count": 0}
        lines = LOG_PATH.read_text().strip().splitlines()
        entries = []
        for line in lines[-50:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return {"entries": entries, "count": len(entries)}

    def _get_discards(self):
        try:
            discards = context_engine.read_discards(20)
            return {"discards": discards, "count": len(discards)}
        except Exception as e:
            return {"error": str(e)}

    def log_message(self, format, *args):
        pass  # Suppress access logs


def start_api(port=API_PORT):
    """Start the dashboard API server in a background thread."""
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def main():
    print(f"Dashboard API starting on http://127.0.0.1:{API_PORT}")
    print(f"Open http://127.0.0.1:{API_PORT}/ in your browser")
    server = HTTPServer(("127.0.0.1", API_PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
