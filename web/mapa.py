"""Genera /output/mapa.html (Leaflet via folium): red, nodos clave,
intersecciones, epicentro, isolineas de PGA y danio (P_falla) por enlace."""
import json
import math

import branca.colormap as cm
import folium
import psycopg2
from folium.plugins import Fullscreen

OUT = "/output/mapa.html"
COLOR_TIPO = {"fibra": "#1f77b4", "poste": "#9467bd", "camino": "#8c564b",
              "ferry": "#17becf", "puente": "#000000"}
NOMBRE_TIPO = {"fibra": "Fibra óptica detectada", "poste": "Postación eléctrica",
               "camino": "Camino sin postación", "ferry": "Trayecto en ferry",
               "puente": "Puente virtual (≤3 km, Yafún S2)"}
# Trazo segun origen del enlace (enlaces sinteticos distinguidos)
DASH_ORIGEN = {"detectado": None, "supuesto": "6 4", "sintetico": "2 4"}
NOMBRE_ORIGEN = {"detectado": "Fibra detectada en terreno (línea continua)",
                 "supuesto": "Sintético: corredor sin fibra visible – poste / camino / ferry (guiones)",
                 "sintetico": "Sintético: puente ≤3 km o acceso a plaza (puntos)"}
COLOR_ROL = {"intercambia": "red", "genera": "darkred", "amarre": "blue", "recibe": "green"}


def geojson_enlaces(cur):
    cur.execute("""
        SELECT json_build_object('type','FeatureCollection','features', json_agg(json_build_object(
            'type','Feature',
            'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(e.geom, 0.0003), 5)::json,
            'properties', json_build_object(
                'id', e.id, 'tipo', e.tipo, 'acceso', CASE WHEN e.acceso THEN 'sí' ELSE 'no' END,
                'origen', e.origen, 'sintetico', CASE WHEN e.sintetico THEN 'sí' ELSE 'no' END,
                'largo_km', round(e.largo_km::numeric, 2),
                'pga_g', round(p.pga_max_g::numeric, 3),
                'dist_epi_km', round(p.dist_epi_min_km::numeric, 1),
                'p_falla', round(p.p_falla::numeric, 4)))))
        FROM enlaces e JOIN prob_falla p ON p.enlace_id = e.id""")
    return cur.fetchone()[0]


def radio_pga(pga_g, m, h):
    """Distancia epicentral [km] a la que Youngs97 entrega pga_g."""
    c = 1.7818 * math.exp(0.554 * m)
    ln_rc = (0.2418 + 1.414 * m + 0.00607 * h - math.log(pga_g)) / 2.552
    r_hipo = math.exp(ln_rc) - c
    return math.sqrt(r_hipo ** 2 - h ** 2) if r_hipo > h else 0.0


