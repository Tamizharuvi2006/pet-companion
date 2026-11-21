[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^COM[1-9][0-9]*$')]
    [string]$Port,
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$availablePorts = [System.IO.Ports.SerialPort]::GetPortNames()
if ($Port -notin $availablePorts) { throw "Port $Port was not detected. Available ports: $($availablePorts -join ', ')" }

$serial = $null
$passwordSecure = $null
$tokenSecure = $null
$passwordPtr = [IntPtr]::Zero
$tokenPtr = [IntPtr]::Zero
try {
    $serial = New-Object System.IO.Ports.SerialPort($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $serial.NewLine = "`n"
    $serial.ReadTimeout = 500
    $serial.WriteTimeout = 2000
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    $serial.Open()

    if ($Reset) {
        Write-Warning 'This clears only the camera board bella_cam NVS namespace, then reboots.'
        $confirmation = Read-Host "Type RESET BELLA CAM ON $Port to clear camera Wi-Fi/token values"
        if ($confirmation -cne "RESET BELLA CAM ON $Port") { throw 'Confirmation did not match. Camera provisioning was not erased.' }
        $serial.WriteLine('BELLA-CAM-PROVISION-RESET')
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        $cleared = $false
        while ([DateTime]::UtcNow -lt $deadline -and -not $cleared) {
            try { $cleared = $serial.ReadLine().Trim() -eq 'BELLA-CAM-PROVISION RESET; rebooting' }
            catch [TimeoutException] { }
        }
        if (-not $cleared) { throw 'Camera board did not confirm namespace reset.' }
        Write-Host 'Camera provisioning values cleared. Re-run without -Reset to provision.'
        return
    }

    Write-Warning 'Camera credentials are stored in NVS without flash encryption. Anyone with physical flash access may recover them.'
    $ssid = Read-Host 'Wi-Fi SSID'
    $passwordSecure = Read-Host 'Wi-Fi WPA2 password (hidden)' -AsSecureString
    $tokenSecure = Read-Host 'Camera bearer token (hidden; use a dedicated random token)' -AsSecureString
    $passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($passwordSecure)
    $tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenSecure)
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)

    if ([string]::IsNullOrWhiteSpace($ssid) -or $ssid.Length -gt 32 -or $ssid.Contains("`n") -or $ssid.Contains("`r")) { throw 'SSID must be 1-32 characters on one line.' }
    if ($password.Length -lt 8 -or $password.Length -gt 64) { throw 'Wi-Fi password must be 8-64 characters for the configured WPA2 station.' }
    if ($token.Length -lt 16 -or $token.Length -gt 192 -or $token -notmatch '^[A-Za-z0-9._~-]+$') { throw 'Token must be 16-192 URL-safe characters.' }

    $payload = @{ ssid=$ssid; password=$password; camera_token=$token } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
    $serial.WriteLine('BELLA-CAM-PROVISION?')
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline -and -not $ready) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line -eq 'BELLA-CAM-PROVISION READY') { $ready = $true }
            elseif ($line -like 'BELLA-CAM-PROVISION *') { Write-Host $line }
        } catch [TimeoutException] { }
    }
    if (-not $ready) { throw 'Camera provisioning console did not respond. Build and flash a camera firmware profile, then retry.' }

    $serial.WriteLine("BELLA-CAM1:$encoded")
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    $saved = $false
    while ([DateTime]::UtcNow -lt $deadline -and -not $saved) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line -eq 'BELLA-CAM-PROVISION SAVED; rebooting') { $saved = $true }
            elseif ($line -like 'BELLA-CAM-PROVISION *') { Write-Host $line }
        } catch [TimeoutException] { }
    }
    if (-not $saved) { throw 'Camera board did not confirm provisioning. Credential values were not printed.' }
    Write-Host 'Camera Wi-Fi and bearer token provisioned over local USB serial.'
} finally {
    if ($serial -and $serial.IsOpen) { $serial.Close() }
    if ($passwordPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }
    if ($tokenPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPtr) }
    if ($passwordSecure) { $passwordSecure.Dispose() }
    if ($tokenSecure) { $tokenSecure.Dispose() }
    $password = $null
    $token = $null
    $payload = $null
    $encoded = $null
}
