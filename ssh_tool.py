#!/usr/bin/env python3
"""
sovereign-agent/ssh_tool.py
SSH into remote machines using subprocess + ssh command.
Uses existing SSH keys (~/.ssh/).
Operations: ssh_exec(host, command), ssh_connect(host) for interactive.
Returns stdout/stderr cleanly. Timeout handling (default 30s).
Known hosts from config.json "hosts" section.
"""

import os
import json
import subprocess
from pathlib import Path

# Local imports
import config


def _get_hosts():
    """Load known hosts from config.json 'hosts' section."""
    cfg = config.load()
    return cfg.get("hosts", {})


def _resolve_host(host_or_alias):
    """Resolve a host alias to connection info, or use raw host string.

    Returns dict with keys: host, user, port, key_file
    """
    hosts = _get_hosts()

    # Check if it's a known alias
    if host_or_alias in hosts:
        entry = hosts[host_or_alias]
        if isinstance(entry, str):
            # Simple "alias": "user@host" format
            return _parse_host_string(entry)
        elif isinstance(entry, dict):
            return {
                "host": entry.get("host", host_or_alias),
                "user": entry.get("user", "root"),
                "port": entry.get("port", 22),
                "key_file": entry.get("key_file"),
            }

    # Not an alias, parse as raw host string
    return _parse_host_string(host_or_alias)


def _parse_host_string(host_str):
    """Parse user@host:port into components."""
    user = "root"
    port = 22
    host = host_str

    # Extract user@
    if "@" in host:
        user, host = host.rsplit("@", 1)

    # Extract :port
    if ":" in host:
        host, port_str = host.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            pass  # Keep default 22

    return {
        "host": host,
        "user": user,
        "port": port,
        "key_file": None,
    }


def _build_ssh_command(conn_info, command=None):
    """Build the ssh command array."""
    cmd = ["ssh"]

    # Disable strict host key checking for convenience (agent use)
    cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
    cmd.extend(["-o", "ConnectTimeout=10"])

    # Port
    if conn_info["port"] != 22:
        cmd.extend(["-p", str(conn_info["port"])])

    # Key file
    key_file = conn_info.get("key_file")
    if key_file:
        key_path = Path(key_file).expanduser()
        if key_path.exists():
            cmd.extend(["-i", str(key_path)])

    # Default SSH keys — check common locations
    if not key_file:
        for key_name in ["id_ed25519", "id_rsa", "id_ollama"]:
            key_path = Path.home() / ".ssh" / key_name
            if key_path.exists():
                cmd.extend(["-i", str(key_path)])
                break

    # User@Host
    target = f"{conn_info['user']}@{conn_info['host']}"
    cmd.append(target)

    # Command to execute (if any)
    if command:
        cmd.append(command)

    return cmd


def ssh_exec(host, command, timeout=30):
    """Execute a command on a remote host via SSH.

    Args:
        host: hostname, IP, user@host, user@host:port, or a config alias
        command: the shell command to run remotely
        timeout: max seconds to wait (default 30)

    Returns:
        dict with stdout, stderr, returncode, success
    """
    conn_info = _resolve_host(host)
    cmd = _build_ssh_command(conn_info, command)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = result.stdout
        stderr = result.stderr

        # Truncate large output
        if len(stdout) > 8000:
            stdout = stdout[:8000] + f"\n... (truncated, {len(result.stdout)} bytes total)"
        if len(stderr) > 4000:
            stderr = stderr[:4000] + f"\n... (truncated, {len(result.stderr)} bytes total)"

        return {
            "success": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
            "host": f"{conn_info['user']}@{conn_info['host']}",
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"SSH command timed out after {timeout}s",
            "returncode": -1,
            "host": f"{conn_info['user']}@{conn_info['host']}",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": "ssh command not found. Is OpenSSH installed?",
            "returncode": -1,
            "host": f"{conn_info['user']}@{conn_info['host']}",
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "host": f"{conn_info['user']}@{conn_info['host']}",
        }


def list_hosts():
    """List all configured SSH hosts."""
    hosts = _get_hosts()
    result = []
    for alias, entry in hosts.items():
        if isinstance(entry, str):
            result.append({"alias": alias, "target": entry})
        elif isinstance(entry, dict):
            target = f"{entry.get('user', 'root')}@{entry.get('host', alias)}"
            if entry.get("port", 22) != 22:
                target += f":{entry['port']}"
            result.append({"alias": alias, "target": target})
    return result


def add_host(alias, host, user="root", port=22, key_file=None):
    """Add a known host to the config."""
    cfg = config.load()
    if "hosts" not in cfg:
        cfg["hosts"] = {}
    entry = {"host": host, "user": user, "port": port}
    if key_file:
        entry["key_file"] = key_file
    cfg["hosts"][alias] = entry
    config.save(cfg, source="ssh_tool")
    return entry


if __name__ == "__main__":
    print("Sovereign Agent -- SSH Tool")
    print()
    hosts = list_hosts()
    if hosts:
        print("Configured hosts:")
        for h in hosts:
            print(f"  {h['alias']}: {h['target']}")
    else:
        print("No hosts configured in config.json")
        print("Add hosts via: config set hosts.myserver '{\"host\": \"1.2.3.4\", \"user\": \"root\"}'")
