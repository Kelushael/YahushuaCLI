#!/usr/bin/env python3
"""
sovereign-agent/context_engine.py
Strategic context management. The agent swipes left/right on information.
Kept chunks stay in context. Discarded chunks go to you in a discard log.
Everything is indexed in SQLite FTS5 for instant recall.

The agent manages its own mind.
"""

import os
import json
import sqlite3
import hashlib
import time
from pathlib import Path
from datetime import datetime

DB_DIR = Path.home() / ".config" / "sovereign-agent"
DB_PATH = DB_DIR / "context.db"
DISCARD_LOG = DB_DIR / "discards.jsonl"

# How many tokens (approx) to keep in active context before agent should start swiping
CONTEXT_PRESSURE_THRESHOLD = 80000  # ~80k tokens = time to start curating
CHARS_PER_TOKEN = 4  # rough estimate


def _ensure_db():
    """Create the SQLite FTS5 database if it doesn't exist."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Main indexed store — everything the agent has seen or said
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            chunk_id,
            session_id,
            role,
            content,
            tags,
            timestamp,
            source
        )
    """)

    # Active context — what the agent currently holds in mind
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_context (
            chunk_id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            role TEXT NOT NULL,
            priority INTEGER DEFAULT 5,
            added_at TEXT NOT NULL,
            token_estimate INTEGER DEFAULT 0
        )
    """)

    # Decisions log — every keep/discard the agent makes
    c.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def _conn():
    _ensure_db()
    return sqlite3.connect(str(DB_PATH))


def _estimate_tokens(text):
    return len(text) // CHARS_PER_TOKEN


def _chunk_id(content, role="unknown"):
    h = hashlib.sha256(f"{role}:{content[:500]}:{time.time()}".encode()).hexdigest()[:16]
    return h


# ============================================================
# INGEST — chunk incoming information
# ============================================================

def ingest(content, role="user", tags="", source="chat", session_id="default"):
    """
    Ingest a piece of information into the index.
    Returns chunk_id. Does NOT add to active context — agent decides that.
    """
    conn = _conn()
    cid = _chunk_id(content, role)
    ts = datetime.now().isoformat()

    conn.execute(
        "INSERT INTO chunks (chunk_id, session_id, role, content, tags, timestamp, source) VALUES (?,?,?,?,?,?,?)",
        (cid, session_id, role, content, tags, ts, source)
    )
    conn.commit()
    conn.close()
    return cid


# ============================================================
# SWIPE RIGHT — agent keeps this in active context
# ============================================================

def keep(content, role="user", priority=5, reason=""):
    """Agent swipes right. This stays in active context."""
    conn = _conn()
    cid = _chunk_id(content, role)
    ts = datetime.now().isoformat()
    tokens = _estimate_tokens(content)

    # Index it
    conn.execute(
        "INSERT INTO chunks (chunk_id, session_id, role, content, tags, timestamp, source) VALUES (?,?,?,?,?,?,?)",
        (cid, "active", role, content, "kept", ts, "context_engine")
    )

    # Add to active context
    conn.execute(
        "INSERT OR REPLACE INTO active_context (chunk_id, content, role, priority, added_at, token_estimate) VALUES (?,?,?,?,?,?)",
        (cid, content, role, priority, ts, tokens)
    )

    # Log the decision
    conn.execute(
        "INSERT INTO decisions (chunk_id, action, reason, timestamp) VALUES (?,?,?,?)",
        (cid, "keep", reason, ts)
    )

    conn.commit()
    conn.close()
    return {"action": "kept", "chunk_id": cid, "tokens": tokens}


# ============================================================
# SWIPE LEFT — agent discards this, you get it in the discard log
# ============================================================

def discard(content, role="user", reason=""):
    """Agent swipes left. Goes to discard log for Marcus to review."""
    conn = _conn()
    cid = _chunk_id(content, role)
    ts = datetime.now().isoformat()

    # Still index it — searchable later via recall
    conn.execute(
        "INSERT INTO chunks (chunk_id, session_id, role, content, tags, timestamp, source) VALUES (?,?,?,?,?,?,?)",
        (cid, "discarded", role, content, "discarded", ts, "context_engine")
    )

    # Log the decision
    conn.execute(
        "INSERT INTO decisions (chunk_id, action, reason, timestamp) VALUES (?,?,?,?)",
        (cid, "discard", reason, ts)
    )

    conn.commit()
    conn.close()

    # Append to the discard log — Marcus's copy of everything the agent threw out
    entry = {
        "chunk_id": cid,
        "role": role,
        "content": content,
        "reason": reason,
        "timestamp": ts
    }
    with open(DISCARD_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return {"action": "discarded", "chunk_id": cid, "logged_to": str(DISCARD_LOG)}


# ============================================================
# PURGE — agent removes something from active context
# ============================================================

def purge(chunk_id, reason=""):
    """Remove a chunk from active context. Still searchable in index."""
    conn = _conn()
    ts = datetime.now().isoformat()

    # Get the content before removing
    row = conn.execute("SELECT content, role FROM active_context WHERE chunk_id=?", (chunk_id,)).fetchone()
    if row:
        conn.execute("DELETE FROM active_context WHERE chunk_id=?", (chunk_id,))
        conn.execute(
            "INSERT INTO decisions (chunk_id, action, reason, timestamp) VALUES (?,?,?,?)",
            (chunk_id, "purge", reason, ts)
        )
        conn.commit()

        # Also log to discards so Marcus sees it
        entry = {"chunk_id": chunk_id, "role": row[1], "content": row[0],
                 "reason": f"purged: {reason}", "timestamp": ts}
        with open(DISCARD_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")

    conn.close()
    return {"action": "purged", "chunk_id": chunk_id}


# ============================================================
# RECALL — agent searches everything it's ever seen
# ============================================================

def recall(query, limit=5):
    """Search the full index. Returns matching chunks ranked by relevance."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT chunk_id, role, content, tags, timestamp, source FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 query syntax error — fall back to simple LIKE
        rows = conn.execute(
            "SELECT chunk_id, role, content, tags, timestamp, source FROM chunks WHERE content LIKE ? LIMIT ?",
            (f"%{query}%", limit)
        ).fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "chunk_id": r[0], "role": r[1],
            "content": r[2][:500],  # return max 500 chars per result
            "tags": r[3], "timestamp": r[4], "source": r[5]
        })
    return results


