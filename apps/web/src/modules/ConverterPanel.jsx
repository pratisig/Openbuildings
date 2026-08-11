import { useEffect, useMemo, useRef, useState } from 'react';
import api from '../lib/api';
import { layerBounds } from '../lib/layers';

function bboxFeatureCollection(bbox) {
  const [west, south, east, north] = bbox;
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { west, south, east, north, type: 'bounding_box' },
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
          ]],
        },
      },
    ],
  };
}

function baseName(filename = 'conversion') {
  return filename.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9À-ÿ_-]+/g, '_') || 'conversion';
}

export default function ConverterPanel({
  map,
  area,
  onAreaChange,
  onDrawArea,
  onLayer,
  notify,
}) {
  const [tab, setTab] = useState('convert');

  return (
    <div className="panel converter-panel">
      <div className="tabs">
        <button className={tab === 'convert' ? 'tab active' : 'tab'} onClick={() => setTab('convert')}>
          Convertir un fichier
        </button>
        <button className={tab === 'bbox' ? 'tab active' : 'tab'} onClick={() => setTab('bbox')}>
          Créer une BBox
        </button>
      </div>
      {tab === 'convert' ? (
        <FileConverter map={map} onLayer={onLayer} notify={notify} />
      ) : (
        <BboxBuilder
          map={map}
          area={area}
          onAreaChange={onAreaChange}
          onDrawArea={onDrawArea}
          onLayer={onLayer}
          notify={notify}
        />
      )}
    </div>
  );
}

