#!/usr/bin/env bash
# ============================================================
# YahushuaCTLIDE — Public Installer
# curl -sL https://raw.githubusercontent.com/Kelushael/YahushuaCLI/main/install.sh | bash
# ============================================================
set -euo pipefail

# Colors
O='\033[38;5;208m'  # orange
G='\033[38;5;46m'   # green
R='\033[38;5;196m'  # red
D='\033[2m'         # dim
B='\033[1m'         # bold
X='\033[0m'         # reset

banner() {
    echo -e "${O}${B}"
    echo '  ╔═══════════════════════════════════════════╗'
    echo '  ║     YahushuaCTLIDE — Public Installer     ║'
    echo '  ║   Command Terminal Interface & Dev Env    ║'
    echo '  ╚═══════════════════════════════════════════╝'
    echo -e "${X}"
}

info()  { echo -e "  ${O}▸${X} $1"; }
ok()    { echo -e "  ${G}✓${X} $1"; }
fail()  { echo -e "  ${R}✗${X} $1"; }
dim()   { echo -e "  ${D}$1${X}"; }

INSTALL_DIR="${YAHUCTL_DIR:-$HOME/yahushua-ctlide}"
CONFIG_DIR="$HOME/.config/sovereign-agent"
MODELS_DIR="$HOME/models"
LLAMA_CPP_DIR="$HOME/llama.cpp"

# ============================================================
# Checks
# ============================================================

banner

info "Checking system..."

# Python 3
if command -v python3 &>/dev/null; then
    PY=$(python3 --version 2>&1)
    ok "Python: $PY"
else
    fail "Python 3 not found"
    echo "  Install python3 first:"
    echo "    Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "    macOS: brew install python3"
    echo "    Arch: sudo pacman -S python"
    exit 1
fi

# pip / requests module
if python3 -c "import requests" 2>/dev/null; then
    ok "requests module available"
else
    info "Installing requests..."
    pip3 install --user requests 2>/dev/null || python3 -m pip install --user requests 2>/dev/null || {
        fail "Could not install 'requests' module"
        echo "  Run: pip3 install requests"
        exit 1
    }
    ok "requests installed"
fi

# Git
if command -v git &>/dev/null; then
    ok "Git available"
else
    fail "Git not found — install git first"
    exit 1
fi

# ============================================================
# Clone / Update
# ============================================================

echo ""
info "Installing YahushuaCTLIDE..."

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Existing install found, pulling latest..."
    cd "$INSTALL_DIR"
    git pull --ff-only 2>/dev/null || git pull
    ok "Updated"
else
    git clone https://github.com/Kelushael/YahushuaCLI.git "$INSTALL_DIR" 2>/dev/null
    ok "Cloned to $INSTALL_DIR"
fi

# ============================================================
# Config directory
# ============================================================

mkdir -p "$CONFIG_DIR"
mkdir -p "$CONFIG_DIR/tools"
mkdir -p "$CONFIG_DIR/memories"
mkdir -p "$MODELS_DIR"
ok "Config directory: $CONFIG_DIR"

# ============================================================
# Auth token
# ============================================================

echo ""
TOKEN_FILE="$HOME/.axis-token"
if [ -f "$TOKEN_FILE" ]; then
    ok "Auth token found at $TOKEN_FILE"
else
    info "No auth token found."
    echo ""
    echo -e "  ${D}If you have a remote inference endpoint, paste your token now.${X}"
    echo -e "  ${D}Press Enter to skip (local-only mode).${X}"
    echo ""
    read -rp "  Token: " user_token
    if [ -n "$user_token" ]; then
        echo "$user_token" > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
        ok "Token saved to $TOKEN_FILE"
    else
        dim "Skipped — you can add it later: echo 'YOUR_TOKEN' > ~/.axis-token"
    fi
fi

# ============================================================
# Remote endpoint config
# ============================================================

if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo ""
    info "Configure remote inference endpoint?"
    echo -e "  ${D}If you have a server running llama-server or any OpenAI-compatible API,${X}"
    echo -e "  ${D}enter the base URL (e.g., https://your-server.com/v1/chat/completions).${X}"
    echo -e "  ${D}Press Enter to skip (will use local llama-server on port 8181).${X}"
    echo ""
    read -rp "  Remote URL: " remote_url
    if [ -n "$remote_url" ]; then
        python3 -c "
