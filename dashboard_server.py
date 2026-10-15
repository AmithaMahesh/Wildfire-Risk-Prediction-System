from flask import Flask, jsonify, Response
import json, os, glob, time
from datetime import datetime

app = Flask(__name__)

ALERTS_DIR = os.path.expanduser("~/bda-scala/output/alerts")
ACTIVE_WINDOW_SECONDS = 180   # a station is "on alert" if it had an alert in the last 3 minutes

STATIONS = {
    "ST001": {"name": "Los Angeles",   "lat": 34.05, "lon": -118.24},
    "ST002": {"name": "San Francisco", "lat": 37.77, "lon": -122.42},
    "ST003": {"name": "Las Vegas",     "lat": 36.16, "lon": -115.15},
}

# Hardcoded from your actual training run — update if you retrain
MODEL_STATS = {
    "f1": 0.9975,
    "precision": 0.9977,
    "recall": 0.9974,
    "trained_on": "22.1GB NOAA ISD weather data (2020-2023)",
    "data_volume": "22.1 GB",
}


def read_recent_alerts(max_files=30):
    alerts = []
    if not os.path.isdir(ALERTS_DIR):
        return alerts
    files = sorted(glob.glob(os.path.join(ALERTS_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    for f in files[:max_files]:
        try:
            age = time.time() - os.path.getmtime(f)
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    a = json.loads(line)
                    a["_age"] = age
                    a["station_name"] = STATIONS.get(a.get("station_id"), {}).get("name", a.get("station_id"))
                    alerts.append(a)
        except Exception:
            continue
    alerts.sort(key=lambda a: a["_age"])          # newest first
    seen, unique = set(), []
    for a in alerts:                               # one row per social post
        key = a.get("post_id") or id(a)
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    return unique


def build_stations(alerts):
    result = []
    for sid, info in STATIONS.items():
        mine = [a for a in alerts if a.get("station_id") == sid]
        recent = [a for a in mine if a["_age"] <= ACTIVE_WINDOW_SECONDS]
        result.append({
            "id": sid,
            "name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "status": "alert" if recent else "safe",
            "recent_count": len(recent),
            "latest": mine[0] if mine else None,
        })
    return result


@app.route("/api/alerts")
def api_alerts():
    alerts = read_recent_alerts()
    stations = build_stations(alerts)
    at_risk = [s for s in stations if s["status"] == "alert"]
    return jsonify({
        "active_alert": len(at_risk) > 0,
        "stations_at_risk": len(at_risk),
        "total_stations": len(STATIONS),
        "recent_alert_count": sum(s["recent_count"] for s in stations),
        "alerts": alerts[:15],
        "stations": stations,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/model")
def api_model():
    return jsonify(MODEL_STATS)


@app.route("/")
def index():
    return Response(DASHBOARD_HTML, mimetype="text/html")


DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wildfire Early-Warning System</title>
<link rel="stylesheet" href="/static/leaflet.css">
<style>
  :root{
    --bg:#14100F; --panel:#1E1715; --panel2:#251D1A; --border:#33282A;
    --text:#F5F1EC; --muted:#A09389; --ember:#E8590C; --amber:#F2A65A; --green:#3DA66A;
  }
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--text);font-family:"Segoe UI",Calibri,Arial,sans-serif;}
  .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 40px;}

  .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px;flex-wrap:wrap;gap:12px;}
  .brand{display:flex;align-items:center;gap:14px;}
  .logo{width:46px;height:46px;border-radius:12px;background:linear-gradient(135deg,var(--ember),var(--amber));
        display:flex;align-items:center;justify-content:center;font-size:24px;}
  h1{margin:0;font-size:22px;font-weight:700;letter-spacing:.2px;}
  .tagline{color:var(--muted);font-size:13px;margin-top:2px;}
  .live{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12.5px;
        background:var(--panel);border:1px solid var(--border);padding:7px 14px;border-radius:999px;}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:blink 1.6s infinite;}
  @keyframes blink{0%,100%{opacity:1;}50%{opacity:.25;}}

  .banner{display:flex;align-items:center;gap:16px;padding:18px 22px;border-radius:14px;margin-bottom:18px;border:1px solid;}
  .banner.safe{background:#14241B;border-color:#245238;}
  .banner.alert{background:#33190E;border-color:var(--ember);animation:glow 1.8s infinite;}
  @keyframes glow{0%,100%{box-shadow:0 0 0 0 rgba(232,89,12,.45);}50%{box-shadow:0 0 0 10px rgba(232,89,12,0);}}
  .banner .ico{font-size:34px;}
  .banner .t{font-size:19px;font-weight:700;}
  .banner .s{font-size:13px;color:var(--muted);margin-top:3px;}

  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px;}
  .kpi{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px 18px;}
  .kpi .lbl{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;}
  .kpi .val{font-size:28px;font-weight:700;margin-top:6px;color:var(--amber);}
  .kpi .sub{font-size:12px;color:var(--muted);margin-top:2px;}

  .main{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:18px;}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:hidden;}
  .card-head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);}
  .card-head h3{margin:0;font-size:14.5px;font-weight:600;}
  .legend{display:flex;gap:14px;font-size:12px;color:var(--muted);}
  .legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;}
  #map{height:440px;background:#0f0c0b;}

  .stations{padding:12px;display:flex;flex-direction:column;gap:10px;}
  .st{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:13px 14px;}
  .st.alert{border-color:var(--ember);background:#2E1A12;}
  .st-top{display:flex;justify-content:space-between;align-items:center;}
  .st-name{font-weight:600;font-size:14.5px;}
  .st-id{font-size:11.5px;color:var(--muted);}
  .st-meta{font-size:12.5px;color:var(--muted);margin-top:8px;}
  .pill{font-size:10.5px;font-weight:700;letter-spacing:.6px;padding:4px 9px;border-radius:999px;}
  .pill.green{background:#173424;color:#6fd69d;}
  .pill.red{background:var(--ember);color:#fff;}

  table{width:100%;border-collapse:collapse;font-size:13px;}
  th{text-align:left;color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.7px;
     padding:11px 16px;border-bottom:1px solid var(--border);}
  td{padding:11px 16px;border-bottom:1px solid #2a211f;}
  tr:last-child td{border-bottom:none;}
  .tbl-wrap{overflow-x:auto;}
  .empty{color:var(--muted);font-style:italic;padding:22px 18px;display:none;}
  .tag{display:inline-block;font-size:11px;padding:3px 8px;border-radius:6px;margin-right:5px;}
  .tag.ok{background:#173424;color:#6fd69d;}
  .tag.warn{background:#3b2a12;color:var(--amber);}
  .tag.info{background:#1c2a3a;color:#8ec1ff;}

  footer{text-align:center;color:var(--muted);font-size:11.5px;margin-top:22px;}

  .pin{position:relative;width:22px;height:22px;}
  .pin span{position:absolute;inset:4px;border-radius:50%;background:var(--green);border:2px solid #fff;}
  .pin.alert span{background:var(--ember);}
  .pin.alert::after{content:"";position:absolute;inset:0;border-radius:50%;border:2px solid var(--ember);animation:ring 1.6s infinite;}
  @keyframes ring{0%{transform:scale(.8);opacity:.9;}100%{transform:scale(2.8);opacity:0;}}
  .leaflet-popup-content-wrapper{background:#1E1715;color:#F5F1EC;border-radius:10px;}
  .leaflet-popup-tip{background:#1E1715;}

  @media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr);}.main{grid-template-columns:1fr;}}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div class="brand">
      <div class="logo">🔥</div>
      <div>
        <h1>Wildfire Early-Warning System</h1>
        <div class="tagline">Live weather + social signals verified against a Random Forest risk model</div>
      </div>
    </div>
    <div class="live"><span class="dot"></span><span id="lastChecked">Connecting…</span></div>
  </div>

  <div id="banner" class="banner safe">
    <div class="ico" id="bannerIcon">✅</div>
    <div>
      <div class="t" id="bannerTitle">All clear</div>
      <div class="s" id="bannerSub">Monitoring live streams…</div>
    </div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="lbl">Verified alerts (last 3 min)</div><div class="val" id="kAlerts">–</div><div class="sub">weather + social agree</div></div>
    <div class="kpi"><div class="lbl">Stations at risk</div><div class="val" id="kStations">–</div><div class="sub">of monitored stations</div></div>
    <div class="kpi"><div class="lbl">Model F1 score</div><div class="val" id="kF1">–</div><div class="sub" id="kF1sub">&nbsp;</div></div>
    <div class="kpi"><div class="lbl">Training data</div><div class="val" id="kData">–</div><div class="sub">NOAA ISD · 2020–2023</div></div>
  </div>

  <div class="main">
    <div class="card">
      <div class="card-head">
        <h3>Live Risk Map</h3>
        <div class="legend">
          <span><i style="background:var(--green)"></i>Clear</span>
          <span><i style="background:var(--ember)"></i>Fire alert</span>
        </div>
      </div>
      <div id="map"></div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Station Status</h3></div>
      <div class="stations" id="stationList"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><h3>Recent Verified Alerts</h3></div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Detected</th><th>Station</th><th>Temp</th><th>Wind</th><th>Humidity</th><th>Social post</th><th>Data quality</th></tr></thead>
        <tbody id="alertBody"></tbody>
      </table>
    </div>
    <div class="empty" id="emptyMsg">No alerts yet — waiting for streaming data to cross-verify…</div>
  </div>

  <footer>Batch layer: Spark MLlib on HDFS (22.1 GB) · Streaming layer: Spark Structured Streaming · Auto-refresh every 4 s</footer>
</div>

<script src="/static/leaflet.js"></script>
<script>
let map = null;
try {
  map = L.map('map').setView([36.0, -118.7], 6);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri', maxZoom: 16
  }).addTo(map);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16
  }).addTo(map);
  setTimeout(() => map.invalidateSize(), 300);
} catch (e) {
  document.getElementById('map').innerHTML =
    '<div style="padding:40px;color:#A09389">Map could not load. Check static/leaflet.js and your internet connection.</div>';
}

const markers = {}, zones = {}, lastStatus = {};
let fitted = false;

function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function val(v, unit){ return (v === null || v === undefined || v === '') ? '–' : v + unit; }
function ageText(s){
  if (s === null || s === undefined) return '–';
  s = Math.round(s);
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  return Math.floor(s / 3600) + 'h ago';
}
function pinIcon(status){
  return L.divIcon({className: '', html: '<div class="pin ' + status + '"><span></span></div>', iconSize: [22, 22], iconAnchor: [11, 11]});
}
function qualityTags(a){
  let t = '';
  if (a.gap_filled) t += '<span class="tag warn">filled: ' + esc(a.gap_filled) + '</span>';
  if (a.geo_inferred) t += '<span class="tag info">geo from text</span>';
  if (!t) t = '<span class="tag ok">complete</span>';
  return t;
}

function updateMap(stations){
  if (!map) return;
  stations.forEach(s => {
    const l = s.latest;
    const popup = '<b>' + esc(s.name) + '</b><br>' + (s.status === 'alert' ? '🔥 Fire alert' : 'No active alert') +
      (l ? '<br>' + val(l.temperature, '°C') + ' · ' + val(l.wind_speed, ' m/s') + '<br><i>' + esc(l.text) + '</i>' : '');
    if (!markers[s.id]) {
      markers[s.id] = L.marker([s.lat, s.lon], {icon: pinIcon(s.status)}).addTo(map).bindPopup(popup);
      lastStatus[s.id] = s.status;
    } else {
      markers[s.id].setPopupContent(popup);
      if (lastStatus[s.id] !== s.status) {
        markers[s.id].setIcon(pinIcon(s.status));
        lastStatus[s.id] = s.status;
      }
    }
    if (s.status === 'alert' && !zones[s.id]) {
      zones[s.id] = L.circle([s.lat, s.lon], {radius: 45000, color: '#E8590C', weight: 1.5, fillColor: '#E8590C', fillOpacity: 0.22}).addTo(map);
    } else if (s.status !== 'alert' && zones[s.id]) {
      map.removeLayer(zones[s.id]);
      delete zones[s.id];
    }
  });
  if (!fitted && stations.length) {
    map.fitBounds(L.latLngBounds(stations.map(s => [s.lat, s.lon])), {padding: [70, 70]});
    fitted = true;
  }
}

function renderStations(stations){
  document.getElementById('stationList').innerHTML = stations.map(s => {
    const alert = s.status === 'alert';
    const l = s.latest;
    const meta = l ? ('Last alert ' + ageText(l._age) + ' · ' + val(l.temperature, '°C') + ' · ' + val(l.wind_speed, ' m/s'))
                   : 'No alerts received yet';
    return '<div class="st ' + (alert ? 'alert' : '') + '">' +
      '<div class="st-top"><div><div class="st-name">' + esc(s.name) + '</div><div class="st-id">' + esc(s.id) + '</div></div>' +
      '<span class="pill ' + (alert ? 'red' : 'green') + '">' + (alert ? 'FIRE ALERT' : 'ALL CLEAR') + '</span></div>' +
      '<div class="st-meta">' + meta + '</div></div>';
  }).join('');
}

function renderTable(alerts){
  const body = document.getElementById('alertBody');
  const empty = document.getElementById('emptyMsg');
  if (!alerts.length) { body.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';
  body.innerHTML = alerts.map(a =>
    '<tr><td>' + ageText(a._age) + '</td>' +
    '<td>' + esc(a.station_name) + '</td>' +
    '<td>' + val(a.temperature, '°C') + '</td>' +
    '<td>' + val(a.wind_speed, ' m/s') + '</td>' +
    '<td>' + val(a.humidity, '%') + '</td>' +
    '<td>' + esc(a.text) + '</td>' +
    '<td>' + qualityTags(a) + '</td></tr>'
  ).join('');
}

async function refresh(){
  try {
    const res = await fetch('/api/alerts');
    const d = await res.json();

    const banner = document.getElementById('banner');
    if (d.active_alert) {
      const names = d.stations.filter(s => s.status === 'alert').map(s => s.name).join(', ');
      banner.className = 'banner alert';
      document.getElementById('bannerIcon').textContent = '🔥';
      document.getElementById('bannerTitle').textContent = 'FIRE ALERT — ' + d.stations_at_risk + ' station' + (d.stations_at_risk > 1 ? 's' : '') + ' at risk';
      document.getElementById('bannerSub').textContent = names + ' · social reports confirmed by live weather conditions';
    } else {
      banner.className = 'banner safe';
      document.getElementById('bannerIcon').textContent = '✅';
      document.getElementById('bannerTitle').textContent = 'All clear';
      document.getElementById('bannerSub').textContent = 'Monitoring ' + d.total_stations + ' stations on live streams…';
    }

    document.getElementById('kAlerts').textContent = d.recent_alert_count;
    document.getElementById('kStations').textContent = d.stations_at_risk + ' / ' + d.total_stations;

    updateMap(d.stations);
    renderStations(d.stations);
    renderTable(d.alerts);
    document.getElementById('lastChecked').textContent = 'Live · updated ' + d.checked_at.slice(11);
  } catch (e) {
    document.getElementById('lastChecked').textContent = 'Connection error — is dashboard_server.py running?';
  }
}

async function loadModel(){
  try {
    const m = await (await fetch('/api/model')).json();
    document.getElementById('kF1').textContent = m.f1.toFixed(4);
    document.getElementById('kF1sub').textContent = 'P ' + m.precision.toFixed(4) + ' · R ' + m.recall.toFixed(4);
    document.getElementById('kData').textContent = m.data_volume;
  } catch (e) {}
}

loadModel();
refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)