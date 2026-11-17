#!/usr/bin/env bash
#
# gpi-music-player · instalador para RetroPie y Recalbox (GPi Case)
#
# Uso:
#   git clone https://github.com/eduardoarburola/gpi-music-player.git
#   cd gpi-music-player && ./install.sh
#
# En Recalbox no hace falta ser root: todo se instala dentro de /recalbox/share.
# En RetroPie sí hace falta (apt + /usr/local/bin).
#
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m  !\033[0m %s\n' "$*"; }

PYTHON_BIN=""
for candidate in /usr/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN=$(command -v "$candidate"); break; fi
done

# --------------------------------------------------------- 1. plataforma ---
PLATFORM="generic"
if [ -d /recalbox/share ]; then
    PLATFORM="recalbox"
elif [ -d /opt/retropie ]; then
    PLATFORM="retropie"
fi
info "Plataforma detectada: $PLATFORM"

if [ ! -d "$SRC_DIR/gpi_music" ]; then
    warn "No encuentro el código fuente en $SRC_DIR/gpi_music"
    warn "Descarga el repositorio completo antes de instalar."
    exit 1
fi

case "$PLATFORM" in
    recalbox)
        INSTALL_DIR="/recalbox/share/system/gpi-music"
        ROMS_DIR="/recalbox/share/roms/music"
        LAUNCHER_PATH="/recalbox/share/system/gpi-music/gpi-music"
        ES_INIT="/recalbox/share_init/system/.emulationstation/systemlist.xml"
        ES_TARGET="/recalbox/share/system/.emulationstation/systemlist.xml"
        ES_SYSTEMS="/recalbox/share/system/.emulationstation/es_systems.cfg"
        ;;
    retropie)
        INSTALL_DIR="/opt/gpi-music"
        ROMS_DIR=""
        LAUNCHER_PATH="/usr/local/bin/gpi-music"
        ES_INIT=""
        ES_TARGET=""
        ES_SYSTEMS=""
        ;;
    *)
        INSTALL_DIR="${HOME}/.local/share/gpi-music"
        ROMS_DIR="${HOME}/Music"
        LAUNCHER_PATH="${INSTALL_DIR}/gpi-music"
        ES_INIT=""
        ES_TARGET=""
        ES_SYSTEMS=""
        ;;
esac

# -------------------------------------------------------- 2. dependencias ---
info "Comprobando dependencias"
if [ -z "$PYTHON_BIN" ]; then
    warn "No se encontró python3 en el sistema: el reproductor no puede funcionar."
    exit 1
fi
ok "python3: $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"

if "$PYTHON_BIN" -c "import PIL" >/dev/null 2>&1; then
    ok "Pillow disponible (dibujado con Pillow)"
elif "$PYTHON_BIN" -c "import pygame" >/dev/null 2>&1; then
    ok "pygame disponible (dibujado con SDL2)"
else
    warn "Ni Pillow ni pygame están disponibles: no se podrá dibujar la pantalla."
    if [ "$PLATFORM" = "retropie" ]; then
        warn "Instálalos con: sudo apt-get install python3-pil python3-pygame"
    fi
fi

PLAYER_FOUND=""
for player in mpv mpg123 ogg123 ffplay; do
    if command -v "$player" >/dev/null 2>&1; then
        ok "reproductor disponible: $player"
        PLAYER_FOUND="$player"
    fi
done
if [ -z "$PLAYER_FOUND" ]; then
    warn "No hay ningún reproductor de audio (mpv, mpg123, ogg123 o ffplay)."
    if [ "$PLATFORM" = "retropie" ]; then
        warn "Instala uno con: sudo apt-get install mpg123"
    else
        warn "En Recalbox suele bastar con 'mpv' o 'mpg123' si están en la imagen."
    fi
fi