# ============================================================
# ACTIVE CONTEXT — what the agent is currently holding
# ============================================================

def get_active_context():
    """Get everything in active context, ordered by priority."""
    conn = _conn()
    rows = conn.execute(
        "SELECT chunk_id, content, role, priority, added_at, token_estimate FROM active_context ORDER BY priority DESC, added_at ASC"
    ).fetchall()
    conn.close()

    total_tokens = 0
    chunks = []
    for r in rows:
        total_tokens += r[5]
        chunks.append({
            "chunk_id": r[0], "content": r[1], "role": r[2],
            "priority": r[3], "added_at": r[4], "tokens": r[5]
        })

    return {
        "chunks": chunks,
        "count": len(chunks),
        "total_tokens": total_tokens,
        "pressure": total_tokens / CONTEXT_PRESSURE_THRESHOLD
    }


def get_context_as_text():
    """Get active context as a single text block for injection into the model."""
    ctx = get_active_context()
    if not ctx["chunks"]:
        return ""

    lines = []
    for c in ctx["chunks"]:
        lines.append(f"[{c['role']}|p{c['priority']}] {c['content']}")
    return "\n---\n".join(lines)


# ============================================================
# PRESSURE CHECK — should the agent start curating?
# ============================================================

def check_pressure():
    """Check if context pressure is high. Returns advice for the agent."""
    ctx = get_active_context()
    pressure = ctx["pressure"]

    if pressure < 0.5:
        return {"pressure": pressure, "status": "low", "action": "none"}
    elif pressure < 0.8:
        return {"pressure": pressure, "status": "medium",
                "action": "consider purging low-priority chunks",
                "lowest_priority_chunks": [c["chunk_id"] for c in ctx["chunks"] if c["priority"] <= 3][:5]}
    else:
        return {"pressure": pressure, "status": "high",
                "action": "purge aggressively — keep only priority 7+",
                "purgeable": [c["chunk_id"] for c in ctx["chunks"] if c["priority"] <= 6]}


# ============================================================
# STATS
# ============================================================

def stats():
    """Get stats about the context engine."""
    conn = _conn()
    total_indexed = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    total_active = conn.execute("SELECT COUNT(*) FROM active_context").fetchone()[0]
    total_decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    total_keeps = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='keep'").fetchone()[0]
    total_discards = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='discard'").fetchone()[0]
    total_purges = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='purge'").fetchone()[0]
    conn.close()

    discard_count = 0
    if DISCARD_LOG.exists():
        discard_count = sum(1 for _ in open(DISCARD_LOG))

    return {
        "indexed_chunks": total_indexed,
        "active_chunks": total_active,
        "decisions": total_decisions,
        "keeps": total_keeps,
        "discards": total_discards,
        "purges": total_purges,
        "discard_log_entries": discard_count,
        "db_size_kb": round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0
    }


# ============================================================
# DISCARD LOG — Marcus's copy of everything the agent threw out
# ============================================================

def read_discards(last_n=20):
    """Read the last N entries from the discard log."""
    if not DISCARD_LOG.exists():
        return []
    lines = DISCARD_LOG.read_text().strip().splitlines()
    entries = []
    for line in lines[-last_n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


if __name__ == "__main__":
    _ensure_db()
    print("Context engine initialized.")
    print(f"  DB: {DB_PATH}")
    print(f"  Discard log: {DISCARD_LOG}")
    print(f"  Stats: {json.dumps(stats(), indent=2)}")
