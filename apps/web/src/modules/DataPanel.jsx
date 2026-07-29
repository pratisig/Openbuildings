import { useEffect, useState } from 'react';
import api, { areaFromCenter } from '../lib/api';

/**
 * Panneau « Données » — fusionne ce qui était réparti dans 4 applications :
 * l'app Streamlit Open Buildings, l'explorateur Overture, l'extraction OSM
 * de city-roads et le sélecteur administratif de Carto-facileSN.
 */
export default function DataPanel({ map, onLayer, notify }) {
  const [tab, setTab] = useState('buildings');

  return (
    <div className="panel">
      <div className="tabs">
        {[
          ['buildings', 'Bâtiments'],
          ['overture', 'Overture'],
          ['osm', 'OSM'],
          ['admin', 'Admin'],
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? 'tab active' : 'tab'} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'buildings' && <BuildingsTab map={map} onLayer={onLayer} notify={notify} />}
      {tab === 'overture' && <OvertureTab map={map} onLayer={onLayer} notify={notify} />}
      {tab === 'osm' && <OsmTab map={map} onLayer={onLayer} notify={notify} />}
      {tab === 'admin' && <AdminTab onLayer={onLayer} notify={notify} />}
    </div>
  );
}

function useMapArea(map) {
  /** Zone courante : l'emprise visible, ou un rayon autour du centre. */
  return (mode, radiusKm) => {
    if (!map) return null;
    if (mode === 'radius') {
      const c = map.getCenter();
      return areaFromCenter(c.lng, c.lat, radiusKm * 1000);
    }
    const b = map.getBounds();
    return { bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] };
  };
}

function BuildingsTab({ map, onLayer, notify }) {
  const [countries, setCountries] = useState([]);
  const [iso3, setIso3] = useState('SEN');
  const [confidence, setConfidence] = useState(0.7);
  const [limit, setLimit] = useState(3000);
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState(null);
  const getArea = useMapArea(map);

  useEffect(() => {
    api.countries().then((d) => setCountries(d.countries)).catch(() => {});
  }, []);

  async function run(statsOnly) {
    setBusy(true);
    setStats(null);
    try {
      const area = getArea('bbox');
      if (statsOnly) {
        const result = await api.buildingsStats({
          country_iso3: iso3,
          area,
          min_confidence: confidence,
        });
        setStats(result);
        notify(`Statistiques calculées pour ${iso3}`, 'ok');
      } else {
        const data = await api.buildings({
          country_iso3: iso3,
          area,
          min_confidence: confidence,
          limit: Number(limit),
        });
        if (!data.features.length) {
          notify('Aucun bâtiment dans cette emprise — déplacez ou dézoomez la carte', 'warn');
        } else {
          onLayer({
            name: `Bâtiments ${iso3}`,
            data,
            source: 'Open Buildings (Google + Microsoft)',
          });
          notify(`${data.features.length} bâtiments chargés`, 'ok');
        }
      }
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p className="hint">
        Empreintes Google + Microsoft (2,5 milliards de bâtiments). La requête porte sur
        l'emprise visible de la carte.
      </p>
      <label>
        Pays
        <select value={iso3} onChange={(e) => setIso3(e.target.value)}>
          {countries.map((c) => (
            <option key={c.iso3} value={c.iso3}>
              {c.name} ({c.iso3})
            </option>
          ))}
        </select>
      </label>
      <label>
        Confiance minimale : {confidence.toFixed(2)}
        <input
          type="range"
          min="0"
          max="0.95"
          step="0.05"
          value={confidence}
          onChange={(e) => setConfidence(Number(e.target.value))}
        />
      </label>
      <label>
        Nombre maximal
        <input type="number" value={limit} min="100" max="50000" step="500" onChange={(e) => setLimit(e.target.value)} />
      </label>
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => run(false)}>
          {busy ? 'Chargement…' : 'Charger les bâtiments'}
        </button>
        <button disabled={busy} onClick={() => run(true)}>
          Statistiques
        </button>
      </div>
      {stats && (
        <div className="stats">
          <div><span>Total</span><b>{(stats.stats.total ?? 0).toLocaleString('fr-FR')}</b></div>
          <div><span>Surface moyenne</span><b>{Math.round(stats.stats.surface_moyenne_m2 ?? 0)} m²</b></div>
          <div><span>Confiance moyenne</span><b>{(stats.stats.confiance_moyenne ?? 0).toFixed(2)}</b></div>
          {stats.density_per_km2 && <div><span>Densité</span><b>{stats.density_per_km2} /km²</b></div>}
        </div>
      )}
    </div>
  );
}

