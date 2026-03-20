#!/usr/bin/env python3
"""
sovereign-agent/mcp_server.py
Sovereign MCP server. One server, ALL tools. Zero config.

Speaks the MCP protocol over stdin/stdout (JSON-RPC 2.0).
Any MCP-compatible client (Claude Code, Cursor, etc.) can connect.

Tools included:
  - context_keep / context_discard / context_recall / context_purge / context_pressure
  - remember / recall_memory / forget / list_memories
  - ssh_exec
  - read_file / write_file / edit_file / list_dir / search_files
  - exec_shell
  - read_config / write_config
  - create_tool / list_tools
  - create_ui
  - platform_info
"""

import sys
import json
import os
from pathlib import Path

# Ensure our modules are importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import context_engine
import memory
import ssh_tool
import tool_registry
import config
import platform as plat
import ui

# ============================================================
# Tool definitions — the full sovereign toolkit
# ============================================================

TOOLS = [
    # --- Context Engine ---
    {"name": "context_keep", "description": "Swipe right. Keep this information in active context.",
     "inputSchema": {"type": "object", "properties": {
         "content": {"type": "string", "description": "The information to keep"},
         "role": {"type": "string", "description": "Who said it: user, agent, tool", "default": "user"},
         "priority": {"type": "integer", "description": "1-10, higher = more important", "default": 5},
         "reason": {"type": "string", "description": "Why keeping this"}
     }, "required": ["content"]}},

    {"name": "context_discard", "description": "Swipe left. Discard from context. Gets logged for user to review.",
     "inputSchema": {"type": "object", "properties": {
         "content": {"type": "string", "description": "The information to discard"},
         "role": {"type": "string", "description": "Who said it", "default": "user"},
         "reason": {"type": "string", "description": "Why discarding"}
     }, "required": ["content"]}},

    {"name": "context_recall", "description": "Search everything the agent has ever seen or said. FTS5 full-text search.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Search query"},
         "limit": {"type": "integer", "description": "Max results", "default": 5}
     }, "required": ["query"]}},

    {"name": "context_purge", "description": "Remove a specific chunk from active context by ID.",
     "inputSchema": {"type": "object", "properties": {
         "chunk_id": {"type": "string"}, "reason": {"type": "string"}
     }, "required": ["chunk_id"]}},

    {"name": "context_pressure", "description": "Check context pressure. Returns advice on whether to purge.",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "context_stats", "description": "Get stats on the context engine: indexed, active, decisions made.",
     "inputSchema": {"type": "object", "properties": {}}},

    # --- Memory ---
    {"name": "remember", "description": "Store a persistent memory. Survives across sessions.",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "value": {"type": "string"}
     }, "required": ["key", "value"]}},

    {"name": "recall_memory", "description": "Retrieve a memory by key.",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}
     }, "required": ["key"]}},

    {"name": "forget", "description": "Remove a memory.",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}
     }, "required": ["key"]}},

    {"name": "list_memories", "description": "List all stored memories.",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "search_memories", "description": "Search memories by keyword.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}
     }, "required": ["query"]}},

    # --- SSH ---
    {"name": "ssh_exec", "description": "Execute a command on a remote host via SSH.",
     "inputSchema": {"type": "object", "properties": {
         "host": {"type": "string", "description": "user@host or SSH alias"},
         "command": {"type": "string"},
         "timeout": {"type": "integer", "default": 30},
         "identity": {"type": "string", "description": "Path to SSH key (optional)"}
     }, "required": ["host", "command"]}},

    # --- Filesystem ---
    {"name": "read_file", "description": "Read a file.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "lines": {"type": "integer", "description": "Max lines to read"}
     }, "required": ["path"]}},

    {"name": "write_file", "description": "Write content to a file.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"},
         "append": {"type": "boolean", "default": False}
     }, "required": ["path", "content"]}},

    {"name": "list_dir", "description": "List directory contents.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "default": "."}
     }}},

    {"name": "search_files", "description": "Search for files by name pattern.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "default": "."}, "pattern": {"type": "string"}
     }, "required": ["pattern"]}},

    # --- Shell ---
    {"name": "exec_shell", "description": "Execute a shell command.",
     "inputSchema": {"type": "object", "properties": {
         "command": {"type": "string"}, "timeout": {"type": "integer", "default": 30}
     }, "required": ["command"]}},

    # --- Config ---
    {"name": "read_config", "description": "Read agent config. Use key='all' for full dump.",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string", "default": "all"}
     }}},

    {"name": "write_config", "description": "Write a config value. Versioned backup automatic.",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "value": {}
     }, "required": ["key", "value"]}},

    # --- Self-Extending Tools ---
    {"name": "create_tool", "description": "Create a new tool at runtime. The agent extends its own capabilities. Tool persists across sessions.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Tool name (lowercase, no spaces)"},
         "description": {"type": "string", "description": "What the tool does"},
         "parameters": {"type": "object", "description": "OpenAI-style parameter schema"},
         "python_code": {"type": "string", "description": "Python code for the run(args) function body"}
     }, "required": ["name", "description", "parameters", "python_code"]}},

    {"name": "list_tools", "description": "List all available tools (built-in + dynamic).",
     "inputSchema": {"type": "object", "properties": {}}},

    # --- UI ---
    {"name": "create_ui", "description": "Generate an HTML page with sovereign theme.",
     "inputSchema": {"type": "object", "properties": {
         "title": {"type": "string"}, "body_html": {"type": "string"},
         "filename": {"type": "string"}
     }, "required": ["title", "body_html"]}},

    # --- Platform ---
    {"name": "platform_info", "description": "Get platform info: OS, mobile/desktop, available features.",
     "inputSchema": {"type": "object", "properties": {}}},
]


