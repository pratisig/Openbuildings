import { useEffect, useState } from 'react';
import api from '../lib/api';

/**
 * Panneau « Foncier » — reprend TerraCheck Sénégal.
 * Évaluation multicritère d'une parcelle et comparaison de candidates.
 */
export default function LandPanel({ map, onLayer, notify }) {
  const [cities, setCities] = useState([]);
  const [city, setCity] = useState('dakar');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [basket, setBasket] = useState([]);
  const [comparison, setComparison] = useState(null);

  useEffect(() => {
    api.landReferences().then((d) => setCities(d.cities)).catch(() => {});
  }, []);

  function currentPoint() {
    if (!map) return null;
    const c = map.getCenter();
    return { latitude: Math.round(c.lat * 100000) / 100000, longitude: Math.round(c.lng * 100000) / 100000 };
  }

  async function analyze() {
    const point = currentPoint();
    if (!point) return;
    setBusy(true);
    setResult(null);
    try {
      const data = await api.landAnalyze({ ...point, reference_city: city });
      setResult(data);
      const total = data.score.total;
      notify(
        total === null
          ? 'Aucune source disponible pour ce point'
          : `Score ${total}/100 — ${data.score.label} (couverture ${data.score.coverage_pct} %)`,
        total === null ? 'warn' : 'ok',
      );
      onLayer({
        name: `Parcelle ${point.latitude.toFixed(4)}, ${point.longitude.toFixed(4)}`,
        data: {
          type: 'FeatureCollection',
          features: [{
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [point.longitude, point.latitude] },
            properties: {
              score: total,
              verdict: data.score.label,
              risque_inondation: data.flood?.risk_level ?? null,
              terrain: data.topography?.terrain_type ?? null,
              occupation_sol: data.landcover?.label ?? null,
              route_km: data.services?.nearest_road_km ?? null,
            },
          }],
        },
        source: 'Analyse foncière',
      });
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  function addToBasket() {
    const point = currentPoint();
    if (!point) return;
    if (basket.length >= 8) return notify('Maximum 8 parcelles à comparer', 'warn');
    setBasket((prev) => [...prev, point]);
    notify(`Parcelle ${basket.length + 1} ajoutée à la comparaison`, 'ok');
  }

  async function compare() {
    if (basket.length < 2) return notify('Ajoutez au moins 2 parcelles', 'warn');
    setBusy(true);
    setComparison(null);
    try {
      const data = await api.landCompare({
        parcels: basket.map((p) => ({ ...p, reference_city: city })),
      });
      setComparison(data);
      notify(`Meilleure parcelle : n°${data.best.index + 1} (${data.best.score.total}/100)`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="form">
        <p className="hint">
          Évalue le point au centre de la carte : inondation, topographie, occupation du sol,
          accès et services. Une source indisponible ne pénalise pas la parcelle — son poids
          est redistribué.
        </p>
        <label>
          Ville de référence
          <select value={city} onChange={(e) => setCity(e.target.value)}>
            {cities.map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>
        </label>
        <div className="row">
          <button className="primary" disabled={busy} onClick={analyze}>
            {busy ? 'Analyse…' : 'Analyser ce point'}
          </button>
          <button disabled={busy} onClick={addToBasket}>
            Ajouter ({basket.length})
          </button>
        </div>
        {basket.length >= 2 && (
          <div className="row">
            <button disabled={busy} onClick={compare}>Comparer les {basket.length} parcelles</button>
            <button disabled={busy} onClick={() => { setBasket([]); setComparison(null); }}>
              Vider
            </button>
          </div>
        )}

        {result && <LandResult result={result} />}

        {comparison && (
          <div className="ranking">
            <h4 className="section-title">Classement</h4>
            {comparison.ranking.map((r) => (
              <div key={r.index} className="rank-row">
                <span className="rank-label">Parcelle {r.index + 1}</span>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${r.score.total ?? 0}%`, background: r.score.color }}
                  />
                </div>
                <b>{r.score.total ?? '—'}</b>
                <small>{r.score.label}</small>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LandResult({ result }) {
  const { score, flood, topography, landcover, services, travel, warnings } = result;

  return (
    <>
      <div className="score-badge" style={{ borderColor: score.color }}>
        <span className="score-value" style={{ color: score.color }}>
          {score.total ?? '—'}
        </span>
        <span className="score-label">{score.label}</span>
        <small>couverture des données : {score.coverage_pct} %</small>
      </div>

      <div className="stats">
        {flood && (
          <>
            <div><span>Risque d'inondation</span><b>{flood.risk_level}</b></div>
            <div><span>Pluie max/jour</span><b>{flood.max_daily_mm} mm</b></div>
          </>
        )}
        {topography && (
          <>
            <div><span>Altitude</span><b>{topography.elevation_m} m</b></div>
            <div><span>Pente</span><b>{topography.slope_deg}°</b></div>
            <div><span>Terrain</span><b>{topography.terrain_type}</b></div>
          </>
        )}
        {landcover && <div><span>Occupation du sol</span><b>{landcover.label}</b></div>}
        {services && (
          <>
            <div><span>Route la plus proche</span><b>{services.nearest_road_km ?? '—'} km</b></div>
            <div><span>École</span><b>{services.distances_km.school ?? '—'} km</b></div>
            <div><span>Santé</span><b>{services.distances_km.health ?? '—'} km</b></div>
          </>
        )}
        <div><span>{travel.reference_city}</span><b>{travel.distance_km} km</b></div>
        <div><span>Coût transport</span><b>{travel.transport_cost_cfa.toLocaleString('fr-FR')} FCFA</b></div>
      </div>

      {warnings.map((w, i) => (
        <div key={i} className={`notice notice-${w.level}`}>{w.message}</div>
      ))}

      <p className="hint disclaimer">{result.disclaimer}</p>
    </>
  );
}
