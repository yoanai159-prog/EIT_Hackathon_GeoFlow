"""Web map for the platform: OpenStreetMap base (switchable), UTM zone 35N coordinates, scale bar, click popups,
a legend section for every layer that is switched on, and an optional radar overlay for the pilot reservoir.

The map is one self-contained Leaflet page shown with `st.components.v1.html`, so it needs no extra Python package
(Leaflet itself is loaded from a CDN in the browser, pinned to version 1.9.4).

Coordinate systems
  * OSM tiles are published in Web Mercator (EPSG:3857); a browser map cannot show them in another projection, so the
    map is drawn in 3857.
  * All coordinates the user sees are EPSG:32635 (UTM zone 35N): the live cursor readout, the last click, the optional
    UTM grid and the `UTM35N_E_m` / `UTM35N_N_m` attributes of point features in popups.
  * Vector data are stored in EPSG:32635 (EPSG:4326 also works). Other systems are read with geopandas if installed.

Adding your own layers: put the files in `data/vectors/` (see data/vectors/README.md).
"""
from __future__ import annotations

import json
from pathlib import Path

from core import geo, gpkg, styles

LEAFLET_VERSION = "1.9.4"
VECTOR_EXT = {".geojson", ".json", ".gpkg", ".shp"}
_KIND = {"Point": "point", "MultiPoint": "point", "LineString": "line", "MultiLineString": "line"}


# ---- building layers --------------------------------------------------------------------------------

def _kind(geojson: dict) -> str:
    for f in geojson.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type"):
            return _KIND.get(g["type"], "polygon")
    return "polygon"


def make_layer(title: str, geojson: dict, style: dict | None = None, visible: bool = True,
               source_epsg: int | None = None, popup_title: str | None = None,
               fade: tuple[float, float] | None = None, hide_fields=(),
               label_field: str | None = None, label_minzoom: int = 10, decimals: int = 6) -> dict:
    """One map layer from a GeoJSON dict (in `source_epsg`, default: guessed) and a style spec.

    label_field: attribute shown as a name on the map from zoom `label_minzoom` (features without it get no label).
    fade=(fill_factor, stroke_factor) makes the layer paler. hide_fields are attribute names left out of the popup.
    """
    if fade:
        style = styles.faded(style, *fade)
    gj = geo.add_utm_attributes(geo.round_coords(geo.geojson_to_wgs84(geojson, source_epsg), decimals))
    styles.apply_style(gj, style)
    table, index = [], {}
    for f in gj["features"]:                       # one entry per distinct symbol, features carry only its index
        st = f["properties"].pop("__style__")
        key = json.dumps(st, sort_keys=True)
        if key not in index:
            index[key] = len(table)
            table.append(st)
        f["properties"]["__s"] = index[key]
    kind = _kind(gj)
    return {"title": title, "geojson": gj, "styles": table, "visible": visible, "kind": kind,
            "legend": styles.legend(style, title, kind), "popup_title": popup_title, "hide": list(hide_fields),
            "label_field": label_field, "label_minzoom": label_minzoom,
            "bounds": geo.bounds(gj), "n_features": len(gj["features"])}


def feature_style(layer: dict, i: int) -> dict:
    """The resolved symbol style of feature number i of a layer made by make_layer."""
    return layer["styles"][layer["geojson"]["features"][i]["properties"]["__s"]]


def points_geojson(rows, lon="lon", lat="lat", props=None) -> dict:
    """GeoJSON points (lon/lat in WGS 84) from a pandas DataFrame; `props` = columns to keep as attributes."""
    cols = list(props) if props is not None else [c for c in rows.columns if c not in (lon, lat)]
    feats = []
    for _, r in rows.iterrows():
        p = {}
        for c in cols:
            v = r[c]
            p[c] = None if v != v else (v.item() if hasattr(v, "item") else v)  # NaN -> None, numpy -> python
        feats.append({"type": "Feature", "properties": p,
                      "geometry": {"type": "Point", "coordinates": [float(r[lon]), float(r[lat])]}})
    return {"type": "FeatureCollection", "features": feats}


