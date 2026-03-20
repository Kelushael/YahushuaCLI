#!/usr/bin/env python3
"""
sovereign-agent/health.py
Health daemon. Pings /health on the model server every 30s.
If 3 consecutive failures, attempts restart. If restart fails, falls back to local.
Logs everything.
"""

import os
import sys
import time
import threading
import json
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import chat


class HealthDaemon:
    """Watches the model server and takes action on failure."""

    def __init__(self, server=None):
        self.server = server  # ModelServer instance (optional)
        self._running = False
        self._thread = None
        self._consecutive_failures = 0
        self._total_checks = 0
        self._total_failures = 0
        self._total_restarts = 0
        self._last_check = None
        self._last_status = None
        self._fell_back = False
        self._load_config()

    def _load_config(self):
        """Load health check configuration."""
        cfg = config.load()
        h = cfg.get("health", {})
        self.check_interval = h.get("check_interval", 30)
        self.max_failures = h.get("max_failures", 3)
        self.auto_restart = h.get("auto_restart", True)
        self.log_file = Path(h.get("log_file", str(config.CONFIG_DIR / "health.log")))

        m = cfg.get("model", {})
        self.host = m.get("host", "127.0.0.1")
        self.port = m.get("port", 8181)

        r = cfg.get("remote", {})
        self.remote_enabled = r.get("enabled", True)
        self.remote_url = r.get("url", "https://axismundi.fun/v1/chat/completions")
        self.fallback_to_local = r.get("fallback_to_local", True)

    def _log(self, level, message):
        """Write to the health log file."""
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}\n"
        try:
            with open(self.log_file, "a") as f:
                f.write(entry)
        except IOError:
            pass

    def _check_server(self):
        """Ping the server health endpoint. Returns True if healthy."""
        try:
            url = f"http://{self.host}:{self.port}/health"
            r = requests.get(url, timeout=5)
            return r.status_code == 200
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            return False

    def _check_remote(self):
        """Check if the remote endpoint is reachable."""
        if not self.remote_enabled:
            return False
        try:
            # Just check if the host responds; don't send a full request
            token = config.read_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            # Use a lightweight request — OPTIONS or a minimal POST
            r = requests.post(
                self.remote_url,
                json={"messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                headers=headers,
                timeout=10
            )
            # Any response (even 400) means the server is reachable
            return r.status_code < 500
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            return False

    def _attempt_restart(self):
        """Try to restart the local model server."""
        self._total_restarts += 1
        self._log("WARN", f"Attempting server restart (attempt #{self._total_restarts})")

        if self.server is not None:
            success = self.server.restart(quiet=True)
            if success:
                self._log("INFO", "Server restarted successfully")
                self._consecutive_failures = 0
                return True
            else:
                self._log("ERROR", "Server restart failed")
                return False
        else:
            self._log("ERROR", "No server instance available for restart")
            return False

    def _fallback(self):
        """Fall back to remote endpoint or report failure."""
        if self._fell_back:
            return  # Already fell back

        if self.remote_enabled and self.fallback_to_local:
            # We're the local, so "fallback" means switch to remote
            self._log("WARN", "Local server unrecoverable. Checking remote endpoint.")
            remote_ok = self._check_remote()
            if remote_ok:
                self._log("INFO", "Remote endpoint available. Falling back to remote.")
                config.set_value("agent.use_remote", True, source="health_daemon")
                self._fell_back = True
            else:
                self._log("ERROR", "Remote endpoint also unreachable. No fallback available.")
        else:
            self._log("ERROR", "No fallback configured. Server is down.")

    def _run_loop(self):
        """Main health check loop. Runs in a background thread."""
        self._log("INFO", f"Health daemon started. Interval: {self.check_interval}s, Max failures: {self.max_failures}")

        while self._running:
            self._total_checks += 1
            healthy = self._check_server()
            self._last_check = datetime.now().isoformat()
            self._last_status = "healthy" if healthy else "unhealthy"

            if healthy:
                if self._consecutive_failures > 0:
                    self._log("INFO", f"Server recovered after {self._consecutive_failures} failures")
                self._consecutive_failures = 0
                # If we had fallen back, restore local
                if self._fell_back:
                    self._log("INFO", "Local server recovered. Switching back from remote.")
                    config.set_value("agent.use_remote", False, source="health_daemon")
                    self._fell_back = False
            else:
                self._consecutive_failures += 1
                self._total_failures += 1
                self._log("WARN", f"Health check failed ({self._consecutive_failures}/{self.max_failures})")

                if self._consecutive_failures >= self.max_failures:
                    if self.auto_restart:
                        success = self._attempt_restart()
                        if not success:
                            self._fallback()
                    else:
                        self._log("WARN", "Auto-restart disabled. Server remains down.")
                        self._fallback()

            # Sleep in small increments so we can stop quickly
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

        self._log("INFO", "Health daemon stopped")

    def start(self):
        """Start the health daemon in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the health daemon."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def is_running(self):
        """Check if the daemon is running."""
        return self._running and self._thread is not None and self._thread.is_alive()

    def get_status(self):
        """Get current daemon status."""
        return {
            "running": self.is_running(),
            "last_check": self._last_check,
            "last_status": self._last_status,
            "consecutive_failures": self._consecutive_failures,
            "total_checks": self._total_checks,
            "total_failures": self._total_failures,
            "total_restarts": self._total_restarts,
            "fell_back": self._fell_back,
            "check_interval": self.check_interval,
            "max_failures": self.max_failures
        }

    def check_once(self):
        """Run a single health check (not in background). Returns status dict."""
        healthy = self._check_server()
        remote_ok = self._check_remote() if self.remote_enabled else None
        return {
            "local_healthy": healthy,
            "remote_reachable": remote_ok,
            "host": self.host,
            "port": self.port,
            "remote_url": self.remote_url if self.remote_enabled else None,
            "timestamp": datetime.now().isoformat()
        }

    def read_log(self, lines=30):
        """Read the last N lines of the health log."""
        if not self.log_file.exists():
            return []
        try:
            with open(self.log_file, "r") as f:
                all_lines = f.readlines()
            return all_lines[-lines:]
        except IOError:
            return []


if __name__ == "__main__":
    print("Sovereign Agent — Health Check")
    print()
    daemon = HealthDaemon()
    result = daemon.check_once()
    print(f"  Local server ({result['host']}:{result['port']}): ", end="")
    if result["local_healthy"]:
        print("HEALTHY")
    else:
        print("DOWN")

    if result["remote_reachable"] is not None:
        print(f"  Remote ({result['remote_url']}): ", end="")
        if result["remote_reachable"]:
            print("REACHABLE")
        else:
            print("UNREACHABLE")

    print()
    print("  Run as daemon: python3 health.py --daemon")

    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        print()
        print("  Starting health daemon (Ctrl+C to stop)...")
        daemon.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            print("  Stopping...")
            daemon.stop()
            print("  Done.")
