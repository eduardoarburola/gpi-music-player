#!/usr/bin/env bash
#
# Desinstalador de gpi-music-player.
#
set -euo pipefail

INSTALL_DIR="${GPI_MUSIC_DIR:-/opt/gpi-music}"
LAUNCHER="/usr/local/bin/gpi-music"
RETROPIE_USER="${GPI_MUSIC_USER:-pi}"
ES_CUSTOM="/opt/retropie/configs/all/emulationstation/es_systems.cfg"
ES_SYSTEM="/etc/emulationstation/es_systems.cfg"

info() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Necesitas root: sudo $0"
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Quitando el sistema «Música» de EmulationStation"
for cfg in "$ES_CUSTOM" "$ES_SYSTEM"; do
    if [ -f "$cfg" ] && [ -f "$SRC_DIR/scripts/patch_es_systems.py" ]; then
        /usr/bin/python3 "$SRC_DIR/scripts/patch_es_systems.py" --remove "$cfg" || true
        ok "es_systems.cfg actualizado: $cfg"
    fi
done

info "Borrando el lanzador y el código"
rm -f "$LAUNCHER"
rm -rf "$INSTALL_DIR"
ok "Instalación eliminada"

info "Limpiando la configuración del usuario"
if id "$RETROPIE_USER" >/dev/null 2>&1; then
    HOMEDIR=$(getent passwd "$RETROPIE_USER" | cut -d: -f6)
    rm -rf "$HOMEDIR/.config/gpi-music"
    ok "Configuración eliminada ($HOMEDIR/.config/gpi-music)"
    echo "La carpeta ~/RetroPie/roms/music se conserva con tu música."
fi
