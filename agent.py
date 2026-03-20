#!/usr/bin/env python3
"""
sovereign-agent/agent.py
The unified agent. Fuses proven patterns from 0THISWORKSSTILL.py with
context engine, memory, tool registry, SSH, platform detection.

- 12-round iterative tool loop (not recursive)
- Permission gate for dangerous actions
- Self-extending tools via /addcmd /addtool /addspecialty
- Strategic context management (keep/discard/recall)
- Conversation logging to log.jsonl
- Rolling context window (trim when > 20 message pairs)
- Streaming SSE for tool-free responses
- Fuzzy command matching
- Dynamic tool loading at runtime
"""

import os
import sys
import json
import subprocess
import time
import difflib
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import chat
import serve
import health
import context_engine
import memory as mem
import tool_registry
import ssh_tool
import platform as plat

import requests

# ============================================================
# Paths
# ============================================================

CONFIG_DIR = Path.home() / ".config" / "sovereign-agent"
LOG_PATH = CONFIG_DIR / "log.jsonl"
COMMANDS_PATH = CONFIG_DIR / "commands.json"
SPECIALTIES_PATH = CONFIG_DIR / "specialties.json"

# Max tool-call rounds before returning to user
MAX_TOOL_ROUNDS = 12


# ============================================================
# Permission gate — dangerous patterns require confirmation
# ============================================================

GUARDED_PATTERNS = [
    "rm -rf", "rm -r /", "rmdir", "mkfs", "dd if=",
    "shutdown", "reboot", "systemctl stop", "systemctl disable",
    "kill -9", "killall", "pkill",
    "> /dev/", "chmod 777", "chmod -R",
    "DROP TABLE", "DROP DATABASE", "DELETE FROM",
    "curl.*| bash", "curl.*| sh", "wget.*| bash",
    "git push --force", "git reset --hard",
]

def _needs_confirm(command):
    """Check if a shell command matches a guarded pattern."""
    cmd_lower = command.lower().strip()
    for pattern in GUARDED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return True
    return False

def _confirm_action(tool_name, description):
    """Ask user for confirmation. Returns True if approved."""
    chat.blank()
    chat.out(f"  {chat.BOLD}{chat.BRIGHT_YELLOW}[PERMISSION]{chat.RESET} {tool_name}")
    chat.out(f"  {chat.DIM}{description}{chat.RESET}")
    try:
        answer = input(f"  {chat.NEON_ORANGE}Allow? [y/N] {chat.RESET}").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ============================================================
# Tool definitions (OpenAI function-calling format)
# Built-in tools + dynamic tools merged at runtime
# ============================================================

BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_config",
            "description": "Read agent config. Dot paths like 'model.port'. Pass 'all' for full dump.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_config",
            "description": "Write agent config. Auto-backups + audit. Dot paths like 'model.port'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"description": "Value to set (string, number, bool, object)"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "exec_shell",
            "description": "Execute a shell command. Returns stdout/stderr/returncode. 30s default timeout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "description": "Max seconds (default 30, max 300)"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents. 50KB limit. Supports first-N-lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "lines": {"type": "integer", "description": "Max lines to read"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or append to a file. Creates parent dirs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean", "description": "Append instead of overwrite"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List directory contents with sizes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: ~)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by name pattern or grep content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Filename glob or content regex"},
                    "path": {"type": "string", "description": "Search root (default: ~)"},
                    "content": {"type": "boolean", "description": "If true, grep file contents instead of names"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_exec",
            "description": "Execute a command on a remote host via SSH. Supports aliases from config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Host, IP, user@host, or config alias"},
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "description": "Max seconds (default 30)"}
                },
                "required": ["host", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Make an HTTP GET request. Returns status + body (truncated to 8KB).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "headers": {"type": "object", "description": "Optional headers dict"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a value in persistent memory. Survives restarts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"description": "Value to remember (any type)"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Retrieve a value from persistent memory by key.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_memories",
            "description": "Search memories by key or value content.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "context_keep",
            "description": "Swipe right. Keep this information in active context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "priority": {"type": "integer", "description": "1-10 (10=critical)"},
                    "reason": {"type": "string"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "context_discard",
            "description": "Swipe left. Discard from context. Goes to Marcus's discard log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "context_recall",
            "description": "Search everything you've ever seen. FTS5 indexed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "context_pressure",
            "description": "Check context pressure. Should you start curating?",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_tool",
            "description": "Create a new dynamic tool at runtime. Self-extending protocol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "parameters": {"type": "object", "description": "JSON schema for params"},
                    "python_code": {"type": "string", "description": "Python code for the run(args) function body"}
                },
                "required": ["name", "description", "parameters", "python_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "platform_info",
            "description": "Get platform info: OS, mobile/desktop, available tools.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
]


# ============================================================
# Tool execution
# ============================================================

def execute_tool(name, arguments):
    """Execute a tool by name. Returns result string."""
    try:
        # Built-in tools
        if name == "read_config":
            return _tool_read_config(arguments)
        elif name == "write_config":
            return _tool_write_config(arguments)
        elif name == "exec_shell":
            return _tool_exec_shell(arguments)
        elif name == "read_file":
            return _tool_read_file(arguments)
        elif name == "write_file":
            return _tool_write_file(arguments)
        elif name == "list_dir":
            return _tool_list_dir(arguments)
        elif name == "search_files":
            return _tool_search_files(arguments)
        elif name == "ssh_exec":
            return _tool_ssh_exec(arguments)
        elif name == "http_get":
            return _tool_http_get(arguments)
        elif name == "remember":
            return _tool_remember(arguments)
        elif name == "recall_memory":
            return _tool_recall_memory(arguments)
        elif name == "search_memories":
            return _tool_search_memories(arguments)
        elif name == "context_keep":
            return _tool_context_keep(arguments)
        elif name == "context_discard":
            return _tool_context_discard(arguments)
        elif name == "context_recall":
            return _tool_context_recall(arguments)
        elif name == "context_pressure":
            return _tool_context_pressure(arguments)
        elif name == "create_tool":
            return _tool_create_tool(arguments)
        elif name == "platform_info":
            return _tool_platform_info(arguments)
        else:
            # Try dynamic tools
            result = tool_registry.execute_dynamic_tool(name, arguments)
            return result
    except Exception as e:
        return json.dumps({"error": f"Tool '{name}' failed: {str(e)}"})


# --- Built-in tool implementations ---

def _tool_read_config(args):
    key = args.get("key", "all")
    if key == "all":
        return config.dump()
    value = config.get(key)
    if value is None:
        return json.dumps({"key": key, "value": None, "note": "Key not found"})
    return json.dumps({"key": key, "value": value})


def _tool_write_config(args):
    key = args.get("key")
    value = args.get("value")
    if not key:
        return json.dumps({"error": "Missing 'key'"})
    config.set_value(key, value, source="agent_tool")
    return json.dumps({"success": True, "key": key, "value": value})


def _tool_exec_shell(args):
    command = args.get("command", "")
    timeout = min(args.get("timeout", 30), 300)
    if not command:
        return json.dumps({"error": "Empty command"})

    # Permission gate
    if _needs_confirm(command):
        if not _confirm_action("exec_shell", command):
            return json.dumps({"error": "Denied by user", "command": command})

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(Path.home())
        )
        output = {
            "stdout": result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
            "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            "returncode": result.returncode
        }
        if len(result.stdout) > 4000:
            output["stdout_truncated"] = True
            output["stdout_full_length"] = len(result.stdout)
        return json.dumps(output)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Timed out after {timeout}s"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_read_file(args):
    path = args.get("path", "")
    max_lines = args.get("lines")
    if not path:
        return json.dumps({"error": "Empty path"})
    p = Path(path).expanduser()
    if not p.exists():
        return json.dumps({"error": f"Not found: {p}"})
    if not p.is_file():
        return json.dumps({"error": f"Not a file: {p}"})
    try:
        with open(p, "r", errors="replace") as f:
            if max_lines:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(line)
                content = "".join(lines)
                note = f"first {max_lines} lines"
            else:
                content = f.read()
                if len(content) > 50000:
                    content = content[:50000]
                    note = "truncated to 50KB"
                else:
                    note = ""
        return json.dumps({"path": str(p), "content": content, "size": p.stat().st_size, "note": note or None})
    except Exception as e:
        return json.dumps({"error": f"Read failed: {e}"})


def _tool_write_file(args):
    path = args.get("path", "")
    content = args.get("content", "")
    append = args.get("append", False)
    if not path:
        return json.dumps({"error": "Empty path"})

    # Permission gate for writing outside home
    p = Path(path).expanduser()
    home = Path.home()
    if not str(p).startswith(str(home)):
        if not _confirm_action("write_file", f"Write outside home: {p}"):
            return json.dumps({"error": "Denied by user"})

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode) as f:
            f.write(content)
        config._audit("FILE_WRITE", f"path={p} size={len(content)} append={append}")
        return json.dumps({"success": True, "path": str(p), "bytes": len(content), "mode": "append" if append else "write"})
    except Exception as e:
        return json.dumps({"error": f"Write failed: {e}"})


