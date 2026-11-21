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

if ($Reset) {
    Write-Warning 'This erases only Bella provisioning values in device NVS, then reboots. It does not erase firmware or other NVS namespaces.'
    $confirmation = Read-Host "Type RESET BELLA ON $Port to clear its stored Wi-Fi/device credentials"
    if ($confirmation -cne "RESET BELLA ON $Port") { throw 'Confirmation did not match. Provisioning was not erased.' }
    $resetSerial = New-Object System.IO.Ports.SerialPort($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $resetSerial.NewLine = "`n"
    $resetSerial.ReadTimeout = 500
    $resetSerial.WriteTimeout = 2000
    $resetSerial.DtrEnable = $false
    $resetSerial.RtsEnable = $false
    try {
        $resetSerial.Open()
        $resetSerial.WriteLine('BELLA-PROVISION-RESET')
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        $cleared = $false
        while ([DateTime]::UtcNow -lt $deadline -and -not $cleared) {
            try {
                $line = $resetSerial.ReadLine().Trim()
                if ($line -eq 'BELLA-PROVISION RESET; rebooting') { $cleared = $true }
            } catch [TimeoutException] { }
        }
        if (-not $cleared) { throw 'Device did not confirm NVS reset. No credential values were printed.' }
        Write-Host 'Bella provisioning values were cleared; re-run this script without -Reset to provision the device.'
    } finally {
        if ($resetSerial.IsOpen) { $resetSerial.Close() }
    }
    return
}

Write-Host 'Device credentials are sent over the attached USB serial link and saved to device NVS.'
Write-Warning 'NVS is not flash-encrypted by this firmware. Anyone with physical flash access may be able to recover stored credentials.'
$ssid = Read-Host 'Wi-Fi SSID'
$passwordSecure = Read-Host 'Wi-Fi WPA2 password (hidden)' -AsSecureString
$backend = Read-Host 'Backend WebSocket URL (wss://host/ws/device)'
$deviceId = Read-Host 'Device ID (must exactly match the server token map unless demo auth is disabled)'
$tokenSecure = Read-Host 'Device token (hidden; leave blank only when BELLA_DEVICE_AUTH_REQUIRED=false on the server)' -AsSecureString
$passwordPtr = [IntPtr]::Zero
$tokenPtr = [IntPtr]::Zero
$serial = $null
try {
    $passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($passwordSecure)
    $tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenSecure)
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)
    if ([string]::IsNullOrWhiteSpace($ssid) -or $ssid.Length -gt 32) { throw 'SSID must be 1-32 characters.' }
    if ($password.Length -lt 8 -or $password.Length -gt 64) { throw 'Wi-Fi password must be 8-64 characters for the configured WPA2 station.' }
    if ($backend -notmatch '^wss://[^/]+/ws/device$') { throw 'Use the exact secure backend URL: wss://<host>/ws/device' }
    if ($deviceId -notmatch '^[A-Za-z0-9._-]{1,64}$') { throw 'Device ID may contain only letters, digits, dot, underscore, and hyphen.' }
    if ($token.Length -gt 0 -and ($token.Length -lt 16 -or $token.Length -gt 192 -or $token -notmatch '^[A-Za-z0-9._~-]+$')) { throw 'Token must be blank for explicit demo mode or 16-192 URL-safe characters.' }

    $payload = @{ ssid=$ssid; password=$password; backend_ws_url=$backend; device_id=$deviceId; device_token=$token } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
    $serial = New-Object System.IO.Ports.SerialPort($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $serial.NewLine = "`n"
    $serial.ReadTimeout = 500
    $serial.WriteTimeout = 2000
    $serial.DtrEnable = $false
    $serial.RtsEnable = $false
    $serial.Open()
    $serial.WriteLine('BELLA-PROVISION?')
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline -and -not $ready) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line -eq 'BELLA-PROVISION READY') { $ready = $true }
            elseif ($line -like 'BELLA-PROVISION *') { Write-Host $line }
        } catch [TimeoutException] { }
    }
    if (-not $ready) { throw 'Firmware provisioning console did not respond. Build and flash the diagnostic firmware, then retry.' }
    $serial.WriteLine("BELLA1:$encoded")
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    $saved = $false
    while ([DateTime]::UtcNow -lt $deadline -and -not $saved) {
        try {
            $line = $serial.ReadLine().Trim()
            if ($line -eq 'BELLA-PROVISION SAVED; rebooting') { $saved = $true }
            elseif ($line -like 'BELLA-PROVISION *') { Write-Host $line }
        } catch [TimeoutException] { }
    }
    if (-not $saved) { throw 'The device did not confirm provisioning. No credentials were printed; check the input constraints and retry.' }
    if ($token.Length -eq 0) {
        Write-Warning "Provisioned '$deviceId' without a token. This works only while BELLA_DEVICE_AUTH_REQUIRED=false on the server; turn it back on after the demo."
    } else {
        Write-Host "Provisioned device '$deviceId'. Configure its matching token in BELLA_DEVICE_TOKENS on the server."
    }
} finally {
    if ($serial -and $serial.IsOpen) { $serial.Close() }
    if ($passwordPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr) }
    if ($tokenPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPtr) }
    $passwordSecure.Dispose()
    $tokenSecure.Dispose()
    $password = $null
    $token = $null
    $payload = $null
    $encoded = $null
}
