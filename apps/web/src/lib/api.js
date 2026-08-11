/**
 * Client API unique de la plateforme.
 *
 * Avant : chaque projet avait son `API_URL` en dur (carto-facilesn.onrender.com,
 * localhost:8000, openmapagents.geoafrica.fr...) et ses appels fetch dispersés.
 * Ici, un seul module ; changer d'environnement = une seule variable.
 */

const BASE = import.meta.env.VITE_API_URL || '';

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { method = 'GET', body, params, signal } = {}) {
  let url = `${BASE}${path}`;
  if (params) {
    const search = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
    );
    const qs = search.toString();
    if (qs) url += `?${qs}`;
  }

  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.error || detail;
    } catch {
      /* réponse non JSON */
    }
    throw new ApiError(detail, response.status, detail);
  }
  return response.json();
}

async function upload(path, file, inputFormat) {
  const form = new FormData();
  form.append('file', file);
  if (inputFormat) form.append('input_format', inputFormat);
  const response = await fetch(`${BASE}${path}`, { method: 'POST', body: form });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      /* réponse non JSON */
    }
    throw new ApiError(detail, response.status, detail);
  }
  return response.json();
}

async function download(path, body, fallbackName) {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, response.status, detail);
  }
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const blob = await response.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = match ? match[1] : fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  return { count: response.headers.get('x-feature-count') };
}

/** Construit une zone d'étude au format attendu par l'API. */
export function areaFromBounds(bounds) {
  return { bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()] };
}

export function areaFromCenter(lon, lat, radiusM) {
  return { center: [lon, lat], radius_m: radiusM };
}

export const api = {
  ApiError,

  // Système
  health: () => request('/health'),
  catalog: () => request('/api/catalog'),
  migration: () => request('/api/catalog/migration'),

  // Géocodage
  geocode: (q, limit = 5) => request('/api/geocoding/search', { params: { q, limit } }),
  reverse: (lat, lon) => request('/api/geocoding/reverse', { params: { lat, lon } }),

  // Bâtiments
  countries: (q) => request('/api/buildings/countries', { params: { q } }),
  buildings: (body) => request('/api/buildings/query', { method: 'POST', body }),
  buildingsStats: (body) => request('/api/buildings/stats', { method: 'POST', body }),

  // Overture
  overtureThemes: () => request('/api/overture/themes'),
  overture: (body) => request('/api/overture/query', { method: 'POST', body }),
  overtureStats: (body) => request('/api/overture/stats', { method: 'POST', body }),

  // OSM
  osmPresets: () => request('/api/osm/presets'),
  osm: (body) => request('/api/osm/query', { method: 'POST', body }),
  osmRoads: (body) => request('/api/osm/roads', { method: 'POST', body }),

  // Administratif
  senegalLevels: () => request('/api/admin/senegal'),
  senegal: (niveau, withGeometry = true) =>
    request(`/api/admin/senegal/${niveau}`, { params: { with_geometry: withGeometry } }),
  gadm: (iso3, level) => request(`/api/admin/gadm/${iso3}/${level}`),

  // Routage
  routingProfiles: () => request('/api/routing/profiles'),
  route: (body) => request('/api/routing/route', { method: 'POST', body }),
  isochrone: (body) => request('/api/routing/isochrone', { method: 'POST', body }),
  accessibility: (body) => request('/api/routing/accessibility', { method: 'POST', body }),

  // Analyse spatiale
  spatialOperations: () => request('/api/spatial/operations'),
  spatial: (body) => request('/api/spatial/run', { method: 'POST', body }),

  // Imagerie
  rasterDatasets: () => request('/api/raster/datasets'),
  rasterTiles: (body) => request('/api/raster/tiles', { method: 'POST', body }),
  rasterTimeseries: (body) => request('/api/raster/timeseries', { method: 'POST', body }),

  // Inondations
  floodStatus: () => request('/api/flood/status'),
  floodAnalyze: (body) => request('/api/flood/analyze', { method: 'POST', body }),

  // Climat
  climateParameters: () => request('/api/climate/parameters'),
  climate: (body) => request('/api/climate/timeseries', { method: 'POST', body }),

  // Identifiants des services externes
  credentials: () => request('/api/credentials'),
  saveCredentials: (provider, body) => request(`/api/credentials/${provider}`, { method: 'POST', body }),
  testCredentials: (provider) => request(`/api/credentials/${provider}/test`, { method: 'POST' }),
  deleteCredentials: (provider) => request(`/api/credentials/${provider}`, { method: 'DELETE' }),

  // Agriculture
  agricultureCrops: () => request('/api/agriculture/crops'),
  agricultureZones: () => request('/api/agriculture/zones'),
  agricultureSeason: (body) => request('/api/agriculture/season', { method: 'POST', body }),
  agricultureSuitability: (body) => request('/api/agriculture/suitability', { method: 'POST', body }),

  // Foncier
  landCriteria: () => request('/api/land/criteria'),
  landReferences: () => request('/api/land/references'),
  landAnalyze: (body) => request('/api/land/analyze', { method: 'POST', body }),
  landCompare: (body) => request('/api/land/compare', { method: 'POST', body }),

  // Conversion et exports
  converterFormats: () => request('/api/converter/formats'),
  importDataset: (file, inputFormat) => upload('/api/converter/import', file, inputFormat),
  exportFormats: () => request('/api/exports/formats'),
  exportLayer: (format, data, filename) =>
    download('/api/exports/create', { format, data, filename }, `${filename}.${format}`),

  // Agent
  agentTools: () => request('/api/agent/tools'),
  agentChat: (body) => request('/api/agent/chat', { method: 'POST', body }),
};

export default api;
