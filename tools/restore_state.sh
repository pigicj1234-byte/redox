#!/usr/bin/env bash
# ============================================================
# Symbioz Pro - Restore State
# Відновлення стану організму з бекапу
# Використання: bash tools/restore_state.sh [backup_file]
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_BASE="${HOME}/symbioz_backups"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

# ---------- Вибір бекапу ----------
if [ -n "${1:-}" ]; then
    BACKUP_FILE="$1"
else
    echo -e "${BLUE}=== Symbioz Pro State Restore ===${RESET}"
    echo ""

    if [ ! -d "$BACKUP_BASE" ] || [ -z "$(ls -A "${BACKUP_BASE}"/backup_*.tar.gz 2>/dev/null)" ]; then
        echo -e "${RED}No backups found in ${BACKUP_BASE}${RESET}"
        echo "Run 'bash tools/backup_state.sh' first."
        exit 1
    fi

    echo "Available backups:"
    echo "---"
    backups=()
    idx=1
    while IFS= read -r f; do
        backups+=("$f")
        bname=$(basename "$f")
        bsize=$(du -sh "$f" 2>/dev/null | cut -f1)
        # Parse timestamp from filename
        ts=$(echo "$bname" | sed 's/backup_\([0-9]*\)_\([0-9]*\).*/\1 \2/' | sed 's/\(....\)\(..\)\(..\) \(..\)\(..\)\(..\)/\1-\2-\3 \4:\5:\6/')
        echo "  [$idx] ${bname} (${bsize}) - ${ts}"
        ((idx++))
    done < <(ls -1t "${BACKUP_BASE}"/backup_*.tar.gz 2>/dev/null)

    echo ""
    read -p "Select backup number [1]: " choice
    choice="${choice:-1}"

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#backups[@]} )); then
        echo -e "${RED}Invalid selection${RESET}"
        exit 1
    fi

    BACKUP_FILE="${backups[$((choice - 1))]}"
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Backup file not found: ${BACKUP_FILE}${RESET}"
    exit 1
fi

echo ""
echo -e "${YELLOW}WARNING: This will overwrite current state files!${RESET}"
echo -e "Backup:  $(basename "$BACKUP_FILE")"
echo -e "Target:  ${SCRIPT_DIR}"
read -p "Continue? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# ---------- Pre-restore backup ----------
echo -e "\n${BLUE}Creating pre-restore safety backup...${RESET}"
bash "${SCRIPT_DIR}/tools/backup_state.sh" "${BACKUP_BASE}" 2>/dev/null || {
    echo -e "${YELLOW}  Pre-restore backup skipped (no current state)${RESET}"
}

# ---------- Зупиняємо сервіси ----------
echo -e "\n${BLUE}Stopping services before restore...${RESET}"
pkill -f "lifesupport.py" 2>/dev/null && echo "  Stopped LifeSupport" || true
sleep 2

# ---------- Розпаковуємо ----------
echo -e "\n${BLUE}Restoring state...${RESET}"
RESTORE_TMP=$(mktemp -d)

tar -xzf "$BACKUP_FILE" -C "$RESTORE_TMP"

# Find the actual backup directory inside
BACKUP_INNER=$(find "$RESTORE_TMP" -maxdepth 1 -type d -name ".tmp_*" | head -1)
if [ -z "$BACKUP_INNER" ]; then
    BACKUP_INNER="$RESTORE_TMP"
fi

# Restore data/
if [ -d "${BACKUP_INNER}/data" ]; then
    mkdir -p "${SCRIPT_DIR}/data"
    cp -v "${BACKUP_INNER}/data/"* "${SCRIPT_DIR}/data/" 2>/dev/null || true
    echo -e "  ${GREEN}Restored: data/${RESET}"
fi

# Restore src/config/
if [ -d "${BACKUP_INNER}/src/config" ]; then
    mkdir -p "${SCRIPT_DIR}/src/config"
    cp -v "${BACKUP_INNER}/src/config/"* "${SCRIPT_DIR}/src/config/" 2>/dev/null || true
    echo -e "  ${GREEN}Restored: src/config/${RESET}"
fi

# Restore logs (optional)
if [ -d "${BACKUP_INNER}/logs" ]; then
    mkdir -p "${SCRIPT_DIR}/logs"
    cp -v "${BACKUP_INNER}/logs/"* "${SCRIPT_DIR}/logs/" 2>/dev/null || true
    echo -e "  ${GREEN}Restored: logs/${RESET}"
fi

# Show metadata if available
if [ -f "${BACKUP_INNER}/backup_meta.json" ]; then
    echo -e "\n${BLUE}Backup metadata:${RESET}"
    cat "${BACKUP_INNER}/backup_meta.json"
    echo ""
fi

# Cleanup
rm -rf "$RESTORE_TMP"

# ---------- Перезапуск сервісів ----------
echo -e "\n${BLUE}Restarting services...${RESET}"
cd "$SCRIPT_DIR"
if [ -f "services/symbioz_boot.sh" ]; then
    bash services/symbioz_boot.sh &
    echo -e "  ${GREEN}Services restart initiated${RESET}"
fi

echo -e "\n${GREEN}Restore complete!${RESET}"
echo -e "Run 'bash tools/health_check.sh' to verify system health."
