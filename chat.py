#!/usr/bin/env python3
"""
sovereign-agent/chat.py
Clean chat UX. No ANSI cursor tricks. No \\r overwriting.
Just clean print() with simple color codes. Copy-paste safe.
"""

import sys

# ============================================================
# Simple ANSI color codes — no cursor movement, no tricks
# ============================================================
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Foreground
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Bright foreground
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

# Orange approximation (bright red + bold or 256-color)
ORANGE = "\033[38;5;208m"
NEON_ORANGE = "\033[38;5;214m"
DEEP_ORANGE = "\033[38;5;202m"
FIRE = "\033[38;5;196m"

# Neon colors for the arcade aesthetic
NEON_GREEN = "\033[38;5;46m"
NEON_CYAN = "\033[38;5;51m"
NEON_PINK = "\033[38;5;199m"
NEON_PURPLE = "\033[38;5;129m"
NEON_YELLOW = "\033[38;5;226m"
NEON_RED = "\033[38;5;196m"

# Background
BG_BLACK = "\033[40m"
BG_ORANGE = "\033[48;5;208m"


def color(text, color_code):
    """Wrap text in a color code."""
    return f"{color_code}{text}{RESET}"


def bold(text):
    return f"{BOLD}{text}{RESET}"


def dim(text):
    return f"{DIM}{text}{RESET}"


def orange(text):
    return color(text, ORANGE)


def neon(text):
    return color(text, NEON_ORANGE)


def fire(text):
    return color(text, FIRE)


def success(text):
    return color(text, NEON_GREEN)


def error(text):
    return color(text, BRIGHT_RED)


def warning(text):
    return color(text, BRIGHT_YELLOW)


def info(text):
    return color(text, BRIGHT_CYAN)


def muted(text):
    return color(text, DIM)


# ============================================================
# Output functions — all use print() with flush=True
# ============================================================

def out(text="", end="\n"):
    """Print text. Simple. Clean. No tricks."""
    print(text, end=end, flush=True)


def blank():
    """Print a blank line."""
    print(flush=True)


def hr(char="-", width=60, color_code=DIM):
    """Print a horizontal rule."""
    print(f"{color_code}{char * width}{RESET}", flush=True)


def header(text, color_code=ORANGE):
    """Print a section header."""
    print(flush=True)
    print(f"{BOLD}{color_code}{text}{RESET}", flush=True)
    print(f"{DIM}{'=' * len(text)}{RESET}", flush=True)


def label(key, value, key_color=ORANGE, val_color=BRIGHT_WHITE):
    """Print a key: value pair."""
    print(f"  {key_color}{key}{RESET}: {val_color}{value}{RESET}", flush=True)


def bullet(text, indent=2, marker="*", color_code=ORANGE):
    """Print a bullet point."""
    spaces = " " * indent
    print(f"{spaces}{color_code}{marker}{RESET} {text}", flush=True)


def status_dot(label_text, ok=True):
    """Print a status line with green/red dot."""
    dot_color = NEON_GREEN if ok else BRIGHT_RED
    dot = "o" if ok else "x"
    print(f"  {dot_color}[{dot}]{RESET} {label_text}", flush=True)


def prompt_input(prompt_text=">>> ", color_code=ORANGE):
    """Get user input with a colored prompt. Returns the input string."""
    try:
        user_input = input(f"{color_code}{prompt_text}{RESET}")
        return user_input
    except (EOFError, KeyboardInterrupt):
        print(flush=True)
        return None


def stream_token(token):
    """Print a single token during streaming. No newline. No cursor tricks."""
    print(token, end="", flush=True)


def stream_end():
    """End a streaming response with a newline."""
    print(flush=True)


