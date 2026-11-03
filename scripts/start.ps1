<#
.SYNOPSIS
Start Prompt Vault from a source checkout (Windows PowerShell 5.1 or PowerShell 7).

.DESCRIPTION
Creates backend\.venv, installs the app (editable), builds the UI when Node is available, then
runs `promptvault serve`. Needs uv (preferred) or Python 3.11+ with venv. Node 20+ and npm are only
needed to build the UI. Writes only inside the repository and the data directory (PV_DATA_DIR,
default ~\.promptvault). PV_PORT, PV_HOST and the other PV_* settings are honoured; parameters win.

If scripts are blocked by the execution policy, run:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1

Prompt Vault v1 has no authentication: only bind to a non-loopback address behind a reverse proxy
that adds authentication and TLS.

.PARAMETER Port
Port to listen on (default: PV_PORT or 8080).

.PARAMETER BindHost
Address to bind (default: PV_HOST or loopback only).

.PARAMETER NoUiBuild
Never build the UI; serve the API only if it is not built yet.

.PARAMETER RebuildUi
Rebuild the UI even if it looks up to date.

.EXAMPLE
.\scripts\start.ps1 -Port 8090
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 0,
    [string]$BindHost = '',
    [switch]$NoUiBuild,
    [switch]$RebuildUi,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Detailed
    exit 0
}

function Info([string]$m) { Write-Host "start.ps1: $m" }
function Fail([string]$m) { [Console]::Error.WriteLine("start.ps1: $m"); exit 1 }

if ($NoUiBuild -and $RebuildUi) {
    [Console]::Error.WriteLine('start.ps1: -NoUiBuild and -RebuildUi cannot be combined')
    exit 2
}

$Repo = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Repo 'backend'
$Frontend = Join-Path $Repo 'frontend'
$Static = Join-Path $Backend 'src\promptvault\static'
$StaticIndex = Join-Path $Static 'index.html'
if (-not (Test-Path (Join-Path $Backend 'pyproject.toml'))) {
    Fail 'run this script from a checkout of the repository (backend\pyproject.toml not found)'
}

# ---- host warning
$effectiveHost = $BindHost
if (-not $effectiveHost) { $effectiveHost = $env:PV_HOST }
if ($effectiveHost -and $effectiveHost -notmatch '^(localhost|::1|127\..*)$') {
    [Console]::Error.WriteLine("WARNING: binding to '$effectiveHost'. Prompt Vault v1 has no authentication; anyone who can reach this port can read and change your library.")
}

# ---- Python tooling
$uv = Get-Command uv -ErrorAction SilentlyContinue
$py = $null
if ($uv) {
    Info ("using " + (& uv --version))
} else {
    foreach ($cand in @('py', 'python3', 'python')) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $pyArgs = @()
        if ($cand -eq 'py') { $pyArgs = @('-3') }
        & $cmd.Source @pyArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $py = @($cmd.Source) + $pyArgs; break }
    }
    if (-not $py) { Fail 'need uv (https://docs.astral.sh/uv/) or Python 3.11+; neither was found' }
    Info "uv not found, using $($py -join ' ') with venv + pip"
}

# ---- UI
function Test-UiStale {
    if (-not (Test-Path $StaticIndex)) { return $true }
    $built = (Get-Item $StaticIndex).LastWriteTimeUtc
    $src = @(Join-Path $Frontend 'src'; Join-Path $Frontend 'index.html'; Join-Path $Frontend 'package.json') |
        Where-Object { Test-Path $_ }
    $newer = Get-ChildItem -Path $src -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1
    return [bool]$newer
}

if (-not $NoUiBuild -and ($RebuildUi -or (Test-UiStale))) {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($node -and $npm -and (Test-Path (Join-Path $Frontend 'package.json'))) {
        Info ("building the UI (node " + (& node --version) + ")")
        Push-Location $Frontend
        try {
            if (-not (Test-Path 'node_modules')) {
                & npm ci
                if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed (re-run with -NoUiBuild to skip the UI build)' }
            }
            & npm run build
            if ($LASTEXITCODE -ne 0) { Fail 'the UI build failed (re-run with -NoUiBuild to skip it)' }
        } finally { Pop-Location }
    } elseif (-not (Test-Path $StaticIndex)) {
        [Console]::Error.WriteLine("WARNING: the UI is not built and Node/npm were not found: serving the API only (docs at /docs). Install Node 20+ and re-run, or use the Docker image or 'pipx install prompt-vault', which include the UI.")
    }
} elseif ($NoUiBuild -and -not (Test-Path $StaticIndex)) {
    [Console]::Error.WriteLine('WARNING: -NoUiBuild and the UI is not built: serving the API only (docs at /docs).')
}

# ---- install + run
$serveArgs = @('serve')
if ($BindHost) { $serveArgs += @('--host', $BindHost) }
if ($Port -gt 0) { $serveArgs += @('--port', "$Port") }

Push-Location $Backend
try {
    if ($uv) {
        Info 'installing dependencies (uv sync)'
        & uv sync --extra xlsx
        if ($LASTEXITCODE -ne 0) { Fail 'uv sync failed' }
        Info 'starting Prompt Vault (Ctrl+C to stop)'
        & uv run --no-sync promptvault @serveArgs
    } else {
        $venv = Join-Path $Backend '.venv'
        $venvPy = Join-Path $venv 'Scripts\python.exe'
        if (-not (Test-Path $venvPy)) {
            Info "creating $venv"
            $pyExe = $py[0]
            $pyRest = @()
            if ($py.Count -gt 1) { $pyRest = $py[1..($py.Count - 1)] }
            & $pyExe @pyRest -m venv $venv
            if ($LASTEXITCODE -ne 0) { Fail 'could not create the virtual environment' }
        }
        Info 'installing dependencies (pip, editable)'
        & $venvPy -m pip install --quiet --disable-pip-version-check -e "$Backend[xlsx]"
        if ($LASTEXITCODE -ne 0) { Fail 'pip install failed' }
        Info 'starting Prompt Vault (Ctrl+C to stop)'
        & (Join-Path $venv 'Scripts\promptvault.exe') @serveArgs
    }
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
