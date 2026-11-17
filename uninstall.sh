#!/usr/bin/env bash
#
# Desinstalador de gpi-music-player (RetroPie y Recalbox).
#
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }

PYTHON_BIN=""
for candidate in /usr/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN=$(command -v "$candidate"); break; fi
done

if [ -d /recalbox/share ]; then
    PLATFORM="recalbox"
    INSTALL_DIR="/recalbox/share/system/gpi-music"
    LAUNCHER="/recalbox/share/system/gpi-music/gpi-music"
elif [ -d /opt/retropie ]; then
    PLATFORM="retropie"
    INSTALL_DIR="/opt/gpi-music"
    LAUNCHER="/usr/local/bin/gpi-music"
else
    PLATFORM="generic"
    INSTALL_DIR="${HOME}/.local/share/gpi-music"
    LAUNCHER="${INSTALL_DIR}/gpi-music"
fi

info "Quitando el sistema «Música» de EmulationStation"
if [ "$PLATFORM" = "recalbox" ] && [ -n "$PYTHON_BIN" ]; then
    "$PYTHON_BIN" "$SRC_DIR/scripts/patch_recalbox.py" --remove || true
    ok "Recalbox actualizado"
elif [ "$PLATFORM" = "retropie" ]; then
    for cfg in /opt/retropie/configs/all/emulationstation/es_systems.cfg /etc/emulationstation/es_systems.cfg; do
        if [ -f "$cfg" ] && [ -f "$SRC_DIR/scripts/patch_es_systems.py" ]; then
            "$PYTHON_BIN" "$SRC_DIR/scripts/patch_es_systems.py" --remove "$cfg" || true
            ok "es_systems.cfg actualizado: $cfg"
        fi
    done
fi

info "Borrando el lanzador y el código"
rm -f "$LAUNCHER" 2>/dev/null || true
rm -rf "$INSTALL_DIR" 2>/dev/null || true
ok "Instalación eliminada"

info "Limpiando la configuración del usuario"
rm -rf "${HOME}/.config/gpi-music" 2>/dev/null || true
ok "Configuración eliminada (~/.config/gpi-music)"
echo "La carpeta con tu música se conserva."