import json, os
from pathlib import Path
cfg = {
    'version': 1,
    'model': {
        'server_binary': '/usr/local/bin/llama-server',
        'models_dir': os.path.expanduser('~/models'),
        'default_model': 'current.gguf',
        'host': '127.0.0.1',
        'port': 8181,
        'ctx_size': 8192,
        'threads': 4,
        'gpu_layers': 0
    },
    'remote': {
        'enabled': True,
        'url': '$remote_url',
        'fallback_to_local': True
    },
    'agent': {
        'system_prompt': 'You are a sovereign AI agent.',
        'max_tokens': 2048,
        'temperature': 0.7,
        'tool_use': True
    },
    'health': {
        'check_interval': 30,
        'max_failures': 3,
        'auto_restart': True,
        'log_file': str(Path.home() / '.config/sovereign-agent/health.log')
    },
    'ui': {'color_theme': 'orange', 'show_banner': True, 'show_status': True}
}
with open(os.path.expanduser('~/.config/sovereign-agent/config.json'), 'w') as f:
    json.dump(cfg, f, indent=2)
"
        ok "Remote endpoint configured: $remote_url"
    else
        dim "Skipped — will use local server or defaults"
    fi
fi

# ============================================================
# llama-server (optional)
# ============================================================

echo ""
info "Checking for llama-server..."

if command -v llama-server &>/dev/null; then
    ok "llama-server found: $(which llama-server)"
elif [ -f /usr/local/bin/llama-server ]; then
    ok "llama-server found: /usr/local/bin/llama-server"
else
    echo ""
    echo -e "  ${O}llama-server not found.${X}"
    echo -e "  ${D}This is the llama.cpp inference server for running local models.${X}"
    echo -e "  ${D}You only need it if you want to run models locally.${X}"
    echo ""
    read -rp "  Install llama.cpp from source? [y/N] " install_llama
    if [[ "$install_llama" =~ ^[Yy] ]]; then
        info "Building llama.cpp..."
        if command -v cmake &>/dev/null && command -v make &>/dev/null; then
            git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_DIR" 2>/dev/null || {
                cd "$LLAMA_CPP_DIR" && git pull
            }
            cd "$LLAMA_CPP_DIR"
            cmake -B build -DGGML_CUDA=OFF 2>/dev/null
            cmake --build build --config Release -j "$(nproc 2>/dev/null || echo 4)" 2>/dev/null
            if [ -f build/bin/llama-server ]; then
                sudo cp build/bin/llama-server /usr/local/bin/ 2>/dev/null || {
                    cp build/bin/llama-server "$HOME/.local/bin/" 2>/dev/null
                    info "Copied to ~/.local/bin/llama-server (add to PATH if needed)"
                }
                ok "llama-server built and installed"
            else
                fail "Build failed — check cmake/make output"
            fi
        else
            fail "Need cmake and make to build. Install them first."
            echo "  Ubuntu/Debian: sudo apt install cmake build-essential"
            echo "  macOS: brew install cmake"
        fi
    else
        dim "Skipped — you can install llama.cpp later"
        dim "See: https://github.com/ggml-org/llama.cpp"
    fi
fi

# ============================================================
# Model download (optional)
# ============================================================

echo ""
info "Model download"
echo -e "  ${D}YahushuaCTLIDE can download GGUF models for local inference.${X}"
echo -e "  ${D}All models are Q5_K_M quants from bartowski (high quality).${X}"
echo ""
echo "  Available models:"
echo -e "    ${O}1${X}) DeepSeek-R1-0528-Qwen3-8B      ${D}(~6 GB — reasoning, best all-rounder)${X}"
echo -e "    ${O}2${X}) Qwen2.5-Coder-32B-Instruct     ${D}(~22 GB — FreedomCoder, top coding)${X}"
echo -e "    ${O}3${X}) Qwen2.5-32B-Instruct            ${D}(~22 GB — general, Marcus's current)${X}"
echo -e "    ${O}4${X}) DeepSeek-R1-Distill-Qwen-14B    ${D}(~10 GB — reasoning, mid-weight)${X}"
echo -e "    ${O}5${X}) Skip — I'll bring my own model"
echo ""
read -rp "  Choose [1-5]: " model_choice

MODEL_URL=""
MODEL_FILE=""