def _tool_list_dir(args):
    path = args.get("path", "~")
    p = Path(path).expanduser()
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {p}"})
    try:
        entries = []
        for item in sorted(p.iterdir()):
            try:
                st = item.stat()
                entries.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": st.st_size if item.is_file() else None,
                    "symlink": str(item.resolve()) if item.is_symlink() else None
                })
            except (PermissionError, OSError):
                entries.append({"name": item.name, "type": "?", "error": "permission denied"})
        return json.dumps({"path": str(p), "count": len(entries), "entries": entries[:100]})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_search_files(args):
    pattern = args.get("pattern", "")
    path = args.get("path", "~")
    content_search = args.get("content", False)
    if not pattern:
        return json.dumps({"error": "Empty pattern"})
    p = Path(path).expanduser()

    try:
        if content_search:
            result = subprocess.run(
                ["grep", "-rl", "--include=*.py", "--include=*.json", "--include=*.md",
                 "--include=*.txt", "--include=*.sh", "--include=*.yaml", "--include=*.yml",
                 "-m", "1", pattern, str(p)],
                capture_output=True, text=True, timeout=10
            )
            files = result.stdout.strip().splitlines()[:20]
            return json.dumps({"pattern": pattern, "matches": files, "count": len(files)})
        else:
            result = subprocess.run(
                ["find", str(p), "-maxdepth", "4", "-name", pattern, "-type", "f"],
                capture_output=True, text=True, timeout=10
            )
            files = result.stdout.strip().splitlines()[:20]
            return json.dumps({"pattern": pattern, "matches": files, "count": len(files)})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Search timed out"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_ssh_exec(args):
    host = args.get("host", "")
    command = args.get("command", "")
    timeout = args.get("timeout", 30)
    if not host or not command:
        return json.dumps({"error": "Missing host or command"})

    # Permission gate
    if _needs_confirm(command):
        if not _confirm_action("ssh_exec", f"{host}: {command}"):
            return json.dumps({"error": "Denied by user"})

    result = ssh_tool.ssh_exec(host, command, timeout=timeout)
    return json.dumps(result)


def _tool_http_get(args):
    url = args.get("url", "")
    headers = args.get("headers", {})
    if not url:
        return json.dumps({"error": "Empty URL"})
    try:
        r = requests.get(url, headers=headers, timeout=15)
        body = r.text[:8000]
        return json.dumps({
            "status": r.status_code,
            "body": body,
            "truncated": len(r.text) > 8000,
            "headers": dict(r.headers)
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def _tool_remember(args):
    key = args.get("key", "")
    value = args.get("value")
    if not key:
        return json.dumps({"error": "Missing key"})
    mem.remember(key, value)
    return json.dumps({"success": True, "key": key, "stored": True})


def _tool_recall_memory(args):
    key = args.get("key", "")
    if not key:
        return json.dumps({"error": "Missing key"})
    value = mem.recall(key)
    if value is None:
        return json.dumps({"key": key, "found": False})
    return json.dumps({"key": key, "found": True, "value": value})


def _tool_search_memories(args):
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "Missing query"})
    results = mem.search(query)
    return json.dumps({"query": query, "count": len(results), "results": results[:10]})


def _tool_context_keep(args):
    content = args.get("content", "")
    priority = args.get("priority", 5)
    reason = args.get("reason", "")
    if not content:
        return json.dumps({"error": "Empty content"})
    result = context_engine.keep(content, priority=priority, reason=reason)
    return json.dumps(result)


def _tool_context_discard(args):
    content = args.get("content", "")
    reason = args.get("reason", "")
    if not content:
        return json.dumps({"error": "Empty content"})
    result = context_engine.discard(content, reason=reason)
    return json.dumps(result)


def _tool_context_recall(args):
    query = args.get("query", "")
    limit = args.get("limit", 5)
    if not query:
        return json.dumps({"error": "Empty query"})
    results = context_engine.recall(query, limit=limit)
    return json.dumps({"query": query, "count": len(results), "results": results})


def _tool_context_pressure(args):
    result = context_engine.check_pressure()
    return json.dumps(result)


def _tool_create_tool(args):
    name = args.get("name", "")
    desc = args.get("description", "")
    params = args.get("parameters", {"type": "object", "properties": {}, "required": []})
    code = args.get("python_code", "")
    if not name or not code:
        return json.dumps({"error": "Missing name or python_code"})
    ok, msg = tool_registry.create_tool(name, desc, params, code)
    return json.dumps({"success": ok, "message": msg})


def _tool_platform_info(args):
    return json.dumps(plat.platform_info())


# ============================================================
# Conversation logging
# ============================================================

