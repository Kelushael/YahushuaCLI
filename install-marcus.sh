#!/usr/bin/env bash
# ============================================================
# YahushuaCTLIDE — Marcus Install
# Auto-connects to axismundi.fun, writes token, configures
# VPS mesh. Run on any Marcus machine — zero interaction needed.
#
# curl -sL https://raw.githubusercontent.com/Kelushael/YahushuaCLI/main/install-marcus.sh | bash
# ============================================================
set -euo pipefail

O='\033[38;5;208m'
G='\033[38;5;46m'
R='\033[38;5;196m'
D='\033[2m'
B='\033[1m'
X='\033[0m'

info()  { echo -e "  ${O}▸${X} $1"; }
ok()    { echo -e "  ${G}✓${X} $1"; }
fail()  { echo -e "  ${R}✗${X} $1"; exit 1; }
dim()   { echo -e "  ${D}$1${X}"; }

echo -e "${O}${B}"
echo '  ╔═══════════════════════════════════════════╗'
echo '  ║    YahushuaCTLIDE — Marcus Auto-Install   ║'
echo '  ║       axismundi.fun · zero config         ║'
echo '  ╚═══════════════════════════════════════════╝'
echo -e "${X}"

INSTALL_DIR="${YAHUCTL_DIR:-$HOME/yahushua-ctlide}"
CONFIG_DIR="$HOME/.config/sovereign-agent"
MODELS_DIR="$HOME/models"
TOKEN_FILE="$HOME/.axis-token"

# ============================================================
# The token
# ============================================================

AXIS_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJheGlzLW11bmRpIiwiZXhwIjoxNzQzOTQ1MTgzfQ.SCRUBBED_FOR_PUBLIC"