case "$model_choice" in
    1)
        MODEL_URL="https://huggingface.co/bartowski/DeepSeek-R1-0528-Qwen3-8B-GGUF/resolve/main/DeepSeek-R1-0528-Qwen3-8B-Q5_K_M.gguf"
        MODEL_FILE="DeepSeek-R1-0528-Qwen3-8B-Q5_K_M.gguf"
        ;;
    2)
        MODEL_URL="https://huggingface.co/bartowski/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-32B-Instruct-Q5_K_M.gguf"
        MODEL_FILE="Qwen2.5-Coder-32B-Instruct-Q5_K_M.gguf"
        ;;
    3)
        MODEL_URL="https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF/resolve/main/Qwen2.5-32B-Instruct-Q5_K_M.gguf"
        MODEL_FILE="Qwen2.5-32B-Instruct-Q5_K_M.gguf"
        ;;
    4)
        MODEL_URL="https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-14B-Q5_K_M.gguf"
        MODEL_FILE="DeepSeek-R1-Distill-Qwen-14B-Q5_K_M.gguf"
        ;;
    *)
        dim "Skipped model download"
        dim "Drop any .gguf file into ~/models/ and it'll be picked up"
        ;;
esac

if [ -n "$MODEL_URL" ]; then
    if [ -f "$MODELS_DIR/$MODEL_FILE" ]; then
        ok "Model already exists: $MODEL_FILE"
    else
        info "Downloading $MODEL_FILE..."
        dim "This may take a while depending on your connection."
        echo ""
        if command -v wget &>/dev/null; then
            wget -q --show-progress -O "$MODELS_DIR/$MODEL_FILE" "$MODEL_URL" || {
                fail "Download failed"
                dim "You can download manually: wget -O ~/models/$MODEL_FILE $MODEL_URL"
            }
        elif command -v curl &>/dev/null; then
            curl -L --progress-bar -o "$MODELS_DIR/$MODEL_FILE" "$MODEL_URL" || {
                fail "Download failed"
                dim "You can download manually: curl -L -o ~/models/$MODEL_FILE $MODEL_URL"
            }
        else
            fail "Need wget or curl to download models"
            dim "Install one and run: wget -O ~/models/$MODEL_FILE $MODEL_URL"
        fi
    fi

    # Symlink as current.gguf
    if [ -f "$MODELS_DIR/$MODEL_FILE" ]; then
        ln -sf "$MODEL_FILE" "$MODELS_DIR/current.gguf"
        ok "Model ready: $MODEL_FILE → current.gguf"
    fi
fi

# ============================================================
# Shell alias
# ============================================================

echo ""
info "Setting up launch command..."

SHELL_RC=""
if [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
fi

ALIAS_LINE="alias yahushua='python3 $INSTALL_DIR/launch.py'"

if [ -n "$SHELL_RC" ]; then
    if grep -q "alias yahushua=" "$SHELL_RC" 2>/dev/null; then
        ok "Shell alias already exists"
    else
        read -rp "  Add 'yahushua' command to $SHELL_RC? [Y/n] " add_alias
        if [[ ! "$add_alias" =~ ^[Nn] ]]; then
            echo "" >> "$SHELL_RC"
            echo "# YahushuaCTLIDE" >> "$SHELL_RC"
            echo "$ALIAS_LINE" >> "$SHELL_RC"
            ok "Added alias to $SHELL_RC"
            dim "Run: source $SHELL_RC  (or open a new terminal)"
        fi
    fi
fi

# ============================================================
# Done
# ============================================================

echo ""
echo -e "${O}${B}  ╔═══════════════════════════════════════════╗${X}"
echo -e "${O}${B}  ║         Installation Complete!            ║${X}"
echo -e "${O}${B}  ╚═══════════════════════════════════════════╝${X}"
echo ""
echo -e "  ${G}Launch:${X}  python3 $INSTALL_DIR/launch.py"
if [ -n "$SHELL_RC" ] && grep -q "alias yahushua=" "$SHELL_RC" 2>/dev/null; then
    echo -e "  ${G}Or:${X}     yahushua  ${D}(after sourcing $SHELL_RC)${X}"
fi
echo ""
echo -e "  ${D}Config:    $CONFIG_DIR/config.json${X}"
echo -e "  ${D}Models:    $MODELS_DIR/${X}"
echo -e "  ${D}Token:     $TOKEN_FILE${X}"
echo -e "  ${D}Dashboard: http://127.0.0.1:7777  (when running)${X}"
echo ""
echo -e "  ${O}${B}[ YahushuaCTLIDE ]${X} ${D}Command Terminal Interface & Interactive Development Env${X}"
echo ""
