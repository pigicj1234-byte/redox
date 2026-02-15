#!/usr/bin/env bash
# ============================================================
# Symbioz Pro Watchdog
# Автоматичне відновлення критичних процесів
# Запуск: nohup bash services/symbioz_watchdog.sh &
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
WATCHDOG_LOG="${LOG_DIR}/watchdog.log"
CHECK_INTERVAL=30  # секунди між перевірками
MAX_RESTART_ATTEMPTS=5
RESTART_COOLDOWN=60  # секунди між спробами перезапуску

mkdir -p "$LOG_DIR"

# Лічильники перезапусків
declare -A restart_counts
declare -A last_restart_time
restart_counts[ollama]=0
restart_counts[lifesupport]=0
last_restart_time[ollama]=0
last_restart_time[lifesupport]=0

log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${level}] $*" | tee -a "$WATCHDOG_LOG"
}

check_ollama() {
    if pgrep -f "ollama serve" >/dev/null 2>&1; then
        if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

check_lifesupport() {
    if pgrep -f "lifesupport.py" >/dev/null 2>&1; then
        if curl -sf http://127.0.0.1:5055/status >/dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

restart_ollama() {
    local now
    now=$(date +%s)
    local last=${last_restart_time[ollama]}
    local count=${restart_counts[ollama]}

    if (( now - last < RESTART_COOLDOWN )); then
        log "WARN" "Ollama: cooldown active, skipping restart"
        return 1
    fi

    if (( count >= MAX_RESTART_ATTEMPTS )); then
        log "CRIT" "Ollama: max restart attempts ($MAX_RESTART_ATTEMPTS) reached!"
        return 1
    fi

    log "WARN" "Ollama DOWN - restarting (attempt $((count + 1))/$MAX_RESTART_ATTEMPTS)..."

    pkill -f "ollama serve" 2>/dev/null || true
    sleep 2

    if [ -x "${SCRIPT_DIR}/ollama-arm64" ]; then
        OLLAMA_MODELS="${SCRIPT_DIR}/models" nohup "${SCRIPT_DIR}/ollama-arm64" serve >/dev/null 2>&1 &
    elif command -v ollama >/dev/null 2>&1; then
        nohup ollama serve >/dev/null 2>&1 &
    else
        log "ERROR" "Ollama binary not found!"
        return 1
    fi

    sleep 5

    if check_ollama; then
        log "OK" "Ollama restarted successfully"
        restart_counts[ollama]=0
        last_restart_time[ollama]=$now
        return 0
    else
        restart_counts[ollama]=$((count + 1))
        last_restart_time[ollama]=$now
        log "ERROR" "Ollama failed to start"
        return 1
    fi
}

restart_lifesupport() {
    local now
    now=$(date +%s)
    local last=${last_restart_time[lifesupport]}
    local count=${restart_counts[lifesupport]}

    if (( now - last < RESTART_COOLDOWN )); then
        log "WARN" "LifeSupport: cooldown active, skipping restart"
        return 1
    fi

    if (( count >= MAX_RESTART_ATTEMPTS )); then
        log "CRIT" "LifeSupport: max restart attempts ($MAX_RESTART_ATTEMPTS) reached!"
        return 1
    fi

    log "WARN" "LifeSupport DOWN - restarting (attempt $((count + 1))/$MAX_RESTART_ATTEMPTS)..."

    pkill -f "lifesupport.py" 2>/dev/null || true
    sleep 2

    cd "$SCRIPT_DIR"
    nohup python3 -m src.interfaces.lifesupport >/dev/null 2>&1 &
    sleep 5

    if check_lifesupport; then
        log "OK" "LifeSupport restarted successfully"
        restart_counts[lifesupport]=0
        last_restart_time[lifesupport]=$now
        return 0
    else
        restart_counts[lifesupport]=$((count + 1))
        last_restart_time[lifesupport]=$now
        log "ERROR" "LifeSupport failed to start"
        return 1
    fi
}

reset_counters_daily() {
    local current_hour
    current_hour=$(date +%H)
    if [ "$current_hour" = "00" ]; then
        restart_counts[ollama]=0
        restart_counts[lifesupport]=0
        log "INFO" "Daily counter reset"
    fi
}

# ---------- Main Loop ----------
log "INFO" "Symbioz Watchdog started (PID: $$, interval: ${CHECK_INTERVAL}s)"

trap 'log "INFO" "Watchdog stopped (PID: $$)"; exit 0' SIGTERM SIGINT

while true; do
    if ! check_ollama; then
        restart_ollama || true
    fi

    if ! check_lifesupport; then
        restart_lifesupport || true
    fi

    reset_counters_daily

    sleep "$CHECK_INTERVAL"
done
