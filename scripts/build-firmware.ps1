[CmdletBinding()]
param(
    [ValidateSet('diagnostic', 'st7789-240x240', 'ili9341-240x320', 'st7735-128x160', 'touch4-ptt-momentary', 'camera-disabled', 'camera-ai-thinker')]
    [string]$Profile = 'diagnostic'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$primaryProject = Join-Path $repoRoot 'firmware\bella_esp32'
$cameraProject = Join-Path $repoRoot 'firmware\bella_esp32_cam'
$environment = switch ($Profile) {
    'diagnostic' { 'bella_esp32' }
    'st7789-240x240' { 'bella_esp32_st7789_240x240' }
    'ili9341-240x320' { 'bella_esp32_ili9341_240x320' }
    'st7735-128x160' { 'bella_esp32_st7735_128x160' }
    'touch4-ptt-momentary' { 'bella_esp32_touch4_ptt_momentary' }
    'camera-disabled' { 'bella_esp32_cam' }
    'camera-ai-thinker' { 'bella_esp32_cam_ai_thinker' }
}
$project = if ($Profile.StartsWith('camera-')) { $cameraProject } else { $primaryProject }

if (-not (Get-Command pio -ErrorAction SilentlyContinue)) {
    throw 'PlatformIO CLI (pio) is required. Install PlatformIO Core, then rerun this script.'
}
if ($Profile -in @('st7789-240x240', 'ili9341-240x320', 'st7735-128x160', 'touch4-ptt-momentary', 'camera-ai-thinker')) {
    Write-Warning 'This selects a candidate build profile only. Identify and match the physical board/module before flashing.'
}
if ($Profile -eq 'touch4-ptt-momentary') {
    Write-Warning 'Touch 4 push-to-talk requires a physically verified momentary TTP223 module. Toggle/latch mode is unsupported.'
}
if ($Profile -eq 'camera-ai-thinker') {
    Write-Warning 'AI-Thinker pin mapping is enabled only for a positively identified, compatible camera board.'
}

# ESP-IDF/CMake versions in this toolchain mishandle workspaces with spaces.
# Use one free temporary drive alias and remove only the alias created here.
$driveLetter = @('R','S','T','U','V','W','X','Y','Z') | Where-Object { -not (Test-Path "${_}:\") } | Select-Object -First 1
if (-not $driveLetter) { throw 'No free temporary drive letter is available for the ESP-IDF build.' }
$subst = Join-Path $env:SystemRoot 'System32\subst.exe'
& $subst "${driveLetter}:" $repoRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not create a temporary drive alias for the build.' }
try {
    $projectPath = if ($Profile.StartsWith('camera-')) { "${driveLetter}:\firmware\bella_esp32_cam" } else { "${driveLetter}:\firmware\bella_esp32" }
    & pio run -d $projectPath -e $environment
    if ($LASTEXITCODE -ne 0) { throw "Firmware build failed ($LASTEXITCODE)." }
    $artifact = Join-Path $project (".pio\build\{0}\firmware.bin" -f $environment)
    if (-not (Test-Path -LiteralPath $artifact)) { throw 'Build finished without the expected firmware.bin artifact.' }
    Write-Host "Build passed: $artifact"
    Write-Host 'No flash or upload was performed.'
} finally {
    & $subst "${driveLetter}:" /D | Out-Null
}
