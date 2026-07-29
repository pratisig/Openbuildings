/**
 * Bannière d'état de l'API.
 *
 * Sans elle, une API absente se traduisait par des listes déroulantes vides et
 * des « internal server error » — l'utilisateur croyait à des bugs de la
 * plateforme alors que le serveur n'avait simplement pas démarré.
 */
export default function ApiBanner({ health, onRetry }) {
  if (!health) {
    return (
      <div className="api-banner loading">
        <span className="spinner" />
        Connexion à l'API…
      </div>
    );
  }

  if (health.status === 'unreachable') {
    return (
      <div className="api-banner error">
        <div className="banner-main">
          <b>L'API ne répond pas</b>
          <p>
            L'interface fonctionne, mais aucune donnée ne peut être chargée.
            Les listes resteront vides tant que le serveur n'est pas démarré.
          </p>
          <p className="banner-fix">
            Dans un second terminal, à la racine du projet :
            <code>cd apps/api</code>
            <code>..\..\.venv\Scripts\python.exe -m uvicorn pratisig_api.main:app --port 8000</code>
            <span className="banner-note">
              (macOS / Linux : <code>../../.venv/bin/python -m uvicorn pratisig_api.main:app --port 8000</code>)
            </span>
          </p>
        </div>
        <button className="primary" onClick={onRetry}>Réessayer</button>
      </div>
    );
  }

  const degraded = health.degraded || [];
  if (degraded.length > 0) {
    const labels = {
      earthengine: 'Imagerie et Inondations',
      llm: 'Agent',
      geopandas: 'Exports GeoPackage / Shapefile',
      duckdb: 'Bâtiments et Overture',
      isochrone_shapes: 'Isochrones précises',
      shapely: 'Analyses spatiales avancées',
    };
    return (
      <div className="api-banner warn">
        <div className="banner-main">
          <b>Modules optionnels désactivés</b>
          <p>
            {degraded.map((d) => labels[d] || d).join(' · ')} — ces modules
            demandent une configuration supplémentaire. Tout le reste fonctionne.
          </p>
        </div>
      </div>
    );
  }

  return null;
}
