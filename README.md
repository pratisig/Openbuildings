# Open Buildings Downloader

Application Python/Streamlit permettant d'extraire des empreintes de bâtiments pour une zone d'intérêt et de les exporter, notamment dans une **géodatabase fichier compatible ArcGIS Pro**.

> Les données sont indicatives et ne remplacent pas le cadastre ni une donnée topographique validée.

## Fonctionnalités

- Sélection d'une zone d'intérêt par **dessin sur carte**, import d'un **GeoJSON/JSON**, **GeoPackage** ou **Shapefile ZIP**, ou saisie d'une BBOX WGS 84.
- Export des empreintes sous forme de **polygones** ou, en cochant l'option dédiée, sous forme de **centroïdes (points)**.
- Formats de sortie : **File Geodatabase ArcGIS Pro (`.gdb.zip`)**, GeoJSON, Shapefile ZIP, GeoPackage, GeoParquet et CSV.
- Sources disponibles :
  - **VIDA Google–Microsoft** : GeoParquet par pays, avec lecture spatiale optimisée lorsque l'index est fourni.
  - **Google Open Buildings v3 / Earth Engine** : seuil de confiance optionnel (`0.65`, `0.70`, `0.75`). Nécessite un compte/projet Earth Engine configuré.
  - **OpenStreetMap / Overpass** : objets `building=*` issus de la cartographie collaborative.
- Statistiques de base sur les bâtiments extraits et aperçu des attributs.

## Sources : précision et limites

| Source | Nature | Points forts | Limites |
|---|---|---|---|
| VIDA Google–Microsoft | Empreintes produites par IA | Couverture utile dans de nombreux pays du Sud global ; pas de compte Earth Engine requis | Forme, position et complétude dépendent de l'imagerie ; contrôler localement |
| Google Open Buildings v3 | Empreintes IA, attribut `confidence` | Filtrage possible selon la confiance | Quotas, authentification et disponibilité Earth Engine ; un seuil élevé peut supprimer des bâtiments réels |
| OpenStreetMap | Numérisation contributive | Peut être très détaillé et exact là où OSM est actif | Complétude et cohérence très variables selon le territoire ; serveur Overpass parfois chargé |

Les données ouvertes Meta/Facebook HRSL sont des grilles de population/implantation, **pas** une couche mondiale d'empreintes de bâtiments. Elles ne sont donc pas proposées comme source de bâtiments afin d'éviter une confusion.

## Installation et lancement sous Windows

### Prérequis