function OvertureTab({ map, onLayer, notify }) {
  const [themes, setThemes] = useState({});
  const [theme, setTheme] = useState('places');
  const [category, setCategory] = useState('');
  const [limit, setLimit] = useState(1000);
  const [busy, setBusy] = useState(false);
  const getArea = useMapArea(map);

  useEffect(() => {
    api.overtureThemes().then((d) => setThemes(d.themes)).catch(() => {});
  }, []);

  async function run() {
    setBusy(true);
    try {
      const data = await api.overture({
        theme,
        area: getArea('bbox'),
        category: category || undefined,
        limit: Number(limit),
      });
      if (!data.features.length) notify('Aucun résultat dans cette emprise', 'warn');
      else {
        onLayer({ name: `Overture ${theme}`, data, source: 'Overture Maps' });
        notify(`${data.features.length} entités chargées`, 'ok');
      }
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p className="hint">Données Overture Maps interrogées en SQL sur S3, sans téléchargement préalable.</p>
      <label>
        Thème
        <select value={theme} onChange={(e) => setTheme(e.target.value)}>
          {Object.entries(themes).map(([id, meta]) => (
            <option key={id} value={id}>{meta.label}</option>
          ))}
        </select>
      </label>
      {theme === 'places' && (
        <label>
          Catégorie (optionnel)
          <input
            placeholder="restaurant, pharmacy, school…"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
        </label>
      )}
      <label>
        Nombre maximal
        <input type="number" value={limit} min="100" max="20000" step="500" onChange={(e) => setLimit(e.target.value)} />
      </label>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Chargement…' : 'Charger'}
      </button>
    </div>
  );
}

function OsmTab({ map, onLayer, notify }) {
  const [presets, setPresets] = useState([]);
  const [preset, setPreset] = useState('health');
  const [busy, setBusy] = useState(false);
  const getArea = useMapArea(map);

  useEffect(() => {
    api.osmPresets().then((d) => setPresets(d.presets)).catch(() => {});
  }, []);

  async function run(withStats) {
    setBusy(true);
    try {
      const body = { preset, area: getArea('bbox'), limit: 5000 };
      const data = withStats ? await api.osmRoads(body) : await api.osm(body);
      if (!data.features.length) notify('Aucun résultat OSM dans cette emprise', 'warn');
      else {
        const label = presets.find((p) => p.id === preset)?.label || preset;
        onLayer({ name: `OSM ${label}`, data, source: 'OpenStreetMap' });
        const extra = data.metadata.total_length_km ? ` — ${data.metadata.total_length_km} km` : '';
        notify(`${data.features.length} entités${extra}`, 'ok');
      }
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  const isRoads = preset.startsWith('roads');

  return (
    <div className="form">
      <p className="hint">Extraction OpenStreetMap via Overpass. Limitez l'emprise pour aller plus vite.</p>
      <label>
        Type de données
        <select value={preset} onChange={(e) => setPreset(e.target.value)}>
          {presets.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
      </label>
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => run(false)}>
          {busy ? 'Chargement…' : 'Charger'}
        </button>
        {isRoads && (
          <button disabled={busy} onClick={() => run(true)}>
            Avec longueurs
          </button>
        )}
      </div>
    </div>
  );
}

function AdminTab({ onLayer, notify }) {
  const [levels, setLevels] = useState([]);
  const [niveau, setNiveau] = useState('regions');
  const [iso3, setIso3] = useState('SEN');
  const [gadmLevel, setGadmLevel] = useState(1);
  const [mode, setMode] = useState('senegal');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.senegalLevels().then((d) => setLevels(d.levels)).catch(() => {});
  }, []);

  async function run() {
    setBusy(true);
    try {
      const data =
        mode === 'senegal' ? await api.senegal(niveau) : await api.gadm(iso3, Number(gadmLevel));
      onLayer({
        name: mode === 'senegal' ? `Sénégal — ${niveau}` : `${iso3} niveau ${gadmLevel}`,
        data,
        source: 'GADM 4.1',
      });
      notify(`${data.features.length} entités administratives`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p className="hint">Limites administratives : sélectionnez votre zone d'étude.</p>
      <div className="row">
        <button className={mode === 'senegal' ? 'chip active' : 'chip'} onClick={() => setMode('senegal')}>
          Sénégal
        </button>
        <button className={mode === 'gadm' ? 'chip active' : 'chip'} onClick={() => setMode('gadm')}>
          Autre pays
        </button>
      </div>
      {mode === 'senegal' ? (
        <label>
          Niveau
          <select value={niveau} onChange={(e) => setNiveau(e.target.value)}>
            {levels.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label} (~{l.expected})
              </option>
            ))}
          </select>
        </label>
      ) : (
        <>
          <label>
            Code ISO3
            <input value={iso3} maxLength={3} onChange={(e) => setIso3(e.target.value.toUpperCase())} />
          </label>
          <label>
            Niveau GADM
            <select value={gadmLevel} onChange={(e) => setGadmLevel(e.target.value)}>
              {[0, 1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>Niveau {n}</option>
              ))}
            </select>
          </label>
        </>
      )}
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Chargement…' : 'Charger les limites'}
      </button>
    </div>
  );
}
