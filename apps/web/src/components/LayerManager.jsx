import { useState } from 'react';
import api from '../lib/api';
import { PALETTE, layerBounds } from '../lib/layers';

/**
 * Gestionnaire de couches — le point de convergence de tous les modules.
 * Chaque couche, quelle que soit son origine, est exportable dans tous les
 * formats et réutilisable en analyse spatiale.
 */
export default function LayerManager({
  layers,
  rasterTiles,
  map,
  onUpdate,
  onRemove,
  onRemoveRaster,
  onUpdateRaster,
  notify,
}) {
  const [expanded, setExpanded] = useState(null);
  const [formats, setFormats] = useState([]);

  async function loadFormats() {
    if (formats.length) return;
    try {
      const d = await api.exportFormats();
      setFormats(d.formats.filter((f) => f.available));
    } catch {
      /* silencieux */
    }
  }

  async function exportLayer(layer, format) {
    try {
      await api.exportLayer(format, layer.data, layer.name.replace(/\s+/g, '_'));
      notify(`Export ${format.toUpperCase()} téléchargé`, 'ok');
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  function zoomTo(layer) {
    const bounds = layerBounds(layer);
    if (bounds) map?.fitBounds(bounds, { padding: 60, maxZoom: 16 });
    else notify('Couche sans géométrie localisable', 'warn');
  }

  if (!layers.length && !rasterTiles.length) {
    return (
      <div className="panel">
        <p className="hint">
          Aucune couche. Utilisez l'onglet <b>Données</b> pour en charger, puis revenez ici
          pour les styliser, les analyser ou les exporter.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      {rasterTiles.length > 0 && (
        <>
          <h4 className="section-title">Imagerie</h4>
          {rasterTiles.map((tile) => (
            <div key={tile.id} className="layer-item">
              <div className="layer-head">
                <input
                  type="checkbox"
                  checked={tile.visible !== false}
                  onChange={(e) => onUpdateRaster(tile.id, { visible: e.target.checked })}
                />
                <span className="layer-name" title={tile.name}>{tile.name}</span>
                <button className="icon" onClick={() => onRemoveRaster(tile.id)} title="Supprimer">×</button>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={tile.opacity ?? 0.85}
                onChange={(e) => onUpdateRaster(tile.id, { opacity: Number(e.target.value) })}
              />
            </div>
          ))}
        </>
      )}

      {layers.length > 0 && <h4 className="section-title">Couches vectorielles</h4>}
      {layers.map((layer) => (
        <div key={layer.id} className="layer-item">
          <div className="layer-head">
            <input
              type="checkbox"
              checked={layer.visible}
              onChange={(e) => onUpdate(layer.id, { visible: e.target.checked })}
            />
            <span className="swatch" style={{ background: layer.color }} />
            <span className="layer-name" title={`${layer.source} — ${layer.count} entités`}>
              {layer.name}
            </span>
            <span className="layer-count">{layer.count}</span>
            <button
              className="icon"
              onClick={() => {
                setExpanded(expanded === layer.id ? null : layer.id);
                loadFormats();
              }}
              title="Options"
            >
              {expanded === layer.id ? '▴' : '▾'}
            </button>
            <button className="icon" onClick={() => onRemove(layer.id)} title="Supprimer">×</button>
          </div>

          {expanded === layer.id && (
            <div className="layer-body">
              <div className="palette">
                {PALETTE.map((c) => (
                  <button
                    key={c}
                    className={layer.color === c ? 'swatch-btn active' : 'swatch-btn'}
                    style={{ background: c }}
                    onClick={() => onUpdate(layer.id, { color: c })}
                  />
                ))}
              </div>
              <label className="mini">
                Opacité
                <input
                  type="range"
                  min="0.1"
                  max="1"
                  step="0.05"
                  value={layer.opacity}
                  onChange={(e) => onUpdate(layer.id, { opacity: Number(e.target.value) })}
                />
              </label>
              <div className="layer-meta">
                <span>{layer.geometryType}</span>
                <span>{layer.source}</span>
              </div>
              <div className="row wrap">
                <button onClick={() => zoomTo(layer)}>Zoomer</button>
                {formats.map((f) => (
                  <button key={f.id} onClick={() => exportLayer(layer, f.id)} title={f.description}>
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