def _read_style(path: Path) -> dict | None:
    sj, qml = path.with_suffix(".style.json"), path.with_suffix(".qml")
    if sj.exists():
        return json.loads(sj.read_text(encoding="utf-8"))
    if qml.exists():
        return styles.qml_to_style(qml.read_text(encoding="utf-8"))
    return None


def _read_vector_file(path: Path):
    """Return (geojson, source_epsg or None). GeoJSON and GeoPackage are read without extra packages."""
    suffix = path.suffix.lower()
    if suffix in (".geojson", ".json"):
        gj = json.loads(path.read_text(encoding="utf-8"))
        return gj, geo.guess_epsg(gj)
    if suffix == ".gpkg":
        gj = gpkg.read_gpkg(str(path))
        return gj, geo.guess_epsg(gj)
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - depends on the user's environment
        raise RuntimeError(f"{path.name}: reading .shp needs geopandas (pip install geopandas), "
                           "or export the layer from QGIS as GeoJSON in EPSG:32635") from exc
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(geo.EPSG_UTM35N)
    return json.loads(gdf.to_crs(geo.EPSG_WGS84).to_json()), geo.EPSG_WGS84


def load_vector_dir(directory: Path, fade: tuple[float, float] | None = None, visible: dict | None = None,
                    order: list[str] | None = None, titles: dict | None = None,
                    only: list[str] | None = None, labels: dict | None = None) -> tuple[list[dict], list[str]]:
    """Load every vector file in a folder as a map layer. Returns (layers, messages for the user).

    `visible` maps file stem -> bool (default False for every layer not listed), `order` lists stems bottom to top,
    `titles` maps stem -> display title, `only` limits the layers to these stems,
    `labels` maps stem -> (attribute with the name, minimum zoom for showing it).
    """
    layers, msgs = [], []
    if not directory.exists():
        return layers, msgs
    found = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in VECTOR_EXT or path.name.endswith(".style.json"):
            continue
        # a GeoJSON made from a GeoPackage of the same name wins (it is simplified for the browser)
        if path.stem in found and found[path.stem].suffix.lower() == ".geojson":
            continue
        found[path.stem] = path
    stems = [x for x in found if only is None or x in only]
    if order:
        stems = [x for x in order if x in stems] + [x for x in stems if x not in order]
    for stem in stems:
        path = found[stem]
        try:
            gj, epsg = _read_vector_file(path)
            style = _read_style(path)
            layers.append(make_layer((titles or {}).get(stem, stem), gj, style, visible=(visible or {}).get(stem, True),
                                     source_epsg=epsg, fade=fade,
                                     label_field=(labels or {}).get(stem, (None, 10))[0],
                                     label_minzoom=(labels or {}).get(stem, (None, 10))[1],
                                     decimals=5 if path.stat().st_size > 3_000_000 else 6))
            if style is None:
                msgs.append(f"{path.name}: no style file ({stem}.style.json or .qml), default style used")
        except Exception as exc:  # one bad file must not break the map
            msgs.append(f"{path.name}: skipped ({exc})")
    return layers, msgs


# ---- the page ---------------------------------------------------------------------------------------

