#!/usr/bin/env bash
# ============================================================
# Symbioz Pro - Offline Installer
# Autonomous AI organism for Android/Termux
# Usage: bash install.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/symbioz_pro"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RESET='\033[0m'

echo ""
echo -e "${CYAN}============================================${RESET}"
echo -e "${CYAN}   Symbioz Pro - Offline Installer${RESET}"
echo -e "${CYAN}============================================${RESET}"
echo ""

# ---------- 1. Pre-flight checks ----------
echo -e "${YELLOW}[1/8] Pre-flight checks${RESET}"

if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}ERROR: python3 not found. Install with: pkg install python${RESET}"
    exit 1
fi
echo -e "  ${GREEN}python3$(RESET): $(python3 --version 2>&1)"

if ! command -v pip >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
    echo -e "${YELLOW}  pip not found, will attempt install${RESET}"
fi

echo -e "  ${GREEN}Architecture${RESET}: $(uname -m)"
echo -e "  ${GREEN}Storage${RESET}: $(df -h "$HOME" 2>/dev/null | tail -1 | awk '{print $4}') available"
echo ""

# ---------- 2. Install system packages (debs) ----------
echo -e "${YELLOW}[2/8] Installing system packages${RESET}"

if [ -d "${SCRIPT_DIR}/debs" ] && ls "${SCRIPT_DIR}/debs/"*.deb >/dev/null 2>&1; then
    for deb in "${SCRIPT_DIR}/debs/"*.deb; do
        dpkg -i "$deb" 2>/dev/null || apt-get install -f -y 2>/dev/null || true
    done
    echo -e "  ${GREEN}System packages installed${RESET}"
else
    echo -e "  ${YELLOW}No .deb packages found, skipping${RESET}"
fi
echo ""

# ---------- 3. Install Python dependencies ----------
echo -e "${YELLOW}[3/8] Installing Python dependencies${RESET}"

PIP_CMD="pip3"
command -v pip3 >/dev/null 2>&1 || PIP_CMD="pip"

if [ -d "${SCRIPT_DIR}/wheels" ] && ls "${SCRIPT_DIR}/wheels/"*.whl >/dev/null 2>&1; then
    $PIP_CMD install --no-index --find-links="${SCRIPT_DIR}/wheels" -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null || {
        echo -e "  ${YELLOW}Wheel install failed, trying online fallback...${RESET}"
        $PIP_CMD install -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null || {
            echo -e "  ${RED}WARNING: Some dependencies may not be installed${RESET}"
        }
    }
    echo -e "  ${GREEN}Python dependencies installed${RESET}"
elif [ -f "${SCRIPT_DIR}/requirements.txt" ]; then
    $PIP_CMD install -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null || {
        echo -e "  ${RED}WARNING: Could not install Python dependencies${RESET}"
    }
else
    echo -e "  ${YELLOW}No requirements.txt found, skipping${RESET}"
fi
echo ""

# ---------- 4. Setup Ollama ----------
echo -e "${YELLOW}[4/8] Setting up Ollama${RESET}"

if [ -f "${SCRIPT_DIR}/ollama-arm64" ]; then
    chmod +x "${SCRIPT_DIR}/ollama-arm64"
    echo -e "  ${GREEN}Ollama binary ready (local)${RESET}"
elif command -v ollama >/dev/null 2>&1; then
    echo -e "  ${GREEN}Ollama already installed (system)${RESET}"
else
    echo -e "  ${RED}WARNING: Ollama binary not found!${RESET}"
    echo -e "  ${YELLOW}  Place ollama-arm64 in the archive root or install ollama manually${RESET}"
fi
echo ""

# ---------- 5. Import model ----------
echo -e "${YELLOW}[5/8] Importing AI model${RESET}"

OLLAMA_BIN="${SCRIPT_DIR}/ollama-arm64"
[ -x "$OLLAMA_BIN" ] || OLLAMA_BIN="$(command -v ollama 2>/dev/null || echo "")"

if [ -n "$OLLAMA_BIN" ]; then
    export OLLAMA_MODELS="${SCRIPT_DIR}/models"
    # Start Ollama temporarily for model import
    nohup "$OLLAMA_BIN" serve >/dev/null 2>&1 &
    OLLAMA_PID=$!
    sleep 5

    MODEL_FILE="${SCRIPT_DIR}/models/qwen2.5-3b-q4_k_m.gguf"
    if [ -f "$MODEL_FILE" ]; then
        # Create Modelfile for symbioz profile
        cat > /tmp/symbioz_modelfile <<'MODELFILE'
FROM ./models/qwen2.5-3b-q4_k_m.gguf
PARAMETER temperature 0.7
PARAMETER top_p 0.9
SYSTEM "You are Symbioz, an autonomous AI organism. You help your host with analytical thinking, decision support, and knowledge synthesis."
MODELFILE
        cd "$SCRIPT_DIR"
        "$OLLAMA_BIN" create symbioz -f /tmp/symbioz_modelfile 2>/dev/null && {
            echo -e "  ${GREEN}Model 'symbioz' created successfully${RESET}"
        } || {
            echo -e "  ${YELLOW}Model import deferred (will import on first run)${RESET}"
        }
        rm -f /tmp/symbioz_modelfile
    else
        echo -e "  ${YELLOW}Model file not found: ${MODEL_FILE}${RESET}"
        echo -e "  ${YELLOW}  Place qwen2.5-3b-q4_k_m.gguf in models/ directory${RESET}"
    fi

    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
