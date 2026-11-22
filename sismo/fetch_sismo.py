"""Obtiene el GeoJSON del terremoto M8.8 (Maule, 27-02-2010) desde USGS.

Si el archivo ya existe en /data/sismo no se vuelve a descargar.
"""
import json
import os
import sys
import urllib.request

DEST = "/data/sismo/sismo_maule_8.8.geojson"
URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
    "&starttime=2010-02-27&endtime=2010-02-28&minmagnitude=8.5"
)


def main():
    if os.path.exists(DEST) and os.path.getsize(DEST) > 0:
        print(f"[sismo] GeoJSON ya existe: {DEST} (no se descarga)")
    else:
        print(f"[sismo] Descargando desde USGS: {URL}")
        with urllib.request.urlopen(URL, timeout=60) as r:
            data = r.read()
        os.makedirs(os.path.dirname(DEST), exist_ok=True)
        with open(DEST, "wb") as f:
            f.write(data)

    gj = json.load(open(DEST))
    feats = [f for f in gj["features"] if f["properties"]["mag"] >= 8.8]
    if not feats:
        sys.exit("[sismo] El GeoJSON no contiene un evento M>=8.8")
    f = feats[0]
    lon, lat, depth = f["geometry"]["coordinates"]
    print(f"[sismo] {f['id']}  M{f['properties']['mag']}  {f['properties']['place']}"
          f"  epicentro=({lat}, {lon})  prof={depth} km")


if __name__ == "__main__":
    main()
