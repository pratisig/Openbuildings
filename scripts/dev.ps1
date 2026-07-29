<#
.SYNOPSIS
    PratiSIG - demarrage local sous Windows.

.DESCRIPTION
    Equivalent PowerShell de scripts/dev.sh.
    Cree l'environnement Python, installe les dependances, lance l'API et
    l'interface.

.EXAMPLE
    .\scripts\dev.ps1           # API + interface
    .\scripts\dev.ps1 api       # API seule
    .\scripts\dev.ps1 check     # tests + lint + build
    .\scripts\dev.ps1 doctor    # diagnostic de l'environnement
#>

param(
    [ValidateSet('all', 'api', 'check', 'doctor')]
    [string]$Mode = 'all'
)

# ATTENTION : ne pas mettre $ErrorActionPreference = 'Stop'.
# En PowerShell 5.1, tout ce qu'une commande native ecrit sur stderr devient
# alors une erreur terminante (NativeCommandError), meme quand la commande
# reussit. python.exe ecrit divers avertissements sur stderr : le script
# s'interrompait sans raison valable.
$ErrorActionPreference = 'Continue'

$Root   = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root 'apps\api'
$WebDir = Join-Path $Root 'apps\web'
$Venv   = Join-Path $Root '.venv'
$Py     = Join-Path $Venv 'Scripts\python.exe'

function Write-Ok   { param($m) Write-Host $m -ForegroundColor Green }
function Write-Info { param($m) Write-Host $m -ForegroundColor Cyan }
function Write-Warn { param($m) Write-Host $m -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host $m -ForegroundColor Red }

# Variables d'environnement Python heritees d'une autre installation.
# PYTHONHOME mal defini provoque "Could not find platform independent
# libraries <prefix>". On neutralise pour la duree du script uniquement.
function Clear-PythonEnv {
    foreach ($name in @('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) {
            Write-Warn "$name=$value ignore pour cette session (source frequente d'erreurs)."
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
    }
}

# Execute une commande native et renvoie le code de sortie, sans laisser
# PowerShell transformer la sortie stderr en exception.
function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Arguments = @(),
        [switch]$Quiet
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) {
            & $File @Arguments 2>&1 | Out-Null
        } else {
            & $File @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Find-Python {
    # Le lanceur `py` est le plus fiable sous Windows ; `python` est souvent
    # l'alias du Microsoft Store, qui ouvre la boutique au lieu de s'executer.
    $candidates = @(
        @{ File = 'py';      Args = @('-3', '--version') },
        @{ File = 'py';      Args = @('--version') },
        @{ File = 'python';  Args = @('--version') },
        @{ File = 'python3'; Args = @('--version') }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.File -ErrorAction SilentlyContinue)) { continue }
        $output = & $c.File @($c.Args) 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { continue }
        if ($output -match 'Python 3\.(\d+)') {
            if ([int]$Matches[1] -ge 10) {
                # `py -3` doit rester en deux morceaux a l'appel
                if ($c.Args[0] -eq '-3') {
                    return @{ File = $c.File; Prefix = @('-3') }
                }
                return @{ File = $c.File; Prefix = @() }
            }
            Write-Warn "$($c.File) est en $($output.Trim()) - Python 3.10 ou plus recent est requis."
        }
    }
    return $null
}

function Test-Doctor {
    Write-Info '== Diagnostic de l''environnement =='
    Write-Host ''

    Write-Host 'PowerShell : ' -NoNewline
    Write-Host $PSVersionTable.PSVersion

    foreach ($name in @('PYTHONHOME', 'PYTHONPATH')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        Write-Host "$name : " -NoNewline
        if ($value) { Write-Warn "$value  <-- a supprimer si Python echoue" }
        else        { Write-Ok 'non defini (correct)' }
    }

    Write-Host 'Python : ' -NoNewline
    $python = Find-Python
    if ($python) {
        $version = (& $python.File @($python.Prefix + '--version') 2>&1 | Out-String).Trim()
        Write-Ok "$version via '$($python.File) $($python.Prefix -join ' ')'"
    } else {
        Write-Err 'introuvable ou trop ancien (3.10+ requis)'
        Write-Err 'https://www.python.org/downloads/  (cocher "Add python.exe to PATH")'
    }

    Write-Host 'Node.js : ' -NoNewline
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Write-Ok (node --version 2>&1 | Out-String).Trim()
    } else {
        Write-Err 'introuvable - https://nodejs.org/'
    }

    Write-Host 'Environnement .venv : ' -NoNewline
    if (Test-Path $Py) { Write-Ok $Py } else { Write-Warn 'pas encore cree' }

    Write-Host ''
    Write-Info 'Si tout est vert, lancez : .\scripts\dev.ps1'
}

