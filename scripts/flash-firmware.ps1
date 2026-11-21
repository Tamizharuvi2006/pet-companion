[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('diagnostic', 'st7789-240x240', 'ili9341-240x320', 'st7735-128x160', 'touch4-ptt-momentary', 'camera-disabled', 'camera-ai-thinker')]
    [string]$Profile,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^COM[1-9][0-9]*$')]
    [string]$Port,
    [switch]$Flash
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Flash) {
    throw 'This script is build-only unless you explicitly pass -Flash. See scripts/build-firmware.ps1.'
}
if ($Profile -in @('st7789-240x240', 'ili9341-240x320', 'st7735-128x160', 'touch4-ptt-momentary', 'camera-ai-thinker')) {
    Write-Warning 'Only continue after confirming the physical controller and board exactly match this profile.'
}
if ($Profile -eq 'touch4-ptt-momentary') {
    Write-Warning 'Do not select this unless the TTP223 module is confirmed to be momentary, not toggle/latch.'
}
$ports = [System.IO.Ports.SerialPort]::GetPortNames()
if ($Port -notin $ports) { throw "Port $Port was not detected. Available ports: $($ports -join ', ')" }
& (Join-Path $PSScriptRoot 'build-firmware.ps1') -Profile $Profile
$confirmation = Read-Host "About to overwrite firmware on $Port using profile '$Profile'. Type FLASH $Port to continue"
if ($confirmation -cne "FLASH $Port") { throw 'Confirmation did not match. No flash was performed.' }

$environment = switch ($Profile) {
    'diagnostic' { 'bella_esp32' }
    'st7789-240x240' { 'bella_esp32_st7789_240x240' }
    'ili9341-240x320' { 'bella_esp32_ili9341_240x320' }
    'st7735-128x160' { 'bella_esp32_st7735_128x160' }
    'touch4-ptt-momentary' { 'bella_esp32_touch4_ptt_momentary' }
    'camera-disabled' { 'bella_esp32_cam' }
    'camera-ai-thinker' { 'bella_esp32_cam_ai_thinker' }
}
$project = if ($Profile.StartsWith('camera-')) { 'firmware\bella_esp32_cam' } else { 'firmware\bella_esp32' }
$driveLetter = @('R','S','T','U','V','W','X','Y','Z') | Where-Object { -not (Test-Path "${_}:\") } | Select-Object -First 1
if (-not $driveLetter) { throw 'No free temporary drive letter is available for the ESP-IDF upload.' }
$subst = Join-Path $env:SystemRoot 'System32\subst.exe'
& $subst "${driveLetter}:" $repoRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not create a temporary drive alias for upload.' }
try {
    & pio run -d "${driveLetter}:\$project" -e $environment -t upload --upload-port $Port
    if ($LASTEXITCODE -ne 0) { throw "Upload failed ($LASTEXITCODE)." }
    Write-Host 'Upload command completed. Physical boot, pin safety, and peripheral behavior remain unverified.'
} finally {
    & $subst "${driveLetter}:" /D | Out-Null
}
