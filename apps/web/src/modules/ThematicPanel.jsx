import { useEffect, useState } from 'react';
import api from '../lib/api';

/**
 * Panneau « Thématiques » — imagerie satellite, inondations et climat.
 * Remplace les applications FloodWatch (floodingsn, innondationSN) et le
 * panneau GEE de openmapagents.
 */
export default function ThematicPanel({ map, point, area, onRaster, onLayer, notify }) {
  const [tab, setTab] = useState('raster');

  return (
    <div className="panel">
      <div className="tabs">
        {[
          ['raster', 'Imagerie'],
          ['flood', 'Inondations'],
          ['climate', 'Climat'],
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? 'tab active' : 'tab'} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'raster' && <RasterTab map={map} onRaster={onRaster} notify={notify} />}
      {tab === 'flood' && <FloodTab map={map} onRaster={onRaster} notify={notify} />}
      {tab === 'climate' && <ClimateTab map={map} point={point} notify={notify} />}
    </div>
  );
}

function ServiceNotice({ status }) {
  if (!status || status.available !== false) return null;
  return (
    <div className="notice">
      <b>Service indisponible</b>
      <p>
        Ce module nécessite un compte Google Earth Engine. Renseignez
        <code>PRATISIG_GEE_SERVICE_ACCOUNT_EMAIL</code> et
        <code>PRATISIG_GEE_SERVICE_ACCOUNT_KEY_FILE</code> côté serveur.
      </p>
    </div>
  );
}

function today(offsetDays = 0) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toISOString().slice(0, 10);
}

function RasterTab({ map, onRaster, notify }) {
  const [datasets, setDatasets] = useState([]);
  const [gee, setGee] = useState(null);
  const [dataset, setDataset] = useState('sentinel2');
  const [index, setIndex] = useState('NDVI');
  const [start, setStart] = useState(today(-90));
  const [end, setEnd] = useState(today());
  const [cloud, setCloud] = useState(20);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .rasterDatasets()
      .then((d) => {
        setDatasets(d.datasets);
        setGee({ available: d.gee.ready });
      })
      .catch(() => setGee({ available: false }));
  }, []);

  const current = datasets.find((d) => d.id === dataset);

  useEffect(() => {
    if (current && !current.indices.includes(index)) setIndex(current.indices[0]);
  }, [current, index]);

  async function run() {
    if (!map) return;
    setBusy(true);
    try {
      const b = map.getBounds();
      const result = await api.rasterTiles({
        dataset,
        index,
        area: { bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] },
        date_start: start,
        date_end: end,
        cloud_max: Number(cloud),
      });
      onRaster({
        id: `raster-${dataset}-${index}-${Date.now()}`,
        url: result.tile_url,
        name: `${result.label} — ${result.index}`,
        date: result.date,
        opacity: 0.85,
        visible: true,
      });
      notify(`Image du ${result.date} affichée`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <ServiceNotice status={gee} />
      <p className="hint">Indices spectraux calculés à la volée sur l'emprise visible.</p>
      <label>
        Jeu de données
        <select value={dataset} onChange={(e) => setDataset(e.target.value)}>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>{d.label}</option>
          ))}
        </select>
      </label>
      <label>
        Indice
        <select value={index} onChange={(e) => setIndex(e.target.value)}>
          {(current?.indices || []).map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </label>
      <div className="row">
        <label>
          Début
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          Fin
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      {current?.cloud_property && (
        <label>
          Nuages maximum : {cloud} %
          <input type="range" min="0" max="100" step="5" value={cloud} onChange={(e) => setCloud(e.target.value)} />
        </label>
      )}
      <button className="primary" disabled={busy || gee?.available === false} onClick={run}>
        {busy ? 'Génération…' : 'Afficher sur la carte'}
      </button>
    </div>
  );
}

