param(
    [string]$InstallDir = "",
    [string]$RuntimeDir = "",
    [string]$DataDir = "",
    [string]$CacheDir = "",
    [switch]$PortableData,
    [switch]$Yes,
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$Repo = "https://github.com/LexouTasne/Astra-PC.git"

function Say([string]$Text) {
    Write-Host ""
    Write-Host "[Astra] $Text" -ForegroundColor Cyan
}

function Expand-UserPath([string]$PathValue) {
    if (-not $PathValue) { return $PathValue }
    if ($PathValue -eq "~") { return $HOME }
    if ($PathValue.StartsWith("~/") -or $PathValue.StartsWith("~\")) {
        return Join-Path $HOME $PathValue.Substring(2)
    }
    return $PathValue
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$inRepo = (Test-Path (Join-Path $scriptRoot "installer.py")) -and
          (Test-Path (Join-Path $scriptRoot "astra_pc"))

if (-not $InstallDir) {
    if ($env:ASTRA_INSTALL_DIR) {
        $InstallDir = $env:ASTRA_INSTALL_DIR
    } elseif ($env:ASTRA_HOME) {
        $InstallDir = $env:ASTRA_HOME
    } elseif ($inRepo) {
        $InstallDir = $scriptRoot
    } else {
        $InstallDir = Join-Path $HOME "Astra-PC"
    }
}

$InstallDir = Expand-UserPath $InstallDir

if (-not $Yes -and -not $inRepo -and -not $PSBoundParameters.ContainsKey("InstallDir")) {
    $answer = Read-Host "Astra install folder [$InstallDir]"
    if ($answer) { $InstallDir = Expand-UserPath $answer }
}

$Dest = [IO.Path]::GetFullPath($InstallDir)
Say "Application folder -> $Dest"

$git = Get-Command git -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $Dest ".git")) {
    Say "Updating repository..."
    & git -C $Dest pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed. Resolve local changes and retry." }
} elseif ($git) {
    if ((Test-Path $Dest) -and (Get-ChildItem -Force $Dest -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw "$Dest exists and is not an empty folder or Astra Git checkout."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Say "Cloning Astra-PC..."
    & git clone --recursive $Repo $Dest
    if ($LASTEXITCODE -ne 0) { throw "git clone failed." }
} else {
    Say "git not found; downloading GitHub snapshot..."
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("astra-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = Join-Path $tmp "astra.zip"
    Invoke-WebRequest "https://github.com/LexouTasne/Astra-PC/archive/refs/heads/main.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath $tmp -Force
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Move-Item (Join-Path $tmp "Astra-PC-main") $Dest
    Remove-Item $tmp -Recurse -Force
}

$probe = Join-Path $Dest ".astra-write-test"
try {
    "ok" | Set-Content -Path $probe -Encoding UTF8
    Remove-Item $probe -Force
} catch {
    throw "Destination is not writable: $Dest"
}

if ($PortableData) {
    if (-not $DataDir) { $DataDir = Join-Path $Dest ".astra-data" }
    if (-not $CacheDir) { $CacheDir = Join-Path $Dest ".astra-cache" }
}
if ($DataDir -and -not $CacheDir) {
    $CacheDir = Join-Path (Expand-UserPath $DataDir) "cache"
}

if (-not $RuntimeDir) {
    if ($env:ASTRA_RUNTIME_DIR) {
        $RuntimeDir = $env:ASTRA_RUNTIME_DIR
    } else {
        $RuntimeDir = Join-Path $Dest ".venv"
    }
}
$RuntimeDir = [IO.Path]::GetFullPath((Expand-UserPath $RuntimeDir))

if ($DataDir) {
    $DataDir = [IO.Path]::GetFullPath((Expand-UserPath $DataDir))
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $env:ASTRA_DATA_DIR = $DataDir
    Say "Astra data -> $DataDir"
}
if ($CacheDir) {
    $CacheDir = [IO.Path]::GetFullPath((Expand-UserPath $CacheDir))
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    $env:ASTRA_CACHE_DIR = $CacheDir
    Say "Astra cache -> $CacheDir"
}

$env:ASTRA_INSTALL_DIR = $Dest
$env:ASTRA_RUNTIME_DIR = $RuntimeDir

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = Join-Path $HOME ".local\bin\uv.exe"
    if (Test-Path $candidate) { return $candidate }
    return $null
}

$uv = Find-Uv
if (-not $uv) {
    Say "Installing uv in user space..."
    $tmpUv = Join-Path ([IO.Path]::GetTempPath()) ("uv-" + [guid]::NewGuid() + ".ps1")
    Invoke-WebRequest "https://astral.sh/uv/install.ps1" -OutFile $tmpUv
    & powershell -NoProfile -ExecutionPolicy Bypass -File $tmpUv
    Remove-Item $tmpUv -Force
    $uv = Find-Uv
}
if (-not $uv) { throw "uv was not found after installation." }

Set-Location $Dest
Say "Ensuring isolated Python 3.12 runtime -> $RuntimeDir"

$venvPy = Join-Path $RuntimeDir "Scripts\python.exe"
$needVenv = $true
if (Test-Path $venvPy) {
    $version = & $venvPy -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($version -eq "3.12") { $needVenv = $false }
}
if ($needVenv) {
    New-Item -ItemType Directory -Force -Path (Split-Path $RuntimeDir) | Out-Null
    & $uv venv --clear --seed --python 3.12 $RuntimeDir
    if ($LASTEXITCODE -ne 0) { throw "Failed creating Astra Python runtime." }
}

& $venvPy -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Say "Repairing runtime without pip..."
    & $uv pip install --python $venvPy pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw "Failed repairing pip." }
}

Say "Running Astra guided installer..."
$argsList = @()
if ($Yes) { $argsList += "--yes" }
if ($Full -or $env:ASTRA_FULL -eq "1") { $argsList += "--full" }

& $venvPy installer.py @argsList
exit $LASTEXITCODE
