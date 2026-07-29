<#
.SYNOPSIS
    PratiSIG — démarrage local sous Windows.

.DESCRIPTION
    Équivalent PowerShell de scripts/dev.sh.
    Crée l'environnement Python, installe les dépendances, lance l'API et
    l'interface. Ouvre deux fenêtres : une par service.

.EXAMPLE
    .\scripts\dev.ps1           # API + interface
    .\scripts\dev.ps1 api       # API seule
    .\scripts\dev.ps1 check     # tests + lint + build
#>

param(
    [ValidateSet('all', 'api', 'check')]
    [string]$Mode = 'all'
)

$ErrorActionPreference = 'Stop'

$Root   = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root 'apps\api'
$WebDir = Join-Path $Root 'apps\web'
$Venv   = Join-Path $Root '.venv'
$Py     = Join-Path $Venv 'Scripts\python.exe'

function Write-Ok   { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info { param($m) Write-Host $m -ForegroundColor Cyan }
function Write-Warn { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host $m -ForegroundColor Red }

function Find-Python {
    # Sous Windows, le lanceur `py` est le plus fiable ; `python` peut être
    # l'alias du Microsoft Store qui ouvre la boutique au lieu de s'exécuter.
    foreach ($candidate in @('py', 'python', 'python3')) {
        try {
            $version = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $version -match 'Python 3\.(\d+)') {
                if ([int]$Matches[1] -ge 10) { return $candidate }
                Write-Warn "$candidate est en $version — Python 3.10 ou plus récent est requis."
            }
        } catch { }
    }
    return $null
}

function Initialize-Api {
    if (-not (Test-Path $Py)) {
        $python = Find-Python
        if (-not $python) {
            Write-Err "Python 3.10+ introuvable."
            Write-Err "Installez-le depuis https://www.python.org/downloads/"
            Write-Err "en cochant « Add python.exe to PATH » pendant l'installation."
            exit 1
        }
        Write-Info "Création de l'environnement Python…"
        & $python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { Write-Err "Échec de création de l'environnement."; exit 1 }
    }

    & $Py -c "import fastapi" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Info "Installation des dépendances API (socle léger)…"
        & $Py -m pip install --quiet --upgrade pip
        & $Py -m pip install --quiet -r (Join-Path $ApiDir 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { Write-Err "Échec de l'installation des dépendances."; exit 1 }
        & $Py -m pip install --quiet pytest ruff
        Write-Ok "Dépendances installées."
        Write-Warn "Exports SIG, imagerie et agent désactivés."
        Write-Warn "Pour tout activer : .\.venv\Scripts\python.exe -m pip install -r apps\api\requirements-full.txt"
    }
}

function Initialize-Web {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Err "Node.js introuvable. Installez la version LTS : https://nodejs.org/"
        exit 1
    }
    if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
        Write-Info "Installation des dépendances de l'interface…"
        Push-Location $WebDir
        try {
            npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { Write-Err "Échec de npm install."; exit 1 }
        } finally { Pop-Location }
    }
}

switch ($Mode) {

    'check' {
        Initialize-Api
        Write-Info '── Tests ──'
        Push-Location $ApiDir
        try {
            & $Py -m pytest tests -q
            if ($LASTEXITCODE -ne 0) { Write-Err 'Tests en échec.'; exit 1 }
            Write-Info '── Lint ──'
            & $Py -m ruff check pratisig_api tests
            if ($LASTEXITCODE -ne 0) { Write-Err 'Lint en échec.'; exit 1 }
        } finally { Pop-Location }

        Initialize-Web
        Write-Info '── Build interface ──'
        Push-Location $WebDir
        try {
            npm run build
            if ($LASTEXITCODE -ne 0) { Write-Err 'Build en échec.'; exit 1 }
        } finally { Pop-Location }

        Write-Ok 'Toutes les vérifications passent.'
    }

    'api' {
        Initialize-Api
        Write-Ok 'API : http://localhost:8000/docs'
        Write-Info 'Ctrl+C pour arrêter.'
        Push-Location $ApiDir
        try { & $Py -m uvicorn pratisig_api.main:app --reload --port 8000 }
        finally { Pop-Location }
    }

    'all' {
        Initialize-Api
        Initialize-Web

        # Chaque service dans sa propre fenêtre : les journaux restent lisibles
        # et Ctrl+C n'arrête qu'un seul service.
        Write-Info "Démarrage de l'API dans une nouvelle fenêtre…"
        Start-Process powershell -ArgumentList @(
            '-NoExit', '-Command',
            "Set-Location '$ApiDir'; & '$Py' -m uvicorn pratisig_api.main:app --reload --port 8000"
        )

        Write-Info "Attente de l'API…"
        $ready = $false
        foreach ($i in 1..40) {
            Start-Sleep -Seconds 1
            try {
                $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2 -UseBasicParsing
                if ($r.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }

        if ($ready) {
            Write-Ok 'API prête     : http://localhost:8000/docs'
        } else {
            Write-Warn "L'API tarde à répondre — consultez la fenêtre ouverte."
        }
        Write-Ok 'Interface     : http://localhost:5173'
        Write-Host ''
        Write-Info 'Ctrl+C pour arrêter l''interface (fermez l''autre fenêtre pour l''API).'

        Push-Location $WebDir
        try { npm run dev }
        finally { Pop-Location }
    }
}
