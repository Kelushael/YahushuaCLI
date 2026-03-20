#!/usr/bin/env python3
"""
sovereign-agent/launch.py
THE LAUNCHER. Beautiful rainbow/neon ASCII art banner.
Orange + arcade game aesthetic. Shows status. Entry point.
"""

import os
import sys
import time
import signal
from pathlib import Path

# Ensure imports work from any cwd
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import config
import chat
import serve
import health
import agent
import memory as mem
import tool_registry
import context_engine
import platform as plat
import api as dashboard_api

# ============================================================
# The Banner
# ============================================================

def print_banner():
    """Print the sovereign-agent arcade banner. Orange neon. No cursor tricks."""
    # Color sequence for rainbow/neon effect on each line
    colors = [
        "\033[38;5;196m",  # red
        "\033[38;5;202m",  # deep orange
        "\033[38;5;208m",  # orange
        "\033[38;5;214m",  # light orange
        "\033[38;5;220m",  # yellow-orange
        "\033[38;5;226m",  # yellow
        "\033[38;5;214m",  # light orange
        "\033[38;5;208m",  # orange
        "\033[38;5;202m",  # deep orange
        "\033[38;5;196m",  # red
        "\033[38;5;160m",  # dark red
        "\033[38;5;208m",  # orange
    ]

    banner_lines = [
        r"",
        r"   _______ _______ ___ ___ _______ _______ _______ _______ _______ _______  ",
        r"  |   _   |   _   |   |   |   _   |   _   |   _   |_     _|   _   |   _   | ",
        r"  |   |___|.  |   |.  |   |.  1___|.  l   |.  1___|_|   |_|.  |   |.  |   | ",
        r"  |____   |.  |   |.  |   |.  __)_|.  _   |.  __)_|.    _)|.  |   |.  |   | ",
        r"  |:  1   |:  1   |:  1   |:  1   |:  |   |:  1   |:  1   |:  1   |:  1   | ",
        r"  |::.. . |::.. . |\:.. ./|::.. . |::.|:. |::.. . |::.. . |::.. . |::.. . | ",
        r"  `-------`-------' `---' `-------`--- ---`-------`-------`-------`-------'  ",
        r"",
        r"              _______ _______ _______ _______ _______                        ",
        r"             |   _   |   _   |   _   |   _   |_     _|                       ",
        r"             |.  1   |.  |___|.  1___|.  |   | |   |                         ",
        r"             |.  _   |.  |   |.  __)_|.  |   | |   |                         ",
        r"             |:  |   |:  1   |:  1   |:  |   | |   |                         ",
        r"             |::.|:. |::.. . |::.. . |::.|   | |   |                         ",
        r"             `--- ---`-------`-------`--- ---' `---'                          ",
        r"",
    ]

    for i, line in enumerate(banner_lines):
        c = colors[i % len(colors)]
        print(f"{c}{line}{chat.RESET}", flush=True)

    # Tagline
    print(f"     {chat.BOLD}{chat.ORANGE}[ YahushuaCTLIDE ]{chat.RESET}  {chat.DIM}Command Terminal Interface & Interactive Development Env{chat.RESET}", flush=True)
    print(f"     {chat.DIM}{'.' * 55}{chat.RESET}", flush=True)
    print(flush=True)


def print_mini_banner():
    """Smaller banner for constrained terminals."""
    colors = [
        "\033[38;5;202m",
        "\033[38;5;208m",
        "\033[38;5;214m",
        "\033[38;5;208m",
        "\033[38;5;202m",
    ]
    lines = [
        r"  ___ _____   _____ ___ ___ ___ ___ ___ _  _ ",
        r" / __/ _ \ \ / / __| _ \ __| |_/ __| \| | |",
        r" \__ \ (_) \ V /| _||   / _||  _| (_ | .` |_|",
        r" |___/\___/ \_/ |___|_|_\___|_| \___|_|\_(_)",
        r"",
    ]
    for i, line in enumerate(lines):
        c = colors[i % len(colors)]
        print(f"{c}{line}{chat.RESET}", flush=True)
    print(f"  {chat.BOLD}{chat.ORANGE}YahushuaCTLIDE{chat.RESET} {chat.DIM}// CTLIDE{chat.RESET}", flush=True)
    print(flush=True)


# ============================================================
# Status display
# ============================================================

