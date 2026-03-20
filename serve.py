#!/usr/bin/env python3
"""
sovereign-agent/serve.py
Starts llama-server (llama.cpp binary) directly on a GGUF file.
No ollama. Manages the process, health checks it, restarts on failure.
"""

import subprocess
import os
import sys
import time
import signal
import json
import requests
from pathlib import Path
from datetime import datetime

# Local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import chat


class ModelServer:
    """Manages a llama-server process."""

    def __init__(self):
        self.process = None
        self.pid = None
        self.started_at = None
        self.restarts = 0
        self._load_config()

    def _load_config(self):
        """Load server configuration."""
        cfg = config.load()
        m = cfg.get("model", {})
        self.binary = m.get("server_binary", "/usr/local/bin/llama-server")
        self.models_dir = Path(m.get("models_dir", str(Path.home() / "models")))
        self.default_model = m.get("default_model", "current.gguf")
        self.host = m.get("host", "127.0.0.1")
        self.port = m.get("port", 8181)
        self.ctx_size = m.get("ctx_size", 8192)
        self.threads = m.get("threads", 4)
        self.gpu_layers = m.get("gpu_layers", 0)

    def _model_path(self, model_name=None):
        """Resolve full path to a GGUF model file."""
        name = model_name or self.default_model
        path = self.models_dir / name
        # If it's a symlink, that's fine — llama-server follows them
        return path

    def _build_command(self, model_name=None):
        """Build the llama-server command line."""
        model_path = self._model_path(model_name)
        cmd = [
            self.binary,
            "--model", str(model_path),
            "--host", self.host,
            "--port", str(self.port),
            "--ctx-size", str(self.ctx_size),
            "--threads", str(self.threads),
        ]
        if self.gpu_layers > 0:
            cmd.extend(["--n-gpu-layers", str(self.gpu_layers)])
        return cmd

    def find_models(self):
        """List available GGUF models."""
        models = []
        if not self.models_dir.exists():
            return models
        for f in sorted(self.models_dir.iterdir()):
            if f.suffix == ".gguf" or (f.is_symlink() and f.name.endswith(".gguf")):
                size_mb = 0
                try:
                    size_mb = f.stat().st_size / (1024 * 1024)
                except OSError:
                    pass
                is_link = f.is_symlink()
                target = ""
                if is_link:
                    try:
                        target = str(f.resolve().name)
                    except OSError:
                        target = "broken"
                models.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(size_mb, 1),
                    "is_symlink": is_link,
                    "target": target
                })
        return models

    def is_binary_available(self):
        """Check if llama-server binary exists and is executable."""
        p = Path(self.binary)
        return p.exists() and os.access(str(p), os.X_OK)

    def is_running(self):
        """Check if the server process is still running."""
        if self.process is None:
            return False
        poll = self.process.poll()
        return poll is None

    def is_healthy(self):
        """Ping the server's health endpoint."""
        try:
            url = f"http://{self.host}:{self.port}/health"
            r = requests.get(url, timeout=5)
            return r.status_code == 200
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            return False

    def get_status(self):
        """Get a status dict for the server."""
        running = self.is_running()
        healthy = False
        if running:
            healthy = self.is_healthy()
        return {
            "running": running,
            "healthy": healthy,
            "pid": self.process.pid if self.process and running else None,
            "port": self.port,
            "host": self.host,
            "started_at": self.started_at,
            "restarts": self.restarts,
            "binary": self.binary,
            "binary_exists": self.is_binary_available()
        }

    def start(self, model_name=None, quiet=False):
        """Start the llama-server process."""
        if self.is_running():
            if not quiet:
                chat.warning("  Server already running (PID {})".format(self.process.pid))
            return True

        if not self.is_binary_available():
            chat.error_msg(f"llama-server not found at {self.binary}")
            return False

        model_path = self._model_path(model_name)
        if not model_path.exists():
            chat.error_msg(f"Model not found: {model_path}")
            available = self.find_models()
            if available:
                chat.out("  Available models:")
                for m in available:
                    chat.bullet(f"{m['name']} ({m['size_mb']} MB)")
            else:
                chat.out(f"  No GGUF files found in {self.models_dir}")
                chat.out(f"  Create the directory and place a .gguf file there.")
            return False

        cmd = self._build_command(model_name)
        if not quiet:
            chat.system_msg(f"Starting llama-server on port {self.port}")
            chat.system_msg(f"Model: {model_path.name}")

        try:
            # Redirect stdout/stderr to /dev/null or a log file
            log_path = config.CONFIG_DIR / "server.log"
            log_file = open(log_path, "a")
            log_file.write(f"\n--- Server start: {datetime.now().isoformat()} ---\n")
            log_file.write(f"Command: {' '.join(cmd)}\n")
            log_file.flush()

            self.process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            self.pid = self.process.pid
            self.started_at = datetime.now().isoformat()

            if not quiet:
                chat.system_msg(f"Server started (PID {self.pid})")

            # Wait a moment for it to bind the port
            if not quiet:
                chat.system_msg("Waiting for server to be ready...")

            for attempt in range(30):
                time.sleep(1)
                if self.is_healthy():
                    if not quiet:
                        chat.out(chat.success(f"  Server ready on port {self.port}"))
                    config._audit("SERVER_START", f"pid={self.pid} model={model_path.name}")
                    return True
                # Check if process died
                if self.process.poll() is not None:
                    if not quiet:
                        chat.error_msg("Server process exited unexpectedly")
                        chat.out(f"  Check log: {log_path}")
                    self.process = None
                    return False

            # Timeout waiting for health
            if not quiet:
                chat.warning("  Server started but health check not responding after 30s")
                chat.out(f"  It may still be loading the model. Check: {log_path}")
            return True  # Process is running, just slow to load

        except (OSError, subprocess.SubprocessError) as e:
            chat.error_msg(f"Failed to start server: {e}")
            return False

    def stop(self, quiet=False):
        """Stop the llama-server process."""
        if not self.is_running():
            if not quiet:
                chat.system_msg("Server is not running")
            return True

        pid = self.process.pid
        if not quiet:
            chat.system_msg(f"Stopping server (PID {pid})")

        try:
            # Send SIGTERM first
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.process.terminate()
            except OSError:
                pass

        # Wait for graceful shutdown
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if not quiet:
                chat.warning("  Server didn't stop gracefully, sending SIGKILL")
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    self.process.kill()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        self.process = None
        if not quiet:
            chat.out(chat.success(f"  Server stopped"))
        config._audit("SERVER_STOP", f"pid={pid}")
        return True

    def restart(self, model_name=None, quiet=False):
        """Restart the server."""
        self.restarts += 1
        self.stop(quiet=quiet)
        time.sleep(1)
        return self.start(model_name=model_name, quiet=quiet)

    def chat_completion(self, messages, temperature=None, max_tokens=None):
        """Send a chat completion request to the running server."""
        cfg = config.load()
        agent_cfg = cfg.get("agent", {})
        temp = temperature if temperature is not None else agent_cfg.get("temperature", 0.7)
        tokens = max_tokens if max_tokens is not None else agent_cfg.get("max_tokens", 2048)

        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        payload = {
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
            "stream": False
        }

        try:
            r = requests.post(url, json=payload, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def chat_completion_stream(self, messages, temperature=None, max_tokens=None):
        """Send a streaming chat completion request. Yields tokens."""
        cfg = config.load()
        agent_cfg = cfg.get("agent", {})
        temp = temperature if temperature is not None else agent_cfg.get("temperature", 0.7)
        tokens = max_tokens if max_tokens is not None else agent_cfg.get("max_tokens", 2048)

        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        payload = {
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
            "stream": True
        }

        try:
            r = requests.post(url, json=payload, timeout=120, stream=True)
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
        except requests.RequestException as e:
            yield f"\n[stream error: {e}]"


def find_existing_server(port=8181, host="127.0.0.1"):
    """Check if a llama-server is already running on the given port."""
    try:
        url = f"http://{host}:{port}/health"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            return True
    except (requests.ConnectionError, requests.Timeout):
        pass
    return False


if __name__ == "__main__":
    print("Sovereign Agent — Model Server Manager")
    print()
    server = ModelServer()

    if not server.is_binary_available():
        print(f"  llama-server not found at {server.binary}")
    else:
        print(f"  Binary: {server.binary} (OK)")

    print(f"  Models dir: {server.models_dir}")
    models = server.find_models()
    if models:
        for m in models:
            sym = f" -> {m['target']}" if m['is_symlink'] else ""
            print(f"    {m['name']} ({m['size_mb']} MB){sym}")
    else:
        print("    No models found")

    existing = find_existing_server(server.port, server.host)
    if existing:
        print(f"  Server already running on port {server.port}")
    else:
        print(f"  No server on port {server.port}")
