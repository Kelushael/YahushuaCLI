#!/usr/bin/env python3
"""
sovereign-agent/platform.py
Detect platform: android (termux), iphone (ish/a-shell), linux desktop, macos, windows/wsl.
Adjust behavior per platform. Export PLATFORM, IS_MOBILE, available_platform_tools().
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


# ============================================================
# Platform detection
# ============================================================

def _detect_platform():
    """Detect the current platform. Returns a string identifier."""
    # Android / Termux
    prefix = os.environ.get("PREFIX", "")
    if prefix.startswith("/data/data/com.termux"):
        return "android"

    # Check for Termux via other markers
    if os.path.isdir("/data/data/com.termux"):
        return "android"

    # iPhone / ish
    if os.path.exists("/proc/ish"):
        return "iphone"
    # a-Shell detection
    if os.environ.get("SHELL_NAME") == "a-Shell" or os.path.exists("/usr/local/bin/a-Shell"):
        return "iphone"
    # Another ish marker: uname returns "ish"
    try:
        uname = os.uname()
        if "ish" in uname.sysname.lower() or "ish" in uname.release.lower():
            return "iphone"
    except (AttributeError, OSError):
        pass

    platform_str = sys.platform.lower()

    # macOS
    if platform_str == "darwin":
        return "macos"

    # Windows / WSL
    if platform_str == "win32" or platform_str == "cygwin":
        return "windows"
    if platform_str.startswith("linux"):
        # Check for WSL
        try:
            with open("/proc/version", "r") as f:
                version_info = f.read().lower()
            if "microsoft" in version_info or "wsl" in version_info:
                return "wsl"
        except (IOError, FileNotFoundError):
            pass
        return "linux"

    return "unknown"


def _is_mobile(platform):
    """Check if the platform is a mobile device."""
    return platform in ("android", "iphone")


def _get_termux_tools():
    """List available termux-* API commands."""
    tools = []
    termux_cmds = [
        "termux-notification",
        "termux-vibrate",
        "termux-toast",
        "termux-clipboard-set",
        "termux-clipboard-get",
        "termux-battery-status",
        "termux-wifi-connectioninfo",
        "termux-tts-speak",
        "termux-camera-photo",
        "termux-share",
        "termux-open",
        "termux-open-url",
        "termux-volume",
        "termux-brightness",
        "termux-torch",
        "termux-sensor",
        "termux-location",
        "termux-telephony-deviceinfo",
        "termux-sms-send",
        "termux-dialog",
        "termux-download",
        "termux-media-player",
        "termux-microphone-record",
        "termux-fingerprint",
    ]
    for cmd in termux_cmds:
        if shutil.which(cmd):
            tools.append(cmd)
    return tools


def _get_desktop_tools():
    """List available desktop tools/commands."""
    tools = []
    desktop_cmds = [
        "xdg-open",
        "xclip",
        "xsel",
        "notify-send",
        "pactl",
        "xdotool",
        "wmctrl",
        "scrot",
        "feh",
        "mpv",
    ]
    for cmd in desktop_cmds:
        if shutil.which(cmd):
            tools.append(cmd)
    return tools


def _get_macos_tools():
    """List available macOS tools."""
    tools = []
    mac_cmds = [
        "open",
        "pbcopy",
        "pbpaste",
        "osascript",
        "say",
        "screencapture",
        "afplay",
    ]
    for cmd in mac_cmds:
        if shutil.which(cmd):
            tools.append(cmd)
    return tools


def _get_iphone_tools():
    """List available iPhone/ish tools."""
    # Very limited shell on ish/a-Shell
    tools = []
    phone_cmds = [
        "python3",
        "curl",
        "ssh",
        "scp",
    ]
    for cmd in phone_cmds:
        if shutil.which(cmd):
            tools.append(cmd)
    return tools


# ============================================================
# Public API
# ============================================================

PLATFORM = _detect_platform()
IS_MOBILE = _is_mobile(PLATFORM)


def available_platform_tools():
    """Return a list of platform-specific tools/commands available."""
    if PLATFORM == "android":
        return _get_termux_tools()
    elif PLATFORM == "iphone":
        return _get_iphone_tools()
    elif PLATFORM == "macos":
        return _get_macos_tools()
    elif PLATFORM in ("linux", "wsl"):
        return _get_desktop_tools()
    elif PLATFORM == "windows":
        return []  # Subprocess handles Windows differently
    return []


def platform_info():
    """Return a dict of platform information."""
    return {
        "platform": PLATFORM,
        "is_mobile": IS_MOBILE,
        "python_version": sys.version.split()[0],
        "home": str(Path.home()),
        "tools": available_platform_tools(),
    }


def adjust_path(path_str):
    """Adjust a file path for the current platform."""
    if PLATFORM == "android":
        # Termux uses /data/data/com.termux/files/home as ~
        if path_str.startswith("~"):
            home = os.environ.get("HOME", "/data/data/com.termux/files/home")
            return path_str.replace("~", home, 1)
    return os.path.expanduser(path_str)


def open_file(path_str):
    """Open a file with the platform's default handler."""
    path_str = adjust_path(path_str)
    if PLATFORM == "android":
        if shutil.which("termux-open"):
            subprocess.run(["termux-open", path_str])
            return True
    elif PLATFORM == "macos":
        subprocess.run(["open", path_str])
        return True
    elif PLATFORM in ("linux", "wsl"):
        if shutil.which("xdg-open"):
            subprocess.run(["xdg-open", path_str])
            return True
    elif PLATFORM == "windows":
        os.startfile(path_str)
        return True
    return False


def notify(title, message):
    """Send a platform notification."""
    if PLATFORM == "android":
        if shutil.which("termux-notification"):
            subprocess.run(["termux-notification", "--title", title, "--content", message])
            return True
    elif PLATFORM == "macos":
        if shutil.which("osascript"):
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script])
            return True
    elif PLATFORM in ("linux", "wsl"):
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message])
            return True
    return False


if __name__ == "__main__":
    info = platform_info()
    print(f"Platform: {info['platform']}")
    print(f"Mobile: {info['is_mobile']}")
    print(f"Python: {info['python_version']}")
    print(f"Home: {info['home']}")
    print(f"Platform tools: {', '.join(info['tools']) if info['tools'] else 'none'}")
