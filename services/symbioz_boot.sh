#!/usr/bin/env bash
# ============================================================
# Symbioz Pro Boot Script
# Автозапуск при вмиканні пристрою (Termux:Boot)
# Копіюється в ~/.termux/boot/ під час інсталяції
# ============================================================

SYMBIOZ_DIR="${HOME}/symbioz_pro"
LOG_DIR="${SYMBIOZ_DIR}/logs"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [BOOT] $*" >> "${LOG_DIR}/boot.log"
}

log "Symbioz Pro boot sequence initiated"

# ---------- 1. Запуск Ollama ----------
if [ -x "${SYMBIOZ_DIR}/ollama-arm64" ]; then
    export OLLAMA_MODELS="${SYMBIOZ_DIR}/models"
    nohup "${SYMBIOZ_DIR}/ollama-arm64" serve >> "${LOG_DIR}/ollama.log" 2>&1 &
    log "Ollama started (local binary)"
elif command -v ollama >/dev/null 2>&1; then
    nohup ollama serve >> "${LOG_DIR}/ollama.log" 2>&1 &
    log "Ollama started (system binary)"
else
    log "ERROR: Ollama binary not found!"
fi

sleep 5

# ---------- 2. Запуск LifeSupport ----------
cd "$SYMBIOZ_DIR" || exit 1

if [ -f "${SYMBIOZ_DIR}/src/interfaces/lifesupport.py" ]; then
    nohup python3 -m src.interfaces.lifesupport >> "${LOG_DIR}/lifesupport.log" 2>&1 &
    log "LifeSupport started"
else
    log "ERROR: LifeSupport module not found!"
fi

sleep 3

# ---------- 3. Запуск Watchdog ----------
if [ -f "${SYMBIOZ_DIR}/services/symbioz_watchdog.sh" ]; then
    nohup bash "${SYMBIOZ_DIR}/services/symbioz_watchdog.sh" >> "${LOG_DIR}/watchdog.log" 2>&1 &
    log "Watchdog started"
fi

log "Boot sequence completed"

# ---------- 4. Сповіщення (якщо Termux:API встановлено) ----------
if command -v termux-notification >/dev/null 2>&1; then
    termux-notification \
        --title "Symbioz Pro" \
        --content "System started successfully" \
        --id symbioz_boot \
        --priority high
fi