# ============================================================
# Tool execution router
# ============================================================

def execute(name, args):
    """Route a tool call to the right function."""
    try:
        # Context engine
        if name == "context_keep":
            return context_engine.keep(args["content"], args.get("role", "user"),
                                       args.get("priority", 5), args.get("reason", ""))
        elif name == "context_discard":
            return context_engine.discard(args["content"], args.get("role", "user"), args.get("reason", ""))
        elif name == "context_recall":
            return context_engine.recall(args["query"], args.get("limit", 5))
        elif name == "context_purge":
            return context_engine.purge(args["chunk_id"], args.get("reason", ""))
        elif name == "context_pressure":
            return context_engine.check_pressure()
        elif name == "context_stats":
            return context_engine.stats()

        # Memory
        elif name == "remember":
            return memory.remember(args["key"], args["value"])
        elif name == "recall_memory":
            val = memory.recall(args["key"])
            return {"key": args["key"], "value": val} if val else {"key": args["key"], "value": None, "note": "not found"}
        elif name == "forget":
            return {"forgotten": memory.forget(args["key"])}
        elif name == "list_memories":
            return memory.list_memories()
        elif name == "search_memories":
            return memory.search(args["query"])

        # SSH
        elif name == "ssh_exec":
            return ssh_tool.ssh_exec(args["host"], args["command"],
                                     args.get("timeout", 30), args.get("identity"))

        # Filesystem
        elif name == "read_file":
            p = Path(args["path"]).expanduser()
            if not p.exists():
                return {"error": f"not found: {p}"}
            content = p.read_text(errors="replace")
            limit = args.get("lines")
            if limit:
                content = "\n".join(content.splitlines()[:limit])
            if len(content) > 50000:
                content = content[:50000] + "\n... (truncated)"
            return {"path": str(p), "content": content, "size": p.stat().st_size}
        elif name == "write_file":
            p = Path(args["path"]).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if args.get("append") else "w"
            p.write_text(args["content"]) if mode == "w" else open(p, "a").write(args["content"])
            return {"written": str(p), "bytes": len(args["content"])}
        elif name == "list_dir":
            p = Path(args.get("path", ".")).expanduser()
            if not p.is_dir():
                return {"error": f"not a directory: {p}"}
            entries = []
            for item in sorted(p.iterdir()):
                prefix = "[DIR]" if item.is_dir() else "[FILE]"
                size = item.stat().st_size if item.is_file() else 0
                entries.append(f"{prefix} {item.name} ({size})")
            return {"path": str(p), "entries": entries}
        elif name == "search_files":
            import glob
            p = args.get("path", ".")
            matches = glob.glob(os.path.join(p, "**", args["pattern"]), recursive=True)
            return {"pattern": args["pattern"], "matches": matches[:50]}

        # Shell
        elif name == "exec_shell":
            import subprocess
            timeout = min(args.get("timeout", 30), 300)
            r = subprocess.run(args["command"], shell=True, capture_output=True, text=True,
                               timeout=timeout, cwd=str(Path.home()))
            return {"stdout": r.stdout[-4000:], "stderr": r.stderr[-2000:], "code": r.returncode}

        # Config
        elif name == "read_config":
            key = args.get("key", "all")
            if key == "all":
                return json.loads(config.dump())
            return {"key": key, "value": config.get(key)}
        elif name == "write_config":
            config.set_value(args["key"], args["value"], source="mcp_tool")
            return {"set": args["key"], "value": args["value"]}

        # Self-extending tools
        elif name == "create_tool":
            ok, msg = tool_registry.create_tool(args["name"], args["description"],
                                                 args["parameters"], args["python_code"])
            return {"success": ok, "message": msg}
        elif name == "list_tools":
            builtin = [t["name"] for t in TOOLS]
            dynamic = tool_registry.list_dynamic_tools()
            return {"builtin": builtin, "dynamic": [d["name"] for d in dynamic],
                    "total": len(builtin) + len(dynamic)}

        # UI
        elif name == "create_ui":
            path = ui.create_page(args["title"], args["body_html"], args.get("filename"))
            return {"created": path}

        # Platform
        elif name == "platform_info":
            return plat.PLATFORM

        # Dynamic tools
        else:
            result = tool_registry.execute_dynamic_tool(name, args)
            return json.loads(result) if isinstance(result, str) else result

    except Exception as e:
        return {"error": str(e)}


