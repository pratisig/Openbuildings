import { useCallback, useEffect, useState } from 'react';
import MapView, { BASEMAPS } from './components/MapView';
import LayerManager from './components/LayerManager';
import AboutPanel from './components/AboutPanel';
import ApiBanner from './components/ApiBanner';
import MapTools from './components/MapTools';
import DataPanel from './modules/DataPanel';
import AnalysisPanel from './modules/AnalysisPanel';
import ThematicPanel from './modules/ThematicPanel';
import AgriculturePanel from './modules/AgriculturePanel';
import LandPanel from './modules/LandPanel';
import AgentPanel from './modules/AgentPanel';
import CredentialsPanel from './modules/CredentialsPanel';
import { TAB_ICONS, IconMenu, IconMoon, IconSearch, IconSun } from './components/Icons';
import { createLayer } from './lib/layers';
import api from './lib/api';
import './styles/app.css';

/** Navigation groupée par intention, plutôt qu'une liste plate. */
const GROUPS = [
  {
    label: 'Carte',
    tabs: [
      { id: 'data', label: 'Données', title: 'Charger bâtiments, routes, POI et limites administratives' },
      { id: 'layers', label: 'Couches', title: 'Styliser, zoomer et exporter les couches chargées' },
    ],
  },
  {
    label: 'Étudier',
    tabs: [
      { id: 'analysis', label: 'Analyse', title: 'Zone tampon, découpe, itinéraires, accessibilité' },
      { id: 'thematic', label: 'Satellite', title: 'Imagerie, indices spectraux, inondations, climat' },
      { id: 'agriculture', label: 'Agriculture', title: 'Campagne agricole et aptitude des cultures' },
      { id: 'land', label: 'Foncier', title: 'Évaluer une parcelle avant acquisition' },
    ],
  },
  {
    label: 'Outils',
    tabs: [
      { id: 'agent', label: 'Assistant', title: 'Piloter la carte en langage naturel' },
    ],
  },
];

const FOOTER_TABS = [
  { id: 'credentials', label: 'Comptes', title: 'Renseigner les clés des services externes' },
  { id: 'about', label: 'Guide', title: 'À quoi sert chaque module, et d’où il vient' },
];

const PANEL_META = {
  data: ['Données', 'Sources cartographiques à charger sur la carte'],
  layers: ['Couches', 'Style, visibilité et export des données affichées'],
  analysis: ['Analyse', 'Opérations spatiales et calculs de trajet'],
  thematic: ['Satellite', 'Imagerie, inondations et séries climatiques'],
  agriculture: ['Agriculture', 'Suivi de campagne et aptitude culturale'],
  land: ['Foncier', 'Évaluation multicritère d’une parcelle'],
  agent: ['Assistant', 'Dialoguez avec la carte en français'],
  credentials: ['Comptes & clés', 'Services externes optionnels'],
  about: ['Guide', 'Modules, origines et état des services'],
};

