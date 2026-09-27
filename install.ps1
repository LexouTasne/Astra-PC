$ErrorActionPreference = "Stop"

$Repo = "https://github.com/LexouTasne/Astra-PC.git"
$DefaultDest = if ($env:ASTRA_HOME) { $env:ASTRA_HOME } else { Join-Path $HOME "Astra-PC" }
$Full = $env:ASTRA_FULL -eq "1"

function Say([string]$Text) {
    Write-Host ""
    Write-Host "[Astra] $Text" -ForegroundColor Cyan
}

if ((Test-Path (Join-Path (Get-Location) "installer.py")) -and
    (Test-Path (Join-Path (Get-Location) "astra_pc"))) {
    $Dest = (Get-Location).Path
} else {
    $Dest = $DefaultDest
}

Say "Installer universal -> $Dest"

$git = Get-Command git -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $Dest ".git")) {
    Say "Atualizando repositorio..."
    & git -C $Dest pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull falhou. Resolva mudancas locais e rode novamente." }
} elseif ($git) {
    if ((Test-Path $Dest) -and (Get-ChildItem -Force $Dest -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw "$Dest ja existe e nao e um clone Git vazio."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Say "Clonando Astra-PC..."
    & git clone --recursive $Repo $Dest
    if ($LASTEXITCODE -ne 0) { throw "git clone falhou." }
} else {
    Say "git nao encontrado; baixando snapshot do GitHub..."
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

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = Join-Path $HOME ".local\bin\uv.exe"
    if (Test-Path $candidate) { return $candidate }
    return $null
}

$uv = Find-Uv
if (-not $uv) {
    Say "Instalando uv em user-space..."
    $tmpUv = Join-Path ([IO.Path]::GetTempPath()) ("uv-" + [guid]::NewGuid() + ".ps1")
    Invoke-WebRequest "https://astral.sh/uv/install.ps1" -OutFile $tmpUv
    & powershell -NoProfile -ExecutionPolicy Bypass -File $tmpUv
    Remove-Item $tmpUv -Force
    $uv = Find-Uv
}
if (-not $uv) { throw "uv nao foi encontrado depois da instalacao." }

Set-Location $Dest
Say "Garantindo Python 3.12 isolado..."
& $uv python install 3.12
if ($LASTEXITCODE -ne 0) { throw "Falha instalando Python 3.12." }

$venvPy = Join-Path $Dest ".venv\Scripts\python.exe"
$needVenv = $true
if (Test-Path $venvPy) {
    $version = & $venvPy -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($version -eq "3.12") { $needVenv = $false }
}
if ($needVenv) {
    & $uv venv --clear --python 3.12 (Join-Path $Dest ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Falha criando .venv." }
}

Say "Executando Astra installer..."
if ($Full) {
    & $venvPy installer.py --full
} else {
    & $venvPy installer.py --yes --autostart --start --awareness-extras
}
exit $LASTEXITCODE