function FileConverter({ map, onLayer, notify }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dataset, setDataset] = useState(null);
  const [filename, setFilename] = useState('conversion');
  const [inputFormats, setInputFormats] = useState([]);
  const [maxUploadBytes, setMaxUploadBytes] = useState(25 * 1024 * 1024);
  const [outputFormats, setOutputFormats] = useState([]);
  const [output, setOutput] = useState('geojson');

  useEffect(() => {
    Promise.all([api.converterFormats(), api.exportFormats()])
      .then(([inputs, outputs]) => {
        setInputFormats(inputs.formats);
        if (inputs.max_upload_bytes) setMaxUploadBytes(inputs.max_upload_bytes);
        setOutputFormats(outputs.formats.filter((format) => format.available));
      })
      .catch(() => {});
  }, []);

  async function importFile(file) {
    if (!file) return;
    setBusy(true);
    setDataset(null);
    try {
      const data = await api.importDataset(file);
      setDataset(data);
      setFilename(baseName(file.name));
      const layer = onLayer({
        name: baseName(file.name),
        data,
        source: `Fichier importé (${data.metadata.input_format.toUpperCase()})`,
      });
      const bounds = layerBounds(layer);
      if (bounds) map?.fitBounds(bounds, { padding: 60, maxZoom: 16 });
      notify(`${data.metadata.feature_count} entité(s) importée(s) et affichée(s)`, 'ok');
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  async function download() {
    if (!dataset) return;
    setBusy(true);
    try {
      await api.exportLayer(output, dataset, filename);
      notify(`Conversion ${output.toUpperCase()} téléchargée`, 'ok');
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  const accepted = inputFormats
    .filter((format) => format.available)
    .flatMap((format) => format.extensions)
    .join(',');

  return (
    <div className="form">
      <p className="hint">
        Déposez un fichier : il est converti en GeoJSON WGS 84, ajouté à la carte, puis peut être
        téléchargé dans un autre format.
      </p>

      <div
        className={`file-drop${dragging ? ' dragging' : ''}${busy ? ' busy' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          importFile(event.dataTransfer.files?.[0]);
        }}
        onClick={() => !busy && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => event.key === 'Enter' && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          className="file-input"
          type="file"
          accept={accepted}
          onChange={(event) => importFile(event.target.files?.[0])}
        />
        {busy ? <span className="spinner" /> : <span className="file-drop-icon">⇧</span>}
        <b>{busy ? 'Conversion en cours…' : 'Déposer ou choisir un fichier'}</b>
        <small>Limite : {Math.round(maxUploadBytes / (1024 * 1024))} Mo</small>
      </div>

      {inputFormats.length > 0 && (
        <div className="format-cloud" aria-label="Formats d'entrée pris en charge">
          {inputFormats.map((format) => (
            <span
              key={format.id}
              className={format.available ? 'format-pill' : 'format-pill unavailable'}
              title={format.available ? format.description : `${format.description} GeoPandas requis.`}
            >
              {format.label}
            </span>
          ))}
        </div>
      )}

      {dataset && (
        <>
          <div className="conversion-summary">
            <div className="conversion-summary-head">
              <div>
                <b>{dataset.metadata.source_filename}</b>
                <span>{dataset.metadata.input_format.toUpperCase()} → GeoJSON · EPSG:4326</span>
              </div>
              <span className="badge actif">Prêt</span>
            </div>
            <div className="stats">
              <div><span>Entités</span><b>{dataset.metadata.feature_count.toLocaleString('fr-FR')}</b></div>
              <div><span>Géométries</span><b>{dataset.metadata.geometry_types.join(', ') || 'Sans géométrie'}</b></div>
              <div><span>Attributs</span><b>{dataset.metadata.attributes.length}</b></div>
            </div>
            {dataset.metadata.warnings?.map((warning) => (
              <div className="notice-warning" key={warning}>{warning}</div>
            ))}
          </div>

          <hr />
          <h4 className="section-title">Télécharger la conversion</h4>
          <label>
            Nom du fichier
            <input type="text" value={filename} onChange={(event) => setFilename(event.target.value)} />
          </label>
          <label>
            Format de sortie
            <select value={output} onChange={(event) => setOutput(event.target.value)}>
              {outputFormats.map((format) => (
                <option key={format.id} value={format.id}>{format.label}</option>
              ))}
            </select>
          </label>
          <button className="primary" disabled={busy || !output} onClick={download}>
            Télécharger en {outputFormats.find((format) => format.id === output)?.label || output.toUpperCase()}
          </button>
        </>
      )}
    </div>
  );
}

function BboxBuilder({ map, area, onAreaChange, onDrawArea, onLayer, notify }) {
  const [values, setValues] = useState(['', '', '', '']);
  const [outputFormats, setOutputFormats] = useState([]);
  const [output, setOutput] = useState('geojson');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setValues(area ? area.map((value) => String(value)) : ['', '', '', '']);
  }, [area]);

  useEffect(() => {
    api.exportFormats()
      .then((data) => setOutputFormats(data.formats.filter((format) => format.available)))
      .catch(() => {});
  }, []);

  const representations = useMemo(() => {
    if (!area) return [];
    const [west, south, east, north] = area;
    return [
      ['BBox (W,S,E,N)', area.join(', ')],
      ['Tableau JSON', JSON.stringify(area)],
      ['Overpass (S,W,N,E)', `(${south},${west},${north},${east})`],
      ['WKT', `POLYGON ((${west} ${south}, ${east} ${south}, ${east} ${north}, ${west} ${north}, ${west} ${south}))`],
    ];
  }, [area]);

  const dimensions = useMemo(() => {
    if (!area) return null;
    const [west, south, east, north] = area;
    const middleLatitude = (south + north) / 2;
    const width = Math.abs(east - west) * 111.32 * Math.cos((middleLatitude * Math.PI) / 180);
    const height = Math.abs(north - south) * 110.57;
    return { width, height, area: width * height };
  }, [area]);

  function applyValues() {
    const parsed = values.map(Number);
    if (parsed.some((value) => !Number.isFinite(value))) {
      notify('Les quatre coordonnées doivent être numériques', 'warn');
      return;
    }
    const [west, south, east, north] = parsed;
    if (west >= east || south >= north || west < -180 || east > 180 || south < -90 || north > 90) {
      notify('BBox invalide : vérifiez l’ordre Ouest, Sud, Est, Nord', 'warn');
      return;
    }
    onAreaChange(parsed.map((value) => +value.toFixed(6)));
    map?.fitBounds([[west, south], [east, north]], { padding: 60 });
    notify('BBox mise à jour', 'ok');
  }

  async function copy(value) {
    try {
      await navigator.clipboard.writeText(value);
      notify('Coordonnées copiées', 'ok');
    } catch {
      notify('Copie impossible dans ce navigateur', 'warn');
    }
  }

  function addToMap() {
    if (!area) return;
    const layer = onLayer({
      name: 'BBox personnalisée',
      data: bboxFeatureCollection(area),
      source: 'Générateur de BBox',
      color: '#fbbf24',
    });
    const bounds = layerBounds(layer);
    if (bounds) map?.fitBounds(bounds, { padding: 60 });
    notify('BBox ajoutée comme couche', 'ok');
  }

  async function download() {
    if (!area) return;
    setBusy(true);
    try {
      await api.exportLayer(output, bboxFeatureCollection(area), 'bbox_pratisig');
      notify(`BBox téléchargée en ${output.toUpperCase()}`, 'ok');
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <p className="hint">
        Dessinez un rectangle sur la carte ou saisissez ses coordonnées. La BBox reste visible et
        peut être copiée, ajoutée comme couche ou téléchargée.
      </p>
      <button className="primary" onClick={onDrawArea}>▭ Dessiner une BBox sur la carte</button>

      <div className="bbox-grid">
        {['Ouest (min X)', 'Sud (min Y)', 'Est (max X)', 'Nord (max Y)'].map((label, index) => (
          <label key={label}>
            {label}
            <input
              type="number"
              step="0.000001"
              value={values[index]}
              placeholder={index % 2 === 0 ? '-17.440000' : '14.690000'}
              onChange={(event) => setValues((current) => current.map((value, i) => (
                i === index ? event.target.value : value
              )))}
            />
          </label>
        ))}
      </div>
      <button disabled={values.some((value) => value === '')} onClick={applyValues}>Appliquer les coordonnées</button>

      {!area ? (
        <div className="notice-info">
          <b>Aucune BBox définie</b>
          <p>Cliquez sur « Dessiner », puis maintenez le clic et faites glisser sur la carte.</p>
        </div>
      ) : (
        <>
          {dimensions && (
            <div className="stats">
              <div><span>Largeur approx.</span><b>{dimensions.width.toFixed(2)} km</b></div>
              <div><span>Hauteur approx.</span><b>{dimensions.height.toFixed(2)} km</b></div>
              <div><span>Surface approx.</span><b>{dimensions.area.toFixed(2)} km²</b></div>
            </div>
          )}

          <h4 className="section-title">Coordonnées prêtes à l’emploi</h4>
          <div className="bbox-representations">
            {representations.map(([label, value]) => (
              <div className="bbox-output" key={label}>
                <span>{label}</span>
                <code>{value}</code>
                <button className="icon" onClick={() => copy(value)} title={`Copier ${label}`}>⧉</button>
              </div>
            ))}
          </div>

          <div className="row">
            <button onClick={addToMap}>Ajouter comme couche</button>
            <select value={output} onChange={(event) => setOutput(event.target.value)} aria-label="Format BBox">
              {outputFormats.map((format) => (
                <option key={format.id} value={format.id}>{format.label}</option>
              ))}
            </select>
          </div>
          <button className="primary" disabled={busy || !output} onClick={download}>
            {busy ? 'Préparation…' : 'Télécharger la BBox'}
          </button>
        </>
      )}
    </div>
  );
}
