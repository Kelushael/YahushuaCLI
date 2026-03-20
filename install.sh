#!/usr/bin/env bash
# ============================================================
# claude-sov — Sovereign Claude Code
# curl -sL https://raw.githubusercontent.com/Kelushael/YahushuaCLI/main/install.sh | bash
# ============================================================
set -euo pipefail

O='\033[38;5;208m'; G='\033[38;5;46m'; D='\033[2m'; B='\033[1m'; X='\033[0m'
ok()   { echo -e "  ${G}✓${X} $1"; }
info() { echo -e "  ${O}▸${X} $1"; }

echo -e "${O}${B}"
echo '  ╔═══════════════════════════════════════════╗'
echo '  ║          claude-sov — Setup               ║'
echo '  ║     Your models. Their UX. Your rules.    ║'
echo '  ╚═══════════════════════════════════════════╝'
echo -e "${X}"

# ── Checks ────────────────────────────────────────────────────
command -v python3 &>/dev/null || { echo "  Need python3. Install it first."; exit 1; }
command -v git &>/dev/null || { echo "  Need git. Install it first."; exit 1; }
python3 -c "import requests" 2>/dev/null || pip3 install --user requests 2>/dev/null || python3 -m pip install --user requests 2>/dev/null
ok "Dependencies OK"

# ── Install ───────────────────────────────────────────────────
INSTALL_DIR="$HOME/claude-sov"

if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR" && git pull --ff-only 2>/dev/null || git pull
    ok "Updated"
else
    git clone https://github.com/Kelushael/YahushuaCLI.git "$INSTALL_DIR" 2>/dev/null
    ok "Installed to $INSTALL_DIR"
fi

# ── The one question ──────────────────────────────────────────
echo ""
echo -e "  ${O}${B}Where is your model running?${X}"
echo ""
echo -e "    ${O}1${X}) Right here ${D}(local llama-server on this machine)${X}"
echo -e "    ${O}2${X}) Remote server ${D}(VPS / another machine)${X}"
echo ""
read -rp "  Choose [1/2]: " choice

if [[ "$choice" == "2" ]]; then
    echo ""
    read -rp "  Server IP or domain: " SERVER_IP
    SERVER_IP="${SERVER_IP%/}"

    # Check if they gave a full URL or just an IP
    if [[ "$SERVER_IP" == http* ]]; then
        BASE_URL="$SERVER_IP"
    else
        # Default to HTTPS, fall back to HTTP
        if curl -s --max-time 3 "https://$SERVER_IP/v1/messages" -o /dev/null 2>/dev/null; then
            BASE_URL="https://$SERVER_IP"
        else
            BASE_URL="http://$SERVER_IP:8182"
        fi
    fi
else
    BASE_URL="http://127.0.0.1:8182"
    info "Make sure gesher.py is running locally (python3 $INSTALL_DIR/gesher.py)"
fi

# ── Write the launcher ────────────────────────────────────────
cat > "$INSTALL_DIR/claude-sov.sh" << LAUNCHER
#!/usr/bin/env bash
export ANTHROPIC_BASE_URL="$BASE_URL"
export ANTHROPIC_API_KEY="\${ANTHROPIC_API_KEY:-sovereign-local}"
# Read token if it exists
[ -f "\$HOME/.axis-token" ] && export ANTHROPIC_API_KEY="\$(cat \$HOME/.axis-token | tr -d '\\n')"
claude "\$@"
LAUNCHER
chmod +x "$INSTALL_DIR/claude-sov.sh"
ok "Configured → $BASE_URL"

# ── Shell alias ───────────────────────────────────────────────
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

if ! grep -q "alias claude-sov=" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# claude-sov — sovereign Claude Code" >> "$SHELL_RC"
    echo "alias claude-sov='$INSTALL_DIR/claude-sov.sh'" >> "$SHELL_RC"
    ok "Added 'claude-sov' command to $SHELL_RC"
fi

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${O}${B}  Done.${X}"
echo ""
echo -e "  ${G}Run:${X}  source $SHELL_RC && claude-sov"
echo -e "  ${D}Or:   $INSTALL_DIR/claude-sov.sh${X}"
echo ""
echo -e "  ${D}Model endpoint: $BASE_URL${X}"
echo -e "  ${D}To change later: edit $INSTALL_DIR/claude-sov.sh${X}"
echo ""
echo -e "  ${O}${B}claude-sov${X} ${D}— your models, their UX, your rules${X}"
echo ""
