param(
    [Parameter(Mandatory=$true)][string]$X55Address,
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\x55_ed25519",
    [string]$WaylandDisplay = 'wayland-1',
    [string]$RuntimeDirectory = '/var/run/0-runtime-dir',
    [switch]$EnableDownloads,
    [ValidateRange(0, 86400)][int]$MaxSeconds = 0
)

$ErrorActionPreference = 'Stop'
# Todo el código viaja por la entrada estándar; no se instala en la consola.
$bundle = @{}
foreach ($name in @('x55_systems', 'local_library', 'download_core', 'import_site', 'romsgames_source', 'archive_support', 'sdl_backend', 'emulationstation_refresh', 'cover_art', 'graphical_app')) {
    $bundle[$name] = [string](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot "$name.py"))
}
$bundle['catalog'] = [string](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'catalog.json'))
$bundle['read_only'] = -not [bool]$EnableDownloads
$bundle['max_seconds'] = $MaxSeconds
$bundle['wayland'] = $WaylandDisplay
$bundle['runtime'] = $RuntimeDirectory
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($bundle | ConvertTo-Json -Compress)))
$launcher = @'
import base64, json, os, sys, types
bundle = json.loads(base64.b64decode("BUNDLE_DATA"))
os.environ['XDG_RUNTIME_DIR'] = bundle['runtime']
os.environ['WAYLAND_DISPLAY'] = bundle['wayland']
os.environ['SDL_VIDEODRIVER'] = 'wayland'
os.environ['SDL_GAMECONTROLLERCONFIG_FILE'] = '/storage/.config/SDL-GameControllerDB/gamecontrollerdb.txt'
for name in ('x55_systems', 'local_library', 'download_core', 'import_site', 'romsgames_source', 'archive_support', 'sdl_backend', 'emulationstation_refresh', 'cover_art', 'graphical_app'):
    module = types.ModuleType(name)
    module.__file__ = '/storage/x55-in-memory/' + name + '.py'
    sys.modules[name] = module
    exec(compile(bundle[name], module.__file__, 'exec'), module.__dict__)
from graphical_app import Application
from download_core import validate_catalog
app = Application(validate_catalog(json.loads(bundle['catalog'])), '/storage/roms', read_only=bundle['read_only'])
app.run(max_seconds=bundle['max_seconds'] or None)
'@

$launcher.Replace('BUNDLE_DATA', $encoded) | ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes "root@$X55Address" 'python3 -B -u -'
if ($LASTEXITCODE -ne 0) {
    throw "La sesión SSH o la aplicación terminó con código $LASTEXITCODE."
}
