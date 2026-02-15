#!/usr/bin/env bash
# ============================================================
# Symbioz Pro - Backup State
# Збереження стану організму в timestamped архів
# Використання: bash tools/backup_state.sh [backup_dir]
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_BASE="${1:-${HOME}/symbioz_backups}"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_NAME="backup_${TIMESTAMP}"
BACKUP_TMP="${BACKUP_BASE}/.tmp_${BACKUP_NAME}"
BACKUP_FILE="${BACKUP_BASE}/${BACKUP_NAME}.tar.gz"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

echo -e "${BLUE}=== Symbioz Pro State Backup ===${RESET}"
echo -e "Timestamp: ${TIMESTAMP}"
echo -e "Source:    ${SCRIPT_DIR}"
echo -e "Target:    ${BACKUP_FILE}"
echo ""

mkdir -p "$BACKUP_BASE" "$BACKUP_TMP"

# ---------- Збираємо файли стану ----------
file_count=0

# Unity State
if [ -f "${SCRIPT_DIR}/data/unity_state.json" ]; then
    mkdir -p "${BACKUP_TMP}/data"
    cp "${SCRIPT_DIR}/data/unity_state.json" "${BACKUP_TMP}/data/"
    echo -e "  ${GREEN}+${RESET} data/unity_state.json"
    ((file_count++))
fi

# Genesis Configuration
if [ -f "${SCRIPT_DIR}/data/initial_genesis.json" ]; then
    mkdir -p "${BACKUP_TMP}/data"
    cp "${SCRIPT_DIR}/data/initial_genesis.json" "${BACKUP_TMP}/data/"
    echo -e "  ${GREEN}+${RESET} data/initial_genesis.json"
    ((file_count++))
fi

# HMAC Key
if [ -f "${SCRIPT_DIR}/data/tamper_hmac_key.bin" ]; then
    mkdir -p "${BACKUP_TMP}/data"
    cp "${SCRIPT_DIR}/data/tamper_hmac_key.bin" "${BACKUP_TMP}/data/"
    echo -e "  ${GREEN}+${RESET} data/tamper_hmac_key.bin"
    ((file_count++))
fi

# Audit Log History
if [ -f "${SCRIPT_DIR}/src/config/auditloghistory.yaml" ]; then
    mkdir -p "${BACKUP_TMP}/src/config"
    cp "${SCRIPT_DIR}/src/config/auditloghistory.yaml" "${BACKUP_TMP}/src/config/"
    echo -e "  ${GREEN}+${RESET} src/config/auditloghistory.yaml"
    ((file_count++))
fi

# All config files
if [ -d "${SCRIPT_DIR}/src/config" ]; then
    mkdir -p "${BACKUP_TMP}/src/config"
    cp -r "${SCRIPT_DIR}/src/config/"*.yaml "${BACKUP_TMP}/src/config/" 2>/dev/null || true
    cp -r "${SCRIPT_DIR}/src/config/"*.json "${BACKUP_TMP}/src/config/" 2>/dev/null || true
    echo -e "  ${GREEN}+${RESET} src/config/*.yaml, *.json"
fi

# LifeSupport Logs
if [ -d "${SCRIPT_DIR}/logs" ]; then
    mkdir -p "${BACKUP_TMP}/logs"
    cp -r "${SCRIPT_DIR}/logs/"*.log "${BACKUP_TMP}/logs/" 2>/dev/null && {
        echo -e "  ${GREEN}+${RESET} logs/*.log"
        ((file_count++))
    } || echo -e "  ${YELLOW}-${RESET} logs/ (empty or missing)"
fi

# ---------- Метадані бекапу ----------
cat > "${BACKUP_TMP}/backup_meta.json" <<EOF
{
    "timestamp": "${TIMESTAMP}",
    "date": "$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')",
    "source_dir": "${SCRIPT_DIR}",
    "files_count": ${file_count},
    "hostname": "$(hostname 2>/dev/null || echo 'unknown')",
    "user": "$(whoami 2>/dev/null || echo 'unknown')"
}
EOF

# ---------- Пакуємо ----------
echo ""
cd "$BACKUP_BASE"
tar -czf "$BACKUP_FILE" -C "$BACKUP_BASE" ".tmp_${BACKUP_NAME}"
rm -rf "$BACKUP_TMP"

backup_size=$(du -sh "$BACKUP_FILE" 2>/dev/null | cut -f1)
echo -e "${GREEN}Backup created: ${BACKUP_FILE}${RESET}"
echo -e "Size: ${backup_size}"
echo -e "Files: ${file_count}"

# ---------- Ротація (залишаємо останніх 10) ----------
backup_count=$(ls -1 "${BACKUP_BASE}"/backup_*.tar.gz 2>/dev/null | wc -l)
if (( backup_count > 10 )); then
    remove_count=$((backup_count - 10))
    ls -1t "${BACKUP_BASE}"/backup_*.tar.gz | tail -n "$remove_count" | while read -r old; do
        rm -f "$old"
        echo -e "${YELLOW}  Rotated: $(basename "$old")${RESET}"
    done
fi

echo -e "\n${GREEN}Backup complete!${RESET}"
