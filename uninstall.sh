#!/usr/bin/env bash
# ============================================================
# Symbioz Pro - Uninstaller
# Clean removal with automatic backup before deletion
# Usage: bash uninstall.sh
# ============================================================

set -euo pipefail

SYMBIOZ_DIR="${HOME}/symbioz_pro"
BACKUP_DIR="${HOME}/symbioz_backups"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

echo ""
echo -e "${RED}============================================${RESET}"
echo -e "${RED}   Symbioz Pro Uninstaller${RESET}"
echo -e "${RED}============================================${RESET}"
echo ""
echo -e "${YELLOW}WARNING: This will remove Symbioz Pro!${RESET}"
echo -e "Backups will be preserved in: ${BACKUP_DIR}"
echo ""

read -p "Are you sure you want to continue? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo -e "${BLUE}[1/5] Creating final backup...${RESET}"
if [ -f "${SCRIPT_DIR}/tools/backup_state.sh" ]; then
    bash "${SCRIPT_DIR}/tools/backup_state.sh" "$BACKUP_DIR" 2>/dev/null && {
        echo -e "${GREEN}  Backup created successfully${RESET}"
    } || {
        echo -e "${YELLOW}  Backup skipped (no state to backup)${RESET}"
    }
else
    echo -e "${YELLOW}  Backup tool not found, skipping${RESET}"
fi

echo -e "\n${BLUE}[2/5] Stopping all processes...${RESET}"
pkill -f "ollama serve" 2>/dev/null && echo "  Stopped Ollama" || echo "  Ollama was not running"
pkill -f "lifesupport.py" 2>/dev/null && echo "  Stopped LifeSupport" || echo "  LifeSupport was not running"
pkill -f "onefile_ollama.py" 2>/dev/null && echo "  Stopped OneFile" || echo "  OneFile was not running"
pkill -f "symbioz_watchdog.sh" 2>/dev/null && echo "  Stopped Watchdog" || echo "  Watchdog was not running"
sleep 2

echo -e "\n${BLUE}[3/5] Removing autostart configuration...${RESET}"
if [ -f "${HOME}/.termux/boot/symbioz_boot.sh" ]; then
    rm -f "${HOME}/.termux/boot/symbioz_boot.sh"
    echo -e "  ${GREEN}Removed autostart script${RESET}"
else
    echo "  No autostart configuration found"
fi

echo -e "\n${BLUE}[4/5] Removing Symbioz Pro files...${RESET}"
if [ -d "$SYMBIOZ_DIR" ]; then
    du_output=$(du -sh "$SYMBIOZ_DIR" 2>/dev/null | cut -f1)
    rm -rf "$SYMBIOZ_DIR"
    echo -e "  ${GREEN}Removed ${SYMBIOZ_DIR} (${du_output})${RESET}"
else
    echo "  ${SYMBIOZ_DIR} not found (already removed?)"
fi

echo -e "\n${BLUE}[5/5] Cleanup...${RESET}"
# Remove Python cache
find "${SCRIPT_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "  Cleaned Python cache"

echo ""
echo -e "${GREEN}============================================${RESET}"
echo -e "${GREEN}  Symbioz Pro has been removed.${RESET}"
echo -e "${GREEN}============================================${RESET}"
echo ""
echo -e "  Backups preserved in: ${BLUE}${BACKUP_DIR}${RESET}"
if [ -d "$BACKUP_DIR" ]; then
    backup_count=$(ls -1 "${BACKUP_DIR}"/backup_*.tar.gz 2>/dev/null | wc -l)
    echo -e "  Total backups: ${backup_count}"
fi
echo ""
echo -e "  To reinstall: ${BLUE}bash install.sh${RESET}"
echo -e "  To remove backups: ${RED}rm -rf ${BACKUP_DIR}${RESET}"
echo ""