function FloodTab({ map, onRaster, notify }) {
  const [status, setStatus] = useState(null);
  const [floodStart, setFloodStart] = useState('2024-08-01');
  const [floodEnd, setFloodEnd] = useState('2024-10-15');
  const [threshold, setThreshold] = useState(1.3);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    api.floodStatus().then(setStatus).catch(() => setStatus({ available: false }));
  }, []);

  async function run() {
    if (!map) return;
    setBusy(true);
    setResult(null);
    try {
      const b = map.getBounds();
      const data = await api.floodAnalyze({
        area: { bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] },
        flood_start: floodStart,
        flood_end: floodEnd,
        threshold_db: Number(threshold),
        include_population: true,
      });
      setResult(data);
      if (data.tile_url) {
        onRaster({
          id: `raster-flood-${Date.now()}`,
          url: data.tile_url,
          name: `Zones inondées ${floodStart}`,
          opacity: 0.8,
          visible: true,
        });
      }
      notify(`${data.flooded_area_km2} km² inondés détectés`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <ServiceNotice status={status} />
      <p className="hint">
        Détection par comparaison radar Sentinel-1 entre la période de crue et la même
        période l'année précédente. Le masque de pente écarte les faux positifs.
      </p>
      <div className="row">
        <label>
          Début de crue
          <input type="date" value={floodStart} onChange={(e) => setFloodStart(e.target.value)} />
        </label>
        <label>
          Fin de crue
          <input type="date" value={floodEnd} onChange={(e) => setFloodEnd(e.target.value)} />
        </label>
      </div>
      <label>
        Seuil de détection : {threshold} dB
        <input type="range" min="0.8" max="3" step="0.1" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
      </label>
      <button className="primary" disabled={busy || status?.available === false} onClick={run}>
        {busy ? 'Analyse en cours…' : 'Analyser l\u2019emprise visible'}
      </button>
      {result && (
        <div className="stats">
          <div><span>Surface inondée</span><b>{result.flooded_area_km2} km²</b></div>
          <div><span>Part de la zone</span><b>{result.flooded_ratio_pct} %</b></div>
          {result.population?.exposed !== undefined && (
            <>
              <div><span>Population exposée</span><b>{result.population.exposed.toLocaleString('fr-FR')}</b></div>
              <div><span>Part exposée</span><b>{result.population.exposed_pct} %</b></div>
            </>
          )}
          <div><span>Images utilisées</span><b>{result.images?.flood_images}</b></div>
        </div>
      )}
    </div>
  );
}

function ClimateTab({ map, point, notify }) {
  const [start, setStart] = useState('2024-01-01');
  const [end, setEnd] = useState('2024-12-31');
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);

  async function run() {
    if (!map) return;
    setBusy(true);
    try {
      const c = map.getCenter();
      const loc = point || { latitude: c.lat, longitude: c.lng };
      const result = await api.climate({
        latitude: Math.round(loc.latitude * 1000) / 1000,
        longitude: Math.round(loc.longitude * 1000) / 1000,
        start,
        end,
        parameters: ['PRECTOTCORR', 'T2M'],
      });
      setData(result);
      notify(`${result.period.days} jours de données chargés`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  const rain = data?.summary?.PRECTOTCORR;
  const temp = data?.summary?.T2M;

  return (
    <div className="form">
      <p className="hint">Séries climatiques NASA POWER au centre de la carte.</p>
      <div className="row">
        <label>
          Début
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          Fin
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Chargement…' : 'Charger les données'}
      </button>
      {rain && (
        <div className="stats">
          <div><span>Cumul de pluie</span><b>{rain.total_mm} mm</b></div>
          <div><span>Jours de pluie</span><b>{rain.rainy_days}</b></div>
          <div><span>Pluies fortes (≥20 mm)</span><b>{rain.heavy_rain_days}</b></div>
          {temp && <div><span>Température moyenne</span><b>{temp.mean} °C</b></div>}
          {temp && <div><span>Maximum</span><b>{temp.max} °C</b></div>}
        </div>
      )}
      {data && <Sparkline values={data.series.PRECTOTCORR} label="Précipitations quotidiennes (mm)" />}
    </div>
  );
}

function Sparkline({ values, label }) {
  const clean = (values || []).map((v) => (v === null ? 0 : v));
  if (!clean.length) return null;
  const max = Math.max(...clean, 1);
  const width = 260;
  const height = 60;
  const step = width / clean.length;
  const points = clean.map((v, i) => `${i * step},${height - (v / max) * height}`).join(' ');
  return (
    <div className="sparkline">
      <span>{label}</span>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <polyline points={points} fill="none" stroke="#457b9d" strokeWidth="1.5" />
      </svg>
      <small>Maximum : {max.toFixed(1)} mm</small>
    </div>
  );
}
