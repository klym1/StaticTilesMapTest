var baseAddress = "https://map.klym.uk/";

var disableHashChange = false;
var map = L.map('map', 
  {
     zoomControl: false
  }
);
var tileUrl = baseAddress + "buildings/tiles/{z}/{x}/{y}.png";

L.control.zoom({
            position: "topright"
        }).addTo(map);

function highlightFeature(e) {
    var layer = e.target;
    layer.setStyle({
      stroke: true
    });
}

function resetHighlight(e) {
    var layer = e.target;
    layer.setStyle({
      stroke: false
    });
}

function onEachFeature(feature, layer) {
    layer.on({
      mouseover: highlightFeature,
      mouseout: resetHighlight,
      click: zoomToFeature
    });
}

function zoomToFeature(e) {
    map.fitBounds(e.target.getBounds());
}

 var geojsonLayer = new L.geoJson.ajax(baseAddress + "buildings/tiles/buildings.geojson", {
  onEachFeature:onEachFeature,
  style: {
         stroke: false,
         fillOpacity: 0,
         weight: 3,
         color: '#168'
      }
});

 var info = L.control();
 info.onAdd = function(map) {
            this._div = L.DomUtil.create('div', 'info');
            this.update();
            return this._div;
        };

var update = function(jsondata) {
  if(jsondata){
    document.getElementById('streetname').innerText = jsondata.street;
    document.getElementById('start_date').innerText = jsondata.year;    
    document.getElementById('description').innerText = jsondata.description;  
  } else{
    document.getElementById('streetname').innerText = '';
    document.getElementById('start_date').innerText = '';    
    document.getElementById('description').innerText = '';  
  }
};


info.update = update;

geojsonLayer.on('mouseover', function(e) {
    if (e.layer.feature.properties) {
        info.update(e.layer.feature.properties);
    } else {
        info.update();
    }
});  


geojsonLayer.on('mouseout', function(e) {
    update();
});

geojsonLayer.addTo(map);

var tileLayer = L.tileLayer(tileUrl, {
  attributionControl: false,
  minZoom: 15,
  maxZoom: 19
});

tileLayer.addTo(map);

map.setMaxBounds([
  [48.9913,24.814],
  [48.8778,24.6189]
]);

map.setView([48.9228, 24.7103], 16);

map.on('moveend', function(e) {
  var lat = roundLatLon(map.getCenter().lat);
  var lon = roundLatLon(map.getCenter().lng);
  var zoom = map.getZoom();

  disableHashChange = true;
  window.location.hash = [lat, lon, zoom].join(",");
});

map.on('click', function(e) {
  var lat = e.latlng.lat,
      lon = e.latlng.lng;
});

window.onhashchange = function() {
  if (!disableHashChange) {
    var hash = window.location.hash.split(",");;
    if (hash.length == 3) {
      var lat = parseFloat(hash[0].substring(1)), // Remove "#"
          lon = parseFloat(hash[1]),
          zoom = parseInt(hash[2]);

      map.setView([lat, lon], zoom);
    }
  }
  disableHashChange = false;
}

window.onhashchange();

function roundLatLon(l) {
  return Math.round(l * 10000) / 10000;
}

function formatNumber(x) {
  x = x.toString();
  var pattern = /(-?\d+)(\d{3})/;
  while (pattern.test(x))
    x = x.replace(pattern, "$1,$2");
  return x;
}