- Windows 10 ou 11
- [Python 3.10 à 3.12](https://www.python.org/downloads/) installé, avec l'option **Add Python to PATH**
- Une connexion Internet
- Optionnel : [Git for Windows](https://git-scm.com/download/win)

Ouvrez PowerShell et vérifiez Python :

```powershell
python --version
```

### Télécharger le projet

**Avec Git :**

```powershell
cd D:\GIS\GEE
git clone https://github.com/pratisig/Openbuildings.git
cd Openbuildings
```

**Sans Git :** téléchargez le ZIP depuis GitHub (**Code > Download ZIP**), décompressez-le, puis entrez dans le dossier extrait. Pour la version en développement de ce projet, utilisez :

```text
https://github.com/pratisig/Openbuildings/archive/refs/heads/arena/019fb30c-openbuildings.zip
```

Par exemple :

```powershell
cd "D:\GIS\GEE\Openbuildings-arena-019fb30c-openbuildings"
```

### Créer l'environnement et installer les dépendances

À la racine du projet :

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

La commande `Set-ExecutionPolicy` ne modifie la politique que pour la fenêtre PowerShell en cours. Elle résout le blocage habituel des scripts d'activation.

### Lancer l'application

```powershell
python -m streamlit run app.py
```

Ouvrez ensuite l'URL affichée, habituellement :

```text
http://localhost:8501
```

Pour arrêter le serveur : `Ctrl + C` dans PowerShell.

> N'utilisez pas `streamlit run [app.py](http://app.py)` : cette écriture est un lien Markdown. La bonne commande est `python -m streamlit run app.py`.

## Utilisation

1. Choisissez une source dans la barre latérale.
2. Avec **VIDA**, sélectionnez aussi le pays.
3. Dessinez, importez ou saisissez la zone d'intérêt. Commencez par une zone petite (quartier, commune ou ville).
4. Choisissez le format, puis cochez **Exporter les centroïdes (points)** si nécessaire.
5. Cliquez sur **Télécharger les bâtiments**.
6. Pour ArcGIS Pro, téléchargez le format **Géodatabase fichier ArcGIS Pro (ZIP)**, décompressez-le, puis ajoutez le dossier `.gdb` dans le catalogue ArcGIS Pro. La couche est nommée `buildings`.

### Conseils de performance

- VIDA est généralement le meilleur choix lorsque Earth Engine est chargé ou indisponible.
- Ne demandez pas un pays entier dans une seule extraction. Découpez une grande étude en zones.
- OSM/Overpass est un service communautaire : patientez et réessayez en cas d'erreur, ou réduisez l'emprise.
- Earth Engine nécessite une authentification préalable et peut imposer des limites de téléchargement.

## Version portable Windows (`.exe`)

Une application Streamlit avec GeoPandas/GDAL ne se distribue pas fiablement sous la forme d'un unique petit fichier `.exe`. Le format conseillé est un **dossier portable** contenant `OpenBuildings.exe` et ses bibliothèques. Il peut être compressé et copié sur un autre PC Windows compatible, sans réinstaller Python.

### Construire le dossier portable sous Windows

Depuis la racine du projet :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\build_windows_portable.ps1
```

Le résultat est créé dans :

```text
dist\OpenBuildings\
```

Compressez **le dossier entier** `OpenBuildings` en ZIP. Sur le poste utilisateur, décompressez-le puis démarrez :

```text
OpenBuildings.exe
```

L'application s'ouvre sur `http://localhost:8501`. Windows Defender peut afficher un avertissement car un EXE PyInstaller non signé est nouveau ; analysez le ZIP et ne diffusez que des versions construites depuis le dépôt vérifié.

## Déploiement sur GitHub

### Publier le code

```powershell
git status
git add app.py requirements.txt README.md scripts launcher.py .github
git commit -m "Mise à jour de l'application"
git push origin main
```

Utilisez une branche et une Pull Request si votre organisation l'exige. Ne publiez jamais de mots de passe, clés API, fichiers `.env` ou identifiants de service Earth Engine.

### Construire le ZIP portable avec GitHub Actions

Le workflow `.github/workflows/windows-portable.yml` construit l'application sur `windows-latest` et ajoute un artefact téléchargeable.

1. Poussez le workflow sur GitHub.
2. Sur GitHub, ouvrez **Actions** > **Build Windows portable application** > **Run workflow**.
3. À la fin du traitement, téléchargez l'artefact **OpenBuildings-Windows-portable**.
4. Pour déclencher un build lors d'une version, créez et poussez un tag :

```powershell
git tag v1.0.0
git push origin v1.0.0
```

L'artefact GitHub Actions est adapté aux tests et à la distribution interne. Pour une publication officielle, créez une **GitHub Release**, attachez le ZIP portable, documentez la version et, idéalement, signez le binaire Windows.

## Earth Engine : configuration

La source Earth Engine est facultative. Elle dépend des autorisations de votre compte et du projet Google Cloud associé. Sur une machine de développement, installez les dépendances puis authentifiez-vous avec les outils Earth Engine adaptés à votre organisation. Renseignez si nécessaire le projet Google Cloud dans le champ de l'application. Les identifiants ne doivent pas être enregistrés dans le dépôt Git.

## Dépannage

| Message | Action recommandée |
|---|---|
| `streamlit is not recognized` | Activez `.venv` puis utilisez `python -m streamlit run app.py` |
| `HTTPFileSystem requires requests and aiohttp` | Exécutez `python -m pip install -r requirements.txt` |
| Échec VIDA | Vérifiez Internet, réessayez plus tard et réduisez l'emprise |
| Échec Earth Engine | Vérifiez l'authentification/projet, réduisez la zone et réessayez plus tard |
| Échec Overpass | Réduisez la zone ou réessayez après quelques minutes |
| Erreur lors de l'activation `.venv` | Exécutez `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
