# gpi-music-player

Reproductor de música para el **RetroFlag GPi Case** (consola portátil con Raspberry Pi Zero y RetroPie).

La GPi Case es una Game Boy con pantalla de 2.8" y cruceta, pero sin reproductor de música.
Esto añade una sección **«Música»** a EmulationStation: una lista de canciones con carátulas
opcionales, reproducción con los botones de la consola y una pantalla de «sonando ahora»
con barra de progreso.

Works on both the original GPi Case (320×240) and the GPi Case 2W (640×480).

![vista de biblioteca](docs/library.svg)
![reproduciendo](docs/playing.svg)

---

## Qué hace

- **Sección «Música» en EmulationStation**, igual que cualquier otro sistema de la consola.
- **Biblioteca mixta**: MP3/OGG/FLAC/WAV/M4A de la microSD **y** de la red (Samba/NFS montado en
  `/mnt`) **y** de servidores **MPD** (Music Player Daemon) en la LAN.
- **Tags y duración** leídos del propio archivo (ID3v2, Vorbis comments, RIFF, atoms MP4),
  sin instalar nada: si no hay tags se deduce «artista - título» del nombre.
- **Controles con los botones**: cruceta para moverse, A para reproducir/pausar, B para salir,
  X/L/R para saltar de pista, Start para el menú de opciones.
- **Menú de opciones**: aleatorio, repetir, volumen, reescanear la biblioteca y salir.
- Todo se dibuja **directamente sobre `/dev/fb0`**, así que funciona con la pantalla del bus DPI
  del GPi Case (no necesita X ni Wayland).

## Requisitos

- RetroPie 4.x en un Raspberry Pi Zero / Zero W (GPi Case) o Zero 2 (GPi Case 2W).
- El parche de pantalla de RetroFlag (el habitual `GPi_Case_patch`) y los botones funcionando.
- Python 3 con Pillow. El instalador se encarga de `python3-pil`, `fonts-dejavu-core` y `mpg123`.

## Instalación

```bash
git clone https://github.com/eduardoarburola/gpi-music-player.git
cd gpi-music-player
sudo ./install.sh
```

O en una sola línea:

```bash
curl -sSL https://raw.githubusercontent.com/eduardoarburola/gpi-music-player/main/install.sh | sudo bash
```

El instalador:

1. instala las dependencias (`python3-pil`, `fonts-dejavu-core`, `mpg123`, y `mpv` si puede);
2. copia el código a `/opt/gpi-music` y crea el lanzador `/usr/local/bin/gpi-music`;
3. añade el usuario `pi` a los grupos `input` y `video` (para leer los botones y el framebuffer);
4. crea `~/RetroPie/roms/music`;
5. registra el sistema **«Música»** en `es_systems.cfg` (guardando copia de seguridad).

Después, copia tu música a `~/RetroPie/roms/music` (o a la microSD) y **reinicia EmulationStation**.
En el carrusel aparecerá la sección «Música».

> Reinicia la consola una vez después de instalar: el usuario entra en grupos nuevos al iniciar sesión.

## Controles

| Botón | En la biblioteca | Reproduciendo |
|-------|------------------|---------------|
| Cruceta ↑↓ | mover la selección | — |
| Cruceta ←→ | — | saltar ±15 s |
| A / Intro | reproducir la canción | pausar / seguir |
| B / Retroceso | salir a EmulationStation | volver a la biblioteca |
| X / L / R | pista anterior / siguiente | pista anterior / siguiente |
| Start / Select | menú de opciones | menú de opciones |
| Select + A | — | opciones |

Si tu consola asigna las teclas de otra forma, puedes reasignarlas en
`~/.config/gpi-music/config.json` (mapa de códigos de tecla → acción).

## Configuración

El archivo vive en `~/.config/gpi-music/config.json` y se crea solo la primera vez que se guarda.
Los valores por defecto:

