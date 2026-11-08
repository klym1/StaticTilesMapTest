// MapLibre zoom levels use 512px tiles, so they are one less than the old
// Leaflet zoom for the same scale. The URL hash keeps the old (Leaflet) zoom
// numbers so links shared before the switch still open the same view.
var ZOOM_OFFSET = 1;

var map = new maplibregl.Map({
  container: 'map',
  style: '/buildings/map-style.json',
  center: [24.7103, 48.9228],
  zoom: 16 - ZOOM_OFFSET,
  minZoom: 15 - ZOOM_OFFSET,
  maxZoom: 19 - ZOOM_OFFSET,
  maxBounds: [[24.6189, 48.8778], [24.814, 48.9913]],
  attributionControl: false,
  dragRotate: false,
  pitchWithRotate: false,
  touchPitch: false
});
map.touchZoomRotate.disableRotation();

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

// ---- Info panel ----

function update(props) {
  document.getElementById('streetname').innerText = props ? props.street || '' : '';
  document.getElementById('start_date').innerText = props ? props.date || props.year || '' : '';
  document.getElementById('description').innerText = props ? props.description || '' : '';
}

// ---- Hover / click on historic buildings ----

var hoveredId = null;

function setHovered(id) {
  if (hoveredId !== null) {
    map.setFeatureState({ source: 'historic', id: hoveredId }, { hover: false });
  }
  hoveredId = id;
  if (id !== null) {
    map.setFeatureState({ source: 'historic', id: id }, { hover: true });
  }
}

map.on('mousemove', 'historic-buildings', function(e) {
  var feature = e.features[0];
  map.getCanvas().style.cursor = 'pointer';
  if (feature.id !== hoveredId) {
    setHovered(feature.id);
    update(feature.properties);
  }
});

map.on('mouseleave', 'historic-buildings', function() {
  map.getCanvas().style.cursor = '';
  setHovered(null);
  update();
});

map.on('click', 'historic-buildings', function(e) {
  var feature = e.features[0];
  update(feature.properties);
  map.fitBounds(geometryBounds(feature.geometry), { padding: 40, maxZoom: map.getMaxZoom() });
});

function geometryBounds(geometry) {
  var bounds = new maplibregl.LngLatBounds();
  (function walk(coords) {
    if (typeof coords[0] === 'number') {
      bounds.extend(coords);
    } else {
      coords.forEach(walk);
    }
  })(geometry.coordinates);
  return bounds;
}

// ---- URL hash: #lat,lon,zoom ----

var disableHashChange = false;

map.on('moveend', function() {
  var center = map.getCenter();
  var zoom = Math.round((map.getZoom() + ZOOM_OFFSET) * 100) / 100;
  var hash = '#' + [roundLatLon(center.lat), roundLatLon(center.lng), zoom].join(',');
  if (hash !== window.location.hash) {
    disableHashChange = true;
    window.location.hash = hash;
  }
});

window.onhashchange = function() {
  if (!disableHashChange) {
    var hash = window.location.hash.substring(1).split(',');
    if (hash.length == 3) {
      var lat = parseFloat(hash[0]),
          lon = parseFloat(hash[1]),
          zoom = parseFloat(hash[2]);
      if (!isNaN(lat) && !isNaN(lon) && !isNaN(zoom)) {
        map.jumpTo({ center: [lon, lat], zoom: zoom - ZOOM_OFFSET });
      }
    }
  }
  disableHashChange = false;
};

window.onhashchange();

function roundLatLon(l) {
  return Math.round(l * 10000) / 10000;
}
