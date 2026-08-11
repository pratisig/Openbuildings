import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

/** Fonds de carte sans clé API (l'ancien front dépendait d'un jeton Mapbox). */
export const BASEMAPS = {
  sombre: {
    label: 'Sombre',
    style: {
      version: 8,
      sources: {
        base: {
          type: 'raster',
          tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
          tileSize: 256,
          attribution: '© OpenStreetMap, © CARTO',
        },
      },
      layers: [{ id: 'base', type: 'raster', source: 'base' }],
    },
  },
  clair: {
    label: 'Clair',
    style: {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '© OpenStreetMap, © CARTO',
        },
      },
      layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
    },
  },
  rue: {
    label: 'Rue',
    style: {
      version: 8,
      sources: {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          attribution: '© OpenStreetMap',
        },
      },
      layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
    },
  },
  satellite: {
    label: 'Satellite',
    style: {
      version: 8,
      sources: {
        esri: {
          type: 'raster',
          tiles: [
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          ],
          tileSize: 256,
          attribution: '© Esri',
        },
      },
      layers: [{ id: 'esri', type: 'raster', source: 'esri' }],
    },
  },
};

export default function MapView({
  layers,
  rasterTiles,
  selectedArea,
  basemap,
  onMapReady,
  onFeatureClick,
  onMoveEnd,
}) {
  const container = useRef(null);
  const map = useRef(null);
  const drawn = useRef(new Set());

  // Initialisation
  useEffect(() => {
    if (map.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      style: BASEMAPS[basemap]?.style || BASEMAPS.sombre.style,
      center: [-14.5, 14.5], // Sénégal
      zoom: 6,
      attributionControl: { compact: true },
    });
    map.current.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.current.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }));
    map.current.addControl(
      new maplibregl.GeolocateControl({ trackUserLocation: false }),
      'top-right',
    );
    map.current.on('load', () => onMapReady?.(map.current));
    map.current.on('moveend', () => onMoveEnd?.(map.current));
    return () => {
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Changement de fond de carte : les couches sont redessinées ensuite
  useEffect(() => {
    if (!map.current) return;
    const style = BASEMAPS[basemap]?.style;
    if (!style) return;
    drawn.current.clear();
    map.current.setStyle(style);
    map.current.once('styledata', () => renderLayers());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap]);

  // Rendu des couches vectorielles
  function renderLayers() {
    const m = map.current;
    if (!m || !m.isStyleLoaded()) return;

    const wanted = new Set(layers.map((l) => l.id));
    // Retire les couches supprimées
    drawn.current.forEach((id) => {
      if (!wanted.has(id)) {
        ['-fill', '-line', '-circle', '-outline'].forEach((suffix) => {
          if (m.getLayer(id + suffix)) m.removeLayer(id + suffix);
        });
        if (m.getSource(id)) m.removeSource(id);
        drawn.current.delete(id);
      }
    });

    layers.forEach((layer) => {
      const { id, data, color, visible, opacity } = layer;
      const visibility = visible ? 'visible' : 'none';

      if (!m.getSource(id)) {
        m.addSource(id, { type: 'geojson', data });

        m.addLayer({
          id: `${id}-fill`,
          type: 'fill',
          source: id,
          filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
          paint: { 'fill-color': color, 'fill-opacity': opacity * 0.5 },
        });
        m.addLayer({
          id: `${id}-outline`,
          type: 'line',
          source: id,
          filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
          paint: { 'line-color': color, 'line-width': 1.5, 'line-opacity': opacity },
        });
        m.addLayer({
          id: `${id}-line`,
          type: 'line',
          source: id,
          filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]],
          paint: { 'line-color': color, 'line-width': 2, 'line-opacity': opacity },
        });
        m.addLayer({
          id: `${id}-circle`,
          type: 'circle',
          source: id,
          filter: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]],
          paint: {
            'circle-color': color,
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3, 16, 8],
            'circle-opacity': opacity,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#ffffff',
          },
        });

        ['-fill', '-line', '-circle'].forEach((suffix) => {
          m.on('click', id + suffix, (e) => {
            if (e.features?.[0]) onFeatureClick?.(e.features[0], layer);
          });
          m.on('mouseenter', id + suffix, () => {
            m.getCanvas().style.cursor = 'pointer';
          });
          m.on('mouseleave', id + suffix, () => {
            m.getCanvas().style.cursor = '';
          });
        });

        drawn.current.add(id);
      } else {
        m.getSource(id).setData(data);
      }

      ['-fill', '-outline', '-line', '-circle'].forEach((suffix) => {
        if (m.getLayer(id + suffix)) m.setLayoutProperty(id + suffix, 'visibility', visibility);
      });
      if (m.getLayer(`${id}-fill`)) {
        m.setPaintProperty(`${id}-fill`, 'fill-color', color);
        m.setPaintProperty(`${id}-fill`, 'fill-opacity', opacity * 0.5);
      }
      if (m.getLayer(`${id}-outline`)) m.setPaintProperty(`${id}-outline`, 'line-color', color);
      if (m.getLayer(`${id}-line`)) {
        m.setPaintProperty(`${id}-line`, 'line-color', color);
        m.setPaintProperty(`${id}-line`, 'line-opacity', opacity);
      }
      if (m.getLayer(`${id}-circle`)) {
        m.setPaintProperty(`${id}-circle`, 'circle-color', color);
        m.setPaintProperty(`${id}-circle`, 'circle-opacity', opacity);
      }
    });
  }

  useEffect(() => {
    if (!map.current) return;
    if (map.current.isStyleLoaded()) renderLayers();
    else map.current.once('idle', renderLayers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers]);

  // BBox active : elle reste visible après le dessin et les changements de fond.
  useEffect(() => {
    const m = map.current;
    if (!m) return undefined;
    const sourceId = 'pratisig-selected-area';
    const fillId = `${sourceId}-fill`;
    const lineId = `${sourceId}-line`;

    function removeSelection() {
      if (m.getLayer(fillId)) m.removeLayer(fillId);
      if (m.getLayer(lineId)) m.removeLayer(lineId);
      if (m.getSource(sourceId)) m.removeSource(sourceId);
    }

    function renderSelection() {
      if (!m.isStyleLoaded()) return;
      if (!selectedArea) {
        removeSelection();
        return;
      }
      const [west, south, east, north] = selectedArea;
      const data = {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
          ]],
        },
      };
      if (m.getSource(sourceId)) {
        m.getSource(sourceId).setData(data);
        return;
      }
      m.addSource(sourceId, { type: 'geojson', data });
      m.addLayer({
        id: fillId,
        type: 'fill',
        source: sourceId,
        paint: { 'fill-color': '#14b8a6', 'fill-opacity': 0.12 },
      });
      m.addLayer({
        id: lineId,
        type: 'line',
        source: sourceId,
        paint: { 'line-color': '#2dd4bf', 'line-width': 2, 'line-dasharray': [2, 1.5] },
      });
    }

    if (m.isStyleLoaded()) renderSelection();
    else m.once('styledata', renderSelection);
    return () => m.off('styledata', renderSelection);
  }, [selectedArea, basemap]);

  // Tuiles raster (imagerie satellite Earth Engine)
  useEffect(() => {
    const m = map.current;
    if (!m || !m.isStyleLoaded()) return;
    const active = new Set(rasterTiles.map((t) => t.id));

    rasterTiles.forEach((tile) => {
      if (!m.getSource(tile.id)) {
        m.addSource(tile.id, { type: 'raster', tiles: [tile.url], tileSize: 256 });
        const firstVector = m.getStyle().layers.find((l) => l.id.startsWith('layer-'));
        m.addLayer(
          { id: tile.id, type: 'raster', source: tile.id, paint: { 'raster-opacity': tile.opacity ?? 0.85 } },
          firstVector?.id,
        );
      } else {
        m.setPaintProperty(tile.id, 'raster-opacity', tile.opacity ?? 0.85);
        m.setLayoutProperty(tile.id, 'visibility', tile.visible === false ? 'none' : 'visible');
      }
    });

    m.getStyle()
      .layers.filter((l) => l.id.startsWith('raster-') && !active.has(l.id))
      .forEach((l) => {
        if (m.getLayer(l.id)) m.removeLayer(l.id);
        if (m.getSource(l.id)) m.removeSource(l.id);
      });
  }, [rasterTiles]);

  return <div ref={container} className="map-container" />;
}
