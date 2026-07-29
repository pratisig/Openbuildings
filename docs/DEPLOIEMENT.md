# Tester et déployer

## Réponse courte

| Plateforme | Verdict |
|---|---|
| **Streamlit Cloud** | ❌ Impossible — la plateforme n'est plus une app Streamlit |
| **Vercel** | ✅ Pour l'**interface** uniquement — ❌ pour l'API |
| **Render** | ✅ Pour l'**API** — c'est le bon choix |

**Recommandation : API sur Render + interface sur Vercel.** Les deux ont un
plan gratuit suffisant pour tester. Le tout reste une seule plateforme pour
l'utilisateur : le front appelle l'API, qui reste invisible.

Pour un simple essai avant tout déploiement, `./scripts/dev.sh` suffit.

---

## Pourquoi pas Streamlit

C'est la question la plus légitime, puisque quatre de vos dépôts en étaient
(`Openbuildings`, `openbuildings_app`, `floodingsn`, `AGRISIGHT`). Mais
Streamlit ne peut plus héberger cette plateforme :

- **Streamlit n'expose pas d'API.** C'est justement ce qui bloquait avant :
  impossible d'appeler `floodingsn` depuis un script, QGIS ou une autre app.
  La plateforme a été construite autour d'une API — Streamlit ne sait pas la servir.
- **Streamlit réexécute tout le script à chaque clic.** Avec des requêtes
  DuckDB sur S3, c'est intenable.
- **Une seule app par dépôt** sur Streamlit Cloud. Vous retomberiez dans
  l'éparpillement de départ.

L'interface React remplace les quatre apps Streamlit d'un coup.

## Pourquoi pas Vercel pour l'API

Vercel est excellent pour du statique et des fonctions courtes. Il ne convient
pas à cette API :

- **Fonctions éphémères** — pas de processus persistant, donc la connexion
  DuckDB et son cache sont rebâtis à chaque appel.
- **Limite de durée** (10 s en gratuit) — une requête Overture ou une analyse
  Sentinel-1 la dépasse largement.
- **Pas de système de fichiers persistant** — le cache disque est perdu, or il
  est nécessaire pour respecter les quotas de Nominatim et d'Overpass.
- **Blocage d'IP** — c'est exactement ce qui obligeait `terracheck-senegal` à
  faire ses appels Overpass *depuis le navigateur*.

Render fait tourner un vrai conteneur : rien de tout cela ne se pose.

---

## 1. En local (le plus simple)

Prérequis : **Python 3.10+** et **Node.js 18+**.

### Windows (PowerShell)

```powershell
git clone https://github.com/pratisig/Openbuildings.git pratisig-platform
cd pratisig-platform
.\scripts\dev.ps1
```

> ⚠️ `./scripts/dev.sh` **ne fonctionne pas sous PowerShell** : Windows ne sait
> pas exécuter un script bash et se contente de rendre la main sans rien faire,
> sans message d'erreur. Utilisez `dev.ps1`.

