#!/usr/bin/env python3
"""
sovereign-agent/memory.py
Persistent memory system. Key-value store backed by JSON files.
Stored at ~/.config/sovereign-agent/memory/
Each memory is {key}.json with {key, value, created, updated}.
Memories persist across sessions and restarts.
"""

import os
import json
from pathlib import Path
from datetime import datetime

MEMORY_DIR = Path.home() / ".config" / "sovereign-agent" / "memory"


def _ensure_dir():
    """Create memory directory if it doesn't exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_key(key):
    """Sanitize a key to be a safe filename. Replaces unsafe chars with underscores."""
    safe = ""
    for c in key:
        if c.isalnum() or c in ("-", "_", "."):
            safe += c
        else:
            safe += "_"
    # Prevent empty or dot-only names
    if not safe or safe.strip(".") == "":
        safe = "_memory"
    return safe


def _key_path(key):
    """Get the file path for a memory key."""
    return MEMORY_DIR / f"{_sanitize_key(key)}.json"


def remember(key, value):
    """Store a value in memory. Overwrites if key exists."""
    _ensure_dir()
    path = _key_path(key)
    now = datetime.now().isoformat()

    # Check if it already exists (preserve created timestamp)
    existing = None
    if path.exists():
        try:
            with open(path, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = None

    entry = {
        "key": key,
        "value": value,
        "created": existing["created"] if existing else now,
        "updated": now,
    }

    with open(path, "w") as f:
        json.dump(entry, f, indent=2, default=str)

    return entry


def recall(key):
    """Retrieve a value from memory. Returns None if not found."""
    path = _key_path(key)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            entry = json.load(f)
        return entry.get("value")
    except (json.JSONDecodeError, IOError):
        return None


def recall_full(key):
    """Retrieve the full memory entry (key, value, created, updated). Returns None if not found."""
    path = _key_path(key)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def forget(key):
    """Remove a memory. Returns True if it existed, False otherwise."""
    path = _key_path(key)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def list_memories():
    """List all stored memory keys with metadata."""
    _ensure_dir()
    memories = []
    for f in sorted(MEMORY_DIR.iterdir()):
        if f.suffix == ".json" and f.is_file():
            try:
                with open(f, "r") as fh:
                    entry = json.load(fh)
                memories.append({
                    "key": entry.get("key", f.stem),
                    "value_preview": _preview(entry.get("value")),
                    "created": entry.get("created", "unknown"),
                    "updated": entry.get("updated", "unknown"),
                })
            except (json.JSONDecodeError, IOError):
                memories.append({
                    "key": f.stem,
                    "value_preview": "<corrupted>",
                    "created": "unknown",
                    "updated": "unknown",
                })
    return memories


def _preview(value, max_len=80):
    """Create a short preview of a value."""
    if value is None:
        return "null"
    if isinstance(value, str):
        if len(value) <= max_len:
            return value
        return value[:max_len] + "..."
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        s = json.dumps(value, default=str)
        if len(s) <= max_len:
            return s
        return s[:max_len] + "..."
    return str(value)[:max_len]


def count():
    """Return the number of stored memories."""
    _ensure_dir()
    return sum(1 for f in MEMORY_DIR.iterdir() if f.suffix == ".json" and f.is_file())


def search(query):
    """Search memories by key or value content. Returns matching entries."""
    query_lower = query.lower()
    results = []
    _ensure_dir()
    for f in sorted(MEMORY_DIR.iterdir()):
        if f.suffix == ".json" and f.is_file():
            try:
                with open(f, "r") as fh:
                    entry = json.load(fh)
                key = entry.get("key", "")
                value_str = json.dumps(entry.get("value", ""), default=str)
                if query_lower in key.lower() or query_lower in value_str.lower():
                    results.append(entry)
            except (json.JSONDecodeError, IOError):
                continue
    return results


if __name__ == "__main__":
    print("Sovereign Agent -- Memory System")
    print(f"Memory dir: {MEMORY_DIR}")
    print(f"Stored memories: {count()}")
    print()
    mems = list_memories()
    if mems:
        for m in mems:
            print(f"  {m['key']}: {m['value_preview']}")
    else:
        print("  No memories stored yet.")
