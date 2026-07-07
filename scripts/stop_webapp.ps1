param(
    [int]$Port = 8000
)

$ErrorActionPreference = "SilentlyContinue"

Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*fund_backtest.webapp*"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
    }

$listeningLines = netstat -ano |
    Select-String "LISTENING" |
    Select-String ":$Port "

foreach ($line in $listeningLines) {
    $parts = ($line.Line -split "\s+") | Where-Object { $_ }
    if (-not $parts) {
        continue
    }

    [int]$pidValue = 0
    if (-not [int]::TryParse($parts[-1], [ref]$pidValue)) {
        continue
    }

    $process = Get-Process -Id $pidValue
    if ($process -and $process.ProcessName -eq "python") {
        Stop-Process -Id $pidValue -Force
    }
}

Start-Sleep -Milliseconds 500
