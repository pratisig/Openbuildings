<#
.SYNOPSIS
    Collecte d'indices de compromission - LECTURE SEULE.

.DESCRIPTION
    Ce script ne modifie rien et ne supprime rien. Il rassemble les
    informations utiles pour decider de la suite : presence du fichier
    suspect, detournement du PATH ou des associations de fichiers,
    persistance au demarrage, taches planifiees recentes.

    A executer depuis PowerShell. Copiez la sortie complete.

.EXAMPLE
    .\scripts\security-check.ps1
    .\scripts\security-check.ps1 -Save    # ecrit aussi un rapport texte
#>

param([switch]$Save)

$ErrorActionPreference = 'Continue'
$report = [System.Collections.ArrayList]::new()

function Section { param($t) $line = "`n=== $t ==="; Write-Host $line -ForegroundColor Cyan; [void]$report.Add($line) }
function Line    { param($t, $c = 'Gray') Write-Host $t -ForegroundColor $c; [void]$report.Add($t) }
function Bad     { param($t) Line $t 'Red' }
function Good    { param($t) Line $t 'Green' }
function Warn    { param($t) Line $t 'Yellow' }

Line "Rapport genere le $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Line "Machine : $env:COMPUTERNAME   Utilisateur : $env:USERNAME"

# -- 1. Le fichier suspect ----------------------------------------
Section 'Fichier System32\system.dat'
$dat = Join-Path $env:windir 'System32\system.dat'
$item = Get-Item $dat -Force -ErrorAction SilentlyContinue
if ($item) {
    Bad "PRESENT : $($item.FullName)"
    Line "  Taille        : $($item.Length) octets"
    Line "  Cree le       : $($item.CreationTime)"
    Line "  Modifie le    : $($item.LastWriteTime)"
    Line "  Attributs     : $($item.Attributes)"
    try {
        $hash = (Get-FileHash $dat -Algorithm SHA256 -ErrorAction Stop).Hash
        Line "  SHA-256       : $hash"
        Line "  -> A soumettre sur https://www.virustotal.com (le hash, pas le fichier)"
    } catch { Warn "  Hash illisible : $($_.Exception.Message)" }

    # Nature du contenu, sans l'executer
    try {
        $head = (Get-Content $dat -TotalCount 1 -ErrorAction Stop).Trim()
        $sample = $head.Substring(0, [Math]::Min(60, $head.Length))
        Line "  Debut         : $sample..."
        if ($head -match '^[0-9A-Fa-f\s]+$')      { Bad '  Format        : hexadecimal (correspond au dechiffrement XOR du script)' }
        elseif ($head -match '^[A-Za-z0-9+/=\s]+$') { Bad '  Format        : Base64 (correspond au dechiffrement Base64/AES)' }
        else                                        { Line '  Format        : indetermine' }
    } catch { Line '  Contenu binaire ou illisible' }
} else {
    Good 'ABSENT - bonne nouvelle'
}

# -- 2. Le chargeur : powershell.ps1 dans System32 ----------------
Section 'Fichier System32\powershell.ps1 (chargeur)'
$loader = Join-Path $env:windir 'System32\powershell.ps1'
$li = Get-Item $loader -Force -ErrorAction SilentlyContinue
if ($li) {
    Bad "PRESENT : $($li.FullName)"
    Line "  Taille        : $($li.Length) octets"
    Line "  Creation      : $($li.CreationTime)"
    try {
        Line "  SHA-256       : $((Get-FileHash $loader -Algorithm SHA256 -ErrorAction Stop).Hash)"
    } catch { }
    Bad '  Un .ps1 dans System32 n est jamais legitime.'
    Bad '  Il precede powershell.exe si PATHEXT contient .PS1.'
} else {
    Good 'ABSENT'
}

# -- 3. Detournement de PowerShell --------------------------------
Section 'Resolution de la commande powershell'
$expected = Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'
Get-Command powershell -All -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Source -eq $expected) { Good "OK       : $($_.Source)" }
    else                          { Bad  "SUSPECT  : $($_.Source)" }
}
Line "Attendu  : $expected"

Section 'Association des fichiers .ps1'
$assoc = cmd /c assoc .ps1 2>$null
$ftype = cmd /c ftype Microsoft.PowerShellScript.1 2>$null
Line "assoc .ps1 : $assoc"
Line "ftype      : $ftype"
if ($ftype -and $ftype -notmatch 'powershell\.exe') {
    Bad 'DETOURNEE - c est ce qui a ouvert un script inconnu a la place de PowerShell'
} elseif ($ftype) {
    Good 'Association normale'
}

