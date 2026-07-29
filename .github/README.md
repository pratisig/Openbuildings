# Intégration continue

Le workflow GitHub Actions est fourni en modèle dans
[`../docs/ci-github-actions.yml`](../docs/ci-github-actions.yml).

Pour l'activer :

```bash
mkdir -p .github/workflows
cp docs/ci-github-actions.yml .github/workflows/ci.yml
git add .github/workflows/ci.yml && git commit -m "ci: activer GitHub Actions"
```

Il exécute, à chaque push et pull request :
- `ruff check` puis `pytest` sur l'API (Python 3.11) ;
- `npm ci && npm run build` sur l'interface (Node 20).

> Le fichier n'est pas activé par défaut car les jetons d'application GitHub
> ne disposent pas toujours de la permission `workflows` nécessaire pour
> écrire dans `.github/workflows/`.
