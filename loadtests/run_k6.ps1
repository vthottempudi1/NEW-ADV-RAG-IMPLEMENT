param(
    [Parameter(Mandatory = $true)]
    [string]$Script,

    [string]$BaseUrl = "https://api.aiscientificlabs.com",
    [string]$Username = "",
    [string]$Password = "",
    [string]$Duration = "",
    [string]$Vus = "",
    [string]$RagVus = "",
    [string]$SqlVus = "",
    [string]$HybridVus = "",
    [string]$OutFile = ""
)

$env:BASE_URL = $BaseUrl

if ($Username) { $env:LOADTEST_USERNAME = $Username }
if ($Password) { $env:LOADTEST_PASSWORD = $Password }
if ($Duration) { $env:DURATION = $Duration }
if ($Vus) { $env:VUS = $Vus }
if ($RagVus) { $env:RAG_VUS = $RagVus }
if ($SqlVus) { $env:SQL_VUS = $SqlVus }
if ($HybridVus) { $env:HYBRID_VUS = $HybridVus }

$scriptPath = Join-Path $PSScriptRoot $Script
if (-not (Test-Path $scriptPath)) {
    throw "Load test script not found: $scriptPath"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutFile) {
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($Script)
    $OutFile = Join-Path $PSScriptRoot "results\$($baseName)_$timestamp.txt"
}

$k6Command = Get-Command k6 -ErrorAction SilentlyContinue
$k6Path = if ($k6Command) {
    $k6Command.Source
} else {
    "C:\Program Files\k6\k6.exe"
}

if (-not (Test-Path $k6Path)) {
    throw "k6 executable not found. Install k6 or add it to PATH."
}

Write-Host "Running k6 script: $scriptPath"
Write-Host "Base URL: $env:BASE_URL"
Write-Host "Output file: $OutFile"
Write-Host "k6 path: $k6Path"

$previousNativeErrorPreference = $global:PSNativeCommandUseErrorActionPreference
$global:PSNativeCommandUseErrorActionPreference = $false

try {
    & $k6Path run $scriptPath *>&1 | Tee-Object -FilePath $OutFile
    $exitCode = $LASTEXITCODE
} finally {
    $global:PSNativeCommandUseErrorActionPreference = $previousNativeErrorPreference
}

if ($exitCode -ne 0) {
    Write-Warning "k6 exited with code $exitCode. This usually means a threshold failed, not that the wrapper broke. See: $OutFile"
}