def show_status(server, health_daemon):
    """Show system status panel."""
    print(f"  {chat.BOLD}{chat.ORANGE}SYSTEM STATUS{chat.RESET}", flush=True)
    print(f"  {chat.DIM}{'- ' * 25}{chat.RESET}", flush=True)

    # Token
    token = config.read_token()
    if token:
        masked = token[:6] + "..." + token[-4:]
        chat.status_dot(f"Auth token  {chat.DIM}{masked}{chat.RESET}", ok=True)
    else:
        chat.status_dot("Auth token  NOT FOUND", ok=False)

    # Binary
    binary_ok = server.is_binary_available()
    chat.status_dot(f"llama-server  {chat.DIM}{server.binary}{chat.RESET}", ok=binary_ok)

    # Models
    models = server.find_models()
    if models:
        chat.status_dot(f"Models  {chat.DIM}{len(models)} found in {server.models_dir}{chat.RESET}", ok=True)
    else:
        chat.status_dot(f"Models  {chat.DIM}none in {server.models_dir}{chat.RESET}", ok=False)

    # Local server
    server_status = server.get_status()
    if server_status["running"] and server_status["healthy"]:
        chat.status_dot(f"Local server  {chat.DIM}:{server.port} healthy{chat.RESET}", ok=True)
    elif server_status["running"]:
        chat.status_dot(f"Local server  {chat.DIM}:{server.port} starting...{chat.RESET}", ok=True)
    else:
        # Check if something else is on that port
        existing = serve.find_existing_server(server.port, server.host)
        if existing:
            chat.status_dot(f"Local server  {chat.DIM}:{server.port} external process{chat.RESET}", ok=True)
        else:
            chat.status_dot(f"Local server  {chat.DIM}:{server.port} not running{chat.RESET}", ok=False)

    # Remote
    cfg = config.load()
    remote_cfg = cfg.get("remote", {})
    if remote_cfg.get("enabled", False):
        remote_url = remote_cfg.get("url", "")
        chat.status_dot(f"Remote  {chat.DIM}{remote_url}{chat.RESET}", ok=True)
    else:
        chat.status_dot(f"Remote  {chat.DIM}disabled{chat.RESET}", ok=False)

    # Health daemon
    health_status = health_daemon.get_status()
    chat.status_dot(f"Health daemon  {chat.DIM}{'active' if health_status['running'] else 'inactive'}{chat.RESET}",
                    ok=health_status["running"])

    # Config
    versions = config.list_versions()
    chat.status_dot(f"Config  {chat.DIM}v{cfg.get('version', '?')} ({len(versions)} backups){chat.RESET}", ok=True)

    # Platform
    pi = plat.platform_info()
    chat.status_dot(f"Platform  {chat.DIM}{pi['platform']} | Python {pi['python_version']}{chat.RESET}", ok=True)

    # Tools
    dt = tool_registry.list_dynamic_tools()
    tool_count = len(agent.BUILTIN_TOOLS) + len(dt)
    dt_label = f" + {len(dt)} dynamic" if dt else ""
    chat.status_dot(f"Tools  {chat.DIM}{len(agent.BUILTIN_TOOLS)} built-in{dt_label} = {tool_count} total{chat.RESET}", ok=True)

    # Memory
    mc = mem.count()
    chat.status_dot(f"Memory  {chat.DIM}{mc} persistent memories{chat.RESET}", ok=mc > 0)

    # Context engine
    try:
        cs = context_engine.stats()
        chat.status_dot(f"Context  {chat.DIM}{cs['active_chunks']} active, {cs['indexed_chunks']} indexed{chat.RESET}", ok=True)
    except Exception:
        chat.status_dot(f"Context  {chat.DIM}initializing...{chat.RESET}", ok=True)

    print(flush=True)


# ============================================================
# Startup sequence
# ============================================================

def detect_terminal_width():
    """Get terminal width. Fall back to 80."""
    try:
        columns = os.get_terminal_size().columns
        return columns
    except (ValueError, OSError):
        return 80


def startup_checks():
    """Run startup checks and return (server, health_daemon, agent) or None on fatal error."""
    # Initialize config
    cfg = config.load()

    # Create server instance
    server = serve.ModelServer()

    # Create health daemon
    health_daemon = health.HealthDaemon(server)

    # Check if a server is already running on the port
    existing = serve.find_existing_server(server.port, server.host)
    if existing:
        chat.system_msg(f"Model server already running on port {server.port}")
    else:
        # Check if we have models and binary to start one
        if server.is_binary_available() and server.find_models():
            chat.system_msg("Local model server available but not started")
            chat.system_msg("Use /start to launch it, or it will use remote if configured")
        elif not server.is_binary_available():
            chat.system_msg(f"llama-server not at {server.binary} -- will use remote endpoint")
        else:
            chat.system_msg(f"No models in {server.models_dir} -- will use remote endpoint")

    # Start health daemon
    health_daemon.start()

    # Create agent
    ag = agent.Agent(server)
    ag.health_daemon = health_daemon

    return server, health_daemon, ag


