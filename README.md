# X55 ROM Downloader

Aplicación para Powkiddy X55 con ROCKNIX ARM64, pantalla de 1280 × 720 y manejo
con los controles de la consola. Descarga archivos en `/storage/roms/<sistema>`
y muestra los juegos que ya están instalados.

Incluye un catálogo de **38 consolas y 26.490 fichas**. No incluye juegos ni BIOS.
Las fichas consultan RomsGames al seleccionar un juego; la disponibilidad depende
del sitio de origen. Usa únicamente contenido que tengas autorización para descargar.

## Requisitos

- Powkiddy X55 con ROCKNIX ARM64. Probado con Python 3.14.7.
- Python 3.10 o posterior, SDL2 y SDL2_ttf disponibles en el sistema.
- `7za` para extraer 7z; ZIP se procesa con Python.
- Internet para descargar y espacio libre en la tarjeta de ROMs.

El instalador comprueba las bibliotecas y no instala paquetes del sistema.
Otras versiones de ROCKNIX y otros dispositivos requieren validación adicional.

## Instalación desde la consola

1. Descarga `X55-RomDownloader-v0.3.zip` desde **Releases** y descomprímelo.
   También puedes usar **Code → Download ZIP**.
2. Copia la carpeta descomprimida a la tarjeta de ROMs, por ejemplo
   `/storage/roms/tools/X55-RomDownloader`. La carpeta debe contener `install.sh`.
3. Abre una sesión SSH hacia la X55 y ejecuta:

```sh
cd /storage/roms/tools/X55-RomDownloader
bash install.sh --check
bash install.sh
```

El primer comando comprueba el entorno sin instalar. El segundo instala la app
y solicita actualizar la lista de EmulationStation. Aparecerá en
**Descargas → X55 ROM Downloader**. Si no aparece, reinicia EmulationStation
desde su menú. Después funciona sin ordenador ni SSH.

## Instalación desde Windows por SSH

Descarga y descomprime el ZIP. Abre PowerShell en esa carpeta y ejecuta:

```powershell
ssh root@IP_DE_LA_X55
```

Comprueba la huella de la consola y autentícate. Para usar el instalador de
Windows, autoriza una clave SSH personal en la consola; nunca pongas contraseñas
ni claves privadas en el proyecto. Con la clave configurada:

```powershell
.\Install-X55.ps1 -X55Address IP_DE_LA_X55 -IdentityFile "$env:USERPROFILE\.ssh\x55_ed25519"
```

La IP debe ser la de tu consola. La autenticación del instalador es por clave;
no muestra un diálogo para introducir la contraseña.

## Actualización

Cierra la aplicación, descarga una nueva versión y repite la instalación.
El catálogo existente se conserva por defecto. Para sustituirlo por el incluido:

```sh
bash install.sh --update-catalog
```

O desde Windows:

```powershell
.\Install-X55.ps1 -X55Address IP_DE_LA_X55 -UpdateCatalog
```

El instalador guarda copias de los archivos reemplazados en
`/storage/.local/share/x55-rom-downloader/backups`. No reemplaza ROMs o BIOS
ni la configuración general de sistemas de EmulationStation. Añade un fragmento
de menú y, si existe Canvas, los metadatos específicos de la sección Descargas.

## Controles y funciones

- Cruceta o analógico: navegar.
- A: seleccionar o confirmar; B: volver; X: buscar en las listas.
- START: abrir la salida.
- Progreso y cancelación de descargas; extracción ZIP/7z y opción de conservar
  o borrar el archivo comprimido después de verificar la ROM extraída.
- Detección de juegos locales por archivo, título y `gamelist.xml`.
- Actualización de EmulationStation al salir después de instalar juegos.

PSP, Nintendo 64, Nintendo DS, Dreamcast y Saturn llevan aviso de rendimiento
variable. No todos sus juegos funcionarán a plena velocidad. Neo Geo requiere
un romset y BIOS compatibles; conserva el comprimido como ROM. Los discos con
varios archivos requieren extracción manual.

Referencia del perfil: [emuladores ROCKNIX para RK3566](https://github.com/ROCKNIX/distribution/blob/next/documentation/PER_DEVICE_DOCUMENTATION/RK3566/SUPPORTED_EMULATORS_AND_CORES.md).

## Desarrollo y catálogo

No se necesitan dependencias Python externas. Ejecuta las pruebas con:

```sh
python -m unittest discover
```

Las pruebas nativas de 7za se omiten donde no está disponible. Las pruebas de
interfaz usan simulaciones; la validación visual completa requiere una X55.

`x55_systems.py` define las consolas y carpetas. `site_index.json` contiene
metadatos de las fichas; `catalog.json` es el catálogo que usa la aplicación.
Para actualizar los listados desde un ordenador:

```sh
python sync_x55_catalog.py
```

Se conservan los índices marcados completos y se consultan los pendientes.
Produce `catalog.x55.json`; revísalo antes de instalarlo. No actualiza por sí solo
las listas ya completas ni descarga ROMs durante la importación.

## Archivos instalados y errores

- Aplicación: `/storage/.local/share/x55-rom-downloader`.
- Menú: `/storage/.config/emulationstation/es_systems_x55_downloader.cfg`.
- Registro: `/storage/.local/share/x55-rom-downloader/launcher.log`.

Si falla una instalación, conserva el mensaje y comprueba primero
`bash install.sh --check`. Si la app no abre, consulta `launcher.log`.
