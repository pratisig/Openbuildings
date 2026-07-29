import { useCallback, useEffect, useState } from 'react';
import MapView, { BASEMAPS } from './components/MapView';
import LayerManager from './components/LayerManager';
import AboutPanel from './components/AboutPanel';
import DataPanel from './modules/DataPanel';
import AnalysisPanel from './modules/AnalysisPanel';
import ThematicPanel from './modules/ThematicPanel';
import AgentPanel from './modules/AgentPanel';
import { createLayer } from './lib/layers';
import api from './lib/api';
import './styles/app.css';

const TABS = [
  { id: 'data', label: 'Données', icon: '⬢' },
  { id: 'layers', label: 'Couches', icon: '≡' },
  { id: 'analysis', label: 'Analyse', icon: '◈' },
  { id: 'thematic', label: 'Thématiques', icon: '◐' },
  { id: 'agent', label: 'Agent', icon: '✦' },
  { id: 'about', label: 'À propos', icon: '?' },
];

export default function App() {
  const [map, setMap] = useState(null);
  const [tab, setTab] = useState('data');
  const [layers, setLayers] = useState([]);
  const [rasterTiles, setRasterTiles] = useState([]);
  const [basemap, setBasemap] = useState('clair');
  const [toast, setToast] = useState(null);
  const [selected, setSelected] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [health, setHealth] = useState(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: 'unreachable' }));
  }, []);

  const notify = useCallback((message, level = 'ok') => {
    setToast({ message, level, key: Date.now() });
    setTimeout(() => setToast((t) => (t && Date.now() - t.key > 4500 ? null : t)), 5000);
  }, []);

  const addLayer = useCallback(
    (spec) => {
      const layer = createLayer(spec);
      setLayers((prev) => [layer, ...prev]);
      return layer;
    },
    [],
  );

  const updateLayer = useCallback((id, patch) => {
    setLayers((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  }, []);

  const removeLayer = useCallback((id) => {
    setLayers((prev) => prev.filter((l) => l.id !== id));
  }, []);

  const addRaster = useCallback((tile) => {
    setRasterTiles((prev) => [...prev.filter((t) => t.id !== tile.id), tile]);
  }, []);

  const updateRaster = useCallback((id, patch) => {
    setRasterTiles((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }, []);

  const removeRaster = useCallback((id) => {
    setRasterTiles((prev) => prev.filter((t) => t.id !== id));
  }, []);

  async function doSearch(e) {
    e.preventDefault();
    if (!search.trim()) return;
    try {
      const result = await api.geocode(search, 1);
      if (!result.results.length) return notify('Lieu introuvable', 'warn');
      const place = result.results[0];
      if (place.bbox) map?.fitBounds([[place.bbox[0], place.bbox[1]], [place.bbox[2], place.bbox[3]]], { padding: 40 });
      else map?.flyTo({ center: [place.longitude, place.latitude], zoom: 13 });
      notify(place.display_name, 'ok');
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  return (
    <div className="app">
      <header className="header">
        <button className="burger" onClick={() => setSidebarOpen((v) => !v)} title="Afficher/masquer le panneau">
          ☰
        </button>
        <div className="brand">
          <b>PratiSIG</b>
          <span>Plateforme géospatiale — Sénégal &amp; Afrique de l'Ouest</span>
        </div>
        <form className="search" onSubmit={doSearch}>
          <input
            placeholder="Rechercher un lieu…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <select className="basemap" value={basemap} onChange={(e) => setBasemap(e.target.value)}>
          {Object.entries(BASEMAPS).map(([id, b]) => (
            <option key={id} value={id}>{b.label}</option>
          ))}
        </select>
        {health && (
          <span className={`health ${health.status}`} title={
            health.degraded?.length ? `Dégradé : ${health.degraded.join(', ')}` : 'Tous les services actifs'
          }>
            ●
          </span>
        )}
      </header>

      <div className="body">
        <aside className={sidebarOpen ? 'sidebar open' : 'sidebar'}>
          <nav className="nav">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? 'nav-item active' : 'nav-item'}
                onClick={() => setTab(t.id)}
                title={t.label}
              >
                <span className="nav-icon">{t.icon}</span>
                <span className="nav-label">{t.label}</span>
                {t.id === 'layers' && layers.length > 0 && (
                  <span className="nav-badge">{layers.length}</span>
                )}
              </button>
            ))}
          </nav>

          <div className="panel-host">
            {tab === 'data' && <DataPanel map={map} onLayer={addLayer} notify={notify} />}
            {tab === 'layers' && (
              <LayerManager
                layers={layers}
                rasterTiles={rasterTiles}
                map={map}
                onUpdate={updateLayer}
                onRemove={removeLayer}
                onUpdateRaster={updateRaster}
                onRemoveRaster={removeRaster}
                notify={notify}
              />
            )}
            {tab === 'analysis' && (
              <AnalysisPanel map={map} layers={layers} onLayer={addLayer} notify={notify} />
            )}
            {tab === 'thematic' && (
              <ThematicPanel map={map} onRaster={addRaster} onLayer={addLayer} notify={notify} />
            )}
            {tab === 'agent' && (
              <AgentPanel map={map} layers={layers} onLayer={addLayer} notify={notify} />
            )}
            {tab === 'about' && <AboutPanel />}
          </div>
        </aside>

        <main className="main">
          <MapView
            layers={layers}
            rasterTiles={rasterTiles}
            basemap={basemap}
            onMapReady={setMap}
            onFeatureClick={(feature, layer) => setSelected({ feature, layer })}
          />

          {selected && (
            <div className="inspector">
              <div className="inspector-head">
                <b>{selected.layer.name}</b>
                <button className="icon" onClick={() => setSelected(null)}>×</button>
              </div>
              <table>
                <tbody>
                  {Object.entries(selected.feature.properties || {})
                    .filter(([, v]) => v !== null && v !== '')
                    .slice(0, 20)
                    .map(([k, v]) => (
                      <tr key={k}>
                        <td>{k}</td>
                        <td>{String(v).slice(0, 80)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {toast && (
            <div className={`toast ${toast.level}`} key={toast.key}>
              {toast.message}
              <button className="icon" onClick={() => setToast(null)}>×</button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