def main():
    conn = psycopg2.connect("")
    cur = conn.cursor()

    cur.execute("SELECT escenario, attr_nodos_clave, attr_nodos_red, s_lcc_nodos_red FROM resultados_attr")
    attr = {r[0]: r[1:] for r in cur.fetchall()}
    cur.execute("SELECT usgs_id, magnitud, lugar, fecha, profundidad_km, ST_Y(geom), ST_X(geom), "
                "propiedades->>'url' FROM sismo ORDER BY magnitud DESC LIMIT 1")
    sid, mag, lugar, fecha, h, lat, lon, url = cur.fetchone()
    gj = geojson_enlaces(cur)

    m = folium.Map(location=[-36.5, -71.5], zoom_start=6, tiles=None, control_scale=True)
    folium.TileLayer("Esri.WorldGrayCanvas", name="Esri gris").add_to(m)   # base por defecto
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)
    Fullscreen().add_to(m)

    # --- Red por tipo (estado en operacion)
    fg_red = folium.FeatureGroup(name="Red en operación (por tipo)", show=False)
    folium.GeoJson(
        gj,
        style_function=lambda f: {"color": COLOR_TIPO[f["properties"]["tipo"]], "weight": 2,
                                  "dashArray": DASH_ORIGEN[f["properties"]["origen"]]},
        tooltip=folium.GeoJsonTooltip(["id", "tipo", "origen", "sintetico", "acceso", "largo_km"],
                                      ["Enlace", "Tipo", "Origen", "Sintético", "Acceso plaza (Yafún S1)",
                                       "Largo [km]"]),
    ).add_to(fg_red)
    fg_red.add_to(m)

    # --- Danio: probabilidad de falla
    cmap = cm.LinearColormap(["#1a9850", "#fee08b", "#f46d43", "#a50026"],
                             vmin=0, vmax=0.3, caption="Probabilidad de falla del enlace (P_f)")
    fg_dano = folium.FeatureGroup(name="Daño terremoto 8.8 (P_falla)", show=True)
    folium.GeoJson(
        gj,
        style_function=lambda f: {"color": cmap(min(f["properties"]["p_falla"] or 0, 0.3)),
                                  "weight": 3 if (f["properties"]["p_falla"] or 0) > 0.05 else 2,
                                  "dashArray": DASH_ORIGEN[f["properties"]["origen"]],
                                  "opacity": 0.9},
        tooltip=folium.GeoJsonTooltip(
            ["id", "tipo", "origen", "sintetico", "largo_km", "dist_epi_km", "pga_g", "p_falla"],
            ["Enlace", "Tipo", "Origen", "Sintético", "Largo [km]", "Dist. epicentro [km]", "PGA máx [g]",
             "P_falla"]),
    ).add_to(fg_dano)
    fg_dano.add_to(m)
    cmap.add_to(m)

    # --- Isolineas de PGA (Youngs et al. 1997)
    fg_pga = folium.FeatureGroup(name="Isolíneas PGA (Youngs 1997)", show=True)
    for pga in (0.30, 0.20, 0.10, 0.05, 0.02):
        r = radio_pga(pga, mag, h)
        if r > 0:
            folium.Circle([lat, lon], radius=r * 1000, color="#d62728", weight=1,
                          fill=True, fill_opacity=0.04, dash_array="4 4",
                          tooltip=f"PGA ≥ {pga} g (R ≈ {r:.0f} km)").add_to(fg_pga)
    fg_pga.add_to(m)

    folium.Marker(
        [lat, lon],
        icon=folium.Icon(color="red", icon="bolt", prefix="fa"),
        popup=folium.Popup(f"<b>{lugar}</b><br>M{mag} · prof. {h} km<br>{fecha:%Y-%m-%d %H:%M} UTC"
                           f"<br>USGS: <a href='{url}' target='_blank'>{sid}</a>", max_width=300),
        tooltip=f"Epicentro M{mag}",
    ).add_to(m)

    # --- Intersecciones (grado >= 3)
    fg_int = folium.FeatureGroup(name="Intersecciones (grado ≥ 3)", show=False)
    cur.execute("SELECT id, grado, ST_Y(geom), ST_X(geom) FROM intersecciones")
    for vid, g, y, x in cur.fetchall():
        folium.CircleMarker([y, x], radius=3, color="#333", weight=1, fill=True,
                            fill_color="#ffbf00", fill_opacity=1,
                            tooltip=f"Intersección {vid} · grado {g}").add_to(fg_int)
    fg_int.add_to(m)

    # --- Nodos clave
    fg_k = folium.FeatureGroup(name="Nodos clave", show=True)
    cur.execute("""SELECT n.nombre, n.rol, ST_Y(n.geom), ST_X(n.geom), n.vertice_id, n.largo_acceso_km,
                          c.p_conectado_ixp
                   FROM nodos_clave n LEFT JOIN conectividad_nodos_clave c ON c.nodo_id = n.id""")
    for nombre, rol, y, x, vid, d, pc in cur.fetchall():
        folium.Marker(
            [y, x], icon=folium.Icon(color=COLOR_ROL[rol], icon="server" if rol in ("genera", "intercambia")
                                     else ("anchor" if rol == "amarre" else "home"), prefix="fa"),
            tooltip=nombre,
            popup=folium.Popup(f"<b>{nombre}</b><br>Rol: {rol}<br>Plaza de armas → vértice {vid}"
                               f"<br>Enlace de acceso: {d:.2f} km"
                               f"<br>P(conectado al IXP tras sismo): <b>{pc:.3f}</b>", max_width=280),
        ).add_to(fg_k)
    fg_k.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    a0, a1 = attr["antes"], attr["despues"]
    estilo_borde = {"detectado": "solid", "supuesto": "dashed", "sintetico": "dotted"}
    leyenda_tipos = "<div style='font-weight:600'>Trazo según origen</div>" + "".join(
        f"<div><span style='display:inline-block;width:22px;border-top:3px "
        f"{estilo_borde[o]} #444;margin-right:6px'></span>{NOMBRE_ORIGEN[o]}</div>"
        for o in ("detectado", "supuesto", "sintetico")) + (
        "<div style='font-weight:600;margin-top:4px'>Color capa «por tipo»</div>") + "".join(
        f"<div><span style='display:inline-block;width:22px;border-top:3px solid {c};"
        f"margin-right:6px'></span>{NOMBRE_TIPO[t]}</div>"
        for t, c in COLOR_TIPO.items())
    panel = f"""
    <div style="position:fixed;bottom:24px;left:12px;z-index:9999;background:rgba(255,255,255,.95);
                padding:10px 14px;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.3);
                font:13px/1.4 system-ui,sans-serif;max-width:300px">
      <div style="font-weight:600;font-size:14px;margin-bottom:4px">ATTR – Internet chilena</div>
      <table style="border-collapse:collapse;width:100%">
        <tr><th></th><th style="text-align:right">Antes</th><th style="text-align:right">Después</th></tr>
        <tr><td>Nodos clave</td><td style="text-align:right">{a0[0]:.4f}</td>
            <td style="text-align:right;color:#a50026"><b>{a1[0]:.4f}</b></td></tr>
        <tr><td>Nodos de red (FR)</td><td style="text-align:right">{a0[1]:.4f}</td>
            <td style="text-align:right;color:#a50026">{a1[1]:.4f}</td></tr>
        <tr><td>S_LCC (ENRN)</td><td style="text-align:right">{a0[2]:.4f}</td>
            <td style="text-align:right;color:#a50026">{a1[2]:.4f}</td></tr>
      </table>
      <div style="margin-top:6px;color:#555;font-size:12px">
        Nodos clave: 19 (genera/intercambia/recibe).<br>
        Nodos de red: intersecciones grado ≥ 3 + nodos clave.<br>
        Sismo M{mag} Maule 2010 · HAZUS dúctil · Monte Carlo</div>
      <hr style="margin:6px 0">{leyenda_tipos}
    </div>"""
    m.get_root().html.add_child(folium.Element(panel))
    m.get_root().header.add_child(folium.Element("<title>Resiliencia Internet Chile</title>"))

    m.save(OUT)
    with open("/output/index.html", "w") as fh:
        fh.write('<meta http-equiv="refresh" content="0; url=mapa.html">')
    print(f"[web] Mapa generado: {OUT}")


if __name__ == "__main__":
    main()
