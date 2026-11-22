#!/bin/bash
# Carga la infraestructura Yafun (SUBTEL/NIC) y el sismo 8.8 en PostGIS.
set -euo pipefail

SHP_DIR=/data/Respuesta_T5610
SISMO=/data/sismo/sismo_maule_8.8.geojson
PSQL="psql -v ON_ERROR_STOP=1 -q"
export PGOPTIONS="-c client_min_messages=warning"

echo "[loader] Cargando shapefiles (shp2pgsql)..."
for capa in fibra_optica_detectada trayecto_en_ferry camino_sin_postacion_detectado postacion_electrica_detectada; do
  psql -q -c "DROP TABLE IF EXISTS raw_$capa CASCADE"
  shp2pgsql -c -s 4326 -g geom -I -W UTF-8 "$SHP_DIR/$capa.shp" "raw_$capa" 2>/dev/null | $PSQL > /dev/null
  n=$(psql -Atc "SELECT count(*) FROM raw_$capa")
  echo "[loader]   raw_$capa: $n lineas"
done

echo "[loader] Creando red y topologia (pgr_createTopology)..."
$PSQL -f sql/01_red_topologia.sql

echo "[loader] Nodos clave en plaza de armas + enlaces de acceso (criterio Yafun S1)..."
$PSQL -f sql/02_nodos_clave.sql

echo "[loader] Clasificando vertices (intersecciones / paso / extremos)..."
$PSQL -f sql/03_intersecciones.sql

echo "[loader] Cargando sismo GeoJSON..."
$PSQL -v geojson="$(cat "$SISMO")" -f sql/04_sismo.sql

Q="psql -P pager=off"
echo "[loader] --- Evidencia de la topologia ---"
$Q -c "SELECT id, cnt, chk, grado, tipo, es_clave, round(ST_X(the_geom)::numeric,4) AS lon,
              round(ST_Y(the_geom)::numeric,4) AS lat FROM enlaces_vertices_pgr ORDER BY id LIMIT 8"
$Q -c "SELECT tipo, count(*) AS vertices FROM enlaces_vertices_pgr GROUP BY tipo ORDER BY tipo"
$Q -c "SELECT origen, tipo, sintetico, count(*) AS enlaces, round(sum(largo_km)::numeric,1) AS km,
              min(p_falla) AS p_falla_min, max(p_falla) AS p_falla_max
       FROM enlaces GROUP BY origen, tipo, sintetico ORDER BY origen, tipo"
$Q -c "SELECT id, tipo, origen, sintetico, source, target, round(largo_km::numeric,3) AS largo_km, p_falla
       FROM enlaces ORDER BY id LIMIT 5"
$Q -c "WITH c AS (SELECT * FROM pgr_connectedComponents(
                  'SELECT id, source, target, 1 AS cost, 1 AS reverse_cost FROM enlaces'))
       SELECT count(DISTINCT component) AS componentes,
              (SELECT count(DISTINCT c.component) FROM nodos_clave n JOIN c ON c.node = n.vertice_id)
                AS componentes_con_nodos_clave,
              (SELECT count(*) FROM enlaces_vertices_pgr WHERE grado = 1) AS vertices_grado_1
       FROM c"
$Q -c "WITH p AS (SELECT coalesce(min(id), (SELECT max(id) + 1 FROM enlaces)) AS p0,
                         coalesce(max(id), 0) AS p1 FROM enlaces WHERE tipo = 'puente')
       SELECT (SELECT count(*) FROM enlaces, p WHERE id < p0)                 AS tras_createtopology,
              (SELECT count(*) FROM enlaces WHERE tipo = 'puente')            AS puentes,
              (SELECT count(*) FROM enlaces, p WHERE id > p1 AND NOT acceso)  AS divisiones_nodos_clave,
              (SELECT count(*) FROM enlaces WHERE acceso)                      AS accesos,
              (SELECT count(*) FROM enlaces)                                   AS total"
$Q -c "SELECT count(*) AS autoloops_source_eq_target, round(sum(largo_km)::numeric, 2) AS km,
              round(max(largo_km)::numeric * 1000) AS max_m
       FROM enlaces WHERE source = target"
$Q -c "SELECT id, nombre, rol, vertice_id, round(largo_acceso_km::numeric,2) AS acceso_km FROM nodos_clave ORDER BY id"
echo "[loader] --- Tabla sismo (GeoJSON USGS) ---"
$Q -x -c "SELECT usgs_id, magnitud, lugar, fecha, profundidad_km, ST_AsText(geom) AS epicentro,
              propiedades->>'url' AS url FROM sismo"
echo "[loader] OK"
