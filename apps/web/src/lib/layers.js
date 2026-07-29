/**
 * Gestion des couches de la carte.
 *
 * Tous les modules produisent des FeatureCollections et les poussent ici :
 * c'est le point de convergence qui permet à l'analyse spatiale et aux
 * exports de fonctionner sur n'importe quelle donnée, quelle que soit sa source.
 */

export const PALETTE = [
  '#e63946', '#2a9d8f', '#e9c46a', '#457b9d', '#f4a261',
  '#8338ec', '#06d6a0', '#ef476f', '#118ab2', '#ff9f1c',
];

let counter = 0;

export function createLayer({ name, data, source, color, visible = true }) {
  counter += 1;
  const features = data?.features || [];
  const geometryTypes = [...new Set(features.map((f) => f.geometry?.type).filter(Boolean))];
  return {
    id: `layer-${counter}-${Date.now()}`,
    name,
    source,
    data,
    color: color || PALETTE[(counter - 1) % PALETTE.length],
    visible,
    opacity: 0.75,
    count: features.length,
    geometryType: geometryTypes[0] || 'Unknown',
    geometryTypes,
    createdAt: new Date().toISOString(),
    metadata: data?.metadata || {},
  };
}

/** Emprise d'une couche, pour le zoom automatique. */
export function layerBounds(layer) {
  const coords = [];
  const walk = (node) => {
    if (!node) return;
    if (Array.isArray(node)) {
      if (typeof node[0] === 'number') coords.push(node);
      else node.forEach(walk);
    }
  };
  (layer.data?.features || []).forEach((f) => walk(f.geometry?.coordinates));
  if (!coords.length) return null;
  const xs = coords.map((c) => c[0]);
  const ys = coords.map((c) => c[1]);
  return [
    [Math.min(...xs), Math.min(...ys)],
    [Math.max(...xs), Math.max(...ys)],
  ];
}

/** Résumé des couches transmis à l'agent (sans les géométries, trop volumineuses). */
export function layersContext(layers, map) {
  return {
    layers: layers.map((l) => ({
      name: l.name,
      count: l.count,
      geometry_type: l.geometryType,
      source: l.source,
      data: l.data,
    })),
    bbox: map
      ? [
          map.getBounds().getWest(),
          map.getBounds().getSouth(),
          map.getBounds().getEast(),
          map.getBounds().getNorth(),
        ]
      : null,
    zoom: map ? Math.round(map.getZoom() * 10) / 10 : null,
  };
}

/** Attributs numériques d'une couche, pour les analyses statistiques. */
export function numericAttributes(layer) {
  const sample = layer.data?.features?.slice(0, 50) || [];
  const keys = new Set();
  sample.forEach((f) => {
    Object.entries(f.properties || {}).forEach(([k, v]) => {
      if (typeof v === 'number' && Number.isFinite(v)) keys.add(k);
    });
  });
  return [...keys];
}
