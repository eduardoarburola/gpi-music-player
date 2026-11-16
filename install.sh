#!/usr/bin/env bash
#
# gpi-music-player · instalador para RetroPie (GPi Case)
#
# Uso:
#   git clone https://github.com/eduardoarburola/gpi-music-player.git
#   cd gpi-music-player && sudo ./install.sh
#
# O, directamente:
#   curl -sSL https://raw.githubusercontent.com/eduardoarburola/gpi-music-player/main/install.sh | sudo bash
#
set -euo pipefail

INSTALL_DIR="${GPI_MUSIC_DIR:-/opt/gpi-music}"
LAUNCHER="/usr/local/bin/gpi-music"
RETROPIE_USER="${GPI_MUSIC_USER:-pi}"
ES_CUSTOM="/opt/retropie/configs/all/emulationstation/es_systems.cfg"
ES_SYSTEM="/etc/emulationstation/es_systems.cfg"

info() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m  !\033[0m %s\n' "$*"; }

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------- 0. root ---
if [ "$(id -u)" -ne 0 ]; then
    warn "Este instalador necesita permisos de root. Ejecuta: sudo $0"
    exit 1
fi

if [ ! -d "$SRC_DIR/gpi_music" ]; then
    warn "No encuentro el código fuente en $SRC_DIR/gpi_music"
    warn "Descarga el repositorio completo antes de instalar."
    exit 1
fi

# ------------------------------------------------------------ 1. entorno ---
info "Comprobando el sistema"
if [ -d /opt/retropie ]; then
    ok "RetroPie detectado"
    IS_RETROPIE=1
else
    warn "No se detecta RetroPie en /opt/retropie (puedes instalarlo igualmente)"
    IS_RETROPIE=0
fi

# ------------------------------------------------------- 2. dependencias ---
info "Instalando dependencias"
MISSING=()
for pkg in python3-pil fonts-dejavu-core mpg123; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        ok "$pkg ya instalado"
    else
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    if apt-get update -qq >/dev/null 2>&1; then
        apt-get install -y -qq "${MISSING[@]}" >/dev/null 2>&1 || warn "Falló la instalación de: ${MISSING[*]}"
    else
        warn "Sin conexión (apt update falló); se intenta instalar sin actualizar"
        apt-get install -y -qq "${MISSING[@]}" >/dev/null 2>&1 || warn "Falló la instalación de: ${MISSING[*]}"
    fi
    for pkg in "${MISSING[@]}"; do
        dpkg -s "$pkg" >/dev/null 2>&1 && ok "$pkg instalado" || warn "$pkg no se pudo instalar"
    done
fi

# mpv es opcional: da mejor control (seek exacto y posición real).
if ! command -v mpv >/dev/null 2>&1; then
    apt-get install -y -qq mpv >/dev/null 2>&1 && ok "mpv instalado (opcional)" || warn "mpv no disponible (se usará mpg123)"
fi

if ! /usr/bin/python3 -c "import PIL" >/dev/null 2>&1; then
    warn "Pillow (python3-pil) no está disponible: el reproductor no podrá dibujar la pantalla."
    warn "Instálalo con: sudo apt-get install python3-pil"
fi

# --------------------------------------------------------- 3. instalación ---
info "Instalando gpi-music en $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/gpi_music"
cp -r "$SRC_DIR/gpi_music" "$INSTALL_DIR/gpi_music"
mkdir -p "$INSTALL_DIR/scripts"
cp -r "$SRC_DIR/scripts/." "$INSTALL_DIR/scripts/"
cp -f "$SRC_DIR/README.md" "$INSTALL_DIR/README.md" 2>/dev/null || true
find "$INSTALL_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
ok "Código instalado"

install -m 0755 "$SRC_DIR/scripts/gpi-music" "$LAUNCHER"
ok "Lanzador instalado en $LAUNCHER"

# --------------------------------------------------------- 4. permisos IO ---
info "Ajustando permisos de entrada y vídeo"
if id "$RETROPIE_USER" >/dev/null 2>&1; then
    for group in input video; do
        if getent group "$group" >/dev/null 2>&1; then
            usermod -aG "$group" "$RETROPIE_USER"
            ok "$RETROPIE_USER ahora pertenece al grupo $group"
        fi
    done
    HOMEDIR=$(getent passwd "$RETROPIE_USER" | cut -d: -f6)
    mkdir -p "$HOMEDIR/RetroPie/roms/music"
    chown -R "$RETROPIE_USER":"$RETROPIE_USER" "$HOMEDIR/RetroPie/roms/music" 2>/dev/null || true
    ok "Carpeta de música: $HOMEDIR/RetroPie/roms/music"
else
    warn "No existe el usuario $RETROPIE_USER; se omite la configuración de carpetas"
fi

# ------------------------------------------------ 5. EmulationStation -------
if [ "$IS_RETROPIE" -eq 1 ]; then
    info "Registrando el sistema «Música» en EmulationStation"
    mkdir -p "$(dirname "$ES_CUSTOM")"
    if [ ! -f "$ES_CUSTOM" ] && [ -f "$ES_SYSTEM" ]; then
        cp "$ES_SYSTEM" "$ES_CUSTOM"
        ok "Creada la copia personal de es_systems.cfg"
    fi
    if [ -f "$ES_CUSTOM" ]; then
        /usr/bin/python3 "$INSTALL_DIR/scripts/patch_es_systems.py" "$ES_CUSTOM"
        ok "Sistema «Música» añadido en es_systems.cfg"
    else
        warn "No se encontró es_systems.cfg; añade el sistema «Música» a mano"
    fi
    if [ -f "$ES_SYSTEM" ]; then
        /usr/bin/python3 "$INSTALL_DIR/scripts/patch_es_systems.py" "$ES_SYSTEM"
    fi
else
    warn "RetroPie no está instalado: la sección «Música» no se puede añadir a EmulationStation"
fi

# ---------------------------------------------------------- 6. resumen -----
echo
ok "Instalación completada"
echo
echo "  Siguientes pasos:"
echo "   1. Copia tu música en:  ~/RetroPie/roms/music   (MP3, OGG, FLAC, WAV, M4A)"
echo "   2. Reinicia EmulationStation (o reinicia la consola) para ver la sección «Música»."
echo "   3. Comprueba la biblioteca desde SSH con:  gpi-music --scan"
echo
echo "  Si usas una biblioteca en red, edita la configuración:"
echo "   nano ~/.config/gpi-music/config.json"
echo "   (rutas montadas en /mnt, servidores MPD…)"
echo
echo "  Desinstalar: sudo ./uninstall.sh"