Si Windows refuse d'exécuter le script (« l'exécution de scripts est
désactivée »), autorisez-le pour la session courante :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\dev.ps1
```

### macOS / Linux

```bash
git clone https://github.com/pratisig/Openbuildings.git pratisig-platform
cd pratisig-platform
./scripts/dev.sh
```

Le script crée l'environnement Python, installe les dépendances, lance l'API et
l'interface. Comptez deux à trois minutes au premier lancement.

- Interface : <http://localhost:5173>
- API et documentation : <http://localhost:8000/docs>

Autres commandes (remplacez `./scripts/dev.sh` par `.\scripts\dev.ps1` sous
Windows) :

```bash
./scripts/dev.sh api      # API seule
./scripts/dev.sh check    # tests + lint + build
```

### Sans script, à la main

Utile si un script échoue, ou pour comprendre ce qu'il fait. **Deux terminaux.**

Terminal 1 — l'API :

```powershell
# Windows
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps\api\requirements.txt
cd apps\api
..\..\.venv\Scripts\python.exe -m uvicorn pratisig_api.main:app --reload --port 8000
```

```bash
# macOS / Linux
python3 -m venv .venv
./.venv/bin/pip install -r apps/api/requirements.txt
cd apps/api
../../.venv/bin/python -m uvicorn pratisig_api.main:app --reload --port 8000
```

Terminal 2 — l'interface :

```bash
cd apps/web
npm install
npm run dev
```

### Avertissement de sécurité

`scripts/dev.ps1` n'appelle **jamais** `Start-Process`, `Invoke-Expression`
(`iex`) ni aucun binaire résolu via le `PATH`. Python et npm sont invoqués par
chemin absolu.

Si un script inconnu s'ouvre au lancement — en particulier un script contenant
`iex`, `FromBase64String` ou une lecture de `System32\system.dat` — **ce n'est
pas un fichier de ce dépôt**. C'est le signe que le `PATH` ou l'association
des fichiers `.ps1` a été détourné sur la machine. Déconnectez-la du réseau,
lancez une analyse antivirus hors ligne et changez vos mots de passe depuis un
autre appareil.

### Si ça ne marche pas

**Commencez par le diagnostic** — il vérifie Python, Node et les variables
d'environnement problématiques :

```powershell
.\scripts\dev.ps1 doctor
```

| Symptôme | Cause | Solution |
|---|---|---|
| Le script rend la main sans rien afficher | `dev.sh` lancé sous PowerShell | Utilisez `.\scripts\dev.ps1` |
| « Le bloc Catch ou Finally manque » ou « Accolade fermante manquante » | Fichier `.ps1` lu en CP1252 au lieu d'UTF-8 | `git pull` — corrigé depuis. Si l'erreur persiste, votre éditeur a réenregistré le fichier sans BOM : voir la note ci-dessous |
| « Could not find platform independent libraries `<prefix>` » | Variable `PYTHONHOME` héritée d'une autre installation Python | Voir ci-dessous |
| « NativeCommandError » alors que la commande semble réussir | PowerShell traite la sortie stderr comme une erreur | `git pull` — corrigé depuis |
| Un script inconnu s'ouvre au lancement | `PATH` ou association `.ps1` détournée sur la machine | Voir l'avertissement de sécurité ci-dessus |
| Listes déroulantes vides, « internal server error » partout | L'API n'est pas démarrée | La bannière rouge en haut de l'interface le signale et donne la commande |
| « l'exécution de scripts est désactivée » | Politique PowerShell | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `localhost:5173` refuse la connexion | L'interface n'a pas démarré | Vérifiez que Node est installé : `node --version` |
| La boutique Microsoft s'ouvre | Alias Python du Store | Installez Python depuis [python.org](https://www.python.org/downloads/) en cochant « Add python.exe to PATH » |
| `ModuleNotFoundError: pratisig_api` | uvicorn lancé du mauvais dossier | Lancez-le depuis `apps/api` |
| Erreur d'extension DuckDB au démarrage | Extensions `spatial`/`httpfs` non téléchargées | Vérifiez la connexion ; sans elles, Overture et Open Buildings sont indisponibles, le reste fonctionne |


> **« Could not find platform independent libraries »**
>
> Cette erreur vient de votre installation Python, pas de la plateforme. Elle
> survient quand la variable `PYTHONHOME` pointe vers une installation Python
> absente ou différente — souvent le reste d'une désinstallation, d'Anaconda
> ou d'un outil tiers.
>
> Le script neutralise désormais `PYTHONHOME` et `PYTHONPATH` pour sa propre
> exécution. Si le problème persiste ailleurs, supprimez la variable
> définitivement :
>
> ```powershell
> # Vérifier
> $env:PYTHONHOME
>
> # Supprimer pour la session courante
> Remove-Item Env:PYTHONHOME
>
> # Supprimer définitivement (rouvrir le terminal ensuite)
> [Environment]::SetEnvironmentVariable('PYTHONHOME', $null, 'User')
> ```
>
> Si Python reste inutilisable, réinstallez-le depuis
> [python.org](https://www.python.org/downloads/) en cochant
> **« Add python.exe to PATH »**.

> **Note sur l'encodage des scripts `.ps1`**
>
> Windows PowerShell 5.1 (celui installé par défaut) lit un fichier `.ps1`
> **sans BOM** en CP1252, et non en UTF-8. Un tiret cadratin `—` y devient
> `â€"` : ce guillemet est pris pour un délimiteur de chaîne et l'analyse
> syntaxique échoue, avec un message trompeur qui parle d'accolades ou de
> blocs `try`.
>
> `scripts/dev.ps1` est donc enregistré **avec BOM UTF-8** et n'emploie que
> des tirets ASCII. `.gitattributes` préserve cet encodage, et cinq tests le
> vérifient à chaque exécution de `dev.sh check`. Si vous modifiez le script,
> conservez l'encodage « UTF-8 avec BOM ».


### Avec Docker

```bash
cp .env.example .env
docker compose up -d
```

Tout est servi sur <http://localhost:8080>, API comprise (proxy nginx).
C'est la configuration la plus proche de la production.

---

## 2. Premier test — que regarder

Une fois lancé, ces cinq points valident l'essentiel :

1. **`/health`** — indique quels services sont actifs. En socle léger,
   `earthengine`, `geopandas` et `llm` sont `unavailable` : c'est normal.
2. **Onglet « À propos »** — le catalogue des modules et la traçabilité de vos
   15 dépôts. C'est la réponse à « j'ai oublié l'objectif de certains ».
3. **Onglet « Données » → Admin → Sénégal / régions** — charge les 14 régions.
   Valide la chaîne API → carte.
