import { useEffect, useState } from 'react';
import api from '../lib/api';

/**
 * Panneau « Agriculture » — remplace les deux applications AgriSight.
 * Analyse de campagne (degrés-jours, bilan hydrique, stress, rendement)
 * et classement des cultures adaptées à un lieu.
 */
export default function AgriculturePanel({ map, notify }) {
  const [tab, setTab] = useState('season');

  return (
    <div className="panel">
      <div className="tabs">
        {[
          ['season', 'Campagne'],
          ['suitability', 'Aptitude'],
        ].map(([id, label]) => (
          <button key={id} className={tab === id ? 'tab active' : 'tab'} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'season' && <SeasonTab map={map} notify={notify} />}
      {tab === 'suitability' && <SuitabilityTab map={map} notify={notify} />}
    </div>
  );
}

function useCrops() {
  const [crops, setCrops] = useState([]);
  const [soils, setSoils] = useState([]);
  useEffect(() => {
    api.agricultureCrops().then((d) => setCrops(d.crops)).catch(() => {});
    api.agricultureZones().then((d) => setSoils(d.soil_types)).catch(() => {});
  }, []);
  return { crops, soils };
}

function SeasonTab({ map, notify }) {
  const { crops, soils } = useCrops();
  const [crop, setCrop] = useState('mil');
  const [sowing, setSowing] = useState('2024-07-01');
  const [soil, setSoil] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function run() {
    if (!map) return;
    setBusy(true);
    setResult(null);
    try {
      const c = map.getCenter();
      const data = await api.agricultureSeason({
        crop,
        latitude: Math.round(c.lat * 1000) / 1000,
        longitude: Math.round(c.lng * 1000) / 1000,
        sowing_date: sowing,
        soil: soil || undefined,
      });
      setResult(data);
      notify(`${data.crop.label} — ${data.thermal.stage} (${data.thermal.progress_pct} %)`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  const selected = crops.find((c) => c.id === crop);

  return (
    <div className="form">
      <p className="hint">
        Bilan agronomique au centre de la carte, calculé sur le climat réel NASA POWER.
        Aucune courbe n'est simulée.
      </p>
      <label>
        Culture
        <select value={crop} onChange={(e) => setCrop(e.target.value)}>
          {crops.map((c) => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>
      </label>
      {selected && (
        <p className="hint">
          Cycle {selected.cycle_days} j · pluie {selected.rain_min}–{selected.rain_max} mm ·
          optimum {selected.opt_temp} °C · rendement max {selected.yield_max_t_ha} t/ha
        </p>
      )}
      <label>
        Date de semis
        <input type="date" value={sowing} onChange={(e) => setSowing(e.target.value)} />
      </label>
      <label>
        Type de sol (optionnel)
        <select value={soil} onChange={(e) => setSoil(e.target.value)}>
          <option value="">— non précisé —</option>
          {soils.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Analyse…' : 'Analyser la campagne'}
      </button>

      {result && (
        <>
          <div className="stats">
            <div><span>Stade</span><b>{result.thermal.stage}</b></div>
            <div><span>Progression</span><b>{result.thermal.progress_pct} %</b></div>
            <div><span>Degrés-jours</span><b>{result.thermal.gdd_total}</b></div>
            <div><span>Pluie cumulée</span><b>{result.water.rainfall_mm} mm</b></div>
            <div><span>Besoin (ETc)</span><b>{result.water.etc_mm} mm</b></div>
            <div><span>Déficit</span><b>{result.water.deficit_mm} mm</b></div>
            <div><span>Rendement estimé</span><b>{result.yield.estimated_t_ha} t/ha</b></div>
            <div><span>Stress combiné</span><b>{result.stress.combined} %</b></div>
          </div>

          {result.soil && (
            <p className={result.soil.suitable ? 'hint' : 'hint warn-text'}>{result.soil.note}</p>
          )}

          {result.alerts.map((a, i) => (
            <div key={i} className={`notice notice-${a.level}`}>{a.message}</div>
          ))}

          <StressBars stress={result.stress} />
        </>
      )}
    </div>
  );
}

function StressBars({ stress }) {
  const items = [
    ['Thermique', stress.heat, '#e63946'],
    ['Hydrique', stress.water, '#457b9d'],
    ['Froid', stress.cold, '#8338ec'],
  ];
  return (
    <div className="bars">
      {items.map(([label, value, color]) => (
        <div key={label} className="bar-row">
          <span>{label}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${Math.min(100, value)}%`, background: color }} />
          </div>
          <b>{value} %</b>
        </div>
      ))}
    </div>
  );
}

function SuitabilityTab({ map, notify }) {
  const { soils } = useCrops();
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const [soil, setSoil] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function run() {
    if (!map) return;
    setBusy(true);
    setResult(null);
    try {
      const c = map.getCenter();
      const data = await api.agricultureSuitability({
        latitude: Math.round(c.lat * 1000) / 1000,
        longitude: Math.round(c.lng * 1000) / 1000,
        year: Number(year),
        soil: soil || undefined,
      });
      setResult(data);
      notify(`Zone ${data.climate.agro_zone.label} — meilleure culture : ${data.best.label}`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p className="hint">
        Classe les cultures selon le climat annuel réel du centre de la carte et, si précisé,
        le type de sol.
      </p>
      <label>
        Année de référence
        <input type="number" min="1990" max="2100" value={year} onChange={(e) => setYear(e.target.value)} />
      </label>
      <label>
        Type de sol (optionnel)
        <select value={soil} onChange={(e) => setSoil(e.target.value)}>
          <option value="">— non précisé —</option>
          {soils.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Analyse…' : 'Classer les cultures'}
      </button>

      {result && (
        <>
          <div className="stats">
            <div><span>Zone agro-écologique</span><b>{result.climate.agro_zone.label}</b></div>
            <div><span>Pluie annuelle</span><b>{result.climate.annual_rainfall_mm} mm</b></div>
            <div><span>Température moyenne</span><b>{result.climate.mean_temperature_c} °C</b></div>
            <div><span>Jours de pluie</span><b>{result.climate.rainy_days ?? '—'}</b></div>
          </div>
          <div className="ranking">
            {result.ranking.map((r) => (
              <div key={r.crop} className="rank-row">
                <span className="rank-label">{r.label}</span>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{
                      width: `${r.score}%`,
                      background:
                        r.score >= 75 ? '#2a9d8f' : r.score >= 55 ? '#6daa45'
                        : r.score >= 35 ? '#e9c46a' : '#e63946',
                    }}
                  />
                </div>
                <b>{r.score}</b>
                <small>{r.verdict}</small>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
