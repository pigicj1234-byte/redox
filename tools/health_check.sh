#!/usr/bin/env bash
# ============================================================
# Symbioz Pro - Health Check
# Quick diagnostics of all system components
# Usage: bash tools/health_check.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

echo ""
echo -e "${BLUE}Symbioz Pro Health Check${RESET}"
echo ""

passed=0
failed=0
warnings=0

check_pass() {
    echo -e "  ${GREEN}[OK]${RESET} $1"
    ((passed++))
}

check_fail() {
    echo -e "  ${RED}[FAIL]${RESET} $1"
    ((failed++))
}

check_warn() {
    echo -e "  ${YELLOW}[WARN]${RESET} $1"
    ((warnings++))
}

# ---------- 1. Ollama ----------
echo -e "${BLUE}--- Ollama ---${RESET}"
if pgrep -f "ollama serve" >/dev/null 2>&1; then
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        check_pass "Ollama: HEALTHY (port 11434)"
    else
        check_fail "Ollama: process running but API not responding"
    fi
else
    check_fail "Ollama: NOT RUNNING"
fi

# ---------- 2. LifeSupport ----------
echo -e "${BLUE}--- LifeSupport ---${RESET}"
if pgrep -f "lifesupport.py" >/dev/null 2>&1; then
    if curl -sf http://127.0.0.1:5055/status 2>/dev/null | grep -q '"status"'; then
        status_val=$(curl -sf http://127.0.0.1:5055/status 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
        if [ "$status_val" = "healthy" ]; then
            check_pass "LifeSupport: HEALTHY (port 5055)"
        else
            check_warn "LifeSupport: running but status='${status_val}'"
        fi
    else
        check_fail "LifeSupport: process running but API not responding"
    fi
else
    check_fail "LifeSupport: NOT RUNNING"
fi

# ---------- 3. Unity Organism ----------
echo -e "${BLUE}--- Unity Organism ---${RESET}"
cd "$SCRIPT_DIR"
if python3 -m src.interfaces.cli vital 2>/dev/null | grep -q '"alive": *true'; then
    check_pass "Unity: ALIVE"
elif python3 -m src.interfaces.cli vital 2>/dev/null | grep -q '"alive"'; then
    check_warn "Unity: SLEEPING"
else
    check_fail "Unity: NOT RESPONDING or corrupted"
fi

# ---------- 4. Model ----------
echo -e "${BLUE}--- AI Model ---${RESET}"
if command -v ollama >/dev/null 2>&1 || [ -x "${SCRIPT_DIR}/ollama-arm64" ]; then
    model_list=$(ollama list 2>/dev/null || "${SCRIPT_DIR}/ollama-arm64" list 2>/dev/null || echo "")
    if echo "$model_list" | grep -qi "symbioz"; then
        check_pass "Model: symbioz profile found"
    elif echo "$model_list" | grep -qi "qwen"; then
        check_warn "Model: qwen found but no 'symbioz' profile"
    elif [ -n "$model_list" ]; then
        check_warn "Model: ollama has models but 'symbioz' not found"
    else
        check_fail "Model: no models loaded"
    fi
else
    check_fail "Model: ollama binary not found"
fi

# ---------- 5. Watchdog ----------
echo -e "${BLUE}--- Watchdog ---${RESET}"
if pgrep -f "symbioz_watchdog.sh" >/dev/null 2>&1; then
    check_pass "Watchdog: ACTIVE"
else
    check_warn "Watchdog: not running (optional)"
fi

# ---------- 6. Data Integrity ----------
echo -e "${BLUE}--- Data Integrity ---${RESET}"
if [ -f "${SCRIPT_DIR}/data/unity_state.json" ]; then
    if python3 -c "import json; json.load(open('${SCRIPT_DIR}/data/unity_state.json'))" 2>/dev/null; then
        check_pass "unity_state.json: valid JSON"
    else
        check_fail "unity_state.json: corrupted!"
    fi
else
    check_warn "unity_state.json: not found (first run?)"
fi

if [ -f "${SCRIPT_DIR}/data/initial_genesis.json" ]; then
    check_pass "initial_genesis.json: present"
else
    check_warn "initial_genesis.json: not found"
fi

if [ -f "${SCRIPT_DIR}/data/tamper_hmac_key.bin" ]; then
    check_pass "tamper_hmac_key.bin: present"
else
    check_warn "tamper_hmac_key.bin: not found"
fi

# ---------- 7. Disk Space ----------
echo -e "${BLUE}--- Resources ---${RESET}"
available_mb=$(df -m "$SCRIPT_DIR" 2>/dev/null | tail -1 | awk '{print $4}')
if [ -n "$available_mb" ] && [ "$available_mb" -gt 500 ] 2>/dev/null; then
    check_pass "Disk: ${available_mb}MB available"
elif [ -n "$available_mb" ] && [ "$available_mb" -gt 100 ] 2>/dev/null; then
    check_warn "Disk: ${available_mb}MB available (low!)"
else
    check_warn "Disk: could not determine free space"
fi

# ---------- 8. Backups ----------
echo -e "${BLUE}--- Backups ---${RESET}"
backup_count=$(ls -1 "${HOME}/symbioz_backups"/backup_*.tar.gz 2>/dev/null | wc -l)
if (( backup_count > 0 )); then
    latest=$(ls -1t "${HOME}/symbioz_backups"/backup_*.tar.gz 2>/dev/null | head -1)
    latest_name=$(basename "$latest")
    check_pass "Backups: ${backup_count} found (latest: ${latest_name})"
else
    check_warn "Backups: none found (run: bash tools/backup_state.sh)"
fi

# ---------- Summary ----------
echo ""
echo -e "${BLUE}========================================${RESET}"
total=$((passed + failed + warnings))
echo -e "  Passed:   ${GREEN}${passed}${RESET}/${total}"
echo -e "  Failed:   ${RED}${failed}${RESET}/${total}"
echo -e "  Warnings: ${YELLOW}${warnings}${RESET}/${total}"

if (( failed == 0 )); then
    echo -e "\n  ${GREEN}System status: OPERATIONAL${RESET}"
elif (( failed <= 2 )); then
    echo -e "\n  ${YELLOW}System status: DEGRADED${RESET}"
else
    echo -e "\n  ${RED}System status: CRITICAL${RESET}"
fi
echo -e "${BLUE}========================================${RESET}"
echo ""