export default function App() {
  const [map, setMap] = useState(null);
  const [tab, setTab] = useState('data');
  const [layers, setLayers] = useState([]);
  const [rasterTiles, setRasterTiles] = useState([]);
  const [basemap, setBasemap] = useState('sombre');
  const [theme, setTheme] = useState('dark');
  const [toast, setToast] = useState(null);
  const [selected, setSelected] = useState(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [health, setHealth] = useState(null);
  const [search, setSearch] = useState('');
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [selectedArea, setSelectedArea] = useState(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const loadHealth = useCallback(() => {
    setHealth(null);
    api.health().then(setHealth).catch(() => setHealth({ status: 'unreachable' }));
  }, []);

  useEffect(() => { loadHealth(); }, [loadHealth]);

  const notify = useCallback((message, level = 'ok') => {
    setToast({ message, level, key: Date.now() });
    setTimeout(() => setToast((t) => (t && Date.now() - t.key > 4500 ? null : t)), 5000);
  }, []);

  const addLayer = useCallback((spec) => {
    const layer = createLayer(spec);
    setLayers((prev) => [layer, ...prev]);
    return layer;
  }, []);

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
      if (place.bbox) {
        map?.fitBounds([[place.bbox[0], place.bbox[1]], [place.bbox[2], place.bbox[3]]], { padding: 40 });
      } else {
        map?.flyTo({ center: [place.longitude, place.latitude], zoom: 13 });
      }
      notify(place.display_name, 'ok');
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  function selectTab(id) {
    if (tab === id && panelOpen) setPanelOpen(false);
    else { setTab(id); setPanelOpen(true); }
  }

  const [panelTitle, panelSubtitle] = PANEL_META[tab] || ['', ''];

  function renderRailItem(item) {
    const Icon = TAB_ICONS[item.id];
    return (
      <button
        key={item.id}
        className={tab === item.id && panelOpen ? 'rail-item active' : 'rail-item'}
        onClick={() => selectTab(item.id)}
        title={item.title}
      >
        <Icon className="rail-icon" />
        <span>{item.label}</span>
        {item.id === 'layers' && layers.length > 0 && (
          <span className="rail-badge">{layers.length}</span>
        )}
      </button>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <button className="ghost-btn" onClick={() => setPanelOpen((v) => !v)} title="Afficher ou masquer le panneau">
          <IconMenu />
        </button>

        <div className="brand">
          <div className="brand-mark">PS</div>
          <div className="brand-text">
            <b>PratiSIG</b>
            <span>Sénégal &amp; Afrique de l’Ouest</span>
          </div>
        </div>

        <div className="header-sep" />

        <form className="search" onSubmit={doSearch}>
          <IconSearch className="search-icon" />
          <input
            placeholder="Rechercher un lieu, une ville, une adresse…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>

        <div className="header-actions">
          <select
            className="ghost-btn"
            value={basemap}
            onChange={(e) => setBasemap(e.target.value)}
            title="Fond de carte"
            style={{ paddingRight: 26 }}
          >
            {Object.entries(BASEMAPS).map(([id, b]) => (
              <option key={id} value={id}>{b.label}</option>
            ))}
          </select>

          <button
            className="ghost-btn"
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
            title={theme === 'dark' ? 'Passer en thème clair' : 'Passer en thème sombre'}
          >
            {theme === 'dark' ? <IconSun /> : <IconMoon />}
          </button>

          {health && (
            <span
              className="status-pill"
              title={
                health.status === 'unreachable'
                  ? 'API injoignable'
                  : health.degraded?.length
                    ? `Modules optionnels inactifs : ${health.degraded.join(', ')}`
                    : 'Tous les services actifs'
              }
            >
              <span className={`status-dot ${health.status}`} />
              {health.status === 'unreachable'
                ? 'Hors ligne'
                : health.degraded?.length
                  ? `${health.degraded.length} inactif${health.degraded.length > 1 ? 's' : ''}`
                  : 'Opérationnel'}
            </span>
          )}
        </div>
      </header>

      <ApiBanner health={health} onRetry={loadHealth} />

      <div className="body">
        <nav className="rail">
          {GROUPS.map((group) => (
            <div key={group.label}>
              <div className="rail-label">{group.label}</div>
              <div className="rail-group">{group.tabs.map(renderRailItem)}</div>
            </div>
          ))}
          <div className="rail-spacer" />
          <div className="rail-group">{FOOTER_TABS.map(renderRailItem)}</div>
        </nav>

        <aside className={panelOpen ? 'panel-dock' : 'panel-dock hidden'}>
          <div className="panel-head">
            <div className="panel-head-text">
              <h2>{panelTitle}</h2>
              <p>{panelSubtitle}</p>
            </div>
            <button className="icon" onClick={() => setPanelOpen(false)} title="Masquer">×</button>
          </div>

          {tab === 'data' && <DataPanel map={map} area={selectedArea} onLayer={addLayer} notify={notify} />}
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
          {tab === 'analysis' && <AnalysisPanel map={map} layers={layers} onLayer={addLayer} notify={notify} />}
          {tab === 'thematic' && (
            <ThematicPanel
              map={map}
              point={selectedPoint}
              area={selectedArea}
              onRaster={addRaster}
              onLayer={addLayer}
              notify={notify}
            />
          )}
          {tab === 'agriculture' && <AgriculturePanel map={map} point={selectedPoint} notify={notify} />}
          {tab === 'land' && <LandPanel map={map} point={selectedPoint} onLayer={addLayer} notify={notify} />}
          {tab === 'agent' && <AgentPanel map={map} layers={layers} onLayer={addLayer} notify={notify} />}
          {tab === 'credentials' && <CredentialsPanel notify={notify} onChange={loadHealth} />}
          {tab === 'about' && <AboutPanel />}
        </aside>

        <main className="main">
          <MapView
            layers={layers}
            rasterTiles={rasterTiles}
            basemap={basemap}
            onMapReady={setMap}
            onFeatureClick={(feature, layer) => setSelected({ feature, layer })}
          />

          <MapTools
            map={map}
            notify={notify}
            onPoint={(p) => { setSelectedPoint(p); setSelectedArea(null); }}
            onArea={(bbox) => { setSelectedArea(bbox); setSelectedPoint(null); }}
          />

          {(selectedPoint || selectedArea) && (
            <div className="selection-chip">
              {selectedPoint
                ? `Point ${selectedPoint.latitude.toFixed(4)}, ${selectedPoint.longitude.toFixed(4)}`
                : `Zone ${selectedArea.map((v) => v.toFixed(3)).join(', ')}`}
              <button
                className="icon"
                onClick={() => { setSelectedPoint(null); setSelectedArea(null); }}
                title="Effacer la sélection"
              >
                ×
              </button>
            </div>
          )}

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