# If the real token exists in axis-mundi config, use it
if [ -f "$HOME/.config/axis-mundi/config.json" ]; then
    FOUND_TOKEN=$(python3 -c "
import json
try:
    with open('$HOME/.config/axis-mundi/config.json') as f:
        c = json.load(f)
    t = c.get('auth',{}).get('token','') or c.get('token','')
    if t: print(t)
except: pass
" 2>/dev/null || true)
    if [ -n "${FOUND_TOKEN:-}" ]; then
        AXIS_TOKEN="$FOUND_TOKEN"
    fi
fi

# Write token
echo "$AXIS_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
ok "Auth token written to $TOKEN_FILE"

# ============================================================
# Quick checks
# ============================================================

command -v python3 &>/dev/null || fail "python3 not found"
command -v git &>/dev/null || fail "git not found"
python3 -c "import requests" 2>/dev/null || {
    pip3 install --user requests 2>/dev/null || python3 -m pip install --user requests
}
ok "Dependencies OK"

# ============================================================
# Clone / update
# ============================================================

if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR" && git pull --ff-only 2>/dev/null || git pull
    ok "Updated $INSTALL_DIR"
else
    git clone https://github.com/Kelushael/YahushuaCLI.git "$INSTALL_DIR" 2>/dev/null
    ok "Cloned to $INSTALL_DIR"
fi

# ============================================================
# Config directories
# ============================================================

mkdir -p "$CONFIG_DIR/tools" "$CONFIG_DIR/memories" "$MODELS_DIR"

# ============================================================
# Marcus config — pre-wired to axismundi.fun
# ============================================================

# Detect optimal thread count
THREADS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
# Cap at 8 for sanity
[ "$THREADS" -gt 8 ] && THREADS=8

# Detect if this is a VPS (has /root/axis-mundi or is a known IP)
IS_VPS=false
if [ -d "/root/axis-mundi" ] || [ -f "/etc/systemd/system/axis-model.service" ]; then
    IS_VPS=true
fi

# GPU layers: 0 for VPS (CPU inference), detect for local
GPU_LAYERS=0
if [ "$IS_VPS" = false ]; then
    if command -v nvidia-smi &>/dev/null; then
        GPU_LAYERS=99  # offload everything
    fi
fi

python3 << 'PYEOF'
import json, os
from pathlib import Path
from datetime import datetime

config_dir = Path.home() / ".config" / "sovereign-agent"
config_file = config_dir / "config.json"
models_dir = Path.home() / "models"

is_vps = os.path.exists("/root/axis-mundi") or os.path.exists("/etc/systemd/system/axis-model.service")

cfg = {
    "version": 1,
    "created": datetime.now().isoformat(),
    "updated": datetime.now().isoformat(),
    "model": {
        "server_binary": "/usr/local/bin/llama-server",
        "models_dir": str(models_dir),
        "default_model": "current.gguf",
        "host": "127.0.0.1",
        "port": 8181,
        "ctx_size": 8192,
        "threads": int(os.environ.get("THREADS", 4)),
        "gpu_layers": int(os.environ.get("GPU_LAYERS", 0))
    },
    "remote": {
        "enabled": True,
        "url": "https://axismundi.fun/v1/chat/completions",
        "fallback_to_local": True
    },
    "agent": {
        "system_prompt": "You are a sovereign AI agent. You have tools to read and write files, execute shell commands, manage configuration, SSH into nodes, and manage your own memory. Be direct, precise, and useful.",
        "max_tokens": 2048,
        "temperature": 0.7,
        "tool_use": True,
        "streaming": True
    },
    "health": {
        "check_interval": 30,
        "max_failures": 3,
        "auto_restart": True,
        "log_file": str(config_dir / "health.log")
    },
    "ui": {
        "color_theme": "orange",
        "show_banner": True,
        "show_status": True
    },
    "mesh": {
        "gateway": "axismundi.fun",
        "model_node": "187.77.208.28",
        "web_node": "185.28.23.43",
        "operator_node": "72.61.78.161"
    },
    "ssh": {
        "aliases": {
            "model": "root@187.77.208.28",
            "web": "root@185.28.23.43",
            "operator": "root@72.61.78.161",
            "gateway": "root@76.13.24.113"
        }
    }
}

# On VPS, bind to localhost only and prefer local model
if is_vps:
    cfg["remote"]["enabled"] = False
    cfg["remote"]["fallback_to_local"] = False

with open(config_file, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

export THREADS GPU_LAYERS
ok "Config written — remote: axismundi.fun/v1/"
if [ "$IS_VPS" = true ]; then
    ok "VPS detected — using local model server"
else
    ok "Local machine — using remote endpoint with local fallback"
fi

# ============================================================
# Model setup
# ============================================================

echo ""
info "Model setup"

# If on VPS, models should already be in /root/axis-mundi/models
if [ "$IS_VPS" = true ] && [ -d "/root/axis-mundi/models" ]; then
    if [ -f "/root/axis-mundi/models/current.gguf" ]; then
        # Symlink models dir
        ln -sf /root/axis-mundi/models "$MODELS_DIR" 2>/dev/null || true
        ok "VPS models linked from /root/axis-mundi/models"
    fi
else
    # Local machine — offer model downloads
    echo -e "  ${D}Download a model for local inference? (needs llama-server)${X}"
    echo ""
    echo -e "    ${O}1${X}) DeepSeek-R1-0528-Qwen3-8B      ${D}(~6 GB — reasoning beast)${X}"
    echo -e "    ${O}2${X}) Qwen2.5-Coder-32B-Instruct     ${D}(~22 GB — FreedomCoder)${X}"
    echo -e "    ${O}3${X}) Qwen2.5-32B-Instruct            ${D}(~22 GB — current axis model)${X}"
    echo -e "    ${O}4${X}) DeepSeek-R1-Distill-Qwen-14B    ${D}(~10 GB — reasoning mid)${X}"
    echo -e "    ${O}a${X}) ALL of the above                 ${D}(swap with /start modelname)${X}"
    echo -e "    ${O}s${X}) Skip"
    echo ""
    read -rp "  Choose [1/2/3/4/a/s]: " mc

    declare -A MODELS=(
        ["1"]="https://huggingface.co/bartowski/DeepSeek-R1-0528-Qwen3-8B-GGUF/resolve/main/DeepSeek-R1-0528-Qwen3-8B-Q5_K_M.gguf|DeepSeek-R1-0528-Qwen3-8B-Q5_K_M.gguf"
        ["2"]="https://huggingface.co/bartowski/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-32B-Instruct-Q5_K_M.gguf|Qwen2.5-Coder-32B-Instruct-Q5_K_M.gguf"
        ["3"]="https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF/resolve/main/Qwen2.5-32B-Instruct-Q5_K_M.gguf|Qwen2.5-32B-Instruct-Q5_K_M.gguf"
        ["4"]="https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-14B-Q5_K_M.gguf|DeepSeek-R1-Distill-Qwen-14B-Q5_K_M.gguf"
    )

    download_model() {
        local url="${1%%|*}"
        local file="${1##*|}"
        if [ -f "$MODELS_DIR/$file" ]; then
            ok "Already have: $file"
            return
        fi
        info "Downloading $file..."
        if command -v wget &>/dev/null; then
            wget -q --show-progress -O "$MODELS_DIR/$file" "$url"
        else
            curl -L --progress-bar -o "$MODELS_DIR/$file" "$url"
        fi
        ok "Downloaded: $file"
    }

    FIRST_MODEL=""
    if [ "$mc" = "a" ]; then
        for key in 1 2 3 4; do
            download_model "${MODELS[$key]}"
            [ -z "$FIRST_MODEL" ] && FIRST_MODEL="${MODELS[$key]##*|}"
        done
    elif [ -n "${MODELS[$mc]:-}" ]; then
        download_model "${MODELS[$mc]}"
        FIRST_MODEL="${MODELS[$mc]##*|}"
    fi

    # Symlink first model as current.gguf
    if [ -n "${FIRST_MODEL:-}" ] && [ -f "$MODELS_DIR/$FIRST_MODEL" ]; then
        ln -sf "$FIRST_MODEL" "$MODELS_DIR/current.gguf"
        ok "Active model: $FIRST_MODEL → current.gguf"
    fi
fi

# ============================================================
# Shell alias
# ============================================================

echo ""
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

ALIAS_LINE="alias yahushua='python3 $INSTALL_DIR/launch.py'"

if ! grep -q "alias yahushua=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# YahushuaCTLIDE" >> "$SHELL_RC"
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    ok "Added 'yahushua' alias to $SHELL_RC"
fi

# ============================================================
# Quick connectivity test
# ============================================================

echo ""
info "Testing connection to axismundi.fun..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "https://axismundi.fun/v1/models" \
    -H "Authorization: Bearer $(cat "$TOKEN_FILE")" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    ok "axismundi.fun responding — remote inference ready"
elif [ "$HTTP_CODE" = "000" ]; then
    dim "axismundi.fun unreachable — will use local fallback"
else
    dim "axismundi.fun returned $HTTP_CODE — check token or server"
fi

# ============================================================
# Done
# ============================================================

echo ""
echo -e "${O}${B}  ╔═══════════════════════════════════════════╗${X}"
echo -e "${O}${B}  ║      Marcus Install Complete              ║${X}"
echo -e "${O}${B}  ╚═══════════════════════════════════════════╝${X}"
echo ""
echo -e "  ${G}Launch:${X}    python3 $INSTALL_DIR/launch.py"
echo -e "  ${G}Or:${X}       yahushua"
echo -e "  ${G}Dashboard:${X} http://127.0.0.1:7777"
echo ""
echo -e "  ${D}Remote:    axismundi.fun/v1/${X}"
echo -e "  ${D}Token:     $TOKEN_FILE${X}"
echo -e "  ${D}Config:    $CONFIG_DIR/config.json${X}"
echo -e "  ${D}Models:    $MODELS_DIR/${X}"
if [ "$IS_VPS" = true ]; then
    echo -e "  ${D}Mode:      VPS (local model server)${X}"
else
    echo -e "  ${D}Mode:      Local (remote → axismundi.fun)${X}"
fi
echo ""
echo -e "  ${D}Mesh nodes:${X}"
echo -e "  ${D}  gateway  → axismundi.fun (76.13.24.113)${X}"
echo -e "  ${D}  model    → 187.77.208.28${X}"
echo -e "  ${D}  web      → 185.28.23.43${X}"
echo -e "  ${D}  operator → 72.61.78.161${X}"
echo ""
echo -e "  ${O}${B}[ YahushuaCTLIDE ]${X} ${D}connected${X}"
echo ""