# ============================================================
# Extra commands only available from the launcher
# ============================================================

def handle_launcher_command(cmd, server, health_daemon, ag):
    """Handle launcher-specific commands. Returns True if handled."""
    parts = cmd.strip().split()
    base = parts[0].lower()

    if base == "/start":
        model_name = parts[1] if len(parts) > 1 else None
        server.start(model_name=model_name)
        return True

    elif base == "/stop":
        server.stop()
        return True

    elif base == "/restart":
        model_name = parts[1] if len(parts) > 1 else None
        server.restart(model_name=model_name)
        return True

    elif base == "/logs":
        log_type = parts[1] if len(parts) > 1 else "health"
        if log_type == "health":
            lines = health_daemon.read_log(20)
            if lines:
                chat.header("Health Log (last 20)")
                for line in lines:
                    print(f"  {chat.DIM}{line.rstrip()}{chat.RESET}", flush=True)
            else:
                chat.out("  No health log entries yet")
        elif log_type == "server":
            log_path = config.CONFIG_DIR / "server.log"
            if log_path.exists():
                chat.header("Server Log (last 20)")
                with open(log_path, "r") as f:
                    all_lines = f.readlines()
                for line in all_lines[-20:]:
                    print(f"  {chat.DIM}{line.rstrip()}{chat.RESET}", flush=True)
            else:
                chat.out("  No server log yet")
        elif log_type == "audit":
            lines = config.get_audit_log(20)
            if lines:
                chat.header("Audit Log (last 20)")
                for line in lines:
                    print(f"  {chat.DIM}{line.rstrip()}{chat.RESET}", flush=True)
            else:
                chat.out("  No audit log entries yet")
        return True

    elif base == "/dashboard":
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{dashboard_api.API_PORT}")
        chat.system_msg("Dashboard opened in browser")
        return True

    elif base == "/banner":
        print_banner()
        return True

    return False


# ============================================================
# Main
# ============================================================

def main():
    """Launch the sovereign agent."""
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print(flush=True)
        chat.blank()
        chat.system_msg("Shutting down...")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    # Clear screen (just newlines, no ANSI escape for clear)
    print("\n" * 2, flush=True)

    # Choose banner based on terminal width
    width = detect_terminal_width()
    if width >= 80:
        print_banner()
    else:
        print_mini_banner()

    # Start dashboard API (background thread)
    try:
        dash_server, dash_port = dashboard_api.start_api()
        chat.status_dot(f"Dashboard  {chat.DIM}http://127.0.0.1:{dash_port}{chat.RESET}", ok=True)
    except Exception:
        chat.status_dot(f"Dashboard  {chat.DIM}failed to start{chat.RESET}", ok=False)

    # Startup
    server, health_daemon, ag = startup_checks()

    # Show status
    show_status(server, health_daemon)

    # Show extra launcher commands
    print(f"  {chat.BOLD}{chat.ORANGE}LAUNCHER COMMANDS{chat.RESET}", flush=True)
    print(f"  {chat.DIM}{'- ' * 25}{chat.RESET}", flush=True)
    extra_cmds = {
        "/start [MODEL]": "Start local llama-server",
        "/stop": "Stop local llama-server",
        "/restart [MODEL]": "Restart local llama-server",
        "/logs health|server|audit": "View logs",
        "/dashboard": "Open dashboard in browser",
        "/banner": "Show the banner again",
    }
    for k, v in extra_cmds.items():
        chat.label(k, v, key_color=chat.NEON_YELLOW)
    print(flush=True)

    # Main chat loop
    print(f"  {chat.DIM}Type a message to chat. /help for all commands. /quit to exit.{chat.RESET}", flush=True)
    print(flush=True)

    while ag.running:
        user_input = chat.prompt_input("sovereign > ", chat.ORANGE)

        if user_input is None:
            chat.blank()
            chat.system_msg("Interrupted")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Check launcher-specific commands first
        if user_input.startswith("/"):
            if handle_launcher_command(user_input, server, health_daemon, ag):
                chat.blank()
                continue
            # Then check agent commands
            if agent.handle_command(user_input, ag):
                chat.blank()
                continue

        # Regular chat
        chat.user_msg(user_input)
        chat.blank()

        # Check streaming preference
        cfg = config.load()
        use_streaming = cfg.get("agent", {}).get("streaming", False)

        if use_streaming:
            response = ag.send_streaming(user_input)
        else:
            response = ag.send(user_input)
            if response:
                chat.agent_msg(response)
        chat.blank()

    # Cleanup
    chat.system_msg("Stopping health daemon...")
    health_daemon.stop()
    chat.system_msg("Sovereign Agent shut down.")
    chat.blank()


if __name__ == "__main__":
    main()
