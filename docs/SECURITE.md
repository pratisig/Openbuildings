# Sécurité

## Garanties de ce dépôt

Les scripts de la plateforme n'emploient **jamais** :

- `Start-Process` ni aucun binaire résolu via le `PATH` — Python et npm sont
  invoqués par chemin absolu ;
- `Invoke-Expression` (`iex`), `FromBase64String`, `-bxor` ni aucun mécanisme
  d'exécution de code déchiffré à la volée.

Six tests automatiques verrouillent ces garanties
(`TestWindowsScript`, `TestSecurityCheckScript`), exécutés par
`./scripts/dev.sh check`.

Si un script inconnu s'ouvre au lancement de `dev.ps1`, **ce n'est pas un
fichier de ce dépôt** : la machine est compromise. Voir ci-dessous.

---

## Incident du 29/07/2026 — compromission d'un poste utilisateur

### Ce qui s'est produit

`scripts/dev.ps1` appelait `Start-Process powershell`. Sur le poste concerné,
`powershell` ne résolvait pas vers l'interpréteur légitime mais vers un
**chargeur malveillant** préexistant. La plateforme n'a pas introduit
l'infection — elle l'a révélée.

### Le mécanisme

Deux fichiers forment une paire :

| Fichier | Rôle |
|---|---|
| `C:\Windows\System32\powershell.ps1` | Le chargeur. Placé dans `System32`, il est trouvé avant `powershell.exe` si `PATHEXT` contient `.PS1`. |
| `C:\Windows\System32\system.dat` | La charge utile, chiffrée. 24 012 octets, contenu hexadécimal. |

Le chargeur lit `system.dat`, le déchiffre (XOR `0xAA`, Base64 ou AES-CBC)
et exécute le résultat via `iex`. Rien n'est jamais écrit en clair sur le
disque : c'est une exécution « fileless », conçue pour échapper aux
antivirus travaillant par signature de fichier.

Écrire dans `System32` exige des droits administrateur : le poste avait déjà
été compromis avec élévation de privilèges.

### Indicateurs relevés

```
C:\Windows\System32\powershell.ps1                 chargeur
C:\Windows\System32\system.dat                     charge utile (SHA-256 5224BE15…)
[Run] desktop = %APPDATA%\desktop\desktop.exe      persistance au démarrage
%APPDATA%\Cash Register\wJ63Pr.ps1                 script bloqué par AMSI
Tâche BgTaskRegistrationMaintenanceTaskcssIt16R    suffixe aléatoire, lance powershell.exe
```

### Chronologie

| Date | Événement |
|---|---|
| 07/12/2025 | Dépôt de `system.dat` |
| 25/07/2026 20:56 | Defender bloque `schtasks /create /tn desktop /rl HIGHEST` |
| 25/07/2026 21:50 | Defender bloque `wJ63Pr.ps1` via AMSI |
| 29/07/2026 | `dev.ps1` appelle `powershell` → ouvre `powershell.ps1` |

Defender a bloqué deux tentatives mais n'a pas supprimé les fichiers
sous-jacents : la menace est restée dormante sept mois.

### Pourquoi l'exécution n'a pas eu lieu

`assoc .ps1` et `ftype` sont vides sur ce poste : Windows n'associe aucun
exécutable aux fichiers `.ps1`. Le chargeur s'est donc **ouvert dans un
éditeur** au lieu de s'exécuter. C'est ce qui a permis de le repérer.

### Correctifs appliqués

- `Start-Process` retiré de `dev.ps1`, remplacé par `Start-Job` avec chemins
  absolus (commit `478c879`) ;
- deux tests interdisent son retour ;
- `scripts/security-check.ps1` ajouté : collecte d'indices en lecture seule.

---

## En cas de suspicion

```powershell
.\scripts\security-check.ps1 -Save
```

Le script ne modifie rien. Il relève la présence du fichier suspect et son
SHA-256, la résolution réelle de `powershell`, les associations de fichiers,
les clés `Run`, les tâches planifiées et l'état de Defender.

### Marche à suivre

1. **Déconnecter la machine du réseau.**
2. **Ne pas supprimer les fichiers suspects** avant analyse — ce sont des
   pièces à conviction.
3. **Changer les mots de passe depuis un autre appareil**, en commençant par
   ceux du compte de code source, et révoquer les jetons d'accès.
4. **Analyse hors ligne** de Microsoft Defender (redémarre et analyse avant
   le chargement de Windows).
5. Soumettre le SHA-256 — **jamais le fichier** — sur
   [VirusTotal](https://www.virustotal.com).

### Sur la réinstallation

Un chargeur installé dans `System32` implique une compromission avec droits
administrateur. Le nettoyage par antivirus retire ce qui est détecté, sans
garantir qu'il ne reste rien. Pour une machine servant au développement et à
la gestion de dépôts de code, **la réinstallation est la seule remise à zéro
fiable**.

---

## Bonnes pratiques pour la plateforme

- **Aucun secret dans le code.** `.gitignore` couvre `.env`, `secrets/` et
  `*-service-account*.json`.
- **Rotation des clés exposées.** Les dépôts d'origine documentaient
  `GEE_PRIVATE_KEY` et `OPENAI_API_KEY` ; `openmapagents` versionnait en clair
  l'adresse d'un compte de service. Ces identifiants doivent être renouvelés.
- **Vérifier avant d'exécuter.** Tout script téléchargé mérite une lecture,
  en particulier s'il contient `iex`, `Invoke-Expression`, `-enc` ou
  `FromBase64String`.
