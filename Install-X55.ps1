param(
    [Parameter(Mandatory=$true)][string]$X55Address,
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\x55_ed25519",
    [switch]$UpdateCatalog,
    [string]$CatalogFile = (Join-Path $PSScriptRoot 'catalog.json')
)

$ErrorActionPreference = 'Stop'
$files = @{}
foreach ($name in @('rom_downloader.py', 'download_core.py', 'graphical_app.py', 'cover_art.py', 'sdl_backend.py', 'launch_rocknix.py', 'archive_support.py', 'romsgames_source.py', 'import_site.py', 'emulationstation_refresh.py', 'local_library.py', 'x55_systems.py')) {
    $files[$name] = ([string](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot $name))).Replace("`r`n", "`n")
}
$files['catalog.json'] = [string](Get-Content -Raw -Encoding UTF8 -LiteralPath $CatalogFile)
$menu = @{}
foreach ($name in @('es_systems_x55_downloader.cfg', 'gamelist.xml', 'logo.svg', 'canvas-metadata.xml')) {
    $menu[$name] = ([string](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot "menu\$name"))).Replace("`r`n", "`n")
}
$payload = @{
    files = $files
    menu = $menu
    port = ([string](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'X55 ROM Downloader.sh'))).Replace("`r`n", "`n")
    update_catalog = [bool]$UpdateCatalog
}
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress)))
$installerText = [string](Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'install_x55.py'))
$installerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($installerText))
$remote = "import base64; ns={'__name__':'x55_installer','__file__':'/tmp/x55-installer-memory.py'}; exec(compile(base64.b64decode('$installerEncoded'),ns['__file__'],'exec'),ns); ns['preflight'](); ns['install'](__import__('json').loads(base64.b64decode('$encoded')))"
$remote | ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes "root@$X55Address" 'python3 -B -u -'
if ($LASTEXITCODE -ne 0) {
    throw "La instalacion termino con codigo $LASTEXITCODE."
}
