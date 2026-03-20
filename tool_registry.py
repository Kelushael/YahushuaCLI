#!/usr/bin/env python3
"""
sovereign-agent/tool_registry.py
Manages built-in + dynamic tools. Self-extending protocol.
Dynamic tools stored as Python files in ~/.config/sovereign-agent/tools/
"""

import os
import json
import importlib.util
from pathlib import Path
from datetime import datetime

TOOLS_DIR = Path.home() / ".config" / "sovereign-agent" / "tools"


def ensure_tools_dir():
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)


def list_dynamic_tools():
    """List all dynamic tool files."""
    ensure_tools_dir()
    tools = []
    for f in sorted(TOOLS_DIR.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tool_def = getattr(mod, "TOOL_DEF", None)
            if tool_def:
                tools.append({
                    "name": tool_def["function"]["name"],
                    "description": tool_def["function"]["description"],
                    "path": str(f),
                    "definition": tool_def
                })
        except Exception as e:
            tools.append({
                "name": f.stem,
                "description": f"(load error: {e})",
                "path": str(f),
                "definition": None
            })
    return tools


def load_dynamic_tool(name):
    """Load a dynamic tool by name. Returns (TOOL_DEF, run_function) or (None, None)."""
    ensure_tools_dir()
    tool_file = TOOLS_DIR / f"{name}.py"
    if not tool_file.exists():
        return None, None
    try:
        spec = importlib.util.spec_from_file_location(name, tool_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "TOOL_DEF", None), getattr(mod, "run", None)
    except Exception:
        return None, None


def create_tool(name, description, parameters, python_code):
    """Create a new dynamic tool. Returns (success, message)."""
    ensure_tools_dir()
    safe_name = name.replace(" ", "_").replace("-", "_").lower()
    tool_file = TOOLS_DIR / f"{safe_name}.py"

    content = f'#!/usr/bin/env python3\n'
    content += f'"""Dynamic tool: {safe_name} -- created {datetime.now().isoformat()}"""\n\n'
    content += f'TOOL_DEF = {{\n'
    content += f'    "type": "function",\n'
    content += f'    "function": {{\n'
    content += f'        "name": {json.dumps(safe_name)},\n'
    content += f'        "description": {json.dumps(description)},\n'
    content += f'        "parameters": {json.dumps(parameters)}\n'
    content += f'    }}\n'
    content += f'}}\n\n\n'
    content += f'def run(args):\n'
    content += f'    """Execute the tool. Returns string result."""\n'
    content += python_code + '\n'

    try:
        tool_file.write_text(content)
        td, fn = load_dynamic_tool(safe_name)
        if td and fn:
            return True, f"Tool '{safe_name}' created at {tool_file}"
        return False, "Tool file written but failed to load -- check syntax"
    except Exception as e:
        return False, f"Failed to create tool: {e}"


def remove_tool(name):
    """Remove a dynamic tool."""
    ensure_tools_dir()
    tool_file = TOOLS_DIR / f"{name}.py"
    if tool_file.exists():
        tool_file.unlink()
        return True, f"Removed tool '{name}'"
    return False, f"Tool '{name}' not found"


def execute_dynamic_tool(name, arguments):
    """Execute a dynamic tool by name."""
    _, run_fn = load_dynamic_tool(name)
    if not run_fn:
        return json.dumps({"error": f"Dynamic tool '{name}' not found or has no run() function"})
    try:
        result = run_fn(arguments)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Tool '{name}' failed: {str(e)}"})


def get_all_tool_definitions(builtin_tools):
    """Merge built-in tools with all loaded dynamic tools."""
    all_tools = list(builtin_tools)
    for dt in list_dynamic_tools():
        if dt["definition"]:
            all_tools.append(dt["definition"])
    return all_tools
