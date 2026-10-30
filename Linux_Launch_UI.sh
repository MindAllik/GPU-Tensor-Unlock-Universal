#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -uo pipefail
cd "$(dirname "$0")"

echo "============================================================================"
echo "  NVIDIA GPU TENSOR UNLOCK // LINUX_LAUNCH_UI [LINUX KERNEL & INITRAMFS]"
echo "============================================================================"

UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME_S" in
    MINGW*|MSYS*|CYGWIN*|Windows_NT*)
        echo "[OS ERROR] Вы запустили Linux_Launch_UI в среде Windows ($UNAME_S)." >&2
        echo "[OS ERROR] Для Windows 10/11 запустите: Windows_Launch_UI.bat" >&2
        echo "[EN] You launched Linux_Launch_UI on Windows ($UNAME_S). Please run Windows_Launch_UI.bat instead." >&2
        read -r -p "Press Enter to exit..." _ || true
        exit 2
        ;;
    Linux*)
        ;;
    *)
        echo "[OS ERROR] Неподдерживаемая ОС ($UNAME_S). Linux_Launch_UI предназначен только для Linux." >&2
        exit 2
        ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 не найден. Установите Python 3.10+ и python3-tk (например: sudo apt install python3 python3-tk)." >&2
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "[ERROR] Модуль Python 'tkinter' не установлен." >&2
    echo "  Ubuntu/Debian: sudo apt-get install -y python3-tk" >&2
    echo "  Arch Linux:    sudo pacman -S tk" >&2
    echo "  Fedora/RHEL:   sudo dnf install -y python3-tkinter" >&2
    exit 1
fi

exec python3 "./linux_unlock_ui.py" "$@"