_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@__LV__/dist/leaflet.css">
<style>
 html,body,#map{height:100%;margin:0} body{font:13px/1.35 "Segoe UI",system-ui,Arial,sans-serif;color:#0b2a4a}
 #map{background:#eaf0f5}
 .box{background:rgba(255,255,255,.94);padding:7px 10px;border-radius:8px;box-shadow:0 1px 6px rgba(11,42,74,.25)}
 .coords{font:12px/1.4 ui-monospace,Consolas,monospace;min-width:300px}
 .coords .h{font:600 11px "Segoe UI",system-ui;color:#5b6f82}
 .legend{max-height:52vh;overflow-y:auto;min-width:150px} .legend h5{margin:7px 0 3px;font-size:12px;color:#0b2a4a}
 .legend h5:first-child{margin-top:0} .legend h6{margin:5px 0 2px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#7b8c9c}
 .legend .row{display:flex;align-items:center;gap:7px;margin:2px 0;font-size:12px}
 .sw{width:16px;height:12px;border-radius:2px;border:1.5px solid #333;box-sizing:border-box;flex:none}
 .sw.point{width:12px;border-radius:50%} .sw.line{height:0;border-width:0 0 3px 0;border-radius:0;width:18px}
 .pop h4{margin:0 0 2px;font-size:14px} .pop .sub{color:#7b8c9c;font-size:11px;margin-bottom:4px}
 .pop table{border-collapse:collapse;font-size:12px} .pop td{padding:2px 6px;border-bottom:1px solid #e3e9ee;vertical-align:top}
 .pop td:first-child{color:#5b6f82;white-space:nowrap}
 .gridlbl{font:11px ui-monospace,Consolas,monospace;color:#7a1f5c;background:rgba(255,255,255,.75);padding:0 2px;white-space:nowrap}
 .pale-tiles{filter:grayscale(.85) contrast(.78) brightness(1.12);opacity:.62}
 .panelbtn{background:#fff;border:1px solid #b9c7d3;border-radius:6px;padding:4px 9px;font:600 12px 'Segoe UI',system-ui;color:#0b2a4a;cursor:pointer;box-shadow:0 1px 4px rgba(11,42,74,.25)}
 .panelbtn:hover{background:#eef5fa}
 .hdr{cursor:pointer;display:flex;justify-content:space-between;gap:10px;align-items:center}
 .hdr .tg{font-weight:700;color:#5b6f82}
 .leaflet-control-layers{border-radius:8px} .leaflet-control-layers-list{font-size:12px}
 #sweep{position:absolute;pointer-events:none;z-index:450;border-radius:50%;display:none}
 #sweep div{width:100%;height:100%;border-radius:50%;animation:spin 6s linear infinite;
   background:conic-gradient(from 0deg,rgba(245,158,11,.34) 0deg,rgba(245,158,11,0) 75deg,rgba(245,158,11,0) 360deg)}
 @keyframes spin{to{transform:rotate(360deg)}} @media (prefers-reduced-motion:reduce){#sweep div{animation:none}}
 .rnode{display:flex;flex-direction:column;align-items:center;transform:translate(-50%,-50%);width:120px}
 .leaflet-tooltip.lbl{background:none;border:none;box-shadow:none;padding:0;font:600 11px 'Segoe UI',system-ui;color:#0b2a4a;text-shadow:0 0 3px #fff,0 0 3px #fff,0 0 3px #fff;white-space:nowrap}
 .leaflet-tooltip.lbl:before{display:none}
 .rnode svg{filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))} .rnode b{font-size:12px;text-shadow:0 0 3px #fff,0 0 3px #fff;white-space:nowrap}
 .rnode i{font:normal 11px "Segoe UI";color:#334;text-shadow:0 0 3px #fff,0 0 3px #fff;white-space:nowrap}
</style></head><body><div id="map"></div><div id="sweep"><div></div></div>
<script src="https://unpkg.com/leaflet@__LV__/dist/leaflet.js"></script>
<script>
const CFG = __CFG__;

/* ---- UTM zone 35N (EPSG:32635), same formulas as core/geo.py ---- */
const A=6378137, F=1/298.257223563, K0=0.9996, E0=500000, LON0=27*Math.PI/180;
const N=F/(2-F), AA=A/(1+N)*(1+N*N/4+Math.pow(N,4)/64);
const AL=[N/2-2*N*N/3+5*Math.pow(N,3)/16, 13*N*N/48-3*Math.pow(N,3)/5, 61*Math.pow(N,3)/240];
const BE=[N/2-2*N*N/3+37*Math.pow(N,3)/96, N*N/48+Math.pow(N,3)/15, 17*Math.pow(N,3)/480];
const DE=[2*N-2*N*N/3-2*Math.pow(N,3), 7*N*N/3-8*Math.pow(N,3)/5, 56*Math.pow(N,3)/15];
function toUTM(lon,lat){
  const phi=lat*Math.PI/180, dl=lon*Math.PI/180-LON0, c=2*Math.sqrt(N)/(1+N);
  const t=Math.sinh(Math.atanh(Math.sin(phi))-c*Math.atanh(c*Math.sin(phi)));
  const xp=Math.atan2(t,Math.cos(dl)), ep=Math.atanh(Math.sin(dl)/Math.sqrt(1+t*t));
  let xi=xp, eta=ep;
  AL.forEach((a,i)=>{const j=i+1; xi+=a*Math.sin(2*j*xp)*Math.cosh(2*j*ep); eta+=a*Math.cos(2*j*xp)*Math.sinh(2*j*ep);});
  return [E0+K0*AA*eta, K0*AA*xi];
}
function fromUTM(e,n){
  const xi=n/(K0*AA), eta=(e-E0)/(K0*AA);
  let xp=xi, ep=eta;
  BE.forEach((b,i)=>{const j=i+1; xp-=b*Math.sin(2*j*xi)*Math.cosh(2*j*eta); ep-=b*Math.cos(2*j*xi)*Math.sinh(2*j*eta);});
  const chi=Math.asin(Math.sin(xp)/Math.cosh(ep));
  let phi=chi; DE.forEach((d,i)=>{phi+=d*Math.sin(2*(i+1)*chi);});
  return [(LON0+Math.atan2(Math.sinh(ep),Math.cos(xp)))*180/Math.PI, phi*180/Math.PI];
}

/* ---- map, base layers (OSM, pale OSM, none), scale ---- */
const map = L.map('map',{preferCanvas:true}).setView(CFG.center, CFG.zoom);
/* ONE shared canvas for all vector layers: stacked canvases would let only the top one receive clicks */
const REND=L.canvas({padding:0.5});
let panelsOn=true;
const ATTR='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
const TILES='https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const bases={'OpenStreetMap':L.tileLayer(TILES,{maxZoom:19,attribution:ATTR}),
             'OpenStreetMap, pale':L.tileLayer(TILES,{maxZoom:19,attribution:ATTR,className:'pale-tiles'}),
             'No base map':L.layerGroup()};
const baseKeys={osm:'OpenStreetMap',pale:'OpenStreetMap, pale',none:'No base map'};
bases[baseKeys[CFG.base]||'OpenStreetMap'].addTo(map);
L.control.scale({metric:true, imperial:false, maxWidth:160, position:'bottomleft'}).addTo(map);

/* ---- helpers ---- */
function el(tag, text, cls){const x=document.createElement(tag); if(text!==undefined) x.textContent=text; if(cls) x.className=cls; return x;}
function popupFor(props, layerTitle, titleField, hide){
  const box=el('div',undefined,'pop');
  const title=(titleField && props[titleField]) || props.name || props.NAME_2 || props.NAME || layerTitle;
  box.appendChild(el('h4', String(title))); box.appendChild(el('div', layerTitle, 'sub'));
  const tb=el('table');
  Object.keys(props).filter(k=>k.indexOf('__')!==0 && hide.indexOf(k)<0).forEach(k=>{
    const v=props[k]; if(v===null||v===undefined||v==='None') return;
    const tr=el('tr'); tr.appendChild(el('td',k)); tr.appendChild(el('td', typeof v==='number'?String(Math.round(v*1e4)/1e4):String(v))); tb.appendChild(tr);});
  box.appendChild(tb); return box;
}

/* ---- vector layers: one shared canvas (draw order = add order), popups on click, name labels ---- */
const overlays={}, groups=[], allBounds=[];
CFG.layers.forEach((lay,i)=>{
  const sty=f=>lay.styles[(f.properties||{}).__s]||{};
  const gl=L.geoJSON(lay.geojson, {renderer:REND,
    style:f=>{const s=sty(f); return {renderer:REND,color:s.stroke, opacity:s.stroke_opacity, weight:s.weight,
              fillColor:s.fill, fillOpacity:s.fill_opacity, dashArray:s.dash||null};},
    pointToLayer:(f,ll)=>{const s=sty(f);
      return L.circleMarker(ll,{renderer:REND,radius:s.radius||6,color:s.stroke,opacity:s.stroke_opacity,weight:s.weight,fillColor:s.fill,fillOpacity:s.fill_opacity});},
    onEachFeature:(f,l)=>l.bindPopup(()=>popupFor(f.properties||{}, lay.title, lay.popup_title, lay.hide||[]), {maxWidth:380, maxHeight:300})
  });
  if(lay.visible) gl.addTo(map);
  overlays[lay.title.replace(/&/g,'&amp;').replace(/</g,'&lt;')+' ('+lay.n_features+')']=gl; groups.push(gl);
  if(lay.bounds && lay.visible) allBounds.push(lay.bounds);
});
/* keep the draw order bottom to top after a layer is switched on again */
function restack(){groups.forEach(g=>{if(map.hasLayer(g)) g.eachLayer(l=>{if(l.bringToFront) l.bringToFront();});});}
/* name labels: shown from a minimum zoom, only for features that have a name */
function updateLabels(){
  const z=map.getZoom();
  CFG.layers.forEach((lay,i)=>{
    if(!lay.label_field) return;
    const show=map.hasLayer(groups[i]) && z>=(lay.label_minzoom||10);
    groups[i].eachLayer(l=>{
      const nm=(l.feature.properties||{})[lay.label_field]; if(!nm) return;
      if(show && !l._lblOn){l.bindTooltip(String(nm),{permanent:true,direction:'center',className:'lbl'}); l.openTooltip(); l._lblOn=true;}
      else if(!show && l._lblOn){l.unbindTooltip(); l._lblOn=false;}
    });
  });
}

/* ---- UTM 35N grid (optional overlay) ---- */
const grid=L.layerGroup();
function drawGrid(){
  grid.clearLayers(); if(!map.hasLayer(grid)) return;
  const b=map.getBounds(), cs=[[b.getWest(),b.getSouth()],[b.getEast(),b.getSouth()],[b.getWest(),b.getNorth()],[b.getEast(),b.getNorth()]].map(c=>toUTM(c[0],c[1]));
  const minE=Math.min(...cs.map(c=>c[0])), maxE=Math.max(...cs.map(c=>c[0])), minN=Math.min(...cs.map(c=>c[1])), maxN=Math.max(...cs.map(c=>c[1]));
  const steps=[500,1000,2000,5000,10000,20000,50000,100000,200000,500000];
  const step=steps.find(s=>(maxE-minE)/s<=8)||500000;
  const sty={color:'#7a1f5c',weight:1,opacity:.55,interactive:false};
  for(let e=Math.floor(minE/step)*step;e<=maxE+step;e+=step){
    const pts=[];for(let i=0;i<=10;i++){const n=minN-step+(maxN-minN+2*step)*i/10; const p=fromUTM(e,n); pts.push([p[1],p[0]]);}
    L.polyline(pts,sty).addTo(grid);
    const q=fromUTM(e,maxN-(maxN-minN)*0.03); L.marker([q[1],q[0]],{interactive:false,icon:L.divIcon({className:'',html:'<span class="gridlbl">E '+(e/1000)+' km</span>'})}).addTo(grid);
  }
  for(let n=Math.floor(minN/step)*step;n<=maxN+step;n+=step){
    const pts=[];for(let i=0;i<=10;i++){const e=minE-step+(maxE-minE+2*step)*i/10; const p=fromUTM(e,n); pts.push([p[1],p[0]]);}
    L.polyline(pts,sty).addTo(grid);
    const q=fromUTM(minE+(maxE-minE)*0.02,n); L.marker([q[1],q[0]],{interactive:false,icon:L.divIcon({className:'',html:'<span class="gridlbl">N '+(n/1000)+' km</span>'})}).addTo(grid);
  }
}
overlays['UTM 35N grid (EPSG:32635)']=grid;

/* ---- radar overlay: rings, sweep, links and risk markers around the pilot reservoir ---- */
const radarGroup=L.layerGroup(); let radarOn=false;
const LVL={ok:{c:'#1B7F4B',t:'Low'},warn:{c:'#C99700',t:'Attention'},high:{c:'#D9660F',t:'High'},crit:{c:'#B3261E',t:'Critical'}};
const SHAPE={ok:'<circle cx="12" cy="12" r="8.5"/>',warn:'<path d="M12 1.5L22.5 12L12 22.5L1.5 12Z"/>',high:'<path d="M12 2L23 21H1Z"/>',crit:'<rect x="3.5" y="3.5" width="17" height="17"/>'};
function buildRadar(){
  const R=CFG.radar; if(!R) return;
  const c=[R.center[0],R.center[1]];
  (R.rings_km||[]).forEach(k=>L.circle(c,{radius:k*1000,renderer:REND,color:'#0B3C5D',weight:1,opacity:.45,dashArray:'3 6',fill:false,interactive:false}).addTo(radarGroup));
  (R.rings_km||[]).forEach(k=>{const p=fromUTM(toUTM(c[1],c[0])[0],toUTM(c[1],c[0])[1]+k*1000);
    L.marker([p[1],p[0]],{interactive:false,icon:L.divIcon({className:'',html:'<span class="gridlbl">'+k+' km</span>'})}).addTo(radarGroup);});
  R.nodes.forEach(n=>{
    const lv=LVL[n.level]||LVL.ok;
    L.polyline([c,[n.lat,n.lon]],{renderer:REND,interactive:false,color:lv.c,weight:2+Math.min(1,n.share)*9,opacity:.75,dashArray:n.backup?'2 9':null,lineCap:'round'}).addTo(radarGroup);
    const html='<div class="rnode"><svg width="26" height="26" viewBox="0 0 24 24" fill="'+lv.c+'" stroke="#fff" stroke-width="2">'+SHAPE[n.level]+'</svg><b>'+n.name+'</b><i>'+lv.t+' · '+n.risk_pct+'%'+(n.backup?' · backup':'')+'</i></div>';
    const m=L.marker([n.lat,n.lon],{icon:L.divIcon({className:'',html:html,iconSize:[0,0]})});
    m.bindPopup(()=>{const b=el('div',undefined,'pop'); b.appendChild(el('h4',n.name)); b.appendChild(el('div',lv.t+' risk, '+n.risk_pct+'%','sub'));
      const tb=el('table'); (n.rows||[]).forEach(r=>{const tr=el('tr'); tr.appendChild(el('td',r[0])); tr.appendChild(el('td',String(r[1]))); tb.appendChild(tr);}); b.appendChild(tb); return b;});
    m.addTo(radarGroup);
  });
  const rm=L.marker(c,{icon:L.divIcon({className:'',iconSize:[0,0],html:'<div class="rnode" style="transform:translate(-50%,6px)"><b>'+R.name+'</b><i>'+R.caption+'</i></div>'})});
  rm.addTo(radarGroup);
  overlays['Radar: dependent settlements, '+R.scenario]=radarGroup;
}
function placeSweep(){
  const R=CFG.radar, sw=document.getElementById('sweep'); if(!R||!radarOn){sw.style.display='none';return;}
  const u=toUTM(R.center[1],R.center[0]), km=Math.max(...(R.rings_km||[10]))*1000, p=fromUTM(u[0],u[1]+km);
  const c0=map.latLngToContainerPoint(R.center), c1=map.latLngToContainerPoint([p[1],p[0]]), r=Math.abs(c1.y-c0.y);
  sw.style.cssText='display:block;left:'+(c0.x-r)+'px;top:'+(c0.y-r)+'px;width:'+(2*r)+'px;height:'+(2*r)+'px';
}
buildRadar();
if(CFG.radar && CFG.radar.visible){radarGroup.addTo(map); radarOn=true;}
map.on('overlayadd',e=>{if(e.layer===radarGroup){radarOn=true;} restack(); updateLabels(); placeSweep(); drawGrid(); refreshLegend();});
map.on('overlayremove',e=>{if(e.layer===radarGroup){radarOn=false;} updateLabels(); placeSweep(); drawGrid(); refreshLegend();});
map.on('zoomend',updateLabels);
map.on('move zoom resize viewreset moveend zoomend',()=>{placeSweep(); drawGrid();});
map.on('baselayerchange',e=>{document.getElementById('map').style.background=(e.name==='No base map')?'#eef3f7':'#eaf0f5';});
const layerCtl=L.control.layers(bases, overlays, {collapsed:false, position:'topright'}).addTo(map);

/* ---- legend: a section for every layer that is switched on ---- */
const lg=L.control({position:'bottomright'}), lgBox=el('div',undefined,'box legend'), lgBody=el('div');
lgBox.appendChild(lgBody);
lg.onAdd=()=>{L.DomEvent.disableClickPropagation(lgBox); L.DomEvent.disableScrollPropagation(lgBox); return lgBox;}; lg.addTo(map);
function swatch(r){const s=el('span',undefined,'sw '+(r.shape||'polygon')); if(r.shape==='line'){s.style.borderColor=r.stroke; if(r.dash) s.style.borderBottomStyle='dashed';}
  else {s.style.borderColor=r.stroke; s.style.background=r.fill; s.style.opacity=Math.max(r.fill_opacity,.4); if(r.dash) s.style.borderStyle='dashed';} return s;}
function refreshLegend(){
  lgBody.textContent=''; let n=0;
  CFG.layers.forEach((lay,i)=>{
    if(!map.hasLayer(groups[i]) || !lay.legend || !lay.legend.length) return;
    n++; const multi=lay.legend.length>1;
    if(multi) lgBody.appendChild(el('h5',lay.title));
    let last=null;
    lay.legend.forEach(r=>{ if(r.group && r.group!==last){lgBody.appendChild(el('h6',r.group)); last=r.group;}
      const row=el('div',undefined,'row'); row.appendChild(swatch(r)); row.appendChild(el('span', multi? r.label : lay.title)); lgBody.appendChild(row);});
  });
  if(radarOn && CFG.radar){n++; lgBody.appendChild(el('h5','Radar: risk level'));
    Object.keys(LVL).forEach(k=>{const row=el('div',undefined,'row'); const s=document.createElementNS('http://www.w3.org/2000/svg','svg');
      s.setAttribute('width','16');s.setAttribute('height','16');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('fill',LVL[k].c); s.innerHTML=SHAPE[k]; row.appendChild(s); row.appendChild(el('span',LVL[k].t)); lgBody.appendChild(row);});}
  lgBox.style.display=(n&&panelsOn)?'block':'none';
}
refreshLegend();

/* ---- coordinates: live cursor and last click, in UTM 35N ---- */
const cc=L.control({position:'bottomleft'}); let l1,l2;
let coordBox, coordBody;
cc.onAdd=()=>{const d=el('div',undefined,'box coords'); coordBody=el('div'); coordBody.appendChild(el('div','UTM 35N, EPSG:32635 (map tiles: Web Mercator)','h'));
  l1=el('div','Cursor: move over the map'); l2=el('div','Click: click on the map'); coordBody.appendChild(l1); coordBody.appendChild(l2); d.appendChild(coordBody);
  coordBox=d; L.DomEvent.disableClickPropagation(d); return d;};
cc.addTo(map);
const fmt=v=>Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g,' ');
function fmtLL(ll){const u=toUTM(ll.lng,ll.lat); return 'E '+fmt(u[0])+' m  N '+fmt(u[1])+' m   ('+ll.lat.toFixed(5)+', '+ll.lng.toFixed(5)+')';}
map.on('mousemove',e=>{l1.textContent='Cursor: '+fmtLL(e.latlng);});
map.on('click',e=>{l2.textContent='Click:  '+fmtLL(e.latlng);});

/* ---- hide / show the panels, so they never cover the map ---- */
function makeCollapsible(box, titleText, body){
  const h=el('div',undefined,'hdr'); h.appendChild(el('b',titleText)); const tg=el('span','−','tg'); h.appendChild(tg);
  box.insertBefore(h, box.firstChild); let open=true;
  h.onclick=()=>{open=!open; body.style.display=open?'':'none'; tg.textContent=open?'−':'+';};
}
makeCollapsible(lgBox,'Legend',lgBody);
makeCollapsible(coordBox,'Coordinates',coordBody);
const pb=L.control({position:'topleft'});
pb.onAdd=()=>{const b=el('button','Hide panels','panelbtn'); b.type='button'; L.DomEvent.disableClickPropagation(b);
  b.onclick=()=>{panelsOn=!panelsOn; b.textContent=panelsOn?'Hide panels':'Show panels';
    layerCtl.getContainer().style.display=panelsOn?'':'none'; coordBox.style.display=panelsOn?'':'none'; refreshLegend();};
  return b;};
pb.addTo(map);

/* ---- initial view ---- */
if(CFG.fit_bounds){map.fitBounds(CFG.fit_bounds,{padding:[20,20]});}
else if(allBounds.length && CFG.fit){
  const s=Math.min(...allBounds.map(b=>b[0][0])), w=Math.min(...allBounds.map(b=>b[0][1])),
        n=Math.max(...allBounds.map(b=>b[1][0])), e=Math.max(...allBounds.map(b=>b[1][1]));
  map.fitBounds([[s,w],[n,e]],{padding:[30,30],maxZoom:12});
}
placeSweep(); updateLabels();
</script></body></html>"""


def _py(o):
    """json fallback: numpy scalars -> python, anything else -> text."""
    return o.item() if hasattr(o, "item") else str(o)


def _json_for_script(obj) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(obj, ensure_ascii=False, default=_py, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--")


def map_html(layers: list[dict], center=(43.27, 26.93), zoom: int = 9, fit: bool = False, base: str = "osm",
             fit_bounds=None, radar: dict | None = None) -> str:
    """The complete HTML page of the map.

    base: "osm", "pale" or "none" (the choice can also be changed in the layer list on the map).
    fit_bounds: [[south, west], [north, east]] to start on; radar: see `radar_config`.
    """
    cfg = {"center": list(center), "zoom": zoom, "fit": fit, "base": base, "fit_bounds": fit_bounds,
           "layers": layers, "radar": radar}
    return _TEMPLATE.replace("__LV__", LEAFLET_VERSION).replace("__CFG__", _json_for_script(cfg))


def render(layers: list[dict], center=(43.27, 26.93), zoom: int = 9, height: int = 650, fit: bool = False,
           base: str = "osm", fit_bounds=None, radar: dict | None = None):
    """Show the map in Streamlit."""
    import streamlit.components.v1 as components

    components.html(map_html(layers, center, zoom, fit, base, fit_bounds, radar), height=height)
