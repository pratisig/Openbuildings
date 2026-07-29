import { useEffect, useState } from 'react';
import api from '../lib/api';
import { numericAttributes } from '../lib/layers';

/**
 * Panneau « Analyse » — analyse spatiale, itinéraires et accessibilité.
 * Ces fonctions étaient soit côté navigateur seulement (turf.js dans
 * openmapagents), soit enfermées dans un plugin QGIS (GeoRouteX).
 */
export default function AnalysisPanel({ map, layers, onLayer, notify }) {
  const [tab, setTab] = useState('spatial');

  return (
    <div className="panel">
      <div className="tabs">
        {[
          ['spatial', 'Spatial'],
          ['routing', 'Itinéraire'],
          ['access', 'Accessibilité'],
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? 'tab active' : 'tab'} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'spatial' && <SpatialTab layers={layers} onLayer={onLayer} notify={notify} />}
      {tab === 'routing' && <RoutingTab map={map} onLayer={onLayer} notify={notify} />}
      {tab === 'access' && <AccessTab layers={layers} onLayer={onLayer} notify={notify} />}
    </div>
  );
}

function SpatialTab({ layers, onLayer, notify }) {
  const [operations, setOperations] = useState([]);
  const [operation, setOperation] = useState('buffer');
  const [layerA, setLayerA] = useState('');
  const [layerB, setLayerB] = useState('');
  const [radius, setRadius] = useState(500);
  const [attribute, setAttribute] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    api.spatialOperations().then((d) => setOperations(d.operations)).catch(() => {});
  }, []);

  useEffect(() => {
    if (layers.length && !layers.find((l) => l.id === layerA)) setLayerA(layers[0].id);
  }, [layers, layerA]);

  const meta = operations.find((o) => o.id === operation);
  const needsB = meta?.inputs === 2;
  const selectedA = layers.find((l) => l.id === layerA);
  const attributes = selectedA ? numericAttributes(selectedA) : [];

  async function run() {
    const a = layers.find((l) => l.id === layerA);
    const b = layers.find((l) => l.id === layerB);
    if (!a) return notify('Sélectionnez une couche source', 'warn');
    if (needsB && !b) return notify('Cette opération nécessite une seconde couche', 'warn');

    setBusy(true);
    setResult(null);
    try {
      const params = {};
      if (operation === 'buffer') params.radius_m = Number(radius);
      if ((operation === 'dissolve' || operation === 'stats') && attribute) params.attribute = attribute;

      const data = await api.spatial({
        operation,
        layer_a: a.data,
        layer_b: b?.data,
        params,
      });

      if (operation === 'stats') {
        setResult(data.result);
        notify('Statistiques calculées', 'ok');
      } else {
        onLayer({
          name: `${meta?.label || operation} — ${a.name}`,
          data,
          source: `Analyse spatiale (${operation})`,
        });
        notify(`${data.metadata.output_count} entités produites`, 'ok');
      }
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      {!layers.length && <p className="hint">Chargez d'abord une couche depuis l'onglet Données.</p>}
      <label>
        Opération
        <select value={operation} onChange={(e) => setOperation(e.target.value)}>
          {operations.map((o) => (
            <option key={o.id} value={o.id}>{o.label}</option>
          ))}
        </select>
      </label>
      {meta && <p className="hint">{meta.description}</p>}
      <label>
        Couche source
        <select value={layerA} onChange={(e) => setLayerA(e.target.value)}>
          {layers.map((l) => (
            <option key={l.id} value={l.id}>{l.name} ({l.count})</option>
          ))}
        </select>
      </label>
      {needsB && (
        <label>
          Couche secondaire
          <select value={layerB} onChange={(e) => setLayerB(e.target.value)}>
            <option value="">— choisir —</option>
            {layers.filter((l) => l.id !== layerA).map((l) => (
              <option key={l.id} value={l.id}>{l.name} ({l.count})</option>
            ))}
          </select>
        </label>
      )}
      {operation === 'buffer' && (
        <label>
          Rayon (mètres)
          <input type="number" value={radius} min="10" step="50" onChange={(e) => setRadius(e.target.value)} />
        </label>
      )}
      {(operation === 'dissolve' || operation === 'stats') && attributes.length > 0 && (
        <label>
          Attribut
          <select value={attribute} onChange={(e) => setAttribute(e.target.value)}>
            <option value="">— aucun —</option>
            {attributes.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </label>
      )}
      <button className="primary" disabled={busy || !layers.length} onClick={run}>
        {busy ? 'Calcul…' : 'Exécuter'}
      </button>
      {result && (
        <div className="stats">
          <div><span>Entités</span><b>{result.count}</b></div>
          {result.total_area_km2 > 0 && <div><span>Surface</span><b>{result.total_area_km2} km²</b></div>}
          {result.total_length_km > 0 && <div><span>Longueur</span><b>{result.total_length_km} km</b></div>}
          {result.attribute && (
            <>
              <div><span>{result.attribute.name} — somme</span><b>{result.attribute.sum}</b></div>
              <div><span>Moyenne</span><b>{result.attribute.mean}</b></div>
              <div><span>Médiane</span><b>{result.attribute.median}</b></div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function RoutingTab({ map, onLayer, notify }) {
  const [origin, setOrigin] = useState('');
  const [destination, setDestination] = useState('');
  const [profile, setProfile] = useState('car');
  const [minutes, setMinutes] = useState('5,10,15');
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);

  async function geocodeOne(query) {
    const result = await api.geocode(query, 1);
    if (!result.results.length) throw new Error(`Lieu introuvable : ${query}`);
    return result.results[0];
  }

  async function computeRoute() {
    setBusy(true);
    setSummary(null);
    try {
      const a = await geocodeOne(origin);
      const b = await geocodeOne(destination);
      const data = await api.route({
        waypoints: [[a.longitude, a.latitude], [b.longitude, b.latitude]],
        profile,
      });
      onLayer({ name: `Itinéraire ${origin} → ${destination}`, data, source: 'OSRM' });
      const props = data.features[0].properties;
      setSummary(props);
      map?.fitBounds(
        [
          [Math.min(a.longitude, b.longitude), Math.min(a.latitude, b.latitude)],
          [Math.max(a.longitude, b.longitude), Math.max(a.latitude, b.latitude)],
        ],
        { padding: 80 },
      );
      notify(`${props.distance_km} km — ${props.duration_min} min`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function computeIsochrone() {
    setBusy(true);
    try {
      const a = await geocodeOne(origin);
      const list = minutes.split(',').map((m) => parseInt(m.trim(), 10)).filter(Boolean);
      const data = await api.isochrone({
        center: [a.longitude, a.latitude],
        minutes: list,
        profile,
      });
      onLayer({ name: `Isochrone ${origin} (${profile})`, data, source: 'OSRM' });
      map?.flyTo({ center: [a.longitude, a.latitude], zoom: 12 });
      notify(
        data.metadata.approximate
          ? 'Isochrone approximée (service de routage indisponible)'
          : `${data.features.length} zones calculées`,
        data.metadata.approximate ? 'warn' : 'ok',
      );
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <label>
        Départ
        <input placeholder="Dakar, Sénégal" value={origin} onChange={(e) => setOrigin(e.target.value)} />
      </label>
      <label>
        Arrivée (itinéraire uniquement)
        <input placeholder="Thiès, Sénégal" value={destination} onChange={(e) => setDestination(e.target.value)} />
      </label>
      <label>
        Mode
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option value="car">Voiture</option>
          <option value="bike">Vélo</option>
          <option value="foot">À pied</option>
        </select>
      </label>
      <button className="primary" disabled={busy || !origin || !destination} onClick={computeRoute}>
        {busy ? 'Calcul…' : 'Calculer l\u2019itinéraire'}
      </button>
      <hr />
      <label>
        Durées d'isochrone (minutes, séparées par des virgules)
        <input value={minutes} onChange={(e) => setMinutes(e.target.value)} />
      </label>
      <button disabled={busy || !origin} onClick={computeIsochrone}>
        Calculer les isochrones
      </button>
      {summary && (
        <div className="stats">
          <div><span>Distance</span><b>{summary.distance_km} km</b></div>
          <div><span>Durée</span><b>{summary.duration_min} min</b></div>
        </div>
      )}
    </div>
  );
}

function AccessTab({ layers, onLayer, notify }) {
  const [originLayer, setOriginLayer] = useState('');
  const [facilityLayer, setFacilityLayer] = useState('');
  const [maxMinutes, setMaxMinutes] = useState(30);
  const [profile, setProfile] = useState('car');
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(null);

  async function run() {
    const origins = layers.find((l) => l.id === originLayer);
    const facilities = layers.find((l) => l.id === facilityLayer);
    if (!origins || !facilities) return notify('Sélectionnez les deux couches', 'warn');

    setBusy(true);
    setSummary(null);
    try {
      const points = origins.data.features
        .map((f) => (f.geometry?.type === 'Point' ? f.geometry.coordinates : null))
        .filter(Boolean)
        .slice(0, 100);
      if (!points.length) return notify('La couche d\u2019origines doit contenir des points', 'warn');

      const data = await api.accessibility({
        origins: points,
        facilities: facilities.data,
        max_minutes: Number(maxMinutes),
        profile,
      });
      onLayer({ name: `Accessibilité — ${facilities.name}`, data, source: 'Analyse d\u2019accessibilité' });
      setSummary(data.metadata);
      notify(`Taux de couverture : ${data.metadata.coverage_rate} %`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p className="hint">
        Pour chaque point d'origine, l'équipement le plus proche et son temps de trajet.
        Cas d'usage : accès aux structures de santé, aux écoles, aux marchés.
      </p>
      <label>
        Origines (points)
        <select value={originLayer} onChange={(e) => setOriginLayer(e.target.value)}>
          <option value="">— choisir —</option>
          {layers.map((l) => (
            <option key={l.id} value={l.id}>{l.name} ({l.count})</option>
          ))}
        </select>
      </label>
      <label>
        Équipements
        <select value={facilityLayer} onChange={(e) => setFacilityLayer(e.target.value)}>
          <option value="">— choisir —</option>
          {layers.map((l) => (
            <option key={l.id} value={l.id}>{l.name} ({l.count})</option>
          ))}
        </select>
      </label>
      <label>
        Seuil (minutes) : {maxMinutes}
        <input type="range" min="5" max="120" step="5" value={maxMinutes} onChange={(e) => setMaxMinutes(e.target.value)} />
      </label>
      <label>
        Mode
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option value="car">Voiture</option>
          <option value="bike">Vélo</option>
          <option value="foot">À pied</option>
        </select>
      </label>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Calcul…' : 'Analyser l\u2019accessibilité'}
      </button>
      {summary && (
        <div className="stats">
          <div><span>Origines</span><b>{summary.origins}</b></div>
          <div><span>Atteignables</span><b>{summary.reachable_count}</b></div>
          <div><span>Couverture</span><b>{summary.coverage_rate} %</b></div>
        </div>
      )}
    </div>
  );
}
