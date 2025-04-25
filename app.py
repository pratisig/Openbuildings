// ------------------ CHARGEMENT DES BÂTIMENTS ------------------
var buildings = ee.FeatureCollection('GOOGLE/Research/open-buildings/v3/polygons');

var zoneDInteret;
var batimentsZone, precision_065_070, precision_070_075, precision_075_plus;

// ------------------ INTERFACE ------------------
var panel = ui.Panel({style: {width: '350px'}});
ui.root.insert(0, panel);

panel.add(ui.Label('🧱 Application de visualisation des bâtiments', {
  fontWeight: 'bold',
  fontSize: '18px'
}));
panel.add(ui.Label('📐 Dessinez une zone d’intérêt (rectangle ou polygone) sur la carte.'));

var messageLabel = ui.Label('', {color: 'red'});
panel.add(messageLabel);

function afficherMessage(msg, color) {
  messageLabel.setValue(msg);
  messageLabel.style().set('color', color || 'red');
}

// Activer l’outil de dessin
var drawingTools = Map.drawingTools();
drawingTools.setShown(true);
drawingTools.setDrawModes(['polygon', 'rectangle']);
function resetDrawing() {
  drawingTools.layers().forEach(function(layer) {
    drawingTools.layers().remove(layer);
  });
  drawingTools.setShape(null);
}
resetDrawing();

// --------- Bouton d’application du dessin ---------
var drawButton = ui.Button({
  label: '✅ Appliquer la zone dessinée',
  onClick: function() {
    if (drawingTools.layers().length() === 0) {
      afficherMessage('❗ Veuillez dessiner une zone d’intérêt.', 'red');
      return;
    }

    var geom = drawingTools.layers().get(0).getEeObject();
    zoneDInteret = ee.FeatureCollection(ee.Feature(geom));
    afficherMessage('✅ Zone d’intérêt appliquée.', 'green');
    actualiserAnalyse();
  }
});
panel.add(drawButton);

// --------- Export : Choix de la collection ---------
panel.add(ui.Label('📦 Choisir la collection à exporter :'));
var collectionSelector = ui.Select({
  items: [
    'Tous les bâtiments',
    'Bâtiments de la zone',
    'Précision >= 0.65 & < 0.7',
    'Précision >= 0.7 & < 0.75',
    'Précision >= 0.75'
  ],
  placeholder: 'Choisir...'
});
panel.add(collectionSelector);

// --------- Export : Choix du format ---------
panel.add(ui.Label('🗂️ Format d’exportation :'));
var formatSelector = ui.Select({
  items: ['SHP', 'CSV', 'GeoJSON'],
  placeholder: 'Choisir...'
});
panel.add(formatSelector);

// --------- Export : Nom du dossier Drive ---------
panel.add(ui.Label('📁 Nom du dossier Drive :'));
var folderInput = ui.Textbox({placeholder: 'ex: GEE_exports'});
panel.add(folderInput);

// --------- Export : Bouton ---------
var exportButton = ui.Button({
  label: '📤 Exporter la collection',
  onClick: function() {
    if (!zoneDInteret) {
      afficherMessage('❗ Dessinez une zone d’intérêt avant d’exporter.', 'red');
      return;
    }

    var choix = collectionSelector.getValue();
    var format = formatSelector.getValue();
    var folder = folderInput.getValue() || 'GEE_exports';

    if (!choix || !format) {
      afficherMessage('❗ Veuillez choisir une collection et un format.', 'red');
      return;
    }

    var toExport;
    if (choix === 'Tous les bâtiments') toExport = buildings;
    else if (choix === 'Bâtiments de la zone') toExport = batimentsZone;
    else if (choix === 'Précision >= 0.65 & < 0.7') toExport = precision_065_070;
    else if (choix === 'Précision >= 0.7 & < 0.75') toExport = precision_070_075;
    else if (choix === 'Précision >= 0.75') toExport = precision_075_plus;

    var clean = toExport.map(function(f) {
      return f.select(f.propertyNames().remove('longitude_latitude'));
    });

    Export.table.toDrive({
      collection: clean,
      description: 'export_selection',
      fileFormat: format,
      folder: folder,
      fileNamePrefix: 'export_selection'
    });

    afficherMessage('✅ Export prêt. Cliquez sur "Tasks" en haut à droite, puis sur "Run".', 'green');
  }
});
panel.add(exportButton);

// --------- Sauvegarder la zone dans les Assets ---------
panel.add(ui.Label('💾 Enregistrer la zone d’intérêt dans vos Assets :'));
var assetNameInput = ui.Textbox({placeholder: 'ex: users/votre_nom/zone_ikongo'});
panel.add(assetNameInput);

var saveAssetButton = ui.Button({
  label: '💽 Sauvegarder la zone',
  onClick: function() {
    var assetName = assetNameInput.getValue();
    if (!assetName || !zoneDInteret) {
      afficherMessage('❗ Dessinez une zone et entrez un nom valide pour l’asset.', 'red');
      return;
    }

    Export.table.toAsset({
      collection: zoneDInteret,
      description: 'export_zone_interet',
      assetId: assetName
    });

    afficherMessage('✅ Export vers les Assets lancé. Cliquez sur "Tasks" > "Run".', 'green');
  }
});
panel.add(saveAssetButton);

// --------- Visualisation initiale des bâtiments ---------
function actualiserAnalyse() {
  Map.clear();

  batimentsZone = buildings.filterBounds(zoneDInteret);
  precision_065_070 = batimentsZone.filter('confidence >= 0.65 && confidence < 0.7');
  precision_070_075 = batimentsZone.filter('confidence >= 0.7 && confidence < 0.75');
  precision_075_plus = batimentsZone.filter('confidence >= 0.75');

  Map.addLayer(zoneDInteret, {color: 'blue'}, 'Zone d’intérêt');
  Map.addLayer(precision_065_070, {color: 'FF0000'}, 'Précision [0.65–0.7)');
  Map.addLayer(precision_070_075, {color: 'FFFF00'}, 'Précision [0.7–0.75)');
  Map.addLayer(precision_075_plus, {color: '00FF00'}, 'Précision ≥ 0.75');
  Map.centerObject(zoneDInteret, 10);
}

// --------- Carte initiale ---------
Map.setOptions('SATELLITE');
Map.addLayer(buildings.limit(1000), {color: '0000FF'}, 'Bâtiments globaux (extrait)');
Map.setCenter(30, 0, 3);
