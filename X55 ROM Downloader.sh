#!/bin/bash
# X55-ROM-DOWNLOADER-PORT
# X55-ROM-DOWNLOADER-MENU
# EmulationStation ejecuta este acceso desde la sección Descargas.
exec /usr/bin/python3 -B /storage/.local/share/x55-rom-downloader/launch_rocknix.py "$@"