# ============================================================
# MCP Protocol — JSON-RPC 2.0 over stdin/stdout
# ============================================================

def send(msg):
    """Send a JSON-RPC message to stdout."""
    out = json.dumps(msg)
    sys.stdout.write(out + "\n")
    sys.stdout.flush()


def handle_request(req):
    """Handle an incoming JSON-RPC request."""
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "sovereign-agent", "version": "1.0.0"}
        }})

    elif method == "notifications/initialized":
        pass  # no response needed

    elif method == "tools/list":
        tool_list = []
        for t in TOOLS:
            tool_list.append({"name": t["name"], "description": t["description"],
                              "inputSchema": t["inputSchema"]})
        # Add dynamic tools
        for dt in tool_registry.list_dynamic_tools():
            if dt["definition"]:
                fn = dt["definition"]["function"]
                tool_list.append({"name": fn["name"], "description": fn["description"],
                                  "inputSchema": fn.get("parameters", {"type": "object", "properties": {}})})
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_list}})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        result = execute(tool_name, tool_args)
        text = json.dumps(result, indent=2) if not isinstance(result, str) else result
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}]
        }})

    elif method == "ping":
        send({"jsonrpc": "2.0", "id": rid, "result": {}})

    else:
        if rid:
            send({"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32601, "message": f"Method not found: {method}"
            }})


def main():
    """Main loop — read JSON-RPC from stdin, respond on stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            handle_request(req)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            sys.stderr.write(f"MCP error: {e}\n")


if __name__ == "__main__":
    main()