Section 'PATHEXT (.PS1 avant .EXE = detournement possible)'
Line "PATHEXT : $env:PATHEXT"
if ($env:PATHEXT -match '\.PS1') {
    $ext = $env:PATHEXT -split ';'
    $iPs1 = [Array]::IndexOf($ext, '.PS1')
    $iExe = [Array]::IndexOf($ext, '.EXE')
    if ($iPs1 -ge 0 -and $iExe -ge 0 -and $iPs1 -lt $iExe) {
        Bad 'DANGEREUX : .PS1 precede .EXE - powershell.ps1 passerait avant powershell.exe'
    } else {
        Warn '.PS1 present dans PATHEXT mais apres .EXE'
    }
} else {
    Good '.PS1 absent de PATHEXT (configuration normale)'
}

# -- 4. PATH : dossiers inscriptibles avant System32 --------------
Section 'PATH - dossiers prioritaires suspects'
$system32 = Join-Path $env:windir 'System32'
$paths = $env:PATH -split ';' | Where-Object { $_ }
$index32 = [Array]::IndexOf($paths, $system32)
$flagged = $false
for ($i = 0; $i -lt $paths.Count; $i++) {
    if ($index32 -ge 0 -and $i -ge $index32) { break }
    $p = $paths[$i]
    if ($p -match 'Temp|AppData\\Local\\Temp|Downloads|Public') {
        Bad "SUSPECT (avant System32) : $p"
        $flagged = $true
    }
}
if (-not $flagged) { Good 'Aucun dossier temporaire prioritaire sur System32' }

# -- 4. Persistance -----------------------------------------------
Section 'Demarrage automatique (registre)'
foreach ($key in @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
)) {
    $entries = Get-ItemProperty $key -ErrorAction SilentlyContinue
    if ($entries) {
        $entries.PSObject.Properties |
            Where-Object { $_.Name -notmatch '^PS' } |
            ForEach-Object {
                $suspect = $_.Value -match 'powershell|iex|hidden|-enc|system\.dat'
                if ($suspect) { Bad "SUSPECT [$key] $($_.Name) = $($_.Value)" }
                else          { Line "  [$(Split-Path $key -Leaf)] $($_.Name) = $($_.Value)" }
            }
    }
}

Section 'Taches planifiees modifiees dans les 90 derniers jours'
$since = (Get-Date).AddDays(-90)
Get-ScheduledTask -ErrorAction SilentlyContinue | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
    $action = ($_.Actions | ForEach-Object { $_.Execute }) -join ', '
    if ($action -match 'powershell|wscript|cscript|mshta|rundll32') {
        Warn "  $($_.TaskName)  ->  $action"
    }
}

Section 'Dossiers de demarrage'
foreach ($dir in @(
    [Environment]::GetFolderPath('Startup'),
    [Environment]::GetFolderPath('CommonStartup')
)) {
    Get-ChildItem $dir -ErrorAction SilentlyContinue | ForEach-Object {
        Warn "  $($_.FullName)"
    }
}

# -- 5. Etat de la protection -------------------------------------
Section 'Windows Defender'
try {
    $d = Get-MpComputerStatus -ErrorAction Stop
    if ($d.RealTimeProtectionEnabled) { Good 'Protection en temps reel : activee' }
    else                               { Bad  'Protection en temps reel : DESACTIVEE' }
    Line "Derniere analyse rapide : $($d.QuickScanEndTime)"
    Line "Signatures              : $($d.AntivirusSignatureLastUpdated)"
} catch { Warn "Etat indisponible : $($_.Exception.Message)" }

Section 'Menaces detectees (historique)'
$threats = Get-MpThreatDetection -ErrorAction SilentlyContinue |
    Sort-Object InitialDetectionTime -Descending | Select-Object -First 10
if ($threats) {
    $threats | ForEach-Object { Bad "  $($_.InitialDetectionTime)  $($_.ThreatID)  $($_.Resources -join ' ')" }
} else {
    Good 'Aucune menace dans l historique'
}

# -- Conclusion ---------------------------------------------------
Section 'Suite a donner'
Line '1. Deconnecter la machine du reseau'
Line '2. Windows Security > Protection contre les virus > Options d analyse'
Line '   > Analyse hors ligne de Microsoft Defender (redemarre et analyse)'
Line '3. Changer les mots de passe DEPUIS UN AUTRE APPAREIL (GitHub en priorite)'
Line '4. Revoquer les jetons GitHub : https://github.com/settings/tokens'
Line '5. Ne pas supprimer system.dat avant l analyse : c est une piece a conviction'

if ($Save) {
    $out = Join-Path $env:USERPROFILE "pratisig-security-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
    $report | Out-File $out -Encoding UTF8
    Write-Host "`nRapport enregistre : $out" -ForegroundColor Cyan
}