def _log_exchange(role, content, tool_name=None):
    """Log a message exchange to log.jsonl."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "role": role,
        "content": content[:2000] if content else "",
    }
    if tool_name:
        entry["tool"] = tool_name
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ============================================================
# Self-extension commands: /addcmd /addtool /addspecialty
# ============================================================

def _load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def handle_addcmd(rest):
    """Add a custom command shortcut. Usage: /addcmd NAME EXPANSION"""
    parts = rest.strip().split(None, 1)
    if len(parts) < 2:
        chat.error_msg("Usage: /addcmd NAME EXPANSION")
        return
    name, expansion = parts
    cmds = _load_json(COMMANDS_PATH)
    cmds[name] = expansion
    _save_json(COMMANDS_PATH, cmds)
    chat.out(chat.success(f"  Added command: /{name} -> {expansion}"))


def handle_addtool(rest):
    """Add a tool. Usage: /addtool NAME DESCRIPTION"""
    parts = rest.strip().split(None, 1)
    if len(parts) < 2:
        chat.error_msg("Usage: /addtool NAME DESCRIPTION")
        return
    name, desc = parts
    chat.out(f"  {chat.DIM}Enter Python code for run(args). Indent with 4 spaces. End with empty line:{chat.RESET}")
    lines = []
    while True:
        try:
            line = input(f"  {chat.DIM}...{chat.RESET} ")
            if not line.strip():
                break
            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break
    if not lines:
        chat.error_msg("No code entered. Cancelled.")
        return
    code = "\n".join(lines)
    params = {"type": "object", "properties": {}, "required": []}
    ok, msg = tool_registry.create_tool(name, desc, params, code)
    if ok:
        chat.out(chat.success(f"  Tool created: {name}"))
    else:
        chat.error_msg(msg)


def handle_addspecialty(rest):
    """Add a specialty prompt. Usage: /addspecialty NAME PROMPT"""
    parts = rest.strip().split(None, 1)
    if len(parts) < 2:
        chat.error_msg("Usage: /addspecialty NAME PROMPT")
        return
    name, prompt = parts
    specs = _load_json(SPECIALTIES_PATH)
    specs[name] = prompt
    _save_json(SPECIALTIES_PATH, specs)
    chat.out(chat.success(f"  Added specialty: {name}"))


def handle_spesh(rest, agent):
    """Activate a specialty. Usage: /spesh NAME"""
    name = rest.strip()
    specs = _load_json(SPECIALTIES_PATH)
    if not name:
        if not specs:
            chat.out("  No specialties defined. Use /addspecialty NAME PROMPT")
            return
        chat.header("Specialties")
        for k, v in specs.items():
            chat.label(k, v[:60] + "..." if len(v) > 60 else v, key_color=chat.NEON_YELLOW)
        return
    if name in specs:
        agent.messages.append({"role": "system", "content": specs[name]})
        chat.out(chat.success(f"  Activated specialty: {name}"))
    else:
        matches = difflib.get_close_matches(name, specs.keys(), n=1, cutoff=0.5)
        if matches:
            chat.out(f"  Did you mean: /spesh {matches[0]}?")
        else:
            chat.error_msg(f"Unknown specialty: {name}")


# ============================================================
# Agent class
# ============================================================

class Agent:
    """The sovereign agent. Talks to model, uses tools, manages context."""

    def __init__(self, server=None):
        self.server = server or serve.ModelServer()
        self.health_daemon = health.HealthDaemon(self.server)
        self.messages = []
        self.running = True
        self.session_id = hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]
        self._init_system_prompt()

    def _init_system_prompt(self):
        """Load the sovereign identity + active context."""
        identity_path = Path(__file__).parent / "identity.md"
        if identity_path.exists():
            system_prompt = identity_path.read_text()
        else:
            cfg = config.load()
            system_prompt = cfg.get("agent", {}).get("system_prompt",
                "You are a sovereign AI agent with tools to read/write files, "
                "execute commands, manage config, SSH into servers, search memories, "
                "and curate your own context. Be direct and useful."
            )

        # Inject platform info
        pi = plat.platform_info()
        system_prompt += f"\n\n[Platform: {pi['platform']} | Python {pi['python_version']} | Home: {pi['home']}]"

        # Inject active context summary
        try:
            ctx = context_engine.get_active_context()
            if ctx["count"] > 0:
                system_prompt += f"\n\n[Active context: {ctx['count']} chunks, ~{ctx['total_tokens']} tokens, pressure {ctx['pressure']:.0%}]"
        except Exception:
            pass

        # Inject memory count
        try:
            mc = mem.count()
            if mc > 0:
                system_prompt += f"\n[Persistent memories: {mc}]"
        except Exception:
            pass

        # Inject dynamic tool count
        try:
            dt = tool_registry.list_dynamic_tools()
            if dt:
                system_prompt += f"\n[Dynamic tools: {len(dt)} ({', '.join(t['name'] for t in dt)})]"
        except Exception:
            pass

        self.messages = [{"role": "system", "content": system_prompt}]

    def _get_tools(self):
        """Get all tools: built-in + dynamic."""
        return tool_registry.get_all_tool_definitions(BUILTIN_TOOLS)

    def _get_endpoint(self):
        """Determine endpoint (local or remote)."""
        cfg = config.load()
        use_remote = cfg.get("agent", {}).get("use_remote", False)
        if use_remote:
            remote_cfg = cfg.get("remote", {})
            return remote_cfg.get("url", "https://axismundi.fun/v1/chat/completions"), True
        model_cfg = cfg.get("model", {})
        host = model_cfg.get("host", "127.0.0.1")
        port = model_cfg.get("port", 8181)
        return f"http://{host}:{port}/v1/chat/completions", False

    def _trim_context(self):
        """Rolling context window. Keep system prompt + last 20 message pairs."""
        max_messages = 42  # system + 20 pairs + tool results
        if len(self.messages) > max_messages:
            system = self.messages[0]
            kept = self.messages[-(max_messages - 1):]
            self.messages = [system] + kept
            chat.system_msg(f"Context trimmed to {len(self.messages)} messages")

    def _send_to_model(self, messages, use_tools=True):
        """Send messages to the model. Returns response JSON."""
        url, is_remote = self._get_endpoint()
        cfg = config.load()
        agent_cfg = cfg.get("agent", {})

        headers = {"Content-Type": "application/json"}
        if is_remote:
            token = config.read_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        payload = {
            "messages": messages,
            "temperature": agent_cfg.get("temperature", 0.7),
            "max_tokens": agent_cfg.get("max_tokens", 2048),
            "stream": False
        }

        if use_tools and agent_cfg.get("tool_use", True):
            payload["tools"] = self._get_tools()
            payload["tool_choice"] = "auto"

        try:
            r = requests.post(url, json=payload, headers=headers, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.ConnectionError:
            return {"error": f"Cannot connect to {url}"}
        except requests.Timeout:
            return {"error": "Request timed out (120s)"}
        except requests.HTTPError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except requests.RequestException as e:
            return {"error": str(e)}

    def send(self, user_input):
        """Send user message. 12-round iterative tool loop. Returns final text."""
        self.messages.append({"role": "user", "content": user_input})
        _log_exchange("user", user_input)
        self._trim_context()

        # Index in context engine
        context_engine.ingest(user_input, role="user", session_id=self.session_id)

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            if round_num == 1:
                chat.out(f"  {chat.DIM}...{chat.RESET}")
            response = self._send_to_model(self.messages)

            if "error" in response:
                chat.error_msg(response["error"])
                return None

            choices = response.get("choices", [])
            if not choices:
                chat.error_msg("Empty response from model")
                return None

            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls", [])

            if not tool_calls:
                # Final answer
                content = message.get("content", "")
                if content:
                    self.messages.append({"role": "assistant", "content": content})
                    _log_exchange("assistant", content)
                    context_engine.ingest(content, role="assistant", session_id=self.session_id)
                return content

            # Process tool calls
            self.messages.append(message)

            if round_num > 1:
                chat.out(f"  {chat.DIM}[round {round_num}/{MAX_TOOL_ROUNDS}]{chat.RESET}")

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                try:
                    arguments = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}

                chat.tool_msg(tool_name, json.dumps(arguments, indent=2)[:200])
                _log_exchange("tool_call", f"{tool_name}: {json.dumps(arguments)[:500]}", tool_name=tool_name)

                result = execute_tool(tool_name, arguments)

                # Show result preview
                try:
                    rp = json.loads(result)
                    if "error" in rp:
                        chat.error_msg(rp['error'])
                    elif "stdout" in rp:
                        # Shell command result
                        out = rp["stdout"].strip()
                        if out:
                            for line in out.splitlines()[:5]:
                                chat.out(f"    {chat.DIM}{line}{chat.RESET}")
                            if len(out.splitlines()) > 5:
                                chat.out(f"    {chat.DIM}... ({len(out.splitlines())} lines){chat.RESET}")
                        if rp.get("stderr", "").strip():
                            chat.out(f"    {chat.DIM}stderr: {rp['stderr'].strip()[:100]}{chat.RESET}")
                        if rp.get("returncode", 0) != 0:
                            chat.out(f"    {chat.DIM}exit: {rp['returncode']}{chat.RESET}")
                    elif "content" in rp:
                        # File read result
                        preview = rp["content"][:200]
                        chat.out(f"    {chat.DIM}{rp.get('path', '?')} ({rp.get('size', '?')} bytes){chat.RESET}")
                    elif "success" in rp:
                        # Write/config result
                        chat.system_msg(f"ok: {rp.get('path', rp.get('key', ''))}")
                    else:
                        # Generic - show compact
                        preview = json.dumps(rp)[:200]
                        if len(json.dumps(rp)) > 200:
                            preview += "..."
                        chat.system_msg(f"result: {preview}")
                except json.JSONDecodeError:
                    chat.system_msg(f"result: {result[:200]}")

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{tool_name}_{round_num}"),
                    "content": result
                })

        # Hit max rounds
        chat.system_msg(f"Reached {MAX_TOOL_ROUNDS} tool rounds. Returning last result.")
        self.messages.append({"role": "user", "content": "[System: max tool rounds reached. Summarize what you accomplished.]"})
        response = self._send_to_model(self.messages, use_tools=False)
        if response and "choices" in response:
            content = response["choices"][0].get("message", {}).get("content", "")
            if content:
                self.messages.append({"role": "assistant", "content": content})
                return content
        return None

    def send_streaming(self, user_input):
        """Stream response without tools. For interactive feel."""
        self.messages.append({"role": "user", "content": user_input})
        _log_exchange("user", user_input)
        self._trim_context()

        url, is_remote = self._get_endpoint()
        cfg = config.load()
        agent_cfg = cfg.get("agent", {})

        headers = {"Content-Type": "application/json"}
        if is_remote:
            token = config.read_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        payload = {
            "messages": self.messages,
            "temperature": agent_cfg.get("temperature", 0.7),
            "max_tokens": agent_cfg.get("max_tokens", 2048),
            "stream": True
        }

        full_response = ""
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=120, stream=True)
            r.raise_for_status()

            chat.agent_msg_start()
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
                                chat.stream_token(content)
                                full_response += content
                    except json.JSONDecodeError:
                        continue
            chat.stream_end()

        except requests.ConnectionError:
            chat.stream_end()
            chat.error_msg(f"Cannot connect to {url}")
            return None
        except requests.RequestException as e:
            chat.stream_end()
            chat.error_msg(str(e))
            return None

        if not full_response:
            chat.out(f"  {chat.DIM}[empty response]{chat.RESET}")

        if full_response:
            self.messages.append({"role": "assistant", "content": full_response})
            _log_exchange("assistant", full_response)
        return full_response

    def autonomous(self, task, max_steps=10):
        """Autonomous mode. Agent works on task without user input."""
        chat.header("Autonomous Mode")
        chat.out(f"  Task: {task}")
        chat.out(f"  Max steps: {max_steps}")
        chat.hr()
        chat.blank()

        prompt = (
            f"You are now in autonomous mode. Your task:\n\n{task}\n\n"
            f"Work step by step. Use tools. {max_steps} steps max. "
            f"Say TASK_COMPLETE when done. Say TASK_BLOCKED if stuck."
        )
        self.messages.append({"role": "user", "content": prompt})

        for step in range(1, max_steps + 1):
            chat.out(f"  {chat.BOLD}{chat.ORANGE}Step {step}/{max_steps}{chat.RESET}")

            response = self._send_to_model(self.messages, use_tools=True)

            if "error" in response:
                chat.error_msg(response["error"])
                break

            choices = response.get("choices", [])
            if not choices:
                break

            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls", [])

            if tool_calls:
                self.messages.append(message)
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "unknown")
                    try:
                        arguments = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        arguments = {}
                    chat.tool_msg(tool_name, json.dumps(arguments, indent=2)[:200])
                    result = execute_tool(tool_name, arguments)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"auto_{tool_name}_{step}"),
                        "content": result
                    })
                continue

            content = message.get("content", "")
            if content:
                self.messages.append({"role": "assistant", "content": content})
                chat.agent_msg(content)

                if "TASK_COMPLETE" in content:
                    chat.blank()
                    chat.out(chat.success("  Task completed."))
                    return True
                if "TASK_BLOCKED" in content:
                    chat.blank()
                    chat.out(chat.warning("  Task blocked. Returning control."))
                    return False

        chat.blank()
        chat.out(chat.warning(f"  Reached max steps ({max_steps}). Returning control."))
        return False

    def reset(self):
        """Reset conversation history."""
        self._init_system_prompt()
        chat.system_msg("Conversation reset")


# ============================================================
# Commands
# ============================================================

COMMANDS = {
    "/help": "Show commands",
    "/status": "System status",
    "/tools": "List all tools (built-in + dynamic)",
    "/memory": "List persistent memories",
    "/context": "Show context engine stats",
    "/addcmd NAME EXPANSION": "Add custom command shortcut",
    "/addtool NAME DESCRIPTION": "Create a new dynamic tool",
    "/addspecialty NAME PROMPT": "Add a specialty prompt",
    "/spesh [NAME]": "Activate a specialty (or list all)",
    "/config": "Show config",
    "/config set KEY VALUE": "Set config value",
    "/config rollback [VER]": "Roll back config",
    "/config versions": "List config versions",
    "/config audit": "Show audit log",
    "/health": "Run health check",
    "/models": "List available models",
    "/auto TASK": "Autonomous mode",
    "/stream": "Toggle streaming mode",
    "/reset": "Reset conversation",
    "/quit": "Exit",
}


def handle_command(cmd, agent):
    """Handle a / command. Returns True if handled."""
    parts = cmd.strip().split(None, 2)
    base = parts[0].lower()

    # Check custom commands first
    custom = _load_json(COMMANDS_PATH)
    cmd_name = base.lstrip("/")
    if cmd_name in custom:
        expansion = custom[cmd_name]
        chat.system_msg(f"Running: {expansion}")
        result = execute_tool("exec_shell", {"command": expansion})
        try:
            r = json.loads(result)
            if r.get("stdout"):
                chat.out(r["stdout"])
            if r.get("stderr"):
                chat.error_msg(r["stderr"])
        except json.JSONDecodeError:
            chat.out(result)
        return True

    if base == "/help":
        chat.header("Commands")
        for k, v in COMMANDS.items():
            chat.label(k, v, key_color=chat.NEON_YELLOW)
        if custom:
            chat.blank()
            chat.out(f"  {chat.BOLD}{chat.ORANGE}Custom Commands{chat.RESET}")
            for k, v in custom.items():
                chat.label(f"  /{k}", v, key_color=chat.NEON_GREEN)
        return True

    elif base == "/status":
        chat.header("System Status")
        server_status = agent.server.get_status()
        chat.status_dot(
            f"Model server ({server_status['host']}:{server_status['port']})",
            ok=server_status.get("healthy", False) or server_status.get("running", False)
        )
        if server_status.get("pid"):
            chat.label("  PID", server_status["pid"])

        health_status = agent.health_daemon.get_status()
        chat.status_dot("Health daemon", ok=health_status["running"])

        token = config.read_token()
        chat.status_dot("Auth token", ok=token is not None)

        pi = plat.platform_info()
        chat.label("  Platform", pi["platform"])

        dt = tool_registry.list_dynamic_tools()
        chat.label("  Tools", f"{len(BUILTIN_TOOLS)} built-in + {len(dt)} dynamic")

        mc = mem.count()
        chat.label("  Memories", mc)

        try:
            cs = context_engine.stats()
            chat.label("  Context", f"{cs['active_chunks']} active, {cs['indexed_chunks']} indexed")
        except Exception:
            pass
        return True

    elif base == "/tools":
        chat.header("Tools")
        chat.out(f"  {chat.BOLD}Built-in ({len(BUILTIN_TOOLS)}){chat.RESET}")
        for t in BUILTIN_TOOLS:
            fn = t["function"]
            chat.bullet(f"{fn['name']}: {chat.DIM}{(fn['description'][:57] + '...') if len(fn['description']) > 60 else fn['description']}{chat.RESET}")
        dt = tool_registry.list_dynamic_tools()
        if dt:
            chat.blank()
            chat.out(f"  {chat.BOLD}Dynamic ({len(dt)}){chat.RESET}")
            for t in dt:
                chat.bullet(f"{t['name']}: {chat.DIM}{(t['description'][:57] + '...') if len(t['description']) > 60 else t['description']}{chat.RESET}", color_code=chat.NEON_GREEN)
        return True

    elif base == "/memory":
        chat.header("Persistent Memory")
        mems = mem.list_memories()
        if not mems:
            chat.out("  No memories stored. Use the remember tool.")
        else:
            for m in mems:
                chat.label(m["key"], m["value_preview"])
        return True

    elif base == "/context":
        chat.header("Context Engine")
        try:
            cs = context_engine.stats()
            chat.label("Indexed chunks", cs["indexed_chunks"])
            chat.label("Active chunks", cs["active_chunks"])
            chat.label("Decisions", f"{cs['keeps']} keeps, {cs['discards']} discards, {cs['purges']} purges")
            chat.label("DB size", f"{cs['db_size_kb']} KB")
            pressure = context_engine.check_pressure()
            chat.label("Pressure", f"{pressure['pressure']:.0%} ({pressure['status']})")
        except Exception as e:
            chat.error_msg(str(e))
        return True

    elif base == "/addcmd":
        rest = cmd[len("/addcmd"):].strip()
        handle_addcmd(rest)
        return True

    elif base == "/addtool":
        rest = cmd[len("/addtool"):].strip()
        handle_addtool(rest)
        return True

    elif base == "/addspecialty":
        rest = cmd[len("/addspecialty"):].strip()
        handle_addspecialty(rest)
        return True

    elif base == "/spesh":
        rest = cmd[len("/spesh"):].strip()
        handle_spesh(rest, agent)
        return True

    elif base == "/config":
        if len(parts) == 1:
            chat.header("Configuration")
            chat.out(config.dump())
            return True
        sub = parts[1].lower()
        if sub == "set" and len(parts) >= 3:
            rest = parts[2]
            kv = rest.split(None, 1)
            if len(kv) < 2:
                chat.error_msg("Usage: /config set KEY VALUE")
                return True
            key, val_str = kv
            try:
                value = json.loads(val_str)
            except json.JSONDecodeError:
                value = val_str
            config.set_value(key, value, source="user_command")
            chat.out(chat.success(f"  Set {key} = {value}"))
            return True
        elif sub == "rollback":
            version = int(parts[2]) if len(parts) > 2 else None
            config.rollback(version=version)
            return True
        elif sub == "versions":
            versions = config.list_versions()
            if not versions:
                chat.out("  No backup versions")
            else:
                rows = [[str(v["version"]), v["modified"], f"{v['size']}B"] for v in versions]
                chat.table(rows, headers=["Ver", "Modified", "Size"])
            return True
        elif sub == "audit":
            lines = config.get_audit_log(30)
            if not lines:
                chat.out("  No audit entries")
            else:
                for line in lines:
                    chat.out(f"  {chat.DIM}{line.rstrip()}{chat.RESET}")
            return True
        return True

    elif base == "/health":
        chat.header("Health Check")
        result = agent.health_daemon.check_once()
        chat.status_dot(f"Local ({result['host']}:{result['port']})", ok=result["local_healthy"])
        if result["remote_reachable"] is not None:
            chat.status_dot(f"Remote ({result['remote_url']})", ok=result["remote_reachable"])
        else:
            chat.out(f"  {chat.DIM}Remote: disabled{chat.RESET}")
        return True

    elif base == "/models":
        chat.header("Available Models")
        models = agent.server.find_models()
        if not models:
            chat.out(f"  No GGUF models in {agent.server.models_dir}")
        else:
            for m in models:
                sym = f" -> {m['target']}" if m['is_symlink'] else ""
                chat.bullet(f"{m['name']} ({m['size_mb']} MB){sym}")
        return True

    elif base == "/auto":
        if len(parts) < 2:
            chat.error_msg("Usage: /auto TASK DESCRIPTION")
            return True
        task = cmd[len("/auto "):].strip()
        agent.autonomous(task)
        return True

    elif base == "/stream":
        cfg = config.load()
        current = cfg.get("agent", {}).get("streaming", False)
        config.set_value("agent.streaming", not current, source="user_command")
        state = "ON" if not current else "OFF"
        chat.out(chat.success(f"  Streaming: {state}"))
        return True

    elif base == "/reset":
        agent.reset()
        return True

    elif base in ("/quit", "/exit", "/q"):
        agent.running = False
        return True

    # Fuzzy match
    all_cmd_names = list(COMMANDS.keys()) + [f"/{k}" for k in custom]
    matches = difflib.get_close_matches(base, [c.split()[0] for c in all_cmd_names], n=1, cutoff=0.5)
    if matches:
        chat.out(f"  Did you mean: {matches[0]}?")
        return True

    return False


# ============================================================
# Chat loop
# ============================================================

def run_chat_loop(agent):
    """Main chat loop."""
    chat.blank()
    chat.out(f"  {chat.DIM}Type /help for commands. /quit to exit.{chat.RESET}")
    chat.blank()

    while agent.running:
        user_input = chat.prompt_input("sovereign > ", chat.ORANGE)

        if user_input is None:
            chat.blank()
            chat.system_msg("Interrupted")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            handled = handle_command(user_input, agent)
            if handled:
                chat.blank()
                continue

        chat.user_msg(user_input)
        chat.blank()

        cfg = config.load()
        use_streaming = cfg.get("agent", {}).get("streaming", False)

        if use_streaming:
            response = agent.send_streaming(user_input)
        else:
            response = agent.send(user_input)
            if response:
                chat.agent_msg(response)
        chat.blank()


if __name__ == "__main__":
    print("Sovereign Agent")
    print("Use launch.py for the full experience.")
    print()
    ag = Agent()
    run_chat_loop(ag)