function Initialize-Api {
    Clear-PythonEnv

    if (-not (Test-Path $Py)) {
        $python = Find-Python
        if (-not $python) {
            Write-Err 'Python 3.10+ introuvable.'
            Write-Err 'Installez-le depuis https://www.python.org/downloads/'
            Write-Err 'en cochant "Add python.exe to PATH" pendant l''installation.'
            Write-Err 'Puis relancez : .\scripts\dev.ps1 doctor'
            exit 1
        }

        Write-Info "Creation de l'environnement Python..."
        $code = Invoke-Native -File $python.File -Arguments ($python.Prefix + @('-m', 'venv', $Venv))
        if ($code -ne 0 -or -not (Test-Path $Py)) {
            Write-Err "Echec de creation de l'environnement (code $code)."
            Write-Err 'Diagnostic : .\scripts\dev.ps1 doctor'
            exit 1
        }
        Write-Ok 'Environnement cree.'
    }

    # Verifie si les dependances sont deja installees.
    # Aucune sortie n'est affichee : seul le code de retour compte.
    $installed = (Invoke-Native -File $Py -Arguments @('-c', 'import fastapi') -Quiet) -eq 0

    if (-not $installed) {
        Write-Info 'Installation des dependances API (socle leger)...'
        Write-Info 'Quelques minutes au premier lancement.'

        Invoke-Native -File $Py -Arguments @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip') -Quiet | Out-Null

        $req = Join-Path $ApiDir 'requirements.txt'
        $code = Invoke-Native -File $Py -Arguments @('-m', 'pip', 'install', '-r', $req)
        if ($code -ne 0) {
            Write-Err "Echec de l'installation des dependances (code $code)."
            exit 1
        }

        Invoke-Native -File $Py -Arguments @('-m', 'pip', 'install', '--quiet', 'pytest', 'ruff') -Quiet | Out-Null

        Write-Ok 'Dependances installees.'
        Write-Warn 'Exports SIG, imagerie satellite et agent restent desactives.'
        Write-Warn 'Pour tout activer :'
        Write-Warn '  .\.venv\Scripts\python.exe -m pip install -r apps\api\requirements-full.txt'
    }
}

function Initialize-Web {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Err 'Node.js introuvable. Installez la version LTS : https://nodejs.org/'
        exit 1
    }
    if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
        Write-Info "Installation des dependances de l'interface..."
        Push-Location $WebDir
        try {
            $code = Invoke-Native -File 'npm.cmd' -Arguments @('install', '--no-audit', '--no-fund')
            if ($code -ne 0) { Write-Err 'Echec de npm install.'; exit 1 }
        } finally {
            Pop-Location
        }
    }
}

switch ($Mode) {

    'doctor' {
        Test-Doctor
    }

    'check' {
        Initialize-Api
        Push-Location $ApiDir
        try {
            Write-Info '-- Tests --'
            if ((Invoke-Native -File $Py -Arguments @('-m', 'pytest', 'tests', '-q')) -ne 0) {
                Write-Err 'Tests en echec.'; exit 1
            }
            Write-Info '-- Lint --'
            if ((Invoke-Native -File $Py -Arguments @('-m', 'ruff', 'check', 'pratisig_api', 'tests')) -ne 0) {
                Write-Err 'Lint en echec.'; exit 1
            }
        } finally {
            Pop-Location
        }

        Initialize-Web
        Write-Info '-- Build interface --'
        Push-Location $WebDir
        try {
            if ((Invoke-Native -File 'npm.cmd' -Arguments @('run', 'build')) -ne 0) {
                Write-Err 'Build en echec.'; exit 1
            }
        } finally {
            Pop-Location
        }

        Write-Ok 'Toutes les verifications passent.'
    }

    'api' {
        Initialize-Api
        Write-Ok 'API : http://localhost:8000/docs'
        Write-Info 'Ctrl+C pour arreter.'
        Push-Location $ApiDir
        try {
            & $Py -m uvicorn pratisig_api.main:app --reload --port 8000
        } finally {
            Pop-Location
        }
    }

    'all' {
        Initialize-Api
        Initialize-Web

        # Note de securite : ce script n'ouvre AUCUNE nouvelle fenetre et
        # n'appelle jamais Start-Process. Les binaires sont invoques par chemin
        # absolu ($Py, npm.cmd), jamais par un nom resolu via le PATH.
        Write-Info "Demarrage de l'API en arriere-plan..."

        $apiJob = Start-Job -ScriptBlock {
            param($dir, $python)
            Set-Location $dir
            & $python -m uvicorn pratisig_api.main:app --port 8000 2>&1
        } -ArgumentList $ApiDir, $Py

        Write-Info "Attente de l'API..."
        $ready = $false
        foreach ($i in 1..40) {
            Start-Sleep -Seconds 1
            try {
                $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' `
                    -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }

        if ($ready) {
            Write-Ok 'API prete     : http://localhost:8000/docs'
        } else {
            Write-Warn "L'API tarde a repondre. Journal :"
            Receive-Job $apiJob | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
        }
        Write-Ok 'Interface     : http://localhost:5173'
        Write-Host ''
        Write-Info 'Ctrl+C arrete les deux services.'

        # Arret propre du job API quand l'interface se termine
        $stopApi = {
            if ($apiJob) { Stop-Job $apiJob -ErrorAction SilentlyContinue; Remove-Job $apiJob -Force -ErrorAction SilentlyContinue }
        }
        Register-EngineEvent PowerShell.Exiting -Action $stopApi | Out-Null

        Push-Location $WebDir
        try {
            & npm.cmd run dev
        } finally {
            Pop-Location
            & $stopApi
        }
    }
}