4. **Onglet « Données » → OSM → Structures de santé** — zoomez d'abord sur une
   ville, puis chargez.
5. **Onglet « Couches » → déplier une couche → exporter** — GeoJSON et CSV sont
   toujours disponibles ; GeoPackage et Shapefile exigent GeoPandas.

Pour tester l'analyse foncière (onglet « Foncier ») et l'agriculture, centrez
la carte sur un point du Sénégal — ces modules travaillent sur le centre de la
vue.

---

## 3. Déploiement — API sur Render

1. Sur [render.com](https://render.com) : **New → Blueprint**
2. Sélectionnez ce dépôt — `render.yaml` est détecté automatiquement
3. Validez : Render construit l'image Docker (5 à 10 minutes la première fois)

L'API est publiée sur `https://pratisig-api.onrender.com` (nom variable).
Vérifiez `https://<votre-api>/health`.

### Limites du plan gratuit à connaître

| Limite | Conséquence | Contournement |
|---|---|---|
| **512 Mo de RAM** | DuckDB tué sur les grosses requêtes | `PRATISIG_DUCKDB_MEMORY_LIMIT=300MB` (déjà dans `render.yaml`) ; limitez les emprises |
| **Veille après 15 min** | Première requête très lente (~50 s) | Normal ; passer au plan payant pour l'éviter |
| **Pas de disque persistant** | Cache perdu au redémarrage | Il se reconstruit ; sans gravité |

Sur plan gratuit, préférez des zones réduites : un quartier plutôt qu'une
région entière.

### Activer les modules optionnels

Dans **Environment** sur Render :

| Variable | Active |
|---|---|
| `PRATISIG_GEE_SERVICE_ACCOUNT_EMAIL` + `PRATISIG_GEE_SERVICE_ACCOUNT_KEY_JSON` | Imagerie satellite et détection d'inondations |
| `PRATISIG_LLM_ENABLED=true` + `PRATISIG_LLM_API_KEY` | Agent cartographique |

Pour Earth Engine, collez le **contenu JSON** de la clé dans
`..._KEY_JSON` (pas un chemin de fichier).

---

## 4. Déploiement — interface sur Vercel

1. Sur [vercel.com](https://vercel.com) : **Add New → Project**, importez le dépôt
2. **Root Directory** : `apps/web` ← indispensable, c'est un monorepo
3. **Environment Variables** : ajoutez

   ```
   VITE_API_URL = https://<votre-api>.onrender.com
   ```

4. Déployez

> `VITE_API_URL` est lue **au moment du build**. Si vous la modifiez ensuite,
> il faut relancer un déploiement (*Redeploy*).

### Puis autoriser le front côté API

Sur Render, mettez à jour :

```
PRATISIG_CORS_ORIGINS = ["https://votre-front.vercel.app"]
```

Le `render.yaml` autorise déjà toutes les URL d'aperçu Vercel via
`PRATISIG_CORS_ORIGIN_REGEX` — utile car chaque déploiement a une URL
différente.

### Alternative : tout sur Render

Si vous préférez un seul fournisseur, ajoutez un second service statique dans
`render.yaml`. C'est un peu plus lent pour le front (pas de CDN mondial), mais
la gestion est simplifiée et l'URL est unique.

---

## 5. Ce qui est vérifié, ce qui ne l'est pas

**Vérifié** : 140 tests passants, lint propre, build de l'interface, API
démarrée avec toutes ses routes fonctionnelles, calculs (scoring foncier,
agronomie, géométrie) testés unitairement.

**Non vérifié** : les appels réseau réels. L'environnement de développement
utilisé bloquait Nominatim, Overpass, OSRM, NASA POWER, Open-Meteo et
source.coop. Leur **gestion d'erreur** est testée — un service injoignable
renvoie un `502` explicite, jamais une donnée inventée — mais les réponses
réelles restent à valider chez vous.

Concrètement, au premier lancement, surveillez ces quatre modules :

| Module | Service | Test rapide |
|---|---|---|
| `geocoding` | Nominatim | Barre de recherche en haut |
| `osm` | Overpass | Données → OSM → Santé |
| `buildings` | source.coop | Données → Bâtiments |
| `climate` | NASA POWER | Thématiques → Climat |

Si l'un échoue, `/health` et le message d'erreur indiquent la cause.

---

## Récapitulatif

```
┌────────────────────────┐        ┌─────────────────────────┐
│  Vercel (gratuit)      │  HTTPS │  Render (gratuit)       │
│  Interface React       │───────▶│  API FastAPI (Docker)   │
│  CDN mondial           │        │  DuckDB · cache · GEE   │
└────────────────────────┘        └─────────────────────────┘
     VITE_API_URL                     PRATISIG_CORS_ORIGINS
```

Pour un simple essai : `./scripts/dev.sh`, rien à déployer.