# -------------------------------------------------------- 3. instalación ---
info "Instalando en $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/gpi_music"
cp -r "$SRC_DIR/gpi_music" "$INSTALL_DIR/gpi_music"
mkdir -p "$INSTALL_DIR/scripts"
cp -r "$SRC_DIR/scripts/." "$INSTALL_DIR/scripts/"
cp -f "$SRC_DIR/README.md" "$INSTALL_DIR/README.md" 2>/dev/null || true
find "$INSTALL_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/gpi-music" "$INSTALL_DIR/scripts"/*.py 2>/dev/null || true
ok "Código instalado"

# El lanzador se genera con la ruta y el intérprete ya resueltos, para que
# funcione desde EmulationStation sin depender de variables de entorno.
write_launcher() {
    cat > "$1" <<LAUNCHER
#!/usr/bin/env bash
# Lanzador de gpi-music (generado por install.sh)
set -euo pipefail
export PYTHONPATH="$INSTALL_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONUNBUFFERED=1
# Si el reproductor se lanza desde EmulationStation no debe abrir una consola.
# SDL_VIDEODRIVER se deja como lo trouve el sistema: en la GPi Case el
# driver disponible es "RPI" y SDL lo selecciona solo.
# Los eventos de los botones se guardan en un fichero para poder diagnosticarlos.
LOG_FILE="$INSTALL_DIR/botones.log"
if [ ! -w "$INSTALL_DIR" ]; then
    LOG_FILE="\${TMPDIR:-/tmp}/gpi-music-botones.log"
fi
exec "$PYTHON_BIN" -m gpi_music --log-input "\$LOG_FILE" "\$@"
LAUNCHER
    chmod 0755 "$1"
}

write_launcher "$INSTALL_DIR/scripts/gpi-music"

if [ "$LAUNCHER_PATH" != "$INSTALL_DIR/scripts/gpi-music" ]; then
    if write_launcher "$LAUNCHER_PATH" 2>/dev/null; then
        ok "Lanzador en $LAUNCHER_PATH"
    else
        warn "No se pudo crear $LAUNCHER_PATH (usa $INSTALL_DIR/scripts/gpi-music)"
    fi
else
    ok "Lanzador en $LAUNCHER_PATH"
fi

# --------------------------------------------------------- 4. biblioteca ---
info "Preparando la carpeta de música"
if [ -n "$ROMS_DIR" ]; then
    if mkdir -p "$ROMS_DIR" 2>/dev/null; then
        ok "Carpeta de música: $ROMS_DIR"
        # EmulationStation oculta los sistemas que no tienen ningún juego.
        CANCIONES="$(find "$ROMS_DIR" -maxdepth 2 -type f \
            \( -iname '*.mp3' -o -iname '*.ogg' -o -iname '*.oga' -o -iname '*.opus' \
               -o -iname '*.wav' -o -iname '*.flac' -o -iname '*.m4a' -o -iname '*.mp4' \
               -o -iname '*.aac' -o -iname '*.wma' \) 2>/dev/null | head -n 1)"
        if [ -z "$CANCIONES" ]; then
            warn "La carpeta está vacía: la sección «Música» no aparecerá en"
            warn "EmulationStation hasta que copies al menos una canción allí."
        fi
    else
        warn "No se pudo crear $ROMS_DIR (¿permisos?)"
    fi
fi

# ---------------------------------------------------- 5. EmulationStation ---
if [ "$PLATFORM" = "recalbox" ]; then
    info "Registrando el sistema «Música» en Recalbox"
    # El share de Recalbox está en exFAT (fmask=0133): los ficheros nunca
    # quedan con permiso de ejecución, así que se lanzan con «/bin/sh».
    ES_COMMAND="/bin/sh $LAUNCHER_PATH %ROM%"
    if "$PYTHON_BIN" "$INSTALL_DIR/scripts/patch_recalbox.py" \
        --init "$ES_INIT" --target "$ES_TARGET" --es-systems "$ES_SYSTEMS" \
        --command "$ES_COMMAND" --roms "$ROMS_DIR"; then
        ok "Sistema «Música» añadido"
    else
        warn "No se pudo registrar el sistema automáticamente"
    fi
    echo
    info "Reiniciando EmulationStation (si el gestor web está activo)"
    if command -v curl >/dev/null 2>&1; then
        if curl -s -m 5 -X POST "http://localhost:81/api/system/frontend/restart" >/dev/null 2>&1; then
            ok "EmulationStation reiniciado"
        else
            warn "Reinicia EmulationStation desde el menú (Start → Ajustar → Reiniciar)"
        fi
    else
        warn "Reinicia EmulationStation desde el menú (Start → Ajustar → Reiniciar)"
    fi
elif [ "$PLATFORM" = "retropie" ]; then
    if [ "$(id -u)" -ne 0 ]; then
        warn "RetroPie necesita permisos de root: ejecuta 'sudo $0'"
        exit 1
    fi
    info "Registrando el sistema «Música» en EmulationStation"
    ES_CUSTOM="/opt/retropie/configs/all/emulationstation/es_systems.cfg"
    ES_SYSTEM="/etc/emulationstation/es_systems.cfg"
    mkdir -p "$(dirname "$ES_CUSTOM")"
    if [ ! -f "$ES_CUSTOM" ] && [ -f "$ES_SYSTEM" ]; then
        cp "$ES_SYSTEM" "$ES_CUSTOM"
        ok "Creada la copia personal de es_systems.cfg"
    fi
    if [ -f "$ES_CUSTOM" ]; then
        "$PYTHON_BIN" "$INSTALL_DIR/scripts/patch_es_systems.py" "$ES_CUSTOM" \
            --command "$LAUNCHER_PATH %ROM%"
        ok "Sistema «Música» añadido en es_systems.cfg"
    fi
    if [ -f "$ES_SYSTEM" ]; then
        "$PYTHON_BIN" "$INSTALL_DIR/scripts/patch_es_systems.py" "$ES_SYSTEM" \
            --command "$LAUNCHER_PATH %ROM%"
    fi
    for group in input video; do
        if getent group "$group" >/dev/null 2>&1 && id pi >/dev/null 2>&1; then
            usermod -aG "$group" pi
            ok "El usuario pi pertenece al grupo $group"
        fi
    done
else
    warn "No se detecta RetroPie ni Recalbox: la sección «Música» no se puede añadir a EmulationStation"
fi

# ------------------------------------------------------------ 6. resumen ---
echo
ok "Instalación completada"
echo
echo "  Siguientes pasos:"
echo "   1. Copia tu música en:  $ROMS_DIR"
echo "   2. Reinicia EmulationStation para ver la sección «Música»."
if [ "$PLATFORM" = "recalbox" ]; then
    echo "   3. Comprueba la biblioteca con:  sh $LAUNCHER_PATH --scan"
    echo "      (el share está en exFAT y no permite ejecutar ficheros)"
else
    echo "   3. Comprueba la biblioteca desde SSH con:  gpi-music --scan"
fi
echo
echo "  Configuración:  ~/.config/gpi-music/config.json"
echo "  (rutas montadas en /mnt, servidores MPD, volumen…)"
echo
echo "  Desinstalar: ./uninstall.sh"
