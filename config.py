#!/usr/bin/env python3
"""
sovereign-agent/config.py
Config system with versioned backups and audit logging.
Read/write ~/.config/sovereign-agent/config.json
Every write creates config.json.v1, v2, etc.
Audit log at ~/.config/sovereign-agent/audit.log
"""

import json
import os
import time
import copy
import shutil
from pathlib import Path
from datetime import datetime

CONFIG_DIR = Path.home() / ".config" / "sovereign-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUDIT_LOG = CONFIG_DIR / "audit.log"
TOKEN_FILE = Path.home() / ".axis-token"

DEFAULT_CONFIG = {
    "version": 1,
    "created": None,
    "updated": None,
    "model": {
        "server_binary": "/usr/local/bin/llama-server",
        "models_dir": str(Path.home() / "models"),
        "default_model": "current.gguf",
        "host": "127.0.0.1",
        "port": 8181,
        "ctx_size": 8192,
        "threads": 4,
        "gpu_layers": 0
    },
    "remote": {
        "enabled": True,
        "url": "https://axismundi.fun/v1/chat/completions",
        "fallback_to_local": True
    },
    "agent": {
        "system_prompt": "You are a sovereign AI agent. You have tools to read and write files, execute shell commands, and manage your own configuration. Be direct, precise, and useful.",
        "max_tokens": 2048,
        "temperature": 0.7,
        "tool_use": True
    },
    "health": {
        "check_interval": 30,
        "max_failures": 3,
        "auto_restart": True,
        "log_file": str(CONFIG_DIR / "health.log")
    },
    "ui": {
        "color_theme": "orange",
        "show_banner": True,
        "show_status": True
    }
}


def _ensure_dirs():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _audit(action, details=""):
    """Append an entry to the audit log."""
    _ensure_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {action}"
    if details:
        entry += f" | {details}"
    entry += "\n"
    with open(AUDIT_LOG, "a") as f:
        f.write(entry)


def _get_next_version():
    """Find the next version number for backup."""
    _ensure_dirs()
    version = 1
    while True:
        backup_path = CONFIG_DIR / f"config.json.v{version}"
        if not backup_path.exists():
            return version
        version += 1


def _backup_current():
    """Create a versioned backup of the current config."""
    if not CONFIG_FILE.exists():
        return None
    version = _get_next_version()
    backup_path = CONFIG_DIR / f"config.json.v{version}"
    shutil.copy2(CONFIG_FILE, backup_path)
    _audit("BACKUP", f"config.json -> config.json.v{version}")
    return version


def load():
    """Load config from disk. Creates default if none exists."""
    _ensure_dirs()
    if not CONFIG_FILE.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        now = datetime.now().isoformat()
        config["created"] = now
        config["updated"] = now
        save(config, source="init", skip_backup=True)
        _audit("INIT", "Created default config")
        return config

    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        return config
    except (json.JSONDecodeError, IOError) as e:
        _audit("ERROR", f"Failed to load config: {e}")
        # Try to recover from latest backup
        recovered = rollback(dry_run=False, silent=True)
        if recovered:
            return recovered
        # Last resort: return defaults
        config = copy.deepcopy(DEFAULT_CONFIG)
        now = datetime.now().isoformat()
        config["created"] = now
        config["updated"] = now
        return config


def save(config, source="unknown", skip_backup=False):
    """Save config to disk with versioned backup."""
    _ensure_dirs()
    if not skip_backup and CONFIG_FILE.exists():
        _backup_current()

    config["updated"] = datetime.now().isoformat()
    if "version" not in config:
        config["version"] = 1
    else:
        if not skip_backup:
            config["version"] = config.get("version", 0) + 1

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    _audit("WRITE", f"source={source} version={config['version']}")
    return config


def get(key_path, default=None):
    """Get a config value by dot-separated path. e.g. 'model.port'"""
    config = load()
    keys = key_path.split(".")
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def set_value(key_path, value, source="agent"):
    """Set a config value by dot-separated path. Creates versioned backup."""
    config = load()
    keys = key_path.split(".")
    current = config
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]

    old_value = current.get(keys[-1], "<unset>")
    current[keys[-1]] = value
    save(config, source=source)
    _audit("SET", f"{key_path}: {old_value} -> {value} (by {source})")
    return config


def rollback(version=None, dry_run=False, silent=False):
    """Roll back to a previous config version."""
    _ensure_dirs()
    if version is not None:
        backup_path = CONFIG_DIR / f"config.json.v{version}"
        if not backup_path.exists():
            if not silent:
                print(f"  No backup at version {version}")
            return None
    else:
        # Find the latest backup
        latest = _get_next_version() - 1
        if latest < 1:
            if not silent:
                print("  No backups available")
            return None
        version = latest
        backup_path = CONFIG_DIR / f"config.json.v{version}"

    try:
        with open(backup_path, "r") as f:
            old_config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        if not silent:
            print(f"  Failed to read backup v{version}: {e}")
        return None

    if dry_run:
        if not silent:
            print(f"  Would rollback to version {version}")
            print(f"  Config from: {old_config.get('updated', 'unknown')}")
        return old_config

    _backup_current()
    with open(CONFIG_FILE, "w") as f:
        json.dump(old_config, f, indent=2)
    _audit("ROLLBACK", f"Restored config.json.v{version}")
    if not silent:
        print(f"  Rolled back to version {version}")
    return old_config


def list_versions():
    """List all available config backup versions."""
    _ensure_dirs()
    versions = []
    v = 1
    while True:
        path = CONFIG_DIR / f"config.json.v{v}"
        if not path.exists():
            break
        stat = path.stat()
        mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size = stat.st_size
        versions.append({
            "version": v,
            "path": str(path),
            "modified": mod_time,
            "size": size
        })
        v += 1
    return versions


def read_token():
    """Read the auth token from ~/.axis-token."""
    try:
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
        return token
    except (IOError, FileNotFoundError):
        return None


def get_audit_log(lines=50):
    """Read the last N lines of the audit log."""
    if not AUDIT_LOG.exists():
        return []
    try:
        with open(AUDIT_LOG, "r") as f:
            all_lines = f.readlines()
        return all_lines[-lines:]
    except IOError:
        return []


def dump():
    """Return the full config as a formatted string."""
    config = load()
    return json.dumps(config, indent=2)


if __name__ == "__main__":
    print("Sovereign Agent Config System")
    print(f"Config dir: {CONFIG_DIR}")
    print(f"Config file: {CONFIG_FILE}")
    print()
    cfg = load()
    print(json.dumps(cfg, indent=2))
    print()
    token = read_token()
    if token:
        print(f"Token: {token[:8]}...{token[-4:]}")
    else:
        print("Token: NOT FOUND")
