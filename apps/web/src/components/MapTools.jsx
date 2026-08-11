import { useEffect, useRef, useState } from 'react';

/**
 * Outils de carte : sélection d'un point et dessin d'un rectangle.
 *
 * Plusieurs modules demandent « un point » ou « une zone » sans qu'aucun outil
 * ne permette de les désigner : l'utilisateur devait deviner que la plateforme
 * utilisait le centre ou l'emprise visible. Ces outils rendent l'action explicite.
 */
export default function MapTools({ map, onPoint, onArea, notify, request }) {
  const [mode, setMode] = useState(null); // null | 'point' | 'area'
  const start = useRef(null);
  const box = useRef(null);

  useEffect(() => {
    if (request?.mode) setMode(request.mode);
  }, [request]);

  useEffect(() => {
    if (!map) return;

    const canvas = map.getCanvas();
    canvas.style.cursor = mode ? 'crosshair' : '';

    // ── Mode point ────────────────────────────────────────────────
    function handleClick(e) {
      if (mode !== 'point') return;
      const { lng, lat } = e.lngLat;
      onPoint?.({ longitude: +lng.toFixed(6), latitude: +lat.toFixed(6) });
      notify?.(`Point sélectionné : ${lat.toFixed(4)}, ${lng.toFixed(4)}`, 'ok');
      setMode(null);
    }

    // ── Mode rectangle ────────────────────────────────────────────
    function down(e) {
      if (mode !== 'area') return;
      e.preventDefault();
      map.dragPan.disable();
      start.current = e.lngLat;

      box.current = document.createElement('div');
      box.current.className = 'draw-box';
      canvas.parentElement.appendChild(box.current);
      box.current.dataset.x = e.point.x;
      box.current.dataset.y = e.point.y;
    }

    function move(e) {
      if (!box.current || !start.current) return;
      const x0 = +box.current.dataset.x;
      const y0 = +box.current.dataset.y;
      const { x, y } = e.point;
      Object.assign(box.current.style, {
        left: `${Math.min(x0, x)}px`,
        top: `${Math.min(y0, y)}px`,
        width: `${Math.abs(x - x0)}px`,
        height: `${Math.abs(y - y0)}px`,
      });
    }

    function up(e) {
      if (!start.current) return;
      const a = start.current;
      const b = e.lngLat;
      cleanup();

      const bbox = [
        Math.min(a.lng, b.lng),
        Math.min(a.lat, b.lat),
        Math.max(a.lng, b.lng),
        Math.max(a.lat, b.lat),
      ].map((v) => +v.toFixed(6));

      if (bbox[2] - bbox[0] < 1e-4 || bbox[3] - bbox[1] < 1e-4) {
        notify?.('Zone trop petite — maintenez le clic et faites glisser', 'warn');
        return;
      }
      onArea?.(bbox);
      notify?.('Zone définie — elle sera utilisée par les modules', 'ok');
      setMode(null);
    }

    function cleanup() {
      if (box.current) {
        box.current.remove();
        box.current = null;
      }
      start.current = null;
      map.dragPan.enable();
    }

    function onKey(e) {
      if (e.key === 'Escape') {
        cleanup();
        setMode(null);
      }
    }

    map.on('click', handleClick);
    map.on('mousedown', down);
    map.on('mousemove', move);
    map.on('mouseup', up);
    window.addEventListener('keydown', onKey);

    return () => {
      map.off('click', handleClick);
      map.off('mousedown', down);
      map.off('mousemove', move);
      map.off('mouseup', up);
      window.removeEventListener('keydown', onKey);
      cleanup();
      canvas.style.cursor = '';
    };
  }, [map, mode, onPoint, onArea, notify]);

  if (!map) return null;

  return (
    <div className="map-tools">
      <button
        className={mode === 'point' ? 'map-tool active' : 'map-tool'}
        onClick={() => setMode(mode === 'point' ? null : 'point')}
        title="Cliquer sur la carte pour choisir un point (Foncier, Agriculture, Climat)"
      >
        <span className="tool-icon">📍</span>
        <span>Point</span>
      </button>
      <button
        className={mode === 'area' ? 'map-tool active' : 'map-tool'}
        onClick={() => setMode(mode === 'area' ? null : 'area')}
        title="Dessiner un rectangle pour délimiter la zone d'étude"
      >
        <span className="tool-icon">▭</span>
        <span>Zone</span>
      </button>
      {mode && (
        <div className="map-tool-hint">
          {mode === 'point'
            ? 'Cliquez sur la carte'
            : 'Maintenez le clic et faites glisser'}
          <small>Échap pour annuler</small>
        </div>
      )}
    </div>
  );
}