else
    echo -e "  ${YELLOW}Skipping model import (no Ollama binary)${RESET}"
fi
echo ""

# ---------- 6. Copy source code ----------
echo -e "${YELLOW}[6/8] Setting up Symbioz Pro${RESET}"

if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    # Copy core files
    for dir in src services tools data; do
        if [ -d "${SCRIPT_DIR}/${dir}" ]; then
            cp -r "${SCRIPT_DIR}/${dir}" "${INSTALL_DIR}/"
        fi
    done
    # Copy config files
    for f in requirements.txt README_OFFLINE.md uninstall.sh; do
        [ -f "${SCRIPT_DIR}/${f}" ] && cp "${SCRIPT_DIR}/${f}" "${INSTALL_DIR}/"
    done
    # Copy Ollama binary
    [ -f "${SCRIPT_DIR}/ollama-arm64" ] && cp "${SCRIPT_DIR}/ollama-arm64" "${INSTALL_DIR}/"
    # Link models (avoid copying 2GB+)
    if [ -d "${SCRIPT_DIR}/models" ] && [ ! -d "${INSTALL_DIR}/models" ]; then
        ln -sf "${SCRIPT_DIR}/models" "${INSTALL_DIR}/models"
    fi
    echo -e "  ${GREEN}Installed to: ${INSTALL_DIR}${RESET}"
else
    echo -e "  ${GREEN}Running from install directory${RESET}"
fi

# Make scripts executable
chmod +x "${INSTALL_DIR}/services/"*.sh 2>/dev/null || true
chmod +x "${INSTALL_DIR}/tools/"*.sh 2>/dev/null || true
chmod +x "${INSTALL_DIR}/uninstall.sh" 2>/dev/null || true
echo ""

# ---------- 7. Initialize genesis ----------
echo -e "${YELLOW}[7/8] Initializing organism${RESET}"

cd "$INSTALL_DIR"
if [ -f "data/initial_genesis.json" ]; then
    python3 -c "
import json, os, hashlib, time
genesis = json.load(open('data/initial_genesis.json'))
state = {
    'alive': True,
    'born': time.time(),
    'genesis_hash': hashlib.sha256(json.dumps(genesis, sort_keys=True).encode()).hexdigest(),
    'version': genesis.get('version', '1.0'),
    'cycles': 0
}
os.makedirs('data', exist_ok=True)
json.dump(state, open('data/unity_state.json', 'w'), indent=2)
print('  Genesis initialized')
" 2>/dev/null && {
        echo -e "  ${GREEN}Organism state initialized${RESET}"
    } || {
        echo -e "  ${YELLOW}Genesis initialization deferred${RESET}"
    }
else
    echo -e "  ${YELLOW}No genesis config found, skipping${RESET}"
fi
echo ""

# ---------- 8. Autostart setup (optional) ----------
echo -e "${YELLOW}[8/8] Autostart configuration (Termux:Boot)${RESET}"

read -p "  Configure autostart on device boot? [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    mkdir -p "${HOME}/.termux/boot"
    if [ -f "${INSTALL_DIR}/services/symbioz_boot.sh" ]; then
        cp "${INSTALL_DIR}/services/symbioz_boot.sh" "${HOME}/.termux/boot/"
        chmod +x "${HOME}/.termux/boot/symbioz_boot.sh"
        echo -e "  ${GREEN}Autostart configured!${RESET}"
        echo -e "  ${BLUE}Install Termux:Boot for full autonomy:${RESET}"
        echo -e "  ${BLUE}  -> https://f-droid.org/packages/com.termux.boot/${RESET}"
    else
        echo -e "  ${RED}Boot script not found${RESET}"
    fi
else
    echo -e "  ${YELLOW}Skipped. Manual start: bash services/symbioz_boot.sh${RESET}"
fi

# ---------- Done ----------
echo ""
echo -e "${GREEN}============================================${RESET}"
echo -e "${GREEN}   Symbioz Pro installed successfully!${RESET}"
echo -e "${GREEN}============================================${RESET}"
echo ""
echo -e "  Install dir:   ${BLUE}${INSTALL_DIR}${RESET}"
echo -e "  Start:         ${CYAN}bash ${INSTALL_DIR}/services/symbioz_boot.sh${RESET}"
echo -e "  Health check:  ${CYAN}bash ${INSTALL_DIR}/tools/health_check.sh${RESET}"
echo -e "  Backup:        ${CYAN}bash ${INSTALL_DIR}/tools/backup_state.sh${RESET}"
echo -e "  Uninstall:     ${CYAN}bash ${INSTALL_DIR}/uninstall.sh${RESET}"
echo ""