```json
{
  "library": {
    "local_paths": ["~/RetroPie/roms/music", "~/Music"],
    "scan_mounts": true,
    "mount_roots": ["/mnt"],
    "mpd_hosts": [],
    "extensions": [".mp3", ".ogg", ".oga", ".opus", ".wav", ".flac", ".m4a", ".mp4", ".aac", ".wma"],
    "recursive": true
  },
  "player": {
    "volume": 0.7,
    "backend": "auto",
    "shuffle": false,
    "repeat": false,
    "alsa_mixer": "",
    "seek_step": 15
  },
  "ui": { "theme": "pixel", "font_size": 15, "show_cover": true, "fps": 20 }
}
```

### Biblioteca en la red

**Samba/NFS**: monta el share (Samba viene instalado y activo en RetroPie) y el reproductor
detecta solo las carpetas de `/mnt`. Por ejemplo, si el share se llama `nas` y dentro hay una
carpeta `Music`, aparecerá como `nas/Music (red)`.

```bash
sudo mkdir -p /mnt/nas
sudo mount -t cifs //192.168.1.50/musica /mnt/nas -o guest,vers=3.0
```

**MPD**: añade el servidor a `mpd_hosts` y sus canciones aparecerán mezcladas con el resto:

```json
"mpd_hosts": [["192.168.1.50", 6600]]
```

### Volumen por software

La GPi Case tiene una rueda de volumen física (hardware). Si prefieres controlarlo por software,
indica el mezclador de ALSA:

```json
"alsa_mixer": "Headphone"
```

## Uso desde SSH

```bash
gpi-music --scan                    # lista la biblioteca y las fuentes detectadas
gpi-music --preview /tmp/ux.png     # guarda una captura de la interfaz
gpi-music --config /ruta/config.json
```

## Problemas frecuentes

**No se ve la sección «Música» en EmulationStation**
EmulationStation solo lee `es_systems.cfg` al arrancar: reinícialo (menú → *Quit EmulationStation*)
o reinicia la consola. Comprueba que existe la entrada:

```bash
grep -A3 "<name>music</name>" /opt/retropie/configs/all/emulationstation/es_systems.cfg
```

**Los botones no responden**
El usuario debe pertenecer al grupo `input`:

```bash
groups | grep input
sudo usermod -aG input pi     # y reinicia la sesión
```

**La pantalla sale en blanco o con colores raros**
Comprueba el framebuffer y sus permisos:

```bash
cat /sys/class/graphics/fb0/bits_per_pixel
sudo usermod -aG video pi
```

Si el framebuffer es de 16 bpp, instala `python3-numpy` para que la conversión a RGB565 sea exacta:

```bash
sudo apt-get install python3-numpy
```

**No suena**
El GPi Case usa audio PWM: la configuración correcta en `/boot/config.txt` es
`dtoverlay=audremap,pins_18_19` y `snd_bcm2835.enable_compat_alsa=1`.
Comprueba el volumen con `alsamixer` y prueba la reproducción con `mpg123 archivo.mp3`.

## Desarrollo

```bash
python3 -m unittest discover -s tests -v    # 42 tests, sin dependencias
python3 -m gpi_music --preview /tmp/ux.png  # vista previa de la interfaz
```

Estructura:

```
gpi_music/
  app.py        máquina de estados: biblioteca, reproducción, navegación
  ui.py         dibujo de las vistas sobre el lienzo
  fb.py         framebuffer: detección de formato y volcado de píxeles
  input.py      lectura de evdev y traducción a acciones
  library.py    escaneo de carpetas y montajes
  metadata.py   tags y duración sin dependencias
  mpd.py        cliente mínimo de MPD
  player.py     motores de audio (mpv / mpg123 / ogg123 / ffplay)
  config.py     configuración en JSON
scripts/
  gpi-music              lanzador
  patch_es_systems.py    alta/baja del sistema en EmulationStation
```

## Licencia

MIT.
