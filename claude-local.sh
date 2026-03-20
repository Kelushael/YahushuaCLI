#!/usr/bin/env bash
# ============================================================
# claude-local.sh — Launch Claude Code against sovereign models
#
# Points Claude Code at Gesher-el bridge on axismundi.fun.
# Gesher-el accepts Anthropic format, translates to OpenAI,
# forwards to llama-server. Claude Code sees it as native.
#
# Usage:
#   source ~/sovereign-agent/claude-local.sh    # set env
#   claude                                       # launch normally
#
# Or add alias to .bashrc/.zshrc:
#   alias claude-sov='source ~/sovereign-agent/claude-local.sh && claude'
# ============================================================

# --- Config ---
# Gesher-el bridge on the VPS (Anthropic-compatible)
SOVEREIGN_URL="${SOVEREIGN_URL:-https://axismundi.fun}"

# Read token from ~/.axis-token (zero-config)
TOKEN_FILE="$HOME/.axis-token"
if [ -f "$TOKEN_FILE" ]; then
    SOVEREIGN_TOKEN=$(cat "$TOKEN_FILE" | tr -d '\n')
else
    SOVEREIGN_TOKEN="sovereign-local"
fi

# --- The swap ---
export ANTHROPIC_BASE_URL="$SOVEREIGN_URL"
export ANTHROPIC_API_KEY="$SOVEREIGN_TOKEN"

echo -e "\033[38;5;208m▸\033[0m Claude Code → $SOVEREIGN_URL (Gesher-el bridge)"
echo -e "\033[38;5;208m▸\033[0m Token: ${SOVEREIGN_TOKEN:0:6}...${SOVEREIGN_TOKEN: -4}"
echo -e "\033[2m  Model: whatever GGUF is loaded on VPS"
echo -e "  To revert: unset ANTHROPIC_BASE_URL ANTHROPIC_API_KEY\033[0m"
echo ""