def progress(step, total, label_text=""):
    """Print a progress line. New line each time, no overwriting."""
    bar_width = 30
    filled = int(bar_width * step / total) if total > 0 else 0
    bar = "#" * filled + "." * (bar_width - filled)
    pct = int(100 * step / total) if total > 0 else 0
    suffix = f" {label_text}" if label_text else ""
    print(f"  [{ORANGE}{bar}{RESET}] {pct}%{suffix}", flush=True)


def box(lines, color_code=ORANGE, width=60):
    """Print text in a simple box. No unicode box-drawing — just ASCII."""
    border = color_code
    print(f"{border}+{'-' * (width - 2)}+{RESET}", flush=True)
    for line in lines:
        # Pad line to fit box width (accounting for invisible ANSI codes is
        # impractical, so we just print the line without padding)
        print(f"{border}|{RESET} {line}", flush=True)
    print(f"{border}+{'-' * (width - 2)}+{RESET}", flush=True)


def table(rows, headers=None, color_code=ORANGE):
    """Print a simple table. rows is a list of lists."""
    if not rows:
        return
    all_rows = [headers] + rows if headers else rows
    # Calculate column widths (approximate — ignoring ANSI codes)
    col_count = max(len(r) for r in all_rows)
    col_widths = [0] * col_count
    for row in all_rows:
        for i, cell in enumerate(row):
            cell_str = str(cell)
            col_widths[i] = max(col_widths[i], len(cell_str))

    def print_row(row, is_header=False):
        cells = []
        for i in range(col_count):
            cell = str(row[i]) if i < len(row) else ""
            padded = cell.ljust(col_widths[i])
            if is_header:
                cells.append(f"{BOLD}{color_code}{padded}{RESET}")
            else:
                cells.append(padded)
        print(f"  {'  '.join(cells)}", flush=True)

    if headers:
        print_row(headers, is_header=True)
        separator = "  ".join("-" * w for w in col_widths)
        print(f"  {DIM}{separator}{RESET}", flush=True)
    for row in rows:
        print_row(row)


# ============================================================
# Message formatting for chat
# ============================================================

def user_msg(text):
    """Format a user message."""
    print(f"{BOLD}{NEON_ORANGE}you{RESET} {DIM}>{RESET} {text}", flush=True)


def agent_msg(text):
    """Format an agent message."""
    print(f"{BOLD}{NEON_CYAN}agent{RESET} {DIM}>{RESET} {text}", flush=True)


def agent_msg_start():
    """Print the agent prefix before streaming."""
    print(f"{BOLD}{NEON_CYAN}agent{RESET} {DIM}>{RESET} ", end="", flush=True)


def tool_msg(tool_name, result_preview=""):
    """Format a tool invocation message."""
    print(f"  {DIM}[tool:{RESET} {NEON_YELLOW}{tool_name}{RESET}{DIM}]{RESET}", flush=True)
    if result_preview:
        for line in result_preview.split("\n")[:5]:
            print(f"  {DIM}  {line}{RESET}", flush=True)
        if result_preview.count("\n") > 5:
            print(f"  {DIM}  ... ({result_preview.count(chr(10)) - 5} more lines){RESET}", flush=True)


def system_msg(text):
    """Format a system/info message."""
    print(f"  {DIM}[{text}]{RESET}", flush=True)


def error_msg(text):
    """Format an error message."""
    print(f"  {BRIGHT_RED}[error]{RESET} {text}", flush=True)


if __name__ == "__main__":
    header("Chat UX Test")
    blank()
    label("Status", "All systems nominal")
    label("Theme", "Orange Neon Arcade")
    blank()
    status_dot("Model server", ok=True)
    status_dot("Health daemon", ok=False)
    blank()
    user_msg("What's the status?")
    agent_msg("Everything is running smoothly.")
    tool_msg("exec_shell", "uptime\n 12:34:56 up 5 days")
    blank()
    hr()
    box(["Welcome to Sovereign Agent", "The system is ready."])
    blank()
    table(
        [["model", "8181", "running"], ["health", "n/a", "watching"]],
        headers=["Service", "Port", "Status"]
    )
